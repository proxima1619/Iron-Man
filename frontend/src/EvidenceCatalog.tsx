import { useEffect, useState } from "react";
import type { components } from "./api.generated";

type Catalog = components["schemas"]["EvidenceCatalog"];

export function EvidenceCatalog({ token }: { token: string }) {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    setCatalog(null);
    setError("");
    if (!token) return;
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), 15000);
    let active = true;
    setBusy(true);
    void (async () => {
      try {
        const response = await fetch("/api/evidence/catalog", {
          headers: { "X-Iron-Man-Token": token },
          signal: controller.signal,
        });
        if (!response.ok)
          throw new Error(
            response.status === 404
              ? "새 근거 API가 아직 실행되지 않았습니다. 백엔드를 scripts/start_api.py로 재시작하세요."
              : "근거 설정을 불러오지 못했습니다. 서버 연결과 담당자 토큰을 확인하세요.",
          );
        const value = (await response.json()) as Catalog;
        if (active) setCatalog(value);
      } catch (e) {
        if (active)
          setError(
            e instanceof Error && e.name !== "AbortError"
              ? e.message
              : "근거 설정 조회 시간이 초과되었습니다.",
          );
      } finally {
        if (active) setBusy(false);
      }
    })();
    return () => {
      active = false;
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [token, revision]);

  return (
    <section
      className="evidence-catalog"
      aria-label="논문 목록과 검토 연결 상태"
    >
      <div className="section-head">
        <h3>논문 목록과 검토 연결</h3>
        <button
          disabled={busy || !token}
          onClick={() => setRevision((v) => v + 1)}
        >
          {busy ? "확인 중…" : "설정 새로고침"}
        </button>
      </div>
      <p className="muted">
        DB 기록 조회에는 API 키가 필요하지 않습니다. 키와 모델은 서버의 새 논문
        검토에 사용하며 브라우저에 전달하지 않습니다.
      </p>
      {!token && <p>담당자 토큰을 입력하면 검토 설정을 확인할 수 있습니다.</p>}
      {error && <p role="status">{error}</p>}
      {catalog && (
        <>
          <dl>
            <dt>검토 모드</dt>
            <dd>
              {catalog.mode === "live"
                ? "실제 LLM 검토"
                : catalog.mode === "fixture"
                  ? "모의 응답"
                  : "설정 오류"}
            </dd>
            <dt>API 키 · 모델</dt>
            <dd>
              {catalog.api_key_configured ? "키 설정됨" : "키 없음"} ·{" "}
              {catalog.model_configured ? "모델 설정됨" : "모델 없음"}
            </dd>
            <dt>문헌 수집</dt>
            <dd>
              {catalog.source_mode === "local"
                ? `사전 수집 ${catalog.sources.length}건`
                : catalog.source_mode === "europepmc"
                  ? "검토 시 Europe PMC 실시간 검색"
                  : "설정 오류"}
            </dd>
          </dl>
          <p>
            {catalog.ready
              ? "검토 설정이 준비됐습니다. 실제 호출 성공 여부는 새 요청의 검토 결과에서 확인하세요."
              : "실제 논문 검토 설정을 확인하세요."}
          </p>
          {!!catalog.issues.length && (
            <ul>
              {catalog.issues.map((issue) => (
                <li key={issue}>{issue}</li>
              ))}
            </ul>
          )}
          {!!catalog.sources.length && (
            <details>
              <summary>검토 입력 문서 {catalog.sources.length}건 보기</summary>
              <ul>
                {catalog.sources.map((source) => {
                  let url: string | null = null;
                  try {
                    const value = new URL(source.source_url || "");
                    if (
                      value.protocol === "https:" &&
                      !value.username &&
                      !value.password
                    )
                      url = value.href;
                  } catch {
                    /* No source URL */
                  }
                  return (
                    <li key={source.source_id}>
                      <strong>{source.title}</strong>
                      <p className="muted">
                        {source.source_type === "paper" ? "논문" : "문서"} ·{" "}
                        {source.publisher} · {source.locator}
                      </p>
                      {url && (
                        <a href={url} target="_blank" rel="noopener noreferrer">
                          출처 원문 열기 ↗
                        </a>
                      )}
                    </li>
                  );
                })}
              </ul>
            </details>
          )}
          <p className="annotation">
            목록은 검토 입력입니다. 관련 논문·반례 분류는 현재 명령과 상태를
            비교한 결과에서 확인하세요. 설정 변경은 기존 DB 보고서를 수정하지
            않습니다. 초기 상태를 준비하고 새 요청을 검토하면 새 결과가
            저장됩니다. 외부 논문의 적용 조건과 서버 승인 정책이 확인되지 않으면
            보류됩니다.
          </p>
        </>
      )}
    </section>
  );
}
