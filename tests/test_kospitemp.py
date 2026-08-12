"""'코스피 온도' 순수 계산 — 종가 리스트만 넣는다(KIS 모킹 없음).

days[-1].v == now.price가 실측으로 참이라(2026-08-12) 현재가를 따로 받지 않는다.
그래서 이 모듈의 계산부는 네트워크와 완전히 분리된다.
"""
import pytest

from backend.education import glossary
from backend.flow import kospitemp as kt

# 2026-08-12 13:57 KST에 index_daily('0001','20260812')로 받은 종가 100개(오래된 순).
# 마지막 값 6602.53은 그 시각 now.price와 같았다 — 마지막 봉이 곧 현재가다.
_KOSPI_20260812 = [
    5763.22, 5781.20, 5405.75, 5553.92, 5642.21, 5460.46, 5438.87, 5277.30,
    5052.46, 5478.70, 5234.05, 5377.30, 5450.33, 5494.78, 5872.34, 5778.01,
    5858.87, 5808.62, 5967.75, 6091.39, 6226.05, 6191.92, 6219.09, 6388.47,
    6417.93, 6475.81, 6475.63, 6615.03, 6641.02, 6690.90, 6598.87, 6936.99,
    7384.56, 7490.05, 7498.00, 7822.24, 7643.15, 7844.01, 7981.41, 7493.18,
    7516.04, 7271.66, 7208.95, 7815.59, 7847.71, 8047.51, 8228.70, 8185.29,
    8476.15, 8788.38, 8801.49, 8639.41, 8160.59, 7484.41, 8096.93, 7730.82,
    7763.95, 8123.62, 8545.98, 8726.60, 8864.24, 9063.84, 9052.42, 9114.55,
    8203.84, 8471.02, 8930.30, 8411.21, 8394.65, 8476.48, 8303.41, 7648.09,
    8088.34, 8051.33, 7656.31, 7246.79, 7291.91, 7475.94, 6806.93, 6856.83,
    7284.41, 6820.60, 6516.27, 6747.95, 6797.70, 7096.89, 6690.62, 6755.75,
    6023.66, 5663.24, 5593.56, 6595.45, 6257.45, 6358.95, 6598.26, 6296.38,
    6258.77, 6299.66, 6345.53, 6602.53,
]


def test_ma_gap_is_distance_from_the_simple_mean():
    """현재가가 평균보다 얼마나 위/아래인가 — 백분율."""
    # 평균 100, 현재 110 → +10%
    closes = [90.0, 100.0, 110.0]
    assert kt.compute(closes)["ma_gap"] == 10.0


def test_ema_gap_weights_recent_days_more():
    """EMA는 최근에 가중이 실린다 — 단조 상승이면 현재가가 EMA보다 위다."""
    closes = [float(x) for x in range(100, 140)]
    g = kt.compute(closes)["ema_gap"]
    assert g is not None and g > 0


def test_down_avg_is_the_mean_drop_not_a_stdev():
    """하락일 평균 하락률(양수 %p). 표준편차가 아니다 — 그건 초보에게 안 읽힌다."""
    # -10%, -10%, -10% 세 번(사이에 보합) → 평균 하락률 10.0
    closes = [100.0, 90.0, 81.0, 72.9]
    assert kt.compute(closes)["down_avg"] == 10.0


def test_too_few_down_days_is_unknown_not_zero():
    """하락일이 3일 미만이면 표본이 너무 작다 — None이지 0이 아니다."""
    closes = [100.0, 101.0, 102.0, 103.0, 104.0]      # 하락일 0
    assert kt.compute(closes)["down_avg"] is None
    assert kt.compute([100.0, 99.0, 100.0, 99.5])["down_avg"] is None   # 2개


def test_short_or_dirty_input_is_all_none():
    """종가 2개 미만이면 전부 None. NaN·0·음수는 버린다(값이 아니다)."""
    assert kt.compute([])["ma_gap"] is None
    assert kt.compute([100.0])["ma_gap"] is None
    assert kt.compute([float("nan"), 0.0, -3.0, 100.0])["ma_gap"] is None


def test_verdict_bands_use_strict_less_than_everywhere():
    """경계는 전부 `<`(미만)로 통일 — 섞으면 경계값에서 읽는 사람도 테스트도 헷갈린다."""
    assert glossary.read_temp("ma_gap", -10.01) == "크게 눌림"
    assert glossary.read_temp("ma_gap", -10.0) == "눌림"      # 경계는 아래 구간
    assert glossary.read_temp("ma_gap", -3.0) == "비슷"
    assert glossary.read_temp("ma_gap", 2.99) == "비슷"
    assert glossary.read_temp("ma_gap", 3.0) == "위"
    assert glossary.read_temp("ma_gap", 10.0) == "크게 위"
    assert glossary.read_temp("ema_gap", 0.0) == "비슷"
    assert glossary.read_temp("down_avg", 0.99) == "잔잔"
    assert glossary.read_temp("down_avg", 3.5) == "거침"


def test_verdict_of_unknown_value_or_key_is_none():
    """모르는 값에 판정을 지어내지 않는다."""
    assert glossary.read_temp("ma_gap", None) is None
    assert glossary.read_temp("없는키", 1.0) is None


def test_todays_measured_values_are_reproducible():
    """2026-08-12 코스피 100거래일 실측 회귀 — 계산을 바꾸면 여기가 먼저 빨개진다.

    설계 문서 '실측' 절은 -6.34 / +2.63 / 4.99인데, 이 픽스처는 같은 날 13:57에
    다시 뽑았다 — 그 사이 장중에 마지막 봉이 움직여(뽑은 시점 6602.53) 앞의 두 값이
    -6.25 / +2.71로 옮겨갔다. 계산이 아니라 입력이 달라진 것이라 기대값을 갱신했다.
    판정 단어는 눌림/위/거침 그대로다(구간이 흔들리지 않았다는 뜻).
    리스트는 그날 응답에서 뽑은 종가다."""
    closes = _KOSPI_20260812
    d = kt.compute(closes)
    assert d["ma_gap"] == pytest.approx(-6.25, abs=0.01)
    assert d["ema_gap"] == pytest.approx(2.71, abs=0.01)
    assert d["down_avg"] == pytest.approx(4.99, abs=0.01)
    assert glossary.read_temp("ma_gap", d["ma_gap"]) == "눌림"
    assert glossary.read_temp("ema_gap", d["ema_gap"]) == "위"
    assert glossary.read_temp("down_avg", d["down_avg"]) == "거침"
