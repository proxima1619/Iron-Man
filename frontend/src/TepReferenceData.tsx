import { useEffect, useState } from "react";
import type { components } from "./api.generated";

type Catalog = components["schemas"]["ReferenceCatalog"];
type Series = components["schemas"]["ReferenceSeries"];

async function read<T>(path: string, token: string, signal: AbortSignal): Promise<T> {
  const response = await fetch("/api/tep/reference/" + path, {
    headers: { "X-Iron-Man-Token": token }, signal,
  });
  const value = await response.json();
  if (!response.ok) throw new Error(typeof value.detail === "string" ? value.detail : "참조 데이터 조회 실패");
  return value as T;
}

export function TepReferenceData({ token, enabled }: { token: string; enabled: boolean }) {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [series, setSeries] = useState<Series | null>(null);
  const [fileId, setFileId] = useState("d00_te.dat");
  const [variable, setVariable] = useState("XMEAS9");
  const [revision, setRevision] = useState(0);
  const [catalogError, setCatalogError] = useState("");
  const [seriesError, setSeriesError] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setCatalog(null); setCatalogError("");
    if (!enabled) return;
    const controller = new AbortController();
    let active = true;
    const timer = window.setTimeout(() => controller.abort(), 15000);
    void read<Catalog>("catalog", token, controller.signal)
      .then(value => {
        if (active) {
          setCatalog(value);
          setFileId(current => value.files.some(file => file.file_id === current && file.present)
            ? current : value.files.find(file => file.present)?.file_id || current);
        }
      })
      .catch(error => { if (active) setCatalogError(error instanceof Error ? error.message : "참조 목록 조회 실패"); })
      .finally(() => window.clearTimeout(timer));
    return () => { active = false; controller.abort(); window.clearTimeout(timer); };
  }, [token, enabled, revision]);

  useEffect(() => {
    setSeries(null); setSeriesError(""); setLoading(false);
    if (!enabled || !catalog) return;
    const controller = new AbortController();
    let active = true;
    const timer = window.setTimeout(() => controller.abort(), 15000);
    setLoading(true);
    void read<Series>(`series/${encodeURIComponent(fileId)}?variable=${encodeURIComponent(variable)}`, token, controller.signal)
      .then(value => { if (active) setSeries(value); })
      .catch(error => { if (active) setSeriesError(error instanceof Error ? error.message : "참조 기록 조회 실패"); })
      .finally(() => { window.clearTimeout(timer); if (active) setLoading(false); });
    return () => { active = false; controller.abort(); window.clearTimeout(timer); };
  }, [catalog, fileId, variable, token, enabled]);

  const shown = enabled && catalog && series?.file.file_id === fileId && series.variable === variable ? series : null;
  const span = shown ? Math.max(shown.statistics.maximum - shown.statistics.minimum, 0.001) : 1;
  const line = shown?.values.map((value, i) => `${75 + 625 * i / Math.max(shown.values.length - 1, 1)},${235 - 180 * (value - shown.statistics.minimum) / span}`).join(" ") || "";
  const condition = shown?.file.condition === "normal" ? "정상 운전 기록" : `Fault ${shown?.file.fault_index} 기록`;
  function download() {
    if (!shown) return;
    const url = URL.createObjectURL(new Blob([JSON.stringify(shown, null, 2) + "\n"], { type: "application/json" }));
    const link = document.createElement("a");
    link.href = url; link.download = `${shown.file.file_id}-${shown.variable}-simulation-reference.json`;
    link.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  return <section className="no-print" aria-labelledby="tep-reference-heading">
    <details>
      <summary id="tep-reference-heading"><strong>TEP 참조 데이터 · 정상/고장 기록 탐색</strong></summary>
      <p><strong>사전 생성된 시뮬레이션 데이터 · 현장 실측 아님</strong></p>
      <p className="muted">정상·고장 공정 기록을 데모에서 살펴볼 수 있습니다. 변경 요청의 기준/변경 결과는 외부 TEP 엔진이 별도로 계산합니다. 실측 오차 평가와 실제 설비 적용성 검증은 미완료이며 TEP 요청은 보류됩니다.</p>
      {!enabled && <p>역할 토큰으로 연결하면 참조 기록을 조회할 수 있습니다.</p>}
      {enabled && <>
        <button onClick={() => setRevision(value => value + 1)}>참조 목록 다시 읽기</button>
        {catalogError && <p role="alert" className="error">{catalogError} 외부 TEP 실행은 참조 파일 없이도 사용할 수 있습니다.</p>}
        {!catalog && !catalogError && <p role="status">참조 목록을 읽고 있습니다.</p>}
        {catalog && <>
          <div className="reference-controls">
            <label>시뮬레이션 기록
              <select value={fileId} onChange={event => setFileId(event.target.value)}>
                {catalog.files.map(file => <option key={file.file_id} value={file.file_id} disabled={!file.present}>
                  {file.file_id} · {file.condition === "normal" ? "정상" : `Fault ${file.fault_index}`} · {file.split === "test" ? "시험" : "학습"} · {file.observation_count}개{!file.present ? " (파일 없음)" : ""}
                </option>)}
              </select>
            </label>
            <label>기록 변수
              <select value={variable} onChange={event => setVariable(event.target.value)}>
                {Object.entries(catalog.variables).map(([key, definition]) => <option key={key} value={key}>{key} · {definition.name} ({definition.unit})</option>)}
              </select>
            </label>
          </div>
          {loading && <p role="status">선택한 기록을 읽고 있습니다.</p>}
          {seriesError && <p role="alert" className="error">{seriesError}</p>}
          {shown && <>
            <h3>{shown.file.file_id} · {condition}</h3>
            <svg viewBox="0 0 760 285" className="reference-chart" role="img" aria-label={`${shown.variable}, ${shown.definition.unit}, 표본 번호별 시뮬레이션 참조 값`}>
              <path d="M75 45 V235 H700" fill="none" stroke="currentColor" />
              <text x="5" y="55" fontSize="12">{shown.statistics.maximum.toFixed(3)}</text>
              <text x="5" y="235" fontSize="12">{shown.statistics.minimum.toFixed(3)}</text>
              <text x="75" y="260" fontSize="12">표본 0</text>
              <text x="640" y="260" fontSize="12">표본 {shown.values.length - 1}</text>
              <text x="75" y="25" fontSize="13">{shown.variable} ({shown.definition.unit})</text>
              <polyline points={line} fill="none" stroke="var(--accent)" strokeWidth="1.5" />
            </svg>
            <p className="muted">시간 기록이 없어 표본 번호로 표시합니다. 동봉 코드의 기록 간격은 180초이며 파일별 간격·고장 시작 표본은 미확인입니다.</p>
            <table><thead><tr><th>관측 수</th><th>최소 ({shown.definition.unit})</th><th>최대 ({shown.definition.unit})</th><th>평균 ({shown.definition.unit})</th></tr></thead>
              <tbody><tr><td>{shown.values.length}</td><td>{shown.statistics.minimum.toFixed(5)}</td><td>{shown.statistics.maximum.toFixed(5)}</td><td>{shown.statistics.mean.toFixed(5)}</td></tr></tbody>
            </table>
            <p className="muted">위 통계는 이 기록의 관측 범위입니다. 안전 허용 한계가 아니며 현재 개루프 실행과 조건이 맞지 않아 오차 지표를 산출하지 않습니다.</p>
            <button onClick={download}>선택 시계열 · 출처 정보 JSON 저장</button>
            <details><summary>선택 변수의 전체 기록 ({shown.values.length}개)</summary>
              <div className="reference-table"><table><thead><tr><th>표본 번호</th><th>{shown.variable} ({shown.definition.unit})</th></tr></thead>
                <tbody>{shown.values.map((value, i) => <tr key={i}><td>{shown.sample_indices[i]}</td><td>{value}</td></tr>)}</tbody>
              </table></div>
            </details>
            <details><summary>참조 자료 출처와 확인 상태</summary>
              <p>로컬 업로드 자료입니다. 다운로드 출처 URL·원본 버전·데이터 라이선스 적용 범위는 확인 중입니다. 동봉 코드의 저작권·허가 고지는 원본에 보존되어 있습니다.</p>
              <p>폐루프 제어 코드가 동봉되어 있으며 파일별 제어기·운전 모드·초기 상태·시드는 확인되지 않았습니다.</p>
              <p>원본 SHA-256: <code>{shown.file.sha256}</code></p>
              <p>자료 프로필: <code>{shown.metadata.profile_id}</code> · {shown.file.stored_layout === "variables_by_observations" ? "전치하여 읽음" : "관측 행으로 읽음"}</p>
              <p>XMV10/11 단위는 percent_full_scale 냉각수 설정입니다. 펌프 RPM이나 펌프 속도 %로 취급하지 않습니다.</p>
            </details>
          </>}
        </>}
      </>}
    </details>
  </section>;
}
