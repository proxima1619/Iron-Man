import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "./style.css";

import type { components } from "./api.generated";

type Row = components["schemas"]["RequestRecord"];
type PlantState = components["schemas"]["Snapshot"];
const labels: Record<string, string> = {
  draft: "접수",
  evaluating: "검토 중",
  blocked: "차단",
  hold: "보류",
  awaiting_approval: "승인 대기",
  approved: "승인 완료",
  rejected: "거절",
  revalidation_required: "재검증 필요",
  executing: "실행 중",
  completed: "가상 적용 완료",
  execution_unknown: "실행 결과 불명",
};
function App() {
  const [token, setToken] = useState("");
  const [speed, setSpeed] = useState(60);
  const [row, setRow] = useState<Row | null>(null);
  const [plant, setPlant] = useState<PlantState | null>(null);
  const [savedRows, setSavedRows] = useState<Row[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [reason, setReason] = useState("모의 보고서 확인");
  async function api(
    path: string,
    body?: unknown,
    method: "GET" | "POST" = body === undefined ? "GET" : "POST",
  ) {
    const r = await fetch("/api" + path, {
      method,
      headers: {
        "Content-Type": "application/json",
        "X-Iron-Man-Token": token,
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const data = await r.json();
    if (!r.ok)
      throw new Error(
        typeof data.detail === "string"
          ? data.detail
          : JSON.stringify(data.detail),
      );
    return data;
  }
  useEffect(() => {
    if (!token) {
      setPlant(null);
      return;
    }
    let active = true;
    api("/state")
      .then((state) => {
        if (active) {
          setPlant(state);
          setError("");
        }
      })
      .catch((e) => {
        if (active) setError(e instanceof Error ? e.message : "상태 조회 오류");
      });
    return () => {
      active = false;
    };
  }, [token]);
  useEffect(() => {
    if (!row || row.status !== "evaluating") return;
    const requestId = row.id;
    const controller = new AbortController();
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const response = await fetch(`/api/requests/${requestId}`, {
          headers: { "X-Iron-Man-Token": token },
          signal: controller.signal,
        });
        if (!response.ok) throw new Error("평가 상태 조회 실패");
        const next: Row = await response.json();
        if (stopped) return;
        setRow((current) => (current?.id === requestId ? next : current));
        setError("");
        if (next.status !== "evaluating") return;
      } catch {
        if (stopped) return;
        setError("평가 상태를 가져오지 못했습니다. 연결·토큰을 확인하세요.");
      }
      timer = setTimeout(poll, 1000);
    }
    timer = setTimeout(poll, 300);
    return () => {
      stopped = true;
      controller.abort();
      clearTimeout(timer);
    };
  }, [row?.id, row?.status, token]);
  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError("");
    try {
      await action();
    } catch (e) {
      setError(e instanceof Error ? e.message : "오류");
      if (row) {
        try {
          setRow(await api(`/requests/${row.id}`));
        } catch {}
      }
    } finally {
      try {
        setPlant(await api("/state"));
      } catch (e) {
        setError(
          (current) =>
            current || (e instanceof Error ? e.message : "상태 조회 오류"),
        );
      }
      setBusy(false);
    }
  }
  const post = (suffix: string, body: unknown = {}) =>
    run(async () => setRow(await api(`/requests/${row!.id}/${suffix}`, body)));
  return (
    <main>
      <header>
        <span className="eyebrow">IRON MAN / TEAM SCAFFOLD</span>
        <h1>설비 변경 요청 안전 관문</h1>
        <p>요청을 검토하고, 담당자가 승인한 명령만 가상 설비에 적용합니다.</p>
      </header>
      <aside>
        개발 중 · 실제 장비 미연결 · 합성 상태와 단순 열수지 계산 · 근거 검토
        방식은 보고서에 표시됩니다.
      </aside>
      <section>
        <h2>1. 요청</h2>
        <label>
          데모 인증 토큰{" "}
          <input
            type="password"
            value={token}
            onChange={(e) => setToken(e.target.value)}
          />
        </label>
        <p className="muted">
          서버 담당자가 제공한 요청 또는 승인 토큰을 입력하세요. 로컬 개발
          기본값: local-operator / local-approver
        </p>
        <label>
          목표 펌프 속도 (%){" "}
          <input
            type="number"
            min="0"
            max="100"
            value={speed}
            onChange={(e) => setSpeed(Number(e.target.value))}
          />
        </label>
        <p className="muted">
          초기 부하 1에서는 80%도 장기 위험으로 차단됩니다. 부하를 0.6으로 설정한
          80% 요청은 가상 설비 정책을 통과하면 담당자 승인 대기가 됩니다.
          요청 예측 300초 외에 3600초·평형 온도·계수 민감도를 검사합니다. 가상 적용한 목표 속도는 다음 명령까지
          유지됩니다.
        </p>
        <button
          disabled={busy}
          onClick={() =>
            run(async () => {
              const created = await api("/requests", {
                command: {
                  type: "set_pump_speed",
                  target_pct: speed,
                  duration_s: 300,
                },
              });
              setRow(created);
              setRow(await api(`/requests/${created.id}/evaluate`, {}));
            })
          }
        >
          새 요청 만들고 검토
        </button>
      </section>
      <section aria-labelledby="plant-heading">
        <h2 id="plant-heading">현재 가상 설비 상태</h2>
        <p className="muted">
          합성 냉각 설비 · 수동 가상 시간. 시간 진행 버튼을 눌렀을 때만 온도와
          실제 펌프 속도가 계산됩니다. 서버를 껐다 켜도 저장된 상태에서
          이어집니다. 실제 장비와 연결되어 있지 않습니다.
        </p>
        {plant ? (
          <>
            <dl className="plant-stats">
              <div>
                <dt>온도</dt>
                <dd>{plant.temperature_c.toFixed(2)} °C</dd>
              </div>
              <div>
                <dt>실제 펌프 속도</dt>
                <dd>{plant.pump_speed_pct.toFixed(2)} %</dd>
              </div>
              <div>
                <dt>목표 펌프 속도</dt>
                <dd>
                  {(
                    plant.target_pump_speed_pct ?? plant.pump_speed_pct
                  ).toFixed(2)}{" "}
                  %
                </dd>
              </div>
              <div>
                <dt>부하</dt>
                <dd>{plant.load_ratio.toFixed(2)}</dd>
              </div>
              <div>
                <dt>누적 가상 시간</dt>
                <dd>{plant.simulation_time_s.toFixed(0)} 초</dd>
              </div>
              <div>
                <dt>상태 버전</dt>
                <dd>{plant.revision}</dd>
              </div>
            </dl>
            <p>
              모델: {plant.model_version || "미기록"} · 계산 범위:{" "}
              {plant.domain_status === "ready" ? "지원됨" : "지원 불가"} · 센서
              상태: {plant.sensor_quality === "valid" ? "유효" : "무효"}
            </p>
            {plant.domain_reason && (
              <p role="alert" className="error">
                {plant.domain_reason}
              </p>
            )}
            <p className="muted">
              마지막 관측: {new Date(plant.observed_at * 1000).toLocaleString()}
              {plant.calculated_at != null && (
                <>
                  {" "}
                  · 마지막 계산:{" "}
                  {new Date(plant.calculated_at * 1000).toLocaleString()}
                </>
              )}
              . 상태 조회는 관측 시각을 갱신하지 않습니다.
            </p>
          </>
        ) : (
          <p>가상 상태를 불러오세요.</p>
        )}
        <div className="actions">
          <button
            disabled={busy}
            onClick={() =>
              run(async () => {
                setPlant(await api("/state"));
              })
            }
          >
            상태 조회
          </button>
          <button
            disabled={busy || !plant || plant.domain_status !== "ready"}
            onClick={() =>
              run(async () => {
                setPlant(await api("/demo/advance", { seconds_s: 10 }));
              })
            }
          >
            가상 시간 10초 진행
          </button>
          <button
            disabled={busy || !plant}
            onClick={() =>
              run(async () => {
                setPlant(await api("/demo/sample", undefined, "POST"));
              })
            }
          >
            관측 갱신
          </button>
          <button
            disabled={busy || !plant || plant.domain_status !== "ready"}
            onClick={() =>
              run(async () => {
                setPlant(
                  await api("/demo/state", {
                    load_ratio: 1.2,
                    sensor_quality: "valid",
                  }),
                );
              })
            }
          >
            데모 부하 1.2로 변경
          </button>
          <button
            disabled={busy || !plant}
            onClick={() =>
              run(async () => {
                setPlant(await api("/demo/reset", undefined, "POST"));
              })
            }
          >
            가상 설비 초기화
          </button>
          <button
            disabled={busy || !plant || plant.domain_status !== "ready"}
            onClick={() => run(async () => {
              setPlant(await api("/demo/state", { load_ratio: .6, sensor_quality: "valid" }));
            })}
          >
            데모 부하 0.6으로 변경
          </button>
        </div>
        <p className="muted">
          시간 진행·관측 갱신·부하 변경·초기화는 승인자 토큰이 필요합니다.
          초기화는 설비를 60°C·속도 100%·부하 1로 되돌리며 요청과 처리 기록을
          유지합니다. 승인 뒤 설비 상태가 달라지면 적용 시 재검증을 요구합니다.
          관측 후 60초가 지나 검토가 보류되면 관측 갱신 후 재검증하세요.
        </p>
      </section>
      <section>
        <h2>저장된 요청</h2>
        <p className="muted">
          서버를 다시 시작해도 같은 SQLite 파일의 기록을 불러올 수 있습니다.
        </p>
        <button
          disabled={busy}
          onClick={() =>
            run(async () => {
              setSavedRows(await api("/requests"));
            })
          }
        >
          저장된 요청 불러오기
        </button>
        <ul>
          {savedRows.map((saved) => (
            <li key={saved.id}>
              <button
                disabled={busy}
                onClick={() =>
                  run(async () => {
                    setRow(await api(`/requests/${saved.id}`));
                  })
                }
              >
                {saved.request.command.target_pct}% · {labels[saved.status]} ·{" "}
                {saved.id.slice(0, 8)}
              </button>
            </li>
          ))}
        </ul>
      </section>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {row && (
        <>
          <section>
            <h2>
              2. 검토 보고서{" "}
              <span className="badge">{labels[row.status] || row.status}</span>
            </h2>
            <p>
              요청 속도: {row.request.command.target_pct}% · 요청 ID: {row.id}
            </p>
            {row.status === "evaluating" && (
              <div role="status" aria-live="polite">
                <p>
                  검토 중입니다. 결과를 자동으로 갱신합니다. 다른 요청도 생성할
                  수 있습니다.
                </p>
                <p className="muted">
                  평가 ID: {row.evaluation?.id} · 제한 시각:{" "}
                  {row.evaluation
                    ? new Date(
                        row.evaluation.deadline_at * 1000,
                      ).toLocaleTimeString()
                    : "—"}
                </p>
                <button
                  disabled={busy}
                  onClick={() => post("evaluation/cancel")}
                >
                  평가 취소
                </button>
              </div>
            )}
            <strong>{row.report?.reason}</strong>
            {row.report && (
              <p className="muted">
                실행 범위: {row.report.execution_scope === "virtual" ? "가상 설비 전용" : "미설정"}
                {" · "}모델: {row.report.model_version}{" · "}정책: {row.report.policy_version}
                {" · "}실제 설비 안전 승인이 아닙니다.
              </p>
            )}
            {row.report?.simulation && (
              <>
                <table>
                  <thead>
                    <tr>
                      <th>시험 조건</th>
                      <th>변경 전 최고 °C</th>
                      <th>변경 후 최고 °C</th>
                      <th>결과</th>
                    </tr>
                  </thead>
                  <tbody>
                    {row.report.simulation.scenarios.map((s) => (
                      <tr key={s.kind}>
                        <td>{s.kind}</td>
                        <td>{s.baseline_peak_c}</td>
                        <td>{s.candidate_peak_c}</td>
                        <td>{s.exceeded ? "한계 초과" : "계산상 한계 이내"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <p className="muted">{row.report.simulation.limitation}</p>
              </>
            )}
            {row.report?.evidence && (
              <p>
                근거 검토:{" "}
                {row.report.evidence.mock
                  ? "모의 응답"
                  : "LLM 검토 경로 · 출처 수집 방식은 아래 설명 참조"}{" "}
                · {row.report.evidence.status}
              </p>
            )}
            {row.report?.evidence?.cards.map((c) => (
              <article key={c.title}>
                <h3>{c.title}</h3>
                {c.source_url && <a href={c.source_url} target="_blank" rel="noopener noreferrer">논문·출처 원문 열기</a>}
                <p>{c.claim}</p>
                <small>
                  원본 위치: {c.locator} · {c.stance} · 적용 조건:{" "}
                  {c.applicability || "unknown"}
                </small>
                {c.excerpt && <blockquote>{c.excerpt}</blockquote>}
                {!!c.matched_conditions?.length && (
                  <p>일치 조건: {c.matched_conditions.join(" / ")}</p>
                )}
                {!!c.missing_conditions?.length && (
                  <p>미확인 조건: {c.missing_conditions.join(" / ")}</p>
                )}
              </article>
            ))}
            <p className="muted">{row.report?.evidence?.limitation}</p>
          </section>
          <section>
            <h2>3. 담당자 판단과 가상 실행</h2>
            <label>
              판단 이유{" "}
              <input
                value={reason}
                onChange={(e) => setReason(e.target.value)}
              />
            </label>
            <div className="actions">
              <button
                disabled={
                  busy ||
                  row.status !== "awaiting_approval" ||
                  !row.report?.can_approve
                }
                onClick={() =>
                  post("decisions", {
                    decision: "approve",
                    report_digest: row.report?.digest,
                    reason,
                  })
                }
              >
                승인
              </button>
              <button
                disabled={
                  busy ||
                  row.status !== "awaiting_approval" ||
                  !row.report?.can_approve
                }
                onClick={() =>
                  post("decisions", {
                    decision: "reject",
                    report_digest: row.report?.digest,
                    reason,
                  })
                }
              >
                거절
              </button>
              <button
                disabled={busy || row.status !== "approved"}
                onClick={() =>
                  post("execute", { report_digest: row.report?.digest })
                }
              >
                가상 설비에 적용
              </button>
              <button
                disabled={
                  busy ||
                  ![
                    "revalidation_required",
                    "hold",
                    "blocked",
                    "rejected",
                  ].includes(row.status)
                }
                onClick={() => post("evaluate")}
              >
                재검증
              </button>
            </div>
            <p className="muted">
              승인 시 승인자 토큰으로 변경하세요. 서버가 역할과 승인 유효성을
              다시 확인합니다.
            </p>
            {row.execution != null && (
              <pre>{JSON.stringify(row.execution, null, 2)}</pre>
            )}
          </section>
          <section>
            <h2>처리 기록</h2>
            <ol>
              {row.events.map((e, i) => (
                <li key={i}>
                  {new Date(e.at * 1000).toLocaleTimeString()} — {e.kind}
                </li>
              ))}
            </ol>
          </section>
        </>
      )}
      <footer>1번 gateway · 2번 simulator · 3번 evidence · 4번 frontend</footer>
    </main>
  );
}
createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
