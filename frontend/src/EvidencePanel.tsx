import type { components } from "./api.generated";

type Report = components["schemas"]["DecisionReport"];
type Review = components["schemas"]["EvidenceReview"];
// Acquisition mode is currently returned by module 3 in limitation, not as a
// structured field. Do not infer live search merely from a paper URL.
export function evidenceOrigin(review: Review) {
  if (review.mock)
    return {
      title: "모의 응답",
      detail: "실제 논문 검색과 LLM 검토를 수행한 결과가 아닙니다.",
    };
  if (review.limitation.startsWith("실시간 Europe PMC 논문 검색·원문 수집"))
    return {
      title: "실시간 검색",
      detail:
        "평가 시 Europe PMC에서 논문을 검색하고 원문을 수집한 검토 경로입니다.",
    };
  if (review.limitation.startsWith("사전 수집 문서 검토"))
    return review.cards.some((c) => c.source_type === "paper")
      ? {
          title: "사전 수집 논문",
          detail:
            "미리 수집한 논문 발췌를 LLM으로 검토했습니다. 이번 평가에서 실시간 검색한 결과는 아닙니다.",
        }
      : {
          title: "사전 수집 문서",
          detail:
            "미리 준비한 문서의 LLM 검토입니다. 팀 작성 데모 규정은 논문·제조사 자료와 구분합니다.",
        };
  return {
    title: "수집 방식 확인 불가",
    detail:
      "응답에 수집 방식이 없습니다. 실패 응답이나 이전 보고서에서 검색 성공을 추정하지 않습니다.",
  };
}
function sourceUrl(value: string | null | undefined) {
  try {
    const u = new URL(value || "");
    return ["https:", "http:"].includes(u.protocol) &&
      !u.username &&
      !u.password
      ? u.href
      : null;
  } catch {
    return null;
  }
}
const types: Record<string, string> = {
  paper: "논문",
  manual: "매뉴얼",
  field_record: "현장 기록",
  team_authored_demo: "팀 작성 데모 규정",
  team_authored_fixture: "팀 작성 모의 자료",
};
const conditions: Record<string, string> = {
  applicable: "적용 조건 확인",
  partial: "일부 일치",
  mismatch: "조건 불일치",
  unknown: "미확인",
};
const stances: Record<string, string> = {
  support: "지지 근거",
  counter: "반례·실패 조건",
  limitation: "한계",
};
const statuses: Record<string, string> = {
  completed: "검토 완료",
  insufficient: "근거 부족",
  failed: "검토 실패",
  demo_fixture: "모의 응답",
};

export function EvidencePanel({
  report,
}: {
  report: Report | null | undefined;
}) {
  const review = report?.evidence;
  const origin = review ? evidenceOrigin(review) : null;
  const evidenceHold =
    report?.verdict === "hold" && report.reason_code === "EVIDENCE_INCOMPLETE";
  return (
    <section aria-labelledby="evidence-heading">
      <div className="section-head">
        <h2 id="evidence-heading">판단 근거와 적용 조건</h2>
        {origin && <span className="badge">{origin.title}</span>}
      </div>
      <p className="muted">
        {origin?.detail || "근거 결과가 아직 전달되지 않았습니다."}
      </p>
      {review && (
        <p>
          근거 검토 상태:{" "}
          <strong>{statuses[review.status] || review.status}</strong>
        </p>
      )}
      {evidenceHold && (
        <aside className="evidence-hold" role="status">
          <h3>근거 검토로 보류되었습니다</h3>
          <p>{report.reason}</p>
          <p className="muted">
            서버 사유 코드: <code>{report.reason_code}</code>
          </p>
          {review?.cards.some((c) => c.source_type === "paper") && (
            <p>
              외부 논문이 있어도 설비에 적용 가능한 조건과 서버에 등록된 출처를
              확인해야 합니다. 이 화면은 서버의 승인 정책을 변경하지 않습니다.
            </p>
          )}
        </aside>
      )}
      {review && !review.cards.length && (
        <p className="annotation">
          반환된 근거 카드가 없습니다.{" "}
          {review.status === "failed"
            ? "검색·문서·LLM 검토의 실패 원인은 아래 서버 설명을 확인하세요."
            : "관련 출처와 적용 조건을 추가로 확인해야 합니다."}
        </p>
      )}
      {review?.cards.map((c) => {
        const url = sourceUrl(c.source_url);
        return (
          <article
            className="evidence"
            id={`evidence-${c.evidence_id}`}
            key={c.evidence_id}
          >
            <div className="section-head">
              <span className="eyebrow">
                {stances[c.stance] || c.stance} /{" "}
                {types[c.source_type] || c.source_type}
              </span>
              <span className="badge">
                {conditions[c.applicability] || c.applicability}
              </span>
            </div>
            <h3>{c.title}</h3>
            <p>{c.claim}</p>
            <h4>원문 인용</h4>
            {c.excerpt ? (
              <blockquote>{c.excerpt}</blockquote>
            ) : (
              <p className="muted">
                인용문이 전달되지 않았습니다. 주장을 원문 인용으로 표시하지
                않습니다.
              </p>
            )}
            <dl>
              <dt>일치 조건</dt>
              <dd>
                {c.matched_conditions?.join(" / ") ||
                  "일치 조건이 명시되지 않음"}
              </dd>
              <dt>부족·미확인 조건</dt>
              <dd>
                {c.missing_conditions?.join(" / ") ||
                  (c.applicability === "applicable"
                    ? "응답에 명시된 부족 조건 없음"
                    : "부족 조건 상세가 없으므로 적용 가능 여부를 추가 확인해야 합니다.")}
              </dd>
              <dt>원문 위치</dt>
              <dd>{c.locator || "미표기"}</dd>
              <dt>발행·버전</dt>
              <dd>
                {c.publisher || "미표기"} · {c.version || "미표기"} ·{" "}
                {c.published_at || "미표기"}
              </dd>
              <dt>이용 조건</dt>
              <dd>{c.usage || "미표기"}</dd>
            </dl>
            {url ? (
              <a href={url} target="_blank" rel="noopener noreferrer">
                논문·출처 원문 열기 ↗
              </a>
            ) : (
              <p className="muted">
                원문 링크가 제공되지 않았습니다. 원문 위치를 확인하세요.
              </p>
            )}
            {c.proposed_test && (
              <p className="muted">
                추가 시험:{" "}
                {c.proposed_test === "degraded_cooling"
                  ? "냉각 효율 저하"
                  : c.proposed_test}{" "}
                · 계수 출처:{" "}
                {c.parameter_origin === "demo_assumption"
                  ? "데모 가정 · 논문에서 검증한 계수 아님"
                  : c.parameter_origin || "미표기"}
              </p>
            )}
          </article>
        );
      })}
      <h3>근거 검토의 한계와 부족 조건</h3>
      <p className="annotation">
        {review?.limitation || "근거 범위와 한계를 확인할 수 없습니다."}
      </p>
    </section>
  );
}
