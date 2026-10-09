import React, { useState } from "react";
import { createRoot } from "react-dom/client";
import "./style.css";

type Row = {
  id: string;
  status: string;
  request: { command: { target_pct: number } };
  report: null | {
    digest: string;
    reason: string;
    mock: boolean;
    simulation: null | {
      limitation: string;
      scenarios: {
        kind: string;
        baseline_peak_c: number;
        candidate_peak_c: number;
        exceeded: boolean;
      }[];
    };
    evidence: null | {
      limitation: string;
      cards: { title: string; claim: string; locator: string }[];
    };
  };
  events: { kind: string; at: number }[];
  execution: unknown;
};
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
  const [token, setToken] = useState("local-operator");
  const [speed, setSpeed] = useState(60);
  const [row, setRow] = useState<Row | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [reason, setReason] = useState("모의 보고서 확인");
  async function api(path: string, body?: unknown) {
    const r = await fetch("/api" + path, {
      method: body === undefined ? "GET" : "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
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
        개발 골격 · 실제 장비 미연결 · 합성 상태 · 시뮬레이션/근거 검토는 고정
        모의 응답입니다.
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
          요청: local-operator / 승인: local-approver — 로컬 시연용 공개 토큰
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
          모의 사례: 60%는 반례 시험 차단, 80%는 모의 승인 가능. 실제 물리
          계산이 아닙니다.
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
            <strong>{row.report?.reason}</strong>
            {row.report?.simulation && (
              <>
                <table>
                  <thead>
                    <tr>
                      <th>모의 조건</th>
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
                        <td>{s.exceeded ? "한계 초과" : "모의 통과"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <p className="muted">{row.report.simulation.limitation}</p>
              </>
            )}
            {row.report?.evidence?.cards.map((c) => (
              <article key={c.title}>
                <h3>{c.title}</h3>
                <p>{c.claim}</p>
                <small>원본 위치: {c.locator} · 적용 조건 확인 불가</small>
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
                disabled={busy || row.status !== "awaiting_approval"}
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
                disabled={busy || row.status !== "awaiting_approval"}
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
            <button
              disabled={busy}
              onClick={() =>
                run(async () => {
                  await api("/demo/state", {
                    load_ratio: 1.2,
                    sensor_quality: "valid",
                  });
                })
              }
            >
              데모: 부하 변경하여 기존 승인 무효화
            </button>
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
