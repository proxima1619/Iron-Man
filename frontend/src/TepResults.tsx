import React, { useState } from "react";
import type { components } from "./api.generated";
type Result = components["schemas"]["TEPResult"];

export function TepResults({ result }: { result: Result }) {
  const [variable, setVariable] = useState("XMEAS9");
  const keys = ["XMEAS7", "XMEAS9", "XMEAS11", "XMEAS21", "XMEAS22"];
  const unit = result.variables[variable]?.unit || "단위 불명";
  const index = Number(variable.slice(5)) - 1;
  const a = result.baseline?.points || [], b = result.candidate?.points || [];
  const values = [...a, ...b].map(p => p.xmeas[index]);
  const min = values.length ? Math.min(...values) : 0;
  const max = values.length ? Math.max(...values) : 1;
  const span = Math.max(max - min, 0.001);
  const x = (t: number) => 65 + 650 * t / result.configuration.horizon_s;
  const y = (v: number) => 245 - 190 * (v - min) / span;
  const line = (points: typeof a) => points.map(p => `${x(p.time_s)},${y(p.xmeas[index])}`).join(" ");
  return <section>
    <div className="section-head">
      <h2>이번 요청에서 새로 실행한 TEP 결과</h2>
      <span className="badge">외부 엔진 계산</span>
    </div>
    <p><strong>시뮬레이션 데이터 · 현장 실측 아님</strong></p>
    <p>{result.detail}</p>
    <p>실행 상태: {result.status} {result.failure_code || ""}</p>
    <div className="tep-origin-grid" aria-label="실행 결과와 참조 자료 구분">
      <article>
        <strong>기준 / 변경 결과</strong>
        <p>현재 요청마다 외부 TEP 엔진이 같은 초기 조건으로 각각 계산한 결과입니다. 아래 그래프와 통계가 이번 실행 기록입니다.</p>
      </article>
      <article>
        <strong>사전 생성 참조 기록</strong>
        <p>이 TEP 보고서에는 참조 기록이 연결되지 않았습니다. 참조 데이터 탐색은 선택 기능이며, 데이터가 없어도 기준·변경 시뮬레이션은 실행됩니다.</p>
      </article>
    </div>
    {result.status === "completed" && <>
      <p>{result.configuration.variable}: 기준 {result.provenance?.initial_xmv[Number(result.configuration.variable.slice(3))-1].toFixed(6)} → 변경 {result.configuration.candidate_value} percent_full_scale. 펌프 속도가 아닙니다.</p>
      <label>측정 변수
        <select value={variable} onChange={e => setVariable(e.target.value)}>
          {keys.map(k => <option key={k} value={k}>{k} · {result.variables[k].name} ({result.variables[k].unit})</option>)}
        </select>
      </label>
      <svg viewBox="0 0 760 290" role="img" aria-label={`${variable} 기준 및 변경 시계열, ${unit}`} style={{width:"100%"}}>
        <path d="M65 45 V245 H715" fill="none" stroke="currentColor" />
        <text x="8" y="45" fontSize="12">{max.toFixed(3)}</text>
        <text x="8" y="245" fontSize="12">{min.toFixed(3)}</text>
        <text x="65" y="270" fontSize="12">0 s</text>
        <text x="650" y="270" fontSize="12">{result.configuration.horizon_s} s</text>
        <text x="65" y="25" fontSize="13">{variable} ({unit})</text>
        <polyline points={line(a)} fill="none" stroke="#2563eb" strokeWidth="2" />
        <polyline points={line(b)} fill="none" stroke="#db5800" strokeWidth="2" />
      </svg>
      <p>파랑: 기준 입력 · 주황: 변경 입력. 두 실행은 같은 초기 상태와 시드에서 시작합니다.</p>
      <table><thead><tr><th>변수 / 단위</th><th>기준 최댓값</th><th>변경 최댓값</th><th>종료 시 차이</th><th>최대 절대 차이</th></tr></thead>
        <tbody>{keys.map(k => <tr key={k}><td>{k} ({result.variables[k].unit})</td>
          <td>{result.comparison[k].baseline_max.toFixed(4)}</td><td>{result.comparison[k].candidate_max.toFixed(4)}</td>
          <td>{result.comparison[k].final_delta.toFixed(4)}</td><td>{result.comparison[k].max_abs_delta.toFixed(4)}</td></tr>)}</tbody>
      </table>
      <details><summary>{variable}의 전체 시계열 ({a.length}개 관측)</summary>
        <table><thead><tr><th>시간 (s)</th><th>기준 ({unit})</th><th>변경 ({unit})</th><th>차이 ({unit})</th></tr></thead>
          <tbody>{a.map((p, i) => <tr key={p.time_s}><td>{p.time_s}</td><td>{p.xmeas[index].toFixed(5)}</td><td>{b[i].xmeas[index].toFixed(5)}</td><td>{(b[i].xmeas[index]-p.xmeas[index]).toFixed(5)}</td></tr>)}</tbody>
        </table>
      </details>
    </>}
    <details><summary>재현 설정과 출처</summary>
      <p>제어기: {result.configuration.controller} · 모드: {result.configuration.operating_mode} · 시드: {result.configuration.random_seed}</p>
      <p>적분 간격 {result.configuration.integration_step_s}s · 관측 주기 {result.configuration.sample_period_s}s · 시험 {result.configuration.horizon_s}s</p>
      <p>실측 오차 평가 / 실제 설비 적용성 검증: 미완료</p>
      <p>TEP 시뮬레이션에서 관측된 범위나 참조 데이터의 통계는 현장 안전 한계로 사용하지 않습니다.</p>
      {result.provenance && <>
        <p>출처: <a href={`https://github.com/rcandell/tesim/tree/${result.provenance.source_commit}`} target="_blank" rel="noreferrer">NIST TE 구현</a></p>
        <p>커밋: <code>{result.provenance.source_commit}</code> · {result.provenance.compiler}</p>
      </>}
      <pre style={{overflowX:"auto"}}>{JSON.stringify(result.configuration, null, 2)}</pre>
    </details>
  </section>;
}
