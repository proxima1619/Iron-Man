import { useEffect, useRef, useState } from "react";
import type { components } from "./api.generated";
import { EvidencePanel } from "./EvidencePanel";
type Row = components["schemas"]["RequestRecord"];
type Feedback = components["schemas"]["RecordFeedback"];

export function RecordFeedback({
  record,
  token,
}: {
  record: Row;
  token: string;
}) {
  const isTep = record.request.command.type === "set_tep_cooling_water";
  const [feedback, setFeedback] = useState<Feedback | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const active = useRef<AbortController | null>(null);
  useEffect(() => {
    active.current?.abort();
    active.current = null;
    setFeedback(null);
    setError("");
    setBusy(false);
    return () => {
      active.current?.abort();
      active.current = null;
    };
  }, [
    record.id,
    record.revision,
    record.report?.digest,
    record.execution?.execution_id,
    token,
  ]);
  async function explain() {
    const controller = new AbortController();
    active.current?.abort();
    active.current = controller;
    const timer = window.setTimeout(() => controller.abort(), 120000);
    setBusy(true);
    setError("");
    setFeedback(null);
    try {
      const response = await fetch(
        `/api/requests/${encodeURIComponent(record.id)}/feedback`,
        {
          method: "POST",
          headers: { "X-Iron-Man-Token": token },
          signal: controller.signal,
        },
      );
      const body = await response.json();
      if (!response.ok)
        throw new Error(
          response.status === 404
            ? "백엔드를 새 코드로 재시작해주세요."
            : typeof body.detail === "string"
              ? body.detail
              : "AI 설명을 받지 못했습니다.",
        );
      if (
        body.request_id !== record.id ||
        body.record_revision !== record.revision ||
        body.report_digest !== (record.report?.digest || null)
      )
        throw new Error(
          "기록이 변경되었습니다. 저장된 결과를 다시 불러온 뒤 요청하세요.",
        );
      if (!controller.signal.aborted) setFeedback(body as Feedback);
    } catch (e) {
      if (active.current === controller)
        setError(
          controller.signal.aborted
            ? "분석 대기 시간이 초과됐습니다. 다시 요청해주세요."
            : e instanceof Error
              ? e.message
              : "AI 설명 요청 실패",
        );
    } finally {
      window.clearTimeout(timer);
      if (active.current === controller) setBusy(false);
    }
  }
  return (
    <section className="record-feedback" aria-label="저장 기록 AI 피드백">
      <h3>이 기록을 AI에게 설명받기</h3>
      <p>
        {isTep
          ? "저장된 TEP 기준·변경 결과와 설정된 문헌을 함께 검토합니다. 계산을 다시 실행하지 않으며 과거 결과는 그대로 유지됩니다."
          : "저장된 명령과 결과를 논문과 함께 분석합니다. 과거 결과는 그대로 유지됩니다."}
      </p>
      {record.report?.reason_code === "INVALID_STATE" && (
        <aside className="evidence-hold">
          <strong>이 기록은 당시 상태 검사에서 보류됐습니다.</strong>
          <p>관측 갱신은 현재 가상 상태만 바꾸므로 저장된 보류 사유는 남아 있습니다. 아래 AI 피드백은 최신 관측 없이 받을 수 있습니다. 당시 계산 결과가 없다면 AI는 보류 이유와 부족 조건을 설명합니다.</p>
        </aside>
      )}
      <button
        className="primary"
        disabled={
          busy ||
          !token ||
          record.status === "evaluating" ||
          record.status === "executing"
        }
        onClick={() => void explain()}
      >
        {busy ? "논문과 기록을 분석 중…" : "AI 피드백 받기"}
      </button>
      <p className="muted">
        버튼을 누르면 서버의 API 키로 분석합니다. 설비를 다시 실행하거나
        승인하지 않습니다. 위에 표시된 당시 판정과 아래의 새 AI 설명은 별개입니다.
      </p>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {feedback && (
        <div aria-live="polite">
          <p className="badge">
            {feedback.status === "completed"
              ? "분석 완료"
              : "분석 완료 · 적용 근거 부족"}
          </p>
          <h3>무슨 일이 일어났나요?</h3>
          <p>{feedback.summary}</p>
          <h3>결과를 어떻게 봐야 하나요?</h3>
          <p className="feedback-text">{feedback.result_interpretation}</p>
          <h3>근거 검토의 한계와 부족 조건</h3>
          <h4>모델과 기록의 한계</h4>
          <ul>
            {feedback.model_limitations.map((item, i) => (
              <li key={i}>{item}</li>
            ))}
          </ul>
          <h4>아직 확인하지 못한 조건</h4>
          {feedback.missing_conditions.length ? (
            <ul>
              {feedback.missing_conditions.map((item, i) => (
                <li key={i}>{item}</li>
              ))}
            </ul>
          ) : (
            <p>
              이번 응답에 추가 부족 조건이 명시되지 않았습니다. 실제 설비의
              안전성을 입증한 것은 아닙니다.
            </p>
          )}
          <h4>담당자가 다음에 확인할 항목</h4>
          <ul>
            {feedback.recommended_checks.map((item, i) => (
              <li key={i}>{item}</li>
            ))}
          </ul>
          <details>
            <summary>논문 인용과 적용 조건 자세히 보기</summary>
            <EvidencePanel report={null} evidence={feedback.evidence} />
          </details>
          <p className="muted">
            {new Date(feedback.generated_at * 1000).toLocaleString("ko-KR")} ·{" "}
            {feedback.model} · 기록 {feedback.request_id.slice(0, 8)} · 참고용
            분석, 실행 허가 아님
          </p>
        </div>
      )}
      {isTep && !feedback && (
        <p className="muted">
          검토가 끝나면 출처, 인용문, TEP 적용 조건, 부족 조건과 모델 한계가 아래에 표시됩니다. 이 피드백은 서버의 보류 판정이나 승인 권한을 바꾸지 않습니다.
        </p>
      )}
    </section>
  );
}
