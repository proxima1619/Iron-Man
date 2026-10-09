import { useEffect, useState } from "react";
import type { components } from "./api.generated";
import { EvidencePanel } from "./EvidencePanel";

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
  const locked = busy || row?.status === "evaluating";
  const age = report ? now - report.snapshot.observed_at : Infinity;
  const fresh = age >= 0 && age <= 60;
  return (
    <section className="demo-experience" id="demo" aria-labelledby="demo-title">
      <div className="demo-heading">
        <div>
          <p className="home-kicker">INTERACTIVE DEMO</p>
          <h2 id="demo-title">지금, 변경 요청을 검토해 보세요.</h2>
          <p>
            합성 냉각 설비에서 요청·검토·담당자 승인·가상 적용을 직접
            체험합니다.
          </p>
        </div>
        <span className="badge">실제 설비 미연결</span>
      </div>
      <div className="demo-layout">
        <div className="demo-controls">
          <div className="demo-database">
            <h3>저장된 데이터로 확인</h3>
            <p className="muted">
              SQLite에 저장된 요청·스냅샷·계산 결과를 선택합니다. 저장 데이터는
              합성 시연 기록입니다.
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
              데이터베이스 기록 불러오기
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
                        setSpeed(stored.request.command.target_pct);
                      });
                  }}
                >
                  <option value="">기록을 선택하세요</option>
                  {savedRows.map((stored) => (
                    <option value={stored.id} key={stored.id}>
                      {stored.request.command.target_pct}% ·{" "}
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
          <h3>1. 시연 조건 선택</h3>
          <label>
            준비할 부하 비율
            <select
              value={load}
              disabled={locked}
              onChange={(e) => setLoad(Number(e.target.value))}
            >
              <option value={1}>1.0 · 장기 위험 검토</option>
              <option value={0.6}>0.6 · 가상 승인 흐름 검토</option>
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
              <span>장기 위험·승인 검토</span>
            </button>
          </div>
          <p className="muted">
            먼저 초기 상태로 준비하세요. 최신 정책은 300초·3600초·평형·계수
            민감도를 확인합니다. 부하 1에서는 80%도 차단될 수 있습니다.
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
            초기 상태로 준비
          </button>
          <p className="muted">
            가상 설비만 초기화합니다. 기록은 유지되며 이전 승인은 재검증이
            필요할 수 있습니다.
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
            {locked ? "처리 중…" : `${speed}% 요청 가상 검토`}
          </button>
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
            <h3>2. 검토 결과</h3>
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
                  {report
                    ? `저장된 관측 시각: ${new Date(report.snapshot.observed_at * 1000).toLocaleString("ko-KR")}`
                    : "아직 저장된 검토 보고서가 없습니다."}
                  <br />
                  현재 설비를 새로 계산한 결과와 구분합니다.
                </p>
              )}
              <p className="verdict">
                {report?.reason || "검토 결과를 기다리고 있습니다."}
              </p>
              <p className="muted">
                요청 {row.id.slice(0, 8)} · 목표{" "}
                {row.request.command.target_pct}% ·{" "}
                {report?.reason_code || "검토 전"}
              </p>
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
