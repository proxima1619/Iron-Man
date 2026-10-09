import { DemoExperience } from "./DemoExperience";
import "./home.css";

export function DemoPage() {
  return (
    <main className="home demo-page">
      <nav className="home-nav" aria-label="데모 화면 메뉴">
        <a className="home-brand" href="#home">
          IRON MAN<span>설비 변경 안전 관문</span>
        </a>
        <a href="#home">← 홈페이지</a>
        <a className="home-console-link" href="#review">
          전체 검토 콘솔 ↗
        </a>
      </nav>
      <DemoExperience />
      <footer className="home-footer">
        <span>합성 냉각 설비 · SQLite 저장 기록</span>
        <a href="#home">홈페이지로 돌아가기</a>
      </footer>
    </main>
  );
}
