import { useEffect, useState } from "react";
import type { components } from "./api.generated";

type Catalog = components["schemas"]["EvidenceCatalog"];

export function EvidenceCatalog({ token }: { token: string }) {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    setCatalog(null);
    setError("");
    if (!token) {
      setBusy(false);
      return;
    }
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), 15000);
    let active = true;
    setBusy(true);
    void (async () => {
      try {
        const response = await fetch("/api/evidence/catalog", {
          headers: { "X-Iron-Man-Token": token },
          signal: controller.signal,
        });
        if (!response.ok)
          throw new Error(
            response.status === 401 || response.status === 403
              ? "요청 담당자 토큰이 유효하지 않습니다. 아래 데모 연결 설정에 공유받은 토큰을 입력하세요."
              : response.status === 404
                ? "서버에 근거 조회 기능이 아직 배포되지 않았습니다. 운영 담당자에게 확인하세요."
                : "근거 설정을 불러오지 못했습니다. 잠시 후 연결 설정 확인을 다시 눌러주세요.",
          );
        const value = (await response.json()) as Catalog;
        if (active) setCatalog(value);
      } catch (e) {
        if (active)
          setError(
            e instanceof Error && e.name !== "AbortError"
              ? e.message
              : "근거 설정 조회 시간이 초과되었습니다.",
          );
      } finally {
        if (active) setBusy(false);
      }
    })();
    return () => {
      active = false;
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [token, revision]);

  return (
    <section className="evidence-catalog" aria-label="AI 설명 준비 상태">
      <div className="section-head">
        <h3>AI 설명 준비 상태</h3>
        <button
          disabled={busy || !token}
          onClick={() => setRevision((v) => v + 1)}
        >
          {busy ? "확인 중…" : "연결 설정 확인"}
        </button>
      </div>
      <p className="muted">
        기록을 선택한 뒤 오른쪽의 AI 피드백 받기를 누르세요.
      </p>
      {!token && <p>담당자 토큰을 입력하면 검토 설정을 확인할 수 있습니다.</p>}
      {error && <p role="status">{error}</p>}
      {catalog && (
        <>
          <details>
            <summary>연결 설정 자세히 보기</summary>
            <dl>
              <dt>검토 모드</dt>
              <dd>
                {catalog.mode === "live"
                  ? "실제 LLM 검토"
                  : catalog.mode === "fixture"
                    ? "모의 응답"
                    : "설정 오류"}
              </dd>
              <dt>API 키 · 모델</dt>
              <dd>
                {catalog.api_key_configured ? "키 설정됨" : "키 없음"} ·{" "}
                {catalog.model_configured ? "모델 설정됨" : "모델 없음"}
              </dd>
              <dt>문헌 수집</dt>
              <dd>
                {catalog.source_mode === "local"
                  ? `사전 수집 ${catalog.sources.length}건`
                  : catalog.source_mode === "europepmc"
                    ? "검토 시 Europe PMC 실시간 검색"
                    : "설정 오류"}
              </dd>
            </dl>
          </details>
          <p>
            {catalog.ready
              ? "키와 모델이 설정됐습니다. AI 피드백을 요청할 수 있습니다."
              : "AI 설명을 받으려면 아래 설정을 확인하세요."}
          </p>
          {!!catalog.issues.length && (
            <ul>
              {catalog.issues.map((issue) => (
                <li key={issue}>{issue}</li>
              ))}
            </ul>
          )}
          {!!catalog.sources.length && (
            <details>
              <summary>참고 논문·문서 {catalog.sources.length}건 보기</summary>
              <ul>
                {catalog.sources.map((source) => {
                  let url: string | null = null;
                  try {
                    const value = new URL(source.source_url || "");
                    if (
                      value.protocol === "https:" &&
                      !value.username &&
                      !value.password
                    )
                      url = value.href;
                  } catch {
                    /* No source URL */
                  }
                  return (
                    <li key={source.source_id}>
                      <strong>{source.title}</strong>
                      <p className="muted">
                        {source.source_type === "paper" ? "논문" : "문서"} ·{" "}
                        {source.publisher} · {source.locator}
                      </p>
                      {url && (
                        <a href={url} target="_blank" rel="noopener noreferrer">
                          출처 원문 열기 ↗
                        </a>
                      )}
                    </li>
                  );
                })}
              </ul>
            </details>
          )}
          <p className="annotation">
            AI 설명에는 API 사용량이 발생합니다. 키 설정 표시는 호출 성공을
            보장하지 않으며, 실패하면 피드백 영역에 이유가 표시됩니다. 가상 설비
            체험은 실제 설비 연결이 필요하지 않습니다.
          </p>
        </>
      )}
    </section>
  );
}
