import { useEffect, useState } from "react";
import "./home.css";

export function Home() {
  const [health, setHealth] = useState<"loading" | "ready" | "offline">(
    "loading",
  );
  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), 5000);
    fetch("/api/health", { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error("health check failed");
        const body = await response.json();
        if (active)
          setHealth(
            body.status === "ok" && body.storage === "sqlite"
              ? "ready"
              : "offline",
          );
      })
      .catch(() => {
        if (active) setHealth("offline");
      })
      .finally(() => {
        window.clearTimeout(timer);
      });
    return () => {
      active = false;
      window.clearTimeout(timer);
      controller.abort();
    };
  }, []);
  return (
    <main className="home">
      <nav className="home-nav" aria-label="홈페이지 메뉴">
        <a className="home-brand" href="#home">
          IRON MAN<span>설비 변경 안전 관문</span>
        </a>
        <a href="#flow">검토 흐름</a>
        <a className="home-console-link" href="#demo">
          데모 체험하기 ↗
        </a>
      </nav>
      <section className="home-hero">
        <div className="home-intro">
          <p className="home-kicker">AI FOR SAFETY & RESILIENCE</p>
          <h1>
            설비를 바꾸기 전에,
            <br />
            결과부터 확인하세요.
          </h1>
          <p className="home-lead">
            변경 요청을 가상 설비에서 검토하고, 위험 조건과 근거를 확인한
            담당자의 판단을 기록합니다.
          </p>
          <a className="home-start" href="#demo">
            데모 직접 체험하기 →
          </a>
        </div>
        <div
          className="home-gate"
          aria-label="요청, 가상 검토, 담당자 판단, 가상 적용 순서"
        >
          <div className="home-gate-title">냉각 펌프 변경 요청</div>
          <ol>
            <li>
              <span>01</span>
              <div>
                <strong>요청</strong>
                <p>목표 속도와 변경 목적</p>
              </div>
            </li>
            <li>
              <span>02</span>
              <div>
                <strong>가상 검토</strong>
                <p>기존 운전과 변경 후 결과 비교</p>
              </div>
            </li>
            <li>
              <span>03</span>
              <div>
                <strong>담당자 판단</strong>
                <p>위험·출처·모델의 한계 확인</p>
              </div>
            </li>
            <li>
              <span>04</span>
              <div>
                <strong>가상 적용</strong>
                <p>서버에서 승인 유효성 재확인</p>
              </div>
            </li>
          </ol>
          <p className="home-scope">합성 모델 시연 · 실제 설비 미연결</p>
        </div>
      </section>
      <section className="home-flow" id="flow">
        <h2>한 화면에서 판단에 필요한 내용을.</h2>
        <dl>
          <div>
            <dt>예상 효과와 위험</dt>
            <dd>
              정상 운전과 냉각 효율 저하 조건의 최고 온도를 비교하고, 제한 초과
              여부를 확인합니다.
            </dd>
          </div>
          <div>
            <dt>근거와 적용 조건</dt>
            <dd>
              모의 응답과 실제 문헌 검토를 구분하고, 출처·인용문·일치 조건과
              부족 조건을 읽습니다.
            </dd>
          </div>
          <div>
            <dt>판단과 기록</dt>
            <dd>
              승인·거절·재시험 이유를 남깁니다. 서버는 승인한 명령과 상태를
              확인한 뒤 가상 설비에 적용합니다.
            </dd>
          </div>
        </dl>
      </section>
      <section className="home-system" aria-label="서비스 상태">
        <div>
          <h2>로컬 시연 환경</h2>
          <p>
            합성 냉각 모델을 사용합니다. TEP 데이터와 실제 PLC는 연결되지
            않았습니다.
          </p>
        </div>
        <p role="status" className={`home-health ${health}`}>
          {health === "loading"
            ? "서버 상태 확인 중"
            : health === "ready"
              ? "서버 응답 정상 · SQLite 사용"
              : "서버 연결 확인 필요"}
          <small>DB 영속성은 요청 저장·재조회로 별도 확인합니다.</small>
        </p>
      </section>
      <footer className="home-footer">
        <span>IRON MAN</span>
        <span>DevDay Community Hackathon · Track 1</span>
      </footer>
    </main>
  );
}
