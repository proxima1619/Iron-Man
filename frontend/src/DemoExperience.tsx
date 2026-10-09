import { useEffect, useState } from "react";
import type { components } from "./api.generated";
import { EvidencePanel } from "./EvidencePanel";
import { EvidenceCatalog } from "./EvidenceCatalog";
import { RecordFeedback } from "./RecordFeedback";

type Row = components["schemas"]["RequestRecord"];
type Session = components["schemas"]["SessionInfo"];
type Snapshot = components["schemas"]["Snapshot"];
const statusLabels: Record<string, string> = {
  draft: "접수",
  evaluating: "가상 검토 중",
  blocked: "위험 조건 차단",
  hold: "보류",
  awaiting_approval: "담당자 승인 대기",
  approved: "승인 완료",
  completed: "가상 적용 완료",
  revalidation_required: "재검증 필요",
  execution_unknown: "적용 결과 불명",
  rejected: "거절",
};

export function DemoExperience() {
  const [operator, setOperator] = useState("local-operator");
  const [approver, setApprover] = useState("local-approver");
  const [speed, setSpeed] = useState(80);
  const [load, setLoad] = useState(0.6);
  const [row, setRow] = useState<Row | null>(null);
  const [savedRows, setSavedRows] = useState<Row[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [fromDatabase, setFromDatabase] = useState(false);
  const [plant, setPlant] = useState<Snapshot | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [reason, setReason] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [now, setNow] = useState(Date.now() / 1000);

  async function api<T>(
    path: string,
    role: "operator" | "approver",
    body?: unknown,
    signal?: AbortSignal,
  ): Promise<T> {
    const controller = new AbortController();
    const abort = () => controller.abort();
    if (signal?.aborted) controller.abort();
    signal?.addEventListener("abort", abort, { once: true });
    const timer = window.setTimeout(abort, 15000);
    try {
      const response = await fetch("/api" + path, {
        method: body === undefined ? "GET" : "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Iron-Man-Token": role === "operator" ? operator : approver,
        },
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: controller.signal,
      });
      const bodyValue = await response.json();
      if (!response.ok)
        throw new Error(
          typeof bodyValue.detail === "string"
            ? bodyValue.detail
            : "서버 처리 실패",
        );
      return bodyValue as T;
    } catch (e) {
      if (controller.signal.aborted && !signal?.aborted)
        throw new Error(
          "응답 시간 초과. 저장된 요청을 확인한 후 다시 진행하세요.",
        );
      throw e;
    } finally {
      window.clearTimeout(timer);
      signal?.removeEventListener("abort", abort);
    }
  }
  async function demoOnly() {
    const health = await api<{
      mode: string;
      real_equipment_connected: boolean;
    }>("/health", "operator");
    if (
      health.mode !== "demo_only" ||
      health.real_equipment_connected !== false
    )
      throw new Error(
        "이 체험은 실제 설비가 연결되지 않은 데모 서버에서만 가능합니다.",
      );
  }
  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError("");
    try {
      await action();
    } catch (e) {
      setError(e instanceof Error ? e.message : "처리 실패");
      if (row) {
        try {
          setRow(await api<Row>(`/requests/${row.id}`, "operator"));
        } catch {
          /* Keep the known request and ask for reconciliation. */
        }
      }
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => window.clearInterval(timer);
  }, []);
  useEffect(() => {
    if (row?.status !== "evaluating") return;
    const id = row.id,
      controller = new AbortController();
    let timer = 0;
    async function poll() {
      try {
        const next = await api<Row>(
          `/requests/${id}`,
          "operator",
          undefined,
          controller.signal,
        );
        if (controller.signal.aborted) return;
        setRow(next);
        if (next.status !== "evaluating") {
          setConfirmed(false);
          return;
        }
      } catch (e) {
        if (controller.signal.aborted) return;
        setError(e instanceof Error ? e.message : "검토 결과 조회 실패");
        return;
      }
      timer = window.setTimeout(() => void poll(), 700);
    }
    void poll();
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [row?.id, row?.status, operator]);

  const report = row?.report;
  const coolingSnapshot = report && "observed_at" in report.snapshot ? report.snapshot : null;
  const pumpCommand = row?.request.command.type === "set_pump_speed" ? row.request.command : null;
  const appliedExecution = row?.execution?.status === "applied" && row.execution.command.type === "set_pump_speed"
    ? row.execution
    : null;
  const locked = busy || row?.status === "evaluating";
  const age = coolingSnapshot ? now - coolingSnapshot.observed_at : Infinity;
  const fresh = age >= 0 && age <= 60;
  return (
    <section className="demo-experience" id="demo" aria-labelledby="demo-title">
      <div className="demo-heading">
        <div>
          <p className="home-kicker">INTERACTIVE DEMO</p>
          <h2 id="demo-title">저장된 결과를 읽고, AI 설명을 받아보세요.</h2>
          <p>
            기록을 선택하면 당시 명령과 결과를 볼 수 있습니다. AI 피드백을
            누르면 논문을 바탕으로 결과와 한계를 설명합니다.
          </p>
        </div>
        <span className="badge">가상 설비 체험 · AI API는 별도 연결</span>
      </div>
      <div className="demo-layout">
        <div className="demo-controls">
          <div className="demo-database">
            <h3>1. 저장된 기록 선택</h3>
            <p className="muted">
              이전에 요청한 펌프 속도와 계산 결과를 불러옵니다. 실제 설비
              측정값이 아닌 합성 시연 기록입니다.
            </p>
            <button
              className="full"
              disabled={locked}
              onClick={() =>
                void run(async () => {
                  setSavedRows(await api<Row[]>("/requests", "operator"));
                  setLoaded(true);
                })
              }
            >
              저장된 기록 보기
            </button>
            {loaded && (
              <label>
                검토할 저장 데이터
                <select
                  value={fromDatabase ? row?.id || "" : ""}
                  disabled={locked}
                  onChange={(e) => {
                    const id = e.target.value;
                    if (id)
                      void run(async () => {
                        const stored = await api<Row>(
                          `/requests/${id}`,
                          "operator",
                        );
                        setRow(stored);
                        setFromDatabase(true);
                        setConfirmed(false);
                        setReason("");
                        setPlant(null);
                        if (stored.request.command.type === "set_pump_speed")
                          setSpeed(stored.request.command.target_pct);
                      });
                  }}
                >
                  <option value="">기록을 선택하세요</option>
                  {savedRows.filter((stored) => stored.request.command.type === "set_pump_speed").map((stored) => (
                    <option value={stored.id} key={stored.id}>
                      {stored.request.command.type === "set_pump_speed" ? `${stored.request.command.target_pct}%` : "TEP"} ·{" "}
                      {statusLabels[stored.status] || stored.status} ·{" "}
                      {stored.id.slice(0, 8)}
                      {stored.report
                        ? ` · 근거 ${stored.report.evidence?.cards.length || 0}개`
                        : " · 보고서 없음"}
                    </option>
                  ))}
                </select>
              </label>
            )}
            {loaded && !savedRows.length && (
              <p className="muted">
                저장된 요청이 없습니다. 아래에서 새 가상 검토를 실행하면 기록이
                저장됩니다.
              </p>
            )}
          </div>
          <EvidenceCatalog token={operator} />
          <details className="new-demo">
            <summary>새 가상 검토도 해보기</summary>
            <h3>새 시연 조건</h3>
            <label>
              설비 부하 선택
              <select
                value={load}
                disabled={locked}
                onChange={(e) => setLoad(Number(e.target.value))}
              >
                <option value={1}>높은 부하 · 냉각 위험 확인</option>
                <option value={0.6}>낮은 부하 · 승인 흐름 체험</option>
              </select>
            </label>
            <div className="demo-options">
              <button
                className={speed === 60 ? "selected" : ""}
                aria-pressed={speed === 60}
                disabled={locked}
                onClick={() => setSpeed(60)}
              >
                <strong>60%</strong>
                <span>위험 조건 차단 사례</span>
              </button>
              <button
                className={speed === 80 ? "selected" : ""}
                aria-pressed={speed === 80}
                disabled={locked}
                onClick={() => setSpeed(80)}
              >
                <strong>80%</strong>
                <span>부하에 따른 결과 비교</span>
              </button>
            </div>
            <p className="muted">
              처음에는 설비 준비를 누르세요. 준비 후 60초가 지나면 상태 다시
              읽기를 누르세요. 높은 부하에서는 80% 속도도 장기 냉각 위험으로
              차단될 수 있습니다.
            </p>
            <button
              className="full"
              disabled={locked}
              onClick={() =>
                void run(async () => {
                  await demoOnly();
                  const session = await api<Session>("/session", "approver");
                  if (session.role !== "approver")
                    throw new Error("승인 담당자 토큰이 필요합니다.");
                  await api<Snapshot>("/demo/reset", "approver", {});
                  setPlant(
                    await api<Snapshot>("/demo/state", "approver", {
                      load_ratio: load,
                      sensor_quality: "valid",
                    }),
                  );
                  setRow(null);
                  setFromDatabase(false);
                  setConfirmed(false);
                })
              }
            >
              선택한 부하로 설비 준비
            </button>
            <p className="muted">
              가상 설비만 초기화합니다. 기록은 유지되며 이전 승인은 재검증이
              필요할 수 있습니다.
            </p>
            <button
              className="full"
              disabled={locked}
              onClick={() =>
                void run(async () => {
                  await demoOnly();
                  setPlant(await api<Snapshot>("/demo/sample", "approver", {}));
                  setConfirmed(false);
                })
              }
            >
              가상 상태 다시 읽기
            </button>
            <p className="muted">
              가상 센서의 관측 시각을 갱신합니다. 저장된 과거 결과를 수정하거나
              설비를 초기화하지 않습니다.
            </p>
            <button
              className="primary full"
              disabled={locked}
              onClick={() =>
                void run(async () => {
                  await demoOnly();
                  await api<Session>("/session", "operator");
                  const created = await api<Row>("/requests", "operator", {
                    purpose: `홈페이지 체험: 냉각 펌프 ${speed}% 변경 검토`,
                    command: { target_pct: speed, duration_s: 300 },
                  });
                  setRow(created);
                  setFromDatabase(false);
                  setConfirmed(false);
                  setRow(
                    await api<Row>(
                      `/requests/${created.id}/evaluate`,
                      "operator",
                      {},
                    ),
                  );
                })
              }
            >
              {locked ? "처리 중…" : `${speed}%로 새 가상 검토 시작`}
            </button>
          </details>
          <details>
            <summary>데모 연결 설정</summary>
            <label>
              요청 담당자 토큰
              <input
                type="password"
                value={operator}
                disabled={locked}
                autoComplete="off"
                onChange={(e) => {
                  setOperator(e.target.value);
                  setRow(null);
                  setConfirmed(false);
                }}
              />
            </label>
            <label>
              승인 담당자 토큰
              <input
                type="password"
                value={approver}
                disabled={locked}
                autoComplete="off"
                onChange={(e) => {
                  setApprover(e.target.value);
                  setConfirmed(false);
                }}
              />
            </label>
            <p className="muted">
              로컬 공개 데모 토큰을 사용합니다. 실제 담당자 신원 인증이 아니며
              토큰을 브라우저에 저장하지 않습니다.
            </p>
          </details>
          {plant && (
            <p className="demo-state">
              온도 {plant.temperature_c.toFixed(1)}°C · 부하 {plant.load_ratio}{" "}
              · 목표 속도 {plant.target_pump_speed_pct ?? plant.pump_speed_pct}%
            </p>
          )}
          <a href="#review">전체 검토 콘솔 열기 ↗</a>
        </div>
        <div className="demo-result" aria-live="polite">
          <div className="section-head">
            <h3>2. 저장 결과와 AI 피드백</h3>
            <span className={`badge ${row?.status || ""}`}>
              {row ? statusLabels[row.status] || row.status : "체험 대기"}
            </span>
          </div>
          {!row && (
            <div className="demo-empty">
              <strong>같은 요청도, 조건에 따라 결과가 달라집니다.</strong>
              <p>왼쪽에서 펌프 속도를 선택하고 가상 검토를 실행하세요.</p>
            </div>
          )}
          {row && (
            <>
              {fromDatabase && (
                <p className="demo-state">
                  DB 기록 조회 · {row.request.purpose}
                  <br />
                  {coolingSnapshot
                    ? `저장된 관측 시각: ${new Date(coolingSnapshot.observed_at * 1000).toLocaleString("ko-KR")}`
                    : report?.tep_simulation
                      ? "TEP 초기화 프로필을 사용한 저장 기록입니다. 현장 관측값은 없습니다."
                      : "아직 저장된 검토 보고서가 없습니다."}
                  <br />
                  당시 저장된 결과입니다. 아래 AI 피드백으로 설명을 받을 수
                  있습니다.
                </p>
              )}
              <p className="verdict">
                {report?.reason ||
                  (row.status === "evaluating"
                    ? "검토가 진행 중입니다."
                    : "저장된 검토 보고서가 없습니다. AI 피드백으로 현재 기록에 대한 설명을 받을 수 있습니다.")}
              </p>
              <p className="muted">
                요청 {row.id.slice(0, 8)} · {pumpCommand
                  ? `목표 ${pumpCommand.target_pct}%`
                  : "TEP 입력 변경"} ·{" "}
                {report?.reason_code || "검토 전"}
              </p>
              <dl>
                <dt>저장된 명령</dt>
                <dd>
                  {pumpCommand
                    ? `펌프 목표 속도 ${pumpCommand.target_pct}% · 예측 구간 ${pumpCommand.duration_s}초`
                    : "TEP 제어 입력 변경 요청"}
                </dd>
                <dt>가상 적용 기록</dt>
                <dd>
                  {appliedExecution
                    ? `가상 목표 속도 ${appliedExecution.command.target_pct}% 적용됨`
                    : row.execution?.status === "unknown"
                      ? "적용 결과 불명 · 다시 실행하지 마세요"
                      : "적용 기록 없음 · 계산 결과와 구분"}
                </dd>
                {appliedExecution && (
                  <>
                    <dt>적용 당시 상태</dt>
                    <dd>
                      온도 {appliedExecution.state.temperature_c}°C · 실제 가상
                      속도 {appliedExecution.state.pump_speed_pct}% · 목표 속도{" "}
                      {appliedExecution.state.target_pump_speed_pct ?? appliedExecution.command.target_pct}
                      %
                    </dd>
                  </>
                )}
              </dl>
              <button
                disabled={busy}
                onClick={() =>
                  void run(async () => {
                    setRow(await api<Row>(`/requests/${row.id}`, "operator"));
                  })
                }
              >
                저장된 결과 다시 확인
              </button>
              {!report && row.status !== "evaluating" && (
                <button
                  disabled={busy}
                  onClick={() =>
                    void run(async () => {
                      await demoOnly();
                      setRow(
                        await api<Row>(
                          `/requests/${row.id}/evaluate`,
                          "operator",
                          {},
                        ),
                      );
                    })
                  }
                >
                  현재 설비 상태로 이 요청 검토
                </button>
              )}
            </>
          )}
          {report?.simulation && (
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>조건</th>
                    <th>기존 최고 온도</th>
                    <th>변경 최고 온도</th>
                    <th>제한</th>
                  </tr>
                </thead>
                <tbody>
                  {report.simulation.scenarios.map((s) => (
                    <tr key={s.kind}>
                      <td>
                        {s.kind === "normal" ? "정상 냉각" : "냉각 효율 저하"}
                      </td>
                      <td>{s.baseline_peak_c.toFixed(2)}°C</td>
                      <td className={s.exceeded ? "danger-text" : ""}>
                        {s.candidate_peak_c.toFixed(2)}°C
                      </td>
                      <td>
                        {s.limit_c}°C ·{" "}
                        {s.exceeded || s.baseline_peak_c > s.limit_c
                          ? "초과"
                          : "이내"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="muted">{report.simulation.limitation}</p>
            </div>
          )}
          {row && <RecordFeedback record={row} token={operator} />}
          {report?.reason_code === "INVALID_STATE" && (
            <aside className="evidence-hold">
              <h3>왜 검토가 멈췄나요?</h3>
              <p>
                {coolingSnapshot?.sensor_quality !== "valid"
                  ? "당시 센서 품질이 불량했습니다."
                  : coolingSnapshot?.domain_status !== "ready"
                    ? "당시 상태가 모델이 지원하는 범위를 벗어났습니다."
                    : "센서와 모델 범위는 유효합니다. 당시 관측 시각이 60초 유효 시간을 벗어났거나 서버 시각보다 미래였기 때문에 검토가 시작되지 않았습니다."}
              </p>
              <p>
                이 기록은 AI 피드백으로 설명받을 수 있습니다. 새 계산이 필요하면
                왼쪽에서 가상 상태를 다시 읽고 새 요청을 시작하세요.
              </p>
            </aside>
          )}
          {report && (
            <>
              <div className="demo-evidence">
                <EvidencePanel report={report} record={row} />
              </div>
              <div className="demo-judgment">
                <h3>3. 담당자 판단</h3>
                <p className="muted">
                  결과와 모델 한계를 확인한 뒤 승인하세요. 서버가
                  역할·보고서·상태·만료를 다시 확인합니다.
                </p>
                <label>
                  판단 이유
                  <textarea
                    maxLength={500}
                    value={reason}
                    disabled={busy}
                    onChange={(e) => setReason(e.target.value)}
                    placeholder="시험 결과와 모델의 한계를 확인한 내용을 적어주세요."
                  />
                </label>
                <label className="check">
                  <input
                    type="checkbox"
                    checked={confirmed}
                    disabled={busy}
                    onChange={(e) => setConfirmed(e.target.checked)}
                  />
                  명령과 검토 결과, 근거 및 합성 모델의 한계를 확인했습니다.
                </label>
                <div className="actions">
                  <button
                    className="primary"
                    disabled={
                      locked ||
                      row?.status !== "awaiting_approval" ||
                      !report.can_approve ||
                      !confirmed ||
                      !reason.trim() ||
                      !fresh
                    }
                    onClick={() =>
                      void run(async () => {
                        await demoOnly();
                        setRow(
                          await api<Row>(
                            `/requests/${row!.id}/decisions`,
                            "approver",
                            {
                              decision: "approve",
                              report_digest: report.digest,
                              reason: reason.trim(),
                            },
                          ),
                        );
                      })
                    }
                  >
                    담당자로 가상 명령 승인
                  </button>
                  <button
                    disabled={locked || row?.status !== "approved"}
                    onClick={() =>
                      void run(async () => {
                        await demoOnly();
                        const next = await api<Row>(
                          `/requests/${row!.id}/execute`,
                          "approver",
                          { report_digest: report.digest },
                        );
                        setRow(next);
                        setPlant(await api<Snapshot>("/state", "approver"));
                      })
                    }
                  >
                    승인한 가상 명령 적용
                  </button>
                </div>
                {row?.status === "awaiting_approval" && !fresh && (
                  <p className="danger-text">
                    관측 시각이 오래됐습니다. 초기 상태 준비 후 새 요청을
                    검토하세요.
                  </p>
                )}
                {row?.status === "blocked" && (
                  <p className="danger-text">
                    차단된 요청은 승인할 수 없습니다. 조건을 변경해 새로
                    검토하세요.
                  </p>
                )}
                {row?.execution?.status === "applied" && (
                  <p className="demo-success">
                    가상 목표 속도를 적용했습니다. 실제 설비에는 명령을 보내지
                    않았습니다.
                  </p>
                )}
                <p className="muted">
                  모델 {report.model_version} · 실행 범위{" "}
                  {report.execution_scope} · 합성 데이터
                </p>
              </div>
            </>
          )}
          {error && (
            <p role="alert" className="error">
              {error}
            </p>
          )}
        </div>
      </div>
    </section>
  );
}
