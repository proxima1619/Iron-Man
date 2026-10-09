import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import type { components } from "./api.generated";
import "./style.css";
import { VirtualPlant } from "./VirtualPlant";
import { TepResults } from "./TepResults";
import { Home } from "./Home";
import { DemoPage } from "./DemoPage";
import { EvidencePanel } from "./EvidencePanel";
import { RecordFeedback } from "./RecordFeedback";

type Row = components["schemas"]["RequestRecord"];
type Session = components["schemas"]["SessionInfo"];
type Note = components["schemas"]["Notification"];
type History = components["schemas"]["RequestHistory"];
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
  normal: "정상 냉각",
  degraded_cooling: "냉각 효율 저하",
  support: "지지 근거",
  counter: "반대·실패 조건",
  limitation: "한계",
  applicable: "조건 일치",
  partial: "일부 일치",
  mismatch: "조건 불일치",
  unknown: "미확인",
  team_authored_fixture: "팀 작성 모의 자료",
  team_authored_demo: "팀 작성 데모 자료",
  paper: "논문",
  manual: "매뉴얼",
  field_record: "현장 기록",
  not_configured: "알림 설정 필요",
  queued: "발송 대기",
  sending: "발송 중",
  sent: "SMTP 접수",
  within_tolerance: "편차 기준 이내",
  material_deviation: "편차 기준 초과",
  threshold_not_configured: "편차 기준 미설정",
};
const label = (key: string) => labels[key] || key;
const date = (s: number) => new Date(s * 1000).toLocaleString("ko-KR");
const num = (n: number) => n.toFixed(2);
const commandLabel = (command: Row["request"]["command"]) => command.type === "set_pump_speed"
  ? `${command.target_pct}% 펌프 속도` : `${command.variable} = ${command.value} percent_full_scale`;
function safeUrl(value?: string | null) {
  try {
    const u = new URL(value || "");
    return ["http:", "https:"].includes(u.protocol) ? u.href : null;
  } catch {
    return null;
  }
}
function App() {
  const [token, setToken] = useState(""),
    [session, setSession] = useState<Session | null>(null);
  const [rows, setRows] = useState<Row[]>([]),
    [row, setRow] = useState<Row | null>(null);
  const [history, setHistory] = useState<History | null>(null),
    [notes, setNotes] = useState<Note[]>([]);
  const [contact, setContact] = useState<string | null>(null),
    [speed, setSpeed] = useState(80),
    [duration, setDuration] = useState(600);
  const [model, setModel] = useState<"tep" | "cooling">("tep");
  const [tepVariable, setTepVariable] = useState<"XMV10" | "XMV11">("XMV10");
  const [tepValue, setTepValue] = useState(42), [samplePeriod, setSamplePeriod] = useState(10);
  const [purpose, setPurpose] = useState(
      "TEP 냉각수 입력 변경의 공정 영향 비교"
    ),
    [email, setEmail] = useState("");
  const [reason, setReason] = useState(""),
    [confirmed, setConfirmed] = useState(false),
    [busy, setBusy] = useState(false);
  const [error, setError] = useState(""),
    [now, setNow] = useState(Date.now() / 1000);
  const report = row?.report,
    approver = session?.role === "approver";
  const coolingSnapshot = report && "temperature_c" in report.snapshot ? report.snapshot : null;
  const snapshotTime = report ? ("observed_at" in report.snapshot ? report.snapshot.observed_at : report.snapshot.configured_at) : 0;
  const age = now - snapshotTime;
  const fresh = !!coolingSnapshot && age >= 0 && age <= 60;
  const pending = row?.status === "awaiting_approval" && report?.can_approve;
  const locked =
    !!row &&
    ["evaluating", "executing", "completed", "execution_unknown"].includes(
      row.status,
    );
  async function api<T>(path: string, body?: unknown): Promise<T> {
    const controller = new AbortController(),
      timer = window.setTimeout(() => controller.abort(), 30000);
    try {
      const response = await fetch("/api" + path, {
        method: body === undefined ? "GET" : "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Iron-Man-Token": token,
        },
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: controller.signal,
      });
      const data = await response.json();
      if (!response.ok)
        throw new Error(
          typeof data.detail === "string"
            ? data.detail
            : JSON.stringify(data.detail),
        );
      return data as T;
    } catch (e) {
      if (e instanceof DOMException && e.name === "AbortError")
        throw new Error(
          "응답 시간 초과. 저장된 상태를 새로고침해 처리 결과를 확인하세요.",
        );
      throw e;
    } finally {
      window.clearTimeout(timer);
    }
  }
  async function details(value: Row, current = session) {
    setRow(value);
    setConfirmed(false);
    setHistory(null);
    setNotes([]);
    setContact(null);
    setHistory(await api<History>(`/requests/${value.id}/history`));
    if (current?.role === "approver") {
      const [messages, owner] = await Promise.all([
        api<Note[]>(`/requests/${value.id}/notifications`),
        api<{ requester_contact: string | null }>(
          `/requests/${value.id}/review-contact`,
        ),
      ]);
      setNotes(messages);
      setContact(owner.requester_contact);
    }
  }
  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError("");
    try {
      await action();
    } catch (e) {
      setError(e instanceof Error ? e.message : "처리 실패");
      if (row)
        try {
          await details(await api<Row>(`/requests/${row.id}`));
        } catch {
          /* Preserve the report and show the failure. */
        }
    } finally {
      setBusy(false);
    }
  }
  async function connect() {
    const current = await api<Session>("/session");
    setSession(current);
    setRows(await api<Row[]>("/requests"));
    if (row) await details(await api<Row>(`/requests/${row.id}`), current);
  }
  async function refresh(value: Row) {
    await details(value);
    setRows(await api<Row[]>("/requests"));
  }
  const post = (suffix: string, body: unknown = {}) =>
    run(async () => {
      if (row)
        await refresh(await api<Row>(`/requests/${row.id}/${suffix}`, body));
    });
  const decision = (value: "approve" | "reject" | "request_retest") =>
    post("decisions", {
      decision: value,
      report_digest: report?.digest,
      reason: reason.trim(),
    });

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => window.clearInterval(timer);
  }, []);
  useEffect(() => {
    if (!row || row.status !== "evaluating" || !session) return;
    const id = row.id,
      controller = new AbortController();
    let stopped = false,
      timer = 0;
    async function poll() {
      try {
        const response = await fetch(`/api/requests/${id}`, {
          headers: { "X-Iron-Man-Token": token },
          signal: controller.signal,
        });
        if (!response.ok)
          throw new Error(
            "평가 상태 조회 실패. 연결을 확인하고 저장된 요청을 새로고침하세요.",
          );
        const value = (await response.json()) as Row;
        if (stopped) return;
        if (value.status !== "evaluating") {
          const history = await api<History>(`/requests/${id}/history`);
          const messages = approver
            ? await api<Note[]>(`/requests/${id}/notifications`)
            : [];
          if (stopped) return;
          setHistory(history);
          setNotes(messages);
          setRow(value);
          setConfirmed(false);
          setRows((previous) =>
            previous.map((saved) => (saved.id === id ? value : saved)),
          );
          return;
        }
        setRow(value);
      } catch (e) {
        if (!stopped)
          setError(e instanceof Error ? e.message : "평가 상태 조회 실패");
      }
      if (!stopped) timer = window.setTimeout(() => void poll(), 1000);
    }
    timer = window.setTimeout(() => void poll(), 500);
    return () => {
      stopped = true;
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [row?.id, row?.status, token, session?.role]);
  return (
    <main>
      <a className="console-home no-print" href="#home">
        ← 홈페이지
      </a>
      <header>
        <div>
          <span className="eyebrow">IRON MAN / OPERATOR REVIEW</span>
          <h1>변경 전에, 결과를 확인합니다.</h1>
          <p>TEP 제어 입력 비교 · 담당자 검토 · 실측 검증 미완료</p>
        </div>
        <div className="mode">
          SYNTHETIC DEMO<small>실제 설비 미연결</small>
        </div>
      </header>
      <aside>
        공개 TEP 외부 모델을 실행하는 시제품입니다. 결과는 시뮬레이션 데이터이며 현장 실측 검증은 미완료입니다.
        TEP 요청은 계산이 완료되어도 승인 정책 미설정으로 보류합니다.
      </aside>
      <section className="connection no-print">
        <div>
          <h2>접속과 저장 상태</h2>
          <p className="muted">
            {session
              ? `${session.actor_label} · ${
                  approver ? "승인 담당자" : "요청 담당자"
                } · SQLite 저장 연결`
              : "서버 인증 대기"}
          </p>
        </div>
        <label>
          데모 토큰
          <input
            type="password"
            autoComplete="off"
            value={token}
            disabled={busy}
            onChange={(e) => {
              setToken(e.target.value);
              setSession(null);
              setContact(null);
              setNotes([]);
              setConfirmed(false);
            }}
          />
        </label>
        <button disabled={busy || !token} onClick={() => void run(connect)}>
          연결 확인
        </button>
      </section>
      <p className="muted no-print">
        서버 담당자가 제공한 역할 토큰을 입력하세요. 로컬 기본값: local-operator
        / local-approver. 이메일 신원 인증이 아닙니다. 토큰은 브라우저 저장소에
        저장하지 않습니다.
      </p>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {model === "cooling" && <VirtualPlant
        token={token}
        approver={approver}
        onChanged={() => setConfirmed(false)}
      />}
      <div className="workspace">
        <nav className="sidebar no-print" aria-label="요청 목록">
          <section>
            <span className="eyebrow">01 / NEW REQUEST</span>
            <h2>변경 요청</h2>
            <form
              onSubmit={(e) => {
                e.preventDefault();
                void run(async () => {
                  const created = await api<Row>("/requests", {
                    purpose,
                    equipment_id: model === "tep" ? "tep-sim-01" : "cooling-demo-01",
                    command: model === "tep" ? {
                      type: "set_tep_cooling_water", variable: tepVariable, value: tepValue,
                      duration_s: duration, sample_period_s: samplePeriod,
                    } : {
                      type: "set_pump_speed",
                      target_pct: speed,
                      duration_s: duration,
                    },
                    ...(email ? { requester_contact: email } : {}),
                  });
                  setRow(created);
                  await refresh(
                    await api<Row>(`/requests/${created.id}/evaluate`, {}),
                  );
                });
              }}
            >
              <label>모델
                <select value={model} onChange={e => {
                  const next = e.target.value as "tep" | "cooling";
                  setModel(next); setDuration(next === "tep" ? 600 : 300);
                  setPurpose(next === "tep" ? "TEP 냉각수 입력 변경의 공정 영향 비교" : "냉각 펌프 속도 변경의 온도 영향 검토");
                }}>
                  <option value="tep">TEP 외부 시뮬레이터</option><option value="cooling">기존 합성 냉각 탱크</option>
                </select>
              </label>
              {model === "tep" ? <>
                <label>냉각수 입력
                  <select value={tepVariable} onChange={e => { setTepVariable(e.target.value as "XMV10" | "XMV11"); setTepValue(e.target.value === "XMV10" ? 42 : 19); }}>
                    <option value="XMV10">XMV10 · 반응기 냉각수</option><option value="XMV11">XMV11 · 응축기 냉각수</option>
                  </select>
                </label>
                <label>정규화 설정 (percent_full_scale)
                  <input required type="number" min="0" max="100" step="any" value={tepValue} onChange={e => setTepValue(Number(e.target.value))} />
                </label>
                <label>관측 주기 (초)
                  <input required type="number" min="1" max="60" step="1" value={samplePeriod} onChange={e => setSamplePeriod(Number(e.target.value))} />
                </label>
                <p className="muted">펌프 속도가 아닙니다. 기본 초기 상태의 개루프 시험이며 실제 계측 데이터와 안전 승인 정책은 없습니다.</p>
              </> : <label>
                목표 속도 (%)
                <input
                  required
                  type="number"
                  min="0"
                  max="100"
                  step="any"
                  value={speed}
                  onChange={(e) => setSpeed(Number(e.target.value))}
                />
              </label>}
              <label>
                예측 구간 (초)
                <input
                  required
                  type="number"
                  min="1"
                  max={model === "tep" ? "1800" : "3600"}
                  step="1"
                  value={duration}
                  onChange={(e) => setDuration(Number(e.target.value))}
                />
              </label>
              <label>
                변경 목적
                <textarea
                  required
                  maxLength={500}
                  value={purpose}
                  onChange={(e) => setPurpose(e.target.value)}
                />
              </label>
              <label>
                요청자 이메일 (선택)
                <input
                  type="email"
                  maxLength={254}
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="담당자가 연락할 주소"
                />
              </label>
              <p className="muted">
                연락처는 승인 담당자에게만 표시됩니다. 주소 소유 여부는 검증하지
                않습니다.
              </p>
              <button
                className="primary full"
                type="submit"
                disabled={busy || !session}
              >
                요청 생성 · 시뮬레이션 검토
              </button>
            </form>
          </section>
          <section>
            <div className="section-head">
              <h2>저장된 요청</h2>
              <button
                disabled={busy || !session}
                onClick={() =>
                  void run(async () => setRows(await api<Row[]>("/requests")))
                }
              >
                새로고침
              </button>
            </div>
            <div className="request-list">
              {!rows.length && <p className="muted">저장된 요청이 없습니다.</p>}
              {rows.map((saved) => (
                <button
                  key={saved.id}
                  className={`request-item ${
                    row?.id === saved.id ? "selected" : ""
                  }`}
                  disabled={busy || !session}
                  onClick={() =>
                    void run(async () =>
                      details(await api<Row>(`/requests/${saved.id}`)),
                    )
                  }
                >
                  <strong>
                    {commandLabel(saved.request.command)} ·{" "}
                    {saved.request.command.duration_s}초
                  </strong>
                  <small>
                    {label(saved.status)} · {saved.id.slice(0, 8)}
                  </small>
                </button>
              ))}
            </div>
          </section>
        </nav>
        <div className="review">
          {!row ? (
            <section className="empty">
              <span className="eyebrow">REVIEW CONSOLE</span>
              <h2>검토할 요청을 선택하세요.</h2>
              <p>같은 초기 상태에서 기준 입력과 변경 입력의 시뮬레이션 결과를 비교합니다.</p>
              {model === "tep" ? <p className="muted">TEP 외부 모델의 실제 실행 결과를 읽습니다. 실제 설비 계측값은 없으며, 승인·실행 정책은 아직 미설정입니다.</p> : <p className="muted">
                초기 부하 1에서는 80%도 장기 위험으로 차단됩니다. 부하 0.6의
                80% 요청은 모든 가상 검사를 통과하면 담당자 검토로 이어집니다.
                요청 300초 외에 3600초·평형 온도·계수 민감도를 검사합니다.
              </p>}
            </section>
          ) : (
            <>
              <section>
                <div className="section-head">
                  <div>
                    <span className="eyebrow">02 / DECISION REPORT</span>
                    <h2>{commandLabel(row.request.command)} 변경 검토</h2>
                  </div>
                  <span className={`badge ${row.status}`}>
                    {label(row.status)}
                  </span>
                </div>
                <p>{row.request.purpose}</p>
                <div className="facts">
                  <div>
                    <small>기존 목표 → 요청 목표</small>
                    <strong>
                      {row.request.command.type === "set_pump_speed" ? `${coolingSnapshot?.target_pump_speed_pct ?? coolingSnapshot?.pump_speed_pct ?? "—"}% → ${row.request.command.target_pct}%`
                        : `${report?.tep_simulation?.provenance?.initial_xmv[Number(row.request.command.variable.slice(3))-1] ?? "기본 초기 입력"} → ${row.request.command.value} percent_full_scale`}
                    </strong>
                  </div>
                  <div>
                    <small>예측 구간</small>
                    <strong>{row.request.command.duration_s}초</strong>
                  </div>
                  <div>
                    <small>{row.request.command.type === "set_pump_speed" ? "초기 온도 / 부하" : "초기 상태"}</small>
                    <strong>
                      {coolingSnapshot
                        ? `${num(coolingSnapshot.temperature_c)}°C / ${
                            coolingSnapshot.load_ratio
                          }`
                        : report && "profile" in report.snapshot ? report.snapshot.profile : "검토 전"}
                    </strong>
                  </div>
                </div>
                <p className="verdict">
                  {report?.reason ||
                    (row.status === "evaluating"
                      ? "별도 프로세스에서 검토 중입니다. 결과를 자동으로 갱신합니다."
                      : "검토 전입니다.")}
                </p>
                {row.status === "evaluating" && (
                  <div role="status" aria-live="polite">
                    <p className="muted">
                      평가 {row.evaluation?.id} · 제한 시각{" "}
                      {row.evaluation ? date(row.evaluation.deadline_at) : "—"}
                    </p>
                    <button
                      className="no-print"
                      disabled={busy || !session}
                      onClick={() => post("evaluation/cancel")}
                    >
                      평가 취소
                    </button>
                  </div>
                )}
                <p className="muted">
                  요청 {row.id} · 개정 {row.revision} ·{" "}
                  {report?.reason_code || "—"}
                </p>
              </section>
              {report?.tep_simulation && <TepResults result={report.tep_simulation} />}
              <section>
                <div className="section-head">
                  <h2>예상 효과와 위험 조건</h2>
                  <span className="eyebrow">PEAK TEMPERATURE / °C</span>
                </div>
                <p className="muted">
                  최고 온도 비교입니다. 현재 API에는 시계열이 없습니다.
                </p>
                {!!report?.simulation?.scenarios.length ? (
                  <>
                    <div className="legend">
                      <span>
                        <i className="baseline" />
                        기존 속도
                      </span>
                      <span>
                        <i className="candidate" />
                        요청 속도
                      </span>
                    </div>
                    {report.simulation.scenarios.map((s) => {
                      const scale =
                        Math.max(
                          100,
                          s.baseline_peak_c,
                          s.candidate_peak_c,
                          s.limit_c,
                        ) * 1.05;
                      return (
                        <article className="scenario" key={s.kind}>
                          <div className="section-head">
                            <h3>{label(s.kind)}</h3>
                            <strong
                              className={
                                s.exceeded || s.baseline_peak_c > s.limit_c
                                  ? "danger-text"
                                  : "muted"
                              }
                            >
                              {s.exceeded || s.baseline_peak_c > s.limit_c
                                ? "온도 한계 초과 · 승인 차단"
                                : "계산상 한계 이내"}
                            </strong>
                          </div>
                          {(
                            [
                              [s.baseline_peak_c, "baseline", "기존"],
                              [s.candidate_peak_c, "candidate", "변경"],
                            ] as const
                          ).map(([value, style, name]) => (
                            <div
                              className="bar"
                              key={style}
                              role="img"
                              aria-label={`${name} 최고 ${num(value)}도`}
                            >
                              <span
                                className={style}
                                style={{ width: `${(value / scale) * 100}%` }}
                              />
                              <b>{num(value)}°C</b>
                              <i
                                className="limit"
                                style={{
                                  left: `${(s.limit_c / scale) * 100}%`,
                                }}
                              />
                            </div>
                          ))}
                          <p className="muted">
                            0°C 기준 막대 · 제한 {num(s.limit_c)}°C · 절대 차이{" "}
                            {num(
                              Math.abs(s.candidate_peak_c - s.baseline_peak_c),
                            )}
                            °C ·{" "}
                            {s.value_origin === "model_calculation"
                              ? "모델 계산"
                              : "고정 모의 값"}
                            {s.evidence_id && (
                              <>
                                {" "}
                                ·{" "}
                                <a href={`#evidence-${s.evidence_id}`}>
                                  연결 근거
                                </a>
                              </>
                            )}
                          </p>
                        </article>
                      );
                    })}
                    <div className="table-scroll">
                      <table>
                        <thead>
                          <tr>
                            <th>조건</th>
                            <th>기존 최고</th>
                            <th>변경 최고</th>
                            <th>절대 차이</th>
                            <th>제한</th>
                          </tr>
                        </thead>
                        <tbody>
                          {report.simulation.scenarios.map((s) => (
                            <tr key={s.kind}>
                              <th>{label(s.kind)}</th>
                              <td>{num(s.baseline_peak_c)}°C</td>
                              <td>{num(s.candidate_peak_c)}°C</td>
                              <td>
                                {num(
                                  Math.abs(
                                    s.candidate_peak_c - s.baseline_peak_c,
                                  ),
                                )}
                                °C
                              </td>
                              <td>{num(s.limit_c)}°C</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </>
                ) : (
                  <p>
                    계산 결과가 없습니다. 입력 상태와 보류 사유를 확인하세요.
                  </p>
                )}
                <div className="annotation">
                  <h3>유의미한 편차 검토</h3>
                  <p>
                    {report?.assessment
                      ? `${label(report.assessment.status)} · 기준 ${
                          report.assessment.threshold_c === null
                            ? "미설정"
                            : `${report.assessment.threshold_c}°C`
                        }`
                      : "편차 평가 없음"}
                  </p>
                  <p className="muted">
                    {report?.assessment?.limitation ||
                      "지표·기준 합의가 필요합니다."}
                  </p>
                  <p>
                    기준 초과 편차는 지정 승인자의 검토 대상입니다. 온도 제한
                    초과·불량 센서·모델 범위 밖 결과는 예외 승인할 수 없습니다.
                  </p>
                </div>
              </section>
              {row && <RecordFeedback record={row} token={token} />}
              <EvidencePanel report={report} record={row} />
              <section>
                <h2>모델 범위와 불확실성</h2>
                <p>
                  {report?.tep_simulation?.detail || report?.simulation?.limitation ||
                    "모델 한계가 전달되지 않았습니다."}
                </p>
                <dl>
                  <dt>실행 범위</dt>
                  <dd>
                    {report?.execution_scope === "virtual"
                      ? "가상 설비 전용"
                      : "미설정"}
                  </dd>
                  <dt>모델 / 정책</dt>
                  <dd>
                    {report?.model_version || "—"} /{" "}
                    {report?.policy_version || "—"}
                  </dd>
                  <dt>데이터 출처</dt>
                  <dd>{report?.tep_simulation ? "공개 TEP 모델의 시뮬레이션 데이터" : "합성 상태"} · 실측 기록 아님</dd>
                  <dt>센서 품질</dt>
                  <dd>{coolingSnapshot?.sensor_quality || "실측 없음"}</dd>
                  <dt>검토 상태 시각</dt>
                  <dd>{report ? date(snapshotTime) : "—"} {report && !coolingSnapshot ? "(초기화 설정 시각)" : ""}</dd>
                </dl>
                <p className="muted">
                  TEP 냉각수 입력은 펌프 속도와 연결하지 않습니다. 기준/변경 결과의 차이는 실측 오차가 아닙니다. 실측 데이터 기반 오차 평가와 실제 설비 적용성 검증은 미완료입니다.
                </p>
              </section>
              <section className="no-print">
                <span className="eyebrow">03 / HUMAN DECISION</span>
                <h2>담당자 판단</h2>
                <p className={fresh ? "muted" : "danger-text"}>
                  {report && !coolingSnapshot ? "TEP 승인 정책 미설정: 검토 및 재시험만 가능합니다."
                    : report
                    ? fresh
                      ? `스냅샷 유효 시간 ${Math.max(
                          0,
                          Math.ceil(60 - age),
                        )}초 남음`
                      : "스냅샷이 오래되었습니다. 재검증하세요."
                    : "검토 보고서가 필요합니다."}{" "}
                  서버가 명령·상태·모델·정책·만료를 다시 확인합니다.
                </p>
                <label>
                  판단 이유
                  <textarea
                    maxLength={500}
                    value={reason}
                    onChange={(e) => setReason(e.target.value)}
                    placeholder="근거, 승인 조건 또는 재시험 이유"
                  />
                </label>
                <div className="approval-summary">
                  <strong>확인할 명령</strong>
                  <p>
                    {row.request.equipment_id} · {row.request.command.type} ·{" "}
                    {commandLabel(row.request.command)} ·{" "}
                    {row.request.command.duration_s}초
                  </p>
                  <code>보고서 SHA-256: {report?.digest || "—"}</code>
                  <label className="check">
                    <input
                      type="checkbox"
                      checked={confirmed}
                      disabled={!approver || !pending || !fresh}
                      onChange={(e) => setConfirmed(e.target.checked)}
                    />
                    명령, 시험 결과, 근거와 모델 한계를 확인했습니다.
                  </label>
                </div>
                <div className="actions">
                  <button
                    className="primary"
                    disabled={
                      busy ||
                      !approver ||
                      !pending ||
                      !fresh ||
                      !confirmed ||
                      !reason.trim()
                    }
                    onClick={() => decision("approve")}
                  >
                    가상 명령 승인
                  </button>
                  <button
                    disabled={busy || !approver || !pending || !reason.trim()}
                    onClick={() => decision("reject")}
                  >
                    거절
                  </button>
                  <button
                    disabled={
                      busy || !session || !report || locked || !reason.trim()
                    }
                    onClick={() => decision("request_retest")}
                  >
                    재시험 요청 · 보류
                  </button>
                  <button
                    disabled={busy || !session || locked}
                    onClick={() => post("evaluate")}
                  >
                    현재 상태로 재검증
                  </button>
                  <button
                    disabled={
                      busy ||
                      !session ||
                      row.status !== "approved" ||
                      !fresh ||
                      !row.approval ||
                      row.approval.expires_at <= now
                    }
                    onClick={() =>
                      post("execute", { report_digest: report?.digest })
                    }
                  >
                    승인한 가상 명령 적용
                  </button>
                </div>
                <p className="muted">
                  {approver
                    ? "서버에서 확인된 승인 담당자입니다."
                    : "승인·거절에는 지정 승인자 역할이 필요합니다."}{" "}
                  서버가 반환한 상태를 표시합니다.
                </p>
                {row.approval && (
                  <p>
                    승인: {row.approval.actor} · 만료{" "}
                    {date(row.approval.expires_at)} · {row.approval.reason}
                  </p>
                )}
                {row.execution && (
                  <pre>{JSON.stringify(row.execution, null, 2)}</pre>
                )}
                {coolingSnapshot && <details>
                  <summary>가상 상태 변경 시연</summary>
                  <p>부하를 바꾸면 기존 승인을 다시 검증해야 합니다.</p>
                  <div className="actions">
                    {[1.2, 1].map((load) => (
                      <button
                        key={load}
                        disabled={busy || !approver}
                        onClick={() =>
                          void run(async () => {
                            await api("/demo/state", {
                              load_ratio: load,
                              sensor_quality: "valid",
                            });
                            setConfirmed(false);
                          })
                        }
                      >
                        부하 {load} 설정
                      </button>
                    ))}
                  </div>
                </details>}
              </section>
              {approver && (
                <section className="no-print">
                  <h2>승인 담당자 알림</h2>
                  <p>
                    요청자 연락처: {contact || "미입력"}{" "}
                    <span className="muted">(소유 미검증)</span>
                  </p>
                  <p className="muted">
                    이메일은 알림입니다. 담당자가 요청자에게 연락하고 화면에서
                    판단합니다. 이메일로 승인되지 않습니다.
                  </p>
                  {!notes.length && <p>저장된 알림이 없습니다.</p>}
                  {notes.map((note) => (
                    <article className="notification" key={note.id}>
                      <strong>
                        {label(note.status)} ·{" "}
                        {note.recipient || "수신자 미설정"}
                      </strong>
                      <p>{note.detail}</p>
                      <small>
                        {date(note.created_at)} · 시도 {note.attempts}회 ·
                        보고서 {note.report_digest.slice(0, 12)}
                      </small>
                      <button
                        disabled={
                          busy ||
                          !pending ||
                          !fresh ||
                          note.status !== "queued" ||
                          note.report_digest !== report?.digest
                        }
                        onClick={() =>
                          void run(async () => {
                            await api(
                              `/requests/${row.id}/notifications/${note.id}/send`,
                              {},
                            );
                            await details(
                              await api<Row>(`/requests/${row.id}`),
                            );
                          })
                        }
                      >
                        지정 승인자에게 알림 발송
                      </button>
                    </article>
                  ))}
                  {!session?.notification_configured && (
                    <p className="annotation">
                      서버 SMTP·발신 주소·승인자 이메일이 필요합니다. 현재
                      이메일은 보내지 않습니다.
                    </p>
                  )}
                </section>
              )}
              <section>
                <div className="section-head">
                  <h2>저장된 검토·판단 이력</h2>
                  <button className="no-print" onClick={() => window.print()}>
                    보고서 인쇄 · PDF
                  </button>
                </div>
                <p className="muted">
                  보고서 {history?.reports.length ?? "—"}건 · 승인{" "}
                  {history?.approvals.length ?? "—"}건 · SQLite 영속 저장. 변조
                  방지 감사 저장소는 아닙니다.
                </p>
                {history?.reports.map((old) => (
                  <p key={old.digest}>
                    개정 {old.revision} · {label(old.verdict)} ·{" "}
                    {old.reason_code} · <code>{old.digest.slice(0, 16)}</code>
                  </p>
                ))}
                <ol className="timeline">
                  {row.events.map((e, i) => (
                    <li key={i}>
                      <time>{date(e.at)}</time>
                      <strong>{label(e.kind)}</strong>
                      {e.actor && <span>{e.actor}</span>}
                      {e.reason && <p>{e.reason}</p>}
                    </li>
                  ))}
                </ol>
              </section>
            </>
          )}
        </div>
      </div>
      <footer>
        1 관문·권한 / 2 계산 / 3 출처·적용 조건 / 4 담당자 검토 화면
      </footer>
    </main>
  );
}
function Website() {
  const [page, setPage] = useState(window.location.hash);
  useEffect(() => {
    const onHash = () => {
      setPage(window.location.hash);
      if (["#home", "#demo", "#review", ""].includes(window.location.hash))
        window.scrollTo(0, 0);
    };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);
  const consolePage = page === "#review" || page.startsWith("#evidence-");
  return consolePage ? <App /> : page === "#demo" ? <DemoPage /> : <Home />;
}
createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <Website />
  </React.StrictMode>,
);
