import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "./style.css";

import type { components } from "./api.generated";

type Row = components["schemas"]["RequestRecord"];
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
  const [savedRows, setSavedRows] = useState<Row[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [reason, setReason] = useState("모의 보고서 확인");
  async function api(path: string, body?: unknown) {
    const r = await fetch("/api" + path, {
      method: body === undefined ? "GET" : "POST",
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
          서버 담당자가 제공한 요청 또는 승인 토큰을 입력하세요.
          로컬 개발 기본값: local-operator / local-approver
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
          현재 합성 상태 예시: 60%는 위험 시험 차단, 80%는 승인 정책 미설정으로
          보류됩니다. 현장 검증 결과가 아닙니다.
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
            {row.report?.evidence && <p>근거 검토: {row.report.evidence.mock
              ? "모의 응답" : "LLM 검토 경로 · 사전 수집 문서"} · {row.report.evidence.status}</p>}
            {row.report?.evidence?.cards.map((c) => (
              <article key={c.title}>
                <h3>{c.title}</h3>
                <p>{c.claim}</p>
                <small>원본 위치: {c.locator} · {c.stance} · 적용 조건: {c.applicability || "unknown"}</small>
                {c.excerpt && <blockquote>{c.excerpt}</blockquote>}
                {!!c.matched_conditions?.length && <p>일치 조건: {c.matched_conditions.join(" / ")}</p>}
                {!!c.missing_conditions?.length && <p>미확인 조건: {c.missing_conditions.join(" / ")}</p>}
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
