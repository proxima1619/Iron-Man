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
  record,
  evidence,
}: {
  report: Report | null | undefined;
  record?: components["schemas"]["RequestRecord"] | null;
  evidence?: Review;
}) {
  const review = evidence || report?.evidence;
  const coolingSnapshot = report && "observed_at" in report.snapshot ? report.snapshot : null;
  const pumpCommand = record?.request.command.type === "set_pump_speed" ? record.request.command : null;
  const appliedExecution = record?.execution?.status === "applied" && record.execution.command.type === "set_pump_speed"
    ? record.execution
    : null;
  const origin = review ? evidenceOrigin(review) : null;
  const orderedCards = [...(review?.cards || [])].sort(
    (a, b) =>
      ["support", "counter", "limitation"].indexOf(a.stance) -
      ["support", "counter", "limitation"].indexOf(b.stance),
  );
  const evidenceHold =
    report?.verdict === "hold" && report.reason_code === "EVIDENCE_INCOMPLETE";
  return (
    <section aria-labelledby="evidence-heading">
      <div className="section-head">
        <h2 id="evidence-heading">판단 근거와 적용 조건</h2>
        {origin && <span className="badge">{origin.title}</span>}
      </div>
      <p className="muted">
        {origin?.detail ||
          (report
            ? "이 보고서에는 문헌 근거가 저장되지 않았습니다. 저장된 계산 결과와 서버 판단을 아래에서 확인하세요."
            : "근거 결과가 아직 전달되지 않았습니다.")}
      </p>
      {report && (
        <div className="result-explanation">
          <h3>저장된 결과로 보는 판단 근거</h3>
          <p>
            <strong>서버 판단:</strong> {report.reason}{" "}
            <code>{report.reason_code}</code>
          </p>
          {report.simulation?.scenarios.length ? (
            <ul>
              {report.simulation.scenarios.map((s) => (
                <li key={s.kind}>
                  <strong>
                    {s.kind === "normal" ? "정상 냉각" : "냉각 효율 저하"}:
                  </strong>{" "}
                  기존 최고 {s.baseline_peak_c.toFixed(2)}°C → 변경 최고{" "}
                  {s.candidate_peak_c.toFixed(2)}°C. 차이{" "}
                  {(s.candidate_peak_c - s.baseline_peak_c).toFixed(2)}°C.{" "}
                  {s.exceeded
                    ? `변경 결과가 ${s.limit_c}°C 제한을 ${(s.candidate_peak_c - s.limit_c).toFixed(2)}°C 초과합니다.`
                    : `변경 결과는 ${s.limit_c}°C 제한 이내입니다.`}
                  {s.baseline_peak_c > s.limit_c &&
                    " 기존 운전 결과도 제한을 초과하므로 함께 검토해야 합니다."}
                  {s.physical_assessment && (
                    <p className="muted">
                      장기 {s.physical_assessment.horizon_s}초 최고: 기존{" "}
                      {s.physical_assessment.baseline.peak_c.toFixed(2)}°C /
                      변경 {s.physical_assessment.candidate.peak_c.toFixed(2)}
                      °C. 변경 평형{" "}
                      {s.physical_assessment.candidate.equilibrium_c === null
                        ? "유한 평형 없음"
                        : `${s.physical_assessment.candidate.equilibrium_c.toFixed(2)}°C`}
                      . 계수 민감도:{" "}
                      {s.physical_assessment.sensitivity.status === "completed"
                        ? `변경 최악 평형 ${s.physical_assessment.sensitivity.candidate_worst_equilibrium_c?.toFixed(2)}°C`
                        : "지원 범위 밖"}
                      .{" "}
                      {s.physical_assessment.candidate.first_exceeded_s !==
                        null &&
                        `첫 초과 표본 ${s.physical_assessment.candidate.first_exceeded_s}초.`}{" "}
                      계수는 데모 가정이며 실측 보정되지 않았습니다.
                    </p>
                  )}
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted">
              계산 결과가 저장되지 않아 숫자에 근거한 효과 비교는 할 수
              없습니다. 서버 보류 사유와 문헌 검토 결과를 확인하세요.
            </p>
          )}
          {appliedExecution ? (
            <p>
              <strong>가상 적용 기록:</strong> 목표 속도{" "}
              {appliedExecution.command.target_pct}% 접수 · 접수 당시 실제 속도{" "}
              {appliedExecution.state.pump_speed_pct.toFixed(2)}%. 적용 접수는
              예측 온도와 실측 결과가 일치했다는 검증이 아닙니다.
            </p>
          ) : record?.execution?.status === "unknown" ? (
            <p className="danger-text">
              실행 결과가 불명입니다. 추가 실행을 시도하지 말고 서버 기록을
              확인해야 합니다.
            </p>
          ) : (
            record && (
              <p className="muted">
                이 요청의 가상 적용 완료 기록은 없습니다. 위 온도는 시뮬레이션
                예측 결과입니다.
              </p>
            )
          )}
          <h3>이 판단에 사용한 조건</h3>
          <dl>
            <dt>{coolingSnapshot ? "초기 온도·부하" : "초기 상태"}</dt>
            <dd>
              {coolingSnapshot
                ? `${coolingSnapshot.temperature_c.toFixed(2)}°C · 부하 ${coolingSnapshot.load_ratio}`
                : report.tep_simulation
                  ? "TEP 표준 프로필 · 공개 공정 모델 초기화"
                  : "상태 정보 없음"}
            </dd>
            {coolingSnapshot && <>
              <dt>기존 목표·초기 속도</dt>
              <dd>
                {coolingSnapshot.target_pump_speed_pct ?? coolingSnapshot.pump_speed_pct}
                % · 초기 실제 속도 {coolingSnapshot.pump_speed_pct}%
              </dd>
            </>}
            {record && (
              <>
                <dt>변경 요청</dt>
                <dd>
                  {pumpCommand
                    ? `${pumpCommand.target_pct}% · 예측 구간 ${pumpCommand.duration_s}초`
                    : record.request.command.type === "set_tep_cooling_water"
                      ? `${record.request.command.variable} ${record.request.command.value} percent_full_scale · ${record.request.command.duration_s}초`
                      : "명령 정보 없음"}
                </dd>
              </>
            )}
            <dt>모델·정책</dt>
            <dd>
              {report.model_version} · {report.policy_version}
            </dd>
            <dt>센서·모델 범위</dt>
            <dd>
              {coolingSnapshot
                ? `${coolingSnapshot.sensor_quality === "valid" ? "유효" : "불량"} · ${coolingSnapshot.domain_status === "ready" ? "지원 범위" : "지원 범위 밖"}`
                : report.tep_simulation
                  ? "현장 센서 없음 · TEP 내부 상태 및 지원 조건 사용"
                  : "확인되지 않음"}
            </dd>
            <dt>데이터·실행 범위</dt>
            <dd>
              {report.tep_simulation ? "공개 TEP 시뮬레이션 · 현장 실측 아님" : "합성 상태 · "}{" "}
              {report.execution_scope === "virtual"
                ? "가상 설비 전용"
                : "미설정"}
            </dd>
          </dl>
          <p className="muted">
            저장된 과거 상태에서 얻은 판단입니다. 현재 상태·모델·정책·승인
            유효성은 적용 전 서버가 다시 검사합니다.
          </p>
        </div>
      )}
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
      {review && !review.mock && (
        <div className="evidence-summary">
          <h3>논문 검토 결과 요약</h3>
          <ul>
            {["support", "counter", "limitation"].map((stance) => {
              const count = review.cards.filter(
                (c) => c.stance === stance,
              ).length;
              return (
                <li key={stance}>
                  <strong>
                    {stances[stance]}: {count}건.
                  </strong>
                  {count === 0 && " 이 검토에서 근거를 확보하지 못했습니다."}
                </li>
              );
            })}
          </ul>
          <p className="muted">
            반례는 별도 반대 논문 또는 같은 논문의 실패 조건에서 나올 수
            있습니다. 근거 개수는 안전성이나 적용 가능성을 보장하지 않습니다.
          </p>
        </div>
      )}
      {orderedCards.map((c, index) => {
        const url = sourceUrl(c.source_url);
        return (
          <article
            className="evidence"
            id={`evidence-${c.evidence_id}`}
            key={c.evidence_id}
          >
            {(index === 0 || orderedCards[index - 1].stance !== c.stance) && (
              <h3>{stances[c.stance]}</h3>
            )}
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
        {review?.limitation ||
          (report
            ? "문헌 근거의 적용 조건과 부족 조건이 이 보고서에 저장되지 않았습니다. 계산 결과만으로 실제 설비 안전을 보증할 수 없습니다."
            : "근거 범위와 한계를 확인할 수 없습니다.")}
      </p>
      {report?.simulation?.limitation && (
        <p className="annotation">
          <strong>계산 모델의 한계:</strong> {report.simulation.limitation}
        </p>
      )}
    </section>
  );
}
