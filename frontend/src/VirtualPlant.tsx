import { useEffect, useState } from "react";
import type { components } from "./api.generated";
type State = components["schemas"]["Snapshot"];

export function VirtualPlant({
  token,
  approver,
  onChanged,
}: {
  token: string;
  approver: boolean;
  onChanged: () => void;
}) {
  const [plant, setPlant] = useState<State | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function api(path: string, body?: unknown): Promise<State> {
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), 15000);
    try {
      const result = await fetch("/api" + path, {
        method: body === undefined ? "GET" : "POST",
        headers: {
          "X-Iron-Man-Token": token,
          "Content-Type": "application/json",
        },
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: controller.signal,
      });
      const value = await result.json();
      if (!result.ok)
        throw new Error(
          typeof value.detail === "string" ? value.detail : "상태 갱신 실패"
        );
      return value as State;
    } finally {
      window.clearTimeout(timer);
    }
  }
  useEffect(() => {
    let active = true;
    setPlant(null);
    setError("");
    if (token)
      void api("/state")
        .then((value) => {
          if (active) setPlant(value);
        })
        .catch((e) => {
          if (active)
            setError(e instanceof Error ? e.message : "상태 조회 실패");
        });
    return () => {
      active = false;
    };
  }, [token]);
  async function change(path: string, body?: unknown) {
    setBusy(true);
    setError("");
    try {
      setPlant(await api(path, body));
      if (body !== undefined) onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : "상태 갱신 실패");
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="no-print" aria-labelledby="plant-heading">
      <div className="section-head">
        <h2 id="plant-heading">현재 가상 설비 상태</h2>
        <span className="eyebrow">MANUAL SIMULATION CLOCK</span>
      </div>
      <p className="muted">
        시간 진행 버튼을 눌러야 온도와 실제 펌프 속도가 계산됩니다. 실제
        설비·TEP와 연결되지 않았습니다.
      </p>
      {plant && (
        <>
          <div className="facts">
            <div>
              <small>온도</small>
              <strong>{plant.temperature_c.toFixed(2)}°C</strong>
            </div>
            <div>
              <small>실제 / 목표 펌프 속도</small>
              <strong>
                {plant.pump_speed_pct.toFixed(2)} /{" "}
                {(plant.target_pump_speed_pct ?? plant.pump_speed_pct).toFixed(
                  2
                )}
                %
              </strong>
            </div>
            <div>
              <small>가상 시간 / 부하</small>
              <strong>
                {plant.simulation_time_s.toFixed(0)}초 /{" "}
                {plant.load_ratio.toFixed(2)}
              </strong>
            </div>
          </div>
          <p className="muted">
            {plant.model_version} · 상태 {plant.revision} · 범위{" "}
            {plant.domain_status} · 센서 {plant.sensor_quality} · 관측{" "}
            {new Date(plant.observed_at * 1000).toLocaleString()}
          </p>
          {plant.domain_reason && (
            <p className="danger-text">{plant.domain_reason}</p>
          )}
        </>
      )}
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      <div className="actions">
        <button disabled={busy || !token} onClick={() => void change("/state")}>
          상태 조회
        </button>
        <button
          disabled={busy || !approver || plant?.domain_status !== "ready"}
          onClick={() => void change("/demo/advance", { seconds_s: 10 })}
        >
          가상 시간 10초 진행
        </button>
        <button
          disabled={busy || !approver}
          onClick={() => void change("/demo/sample", {})}
        >
          관측 갱신
        </button>
        <button
          disabled={busy || !approver}
          onClick={() => void change("/demo/reset", {})}
        >
          가상 설비 초기화
        </button>
        <button
          disabled={busy || !approver || plant?.domain_status !== "ready"}
          onClick={() => void change("/demo/state", { load_ratio: .6, sensor_quality: "valid" })}
        >
          데모 부하 0.6으로 변경
        </button>
      </div>
      <p className="muted">
        상태 조회는 관측 시각을 갱신하지 않습니다. 오래된 관측은 승인 담당자가
        관측 갱신 후 새 검토를 시작하세요. 관측 갱신은 화면의 이전 결과를 닫으며 저장된 기록을 수정하지 않습니다. 초기화는 요청 이력을 유지합니다.
      </p>
    </section>
  );
}
