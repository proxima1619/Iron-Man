import type { components } from "./api.generated";
type Review = components["schemas"]["TEPEvidenceReview"];
const purposes = { model_definition: "모델 정의", physical_mechanism: "일반 물리 현상", simulation_observation: "시뮬레이션 관측", safety_basis: "안전 기준" };
const statuses = { completed: "근거 검토 완료", insufficient: "근거 부족", failed: "검토 실패", demo_fixture: "문헌 검토 미실행" };
function link(value: string | null | undefined) {
  try { const url = new URL(value || ""); return url.protocol === "https:" && !url.username && !url.password ? url.href : null; }
  catch { return null; }
}
export function TepEvidencePanel({ review }: { review: Review | null | undefined }) {
  return <section aria-labelledby="tep-evidence-heading">
    <h2 id="tep-evidence-heading">TEP 근거·역근거 검토</h2>
    {!review ? <p>이 기록에는 TEP 근거 검토 결과가 없습니다.</p> : <>
      <p>{statuses[review.status]} · {review.mock ? "실제 LLM 미호출" : "원문·적용 조건 검증 경로"}</p>
      <p>초기 프로필: {review.initial_profile} · 모델: {review.model_version}</p>
      <p className="muted">{review.limitation}</p>
      {review.cards.map(card => <article key={card.evidence_id}>
        <h3>{card.title}</h3>
        <p>{purposes[card.evidence_purpose]} · {card.stance} · 적용 조건 {card.applicability}</p>
        <p>{card.claim}</p><blockquote>{card.excerpt}</blockquote>
        <p>{card.locator} · {card.version}</p>
        {link(card.source_url) && <a href={link(card.source_url)!} target="_blank" rel="noreferrer">원문 보기</a>}
        <p>관련 변수: {card.variable_ids.join(", ")} · 근거 ID: {card.evidence_id}</p>
        <ul>{card.matched_conditions.map((condition, i) => <li key={i}>비교 조건: {condition}</li>)}</ul>
        <ul>{card.missing_conditions.map((condition, i) => <li key={i}>미확인: {condition}</li>)}</ul>
      </article>)}
      <ul>{review.proposed_tests.map(test => <li key={test.evidence_id}>제안 시험: {test.test_id} · {test.variable} · {test.evidence_id} · 서버 채택 필요</li>)}</ul>
      <ul>{review.unsupported_tests.map((test, i) => <li key={i}>검증하지 못한 시험: {test.requested_test} · {test.reason}</li>)}</ul>
      <ul>{review.missing_conditions.map((condition, i) => <li key={i}>근거 부족: {condition}</li>)}</ul>
      <p>근거 검토 완료는 안전 승인이나 실행 허가가 아닙니다.</p>
    </>}
  </section>;
}
