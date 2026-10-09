"""Review metrics only; the v3 gateway policy retains approval authority."""
import math
import os
from backend.contracts import DeviationMetric, ReviewAssessment


def settings():
    enabled = False  # Reserved; these metrics do not enable or bypass approval.
    raw = os.getenv("IRON_MAN_NEGLIGIBLE_DELTA_C", "")
    try:
        threshold = float(raw)
        if not math.isfinite(threshold) or threshold < 0:
            threshold = None
    except ValueError:
        threshold = None
    return enabled, threshold


def assessment(result, policy=None):
    _, threshold = policy if policy is not None else settings()
    metrics = [DeviationMetric(kind=s.kind, baseline_peak_c=s.baseline_peak_c,
        candidate_peak_c=s.candidate_peak_c,
        absolute_delta_c=abs(s.candidate_peak_c - s.baseline_peak_c),
        material=None if threshold is None else abs(s.candidate_peak_c - s.baseline_peak_c) > threshold)
        for s in result.scenarios]
    status = "threshold_not_configured" if threshold is None else (
        "material_deviation" if any(m.material for m in metrics) else "within_tolerance")
    return ReviewAssessment(threshold_c=threshold, status=status, metrics=metrics,
        limitation="기존 속도 유지 대비 변경 후 최고 온도의 절대 차이입니다. 예측 오차·TEP 정상 범위·현실 안전 기준이 아닙니다.")
