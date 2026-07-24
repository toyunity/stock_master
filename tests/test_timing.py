"""매매 타이밍 판정(이평 20/60/120 × 수급) 순수 함수 테스트.

설계: docs/superpowers/specs/2026-07-14-timing-panel-design.md
보수적 판정 — 추세·수급이 함께 확실할 때만 매수/매도, 나머지 관망.
"""


def _ind(ma20, ma60, ma120, rsi=50.0, golden=False, dead=False):
    return {"ma20": ma20, "ma60": ma60, "ma120": ma120, "rsi14": rsi,
            "golden_fresh": golden, "dead_fresh": dead}


def _flow(direction, streak=0):
    return {"dir": direction, "streak": streak, "reasons": []}


# ── summarize_flows: 확정(주) + 오늘 잠정(확인) → 방향 ──────────────────
def test_summarize_flows_confirmed_and_today_agree_inflow():
    from backend.analysis.timing import summarize_flows
    daily = [{"date": "2026-07-08", "frgn": 100, "orgn": 50},
             {"date": "2026-07-09", "frgn": 120, "orgn": 30},
             {"date": "2026-07-10", "frgn": 80, "orgn": 40}]
    est = [{"frgn": 60, "orgn": 20}]        # 오늘 잠정도 순매수
    s = summarize_flows(daily, est, program_net=1_000)
    assert s["dir"] == "inflow"
    assert s["streak"] == 3                  # 3일 연속 순매수


def test_summarize_flows_disagreement_is_neutral():
    from backend.analysis.timing import summarize_flows
    daily = [{"date": "2026-07-10", "frgn": 100, "orgn": 50}]   # 확정 순매수
    est = [{"frgn": -200, "orgn": -50}]                          # 오늘 잠정 순매도
    s = summarize_flows(daily, est, program_net=0)
    assert s["dir"] == "neutral"             # 상충 → 중립 완충


def test_summarize_flows_outflow():
    from backend.analysis.timing import summarize_flows
    daily = [{"date": "2026-07-09", "frgn": -50, "orgn": -30},
             {"date": "2026-07-10", "frgn": -80, "orgn": -20}]
    s = summarize_flows(daily, [{"frgn": -40, "orgn": -10}], program_net=-500)
    assert s["dir"] == "outflow"
    assert s["streak"] == 2


def test_summarize_flows_empty_is_neutral():
    from backend.analysis.timing import summarize_flows
    assert summarize_flows([], [], program_net=None)["dir"] == "neutral"


def test_streak_word_follows_streak_not_five_day_sum():
    """연속일수와 순매수/순매도 단어가 어긋나면 안 된다(2026-07-23 실사고).

    streak은 '최근일 부호'로 세는데 단어는 '5일 합계 부호'로 골라, 최근 3일이
    모두 순매수인 날 화면에 '외인·기관 3일 연속 순매도'가 떴다(SK하이닉스 실측).
    """
    from backend.analysis.timing import summarize_flows
    daily = [  # 실측: 5일 합은 −54.7만주(7/16 대량 유출), 최근 3일은 순매수
        {"date": "2026-07-16", "frgn": -469637, "orgn": -628785},
        {"date": "2026-07-20", "frgn": +331597, "orgn": -527040},
        {"date": "2026-07-21", "frgn": -237417, "orgn": +366154},
        {"date": "2026-07-22", "frgn": +640418, "orgn": -564978},
        {"date": "2026-07-23", "frgn": +689696, "orgn": -147399},
    ]
    s = summarize_flows(daily, [{"frgn": 559000, "orgn": -14000}], program_net=1)
    assert s["streak"] == 3
    # 부분 문자열이 아니라 전체 목록을 읽어서 검증한다 — 줄끼리 어긋나면 안 된다.
    # 오늘 잠정(+545,000주)은 순매수이므로 '반대 방향'이라고 말해선 안 되고,
    # 중립 처리의 근거는 5일 합계와의 전환 구간이다.
    assert s["reasons"] == [
        "외인·기관 3일 연속 순매수",
        "5일 합계는 순매도 — 방향 전환 구간(중립 처리)",
        "오늘 잠정도 순매수",
        "프로그램 순매수",
    ]
    assert s["dir"] == "neutral"          # 전환 구간은 보수적으로 중립 유지


# ── assess_timing: 추세 × 수급 매트릭스(보수적) ────────────────────────
def test_uptrend_inflow_is_buy():
    from backend.analysis.timing import assess_timing
    v = assess_timing(_ind(100, 90, 80), _flow("inflow", 3), last_price=110)
    assert v["stance"] == "buy" and v["tone"] == "good" and v["overheated"] is False
    assert v["headline"] and v["comment"] and v["reasons"]


def test_uptrend_outflow_is_hold():
    from backend.analysis.timing import assess_timing
    v = assess_timing(_ind(100, 90, 80), _flow("outflow"), last_price=110)
    assert v["stance"] == "hold"


def test_downtrend_outflow_is_sell():
    from backend.analysis.timing import assess_timing
    v = assess_timing(_ind(80, 90, 100), _flow("outflow"), last_price=70)
    assert v["stance"] == "sell" and v["tone"] == "warn"


def test_downtrend_inflow_is_watch():
    from backend.analysis.timing import assess_timing
    v = assess_timing(_ind(80, 90, 100), _flow("inflow"), last_price=70)
    assert v["stance"] == "watch" and v["tone"] == "info"


def test_uptrend_inflow_but_overheated_downgrades_to_hold():
    from backend.analysis.timing import assess_timing
    v = assess_timing(_ind(100, 90, 80, rsi=80), _flow("inflow"), last_price=110)
    assert v["stance"] == "hold" and v["overheated"] is True


def test_neutral_trend_neutral_flow_is_hold():
    from backend.analysis.timing import assess_timing
    # 현재가가 20일선 아래지만 이평은 정배열 배치 → 추세 중립(혼조)
    v = assess_timing(_ind(100, 90, 80), _flow("neutral"), last_price=95)
    assert v["stance"] == "hold"


def test_insufficient_data_is_hold_out():
    from backend.analysis.timing import assess_timing
    v = assess_timing(_ind(100, 90, None), _flow("inflow"), last_price=110)
    assert v["stance"] is None            # ma120 없음 → 판정 보류


def test_fresh_golden_cross_inflow_high_confidence_buy():
    from backend.analysis.timing import assess_timing
    v = assess_timing(_ind(100, 90, 80, golden=True), _flow("inflow", 2), last_price=110)
    assert v["stance"] == "buy" and v["confidence"] >= 3


def test_fresh_dead_cross_outflow_is_sell():
    from backend.analysis.timing import assess_timing
    v = assess_timing(_ind(80, 90, 100, dead=True), _flow("outflow", 2), last_price=70)
    assert v["stance"] == "sell" and v["confidence"] >= 3


# ── FlowState 통합: 스냅샷에 timing 실림 ──────────────────────────────
def test_flowstate_snapshot_carries_timing():
    from backend.flow.models import FlowState
    s = FlowState("000660", "SK하이닉스", "live")
    assert s.snapshot()["timing"] is None            # 기본 None(판정 보류)
    s.set_timing({"stance": "buy", "tone": "good", "headline": "🟢 매수 우호"})
    assert s.snapshot()["timing"]["stance"] == "buy"
    s.reset_intraday()
    assert s.snapshot()["timing"] is None            # 날짜 변경 시 비움


# ── compute_timing: 캔들→지표→수급→판정 통합 헬퍼 ─────────────────────
def test_compute_timing_detects_uptrend_and_flow():
    from backend.analysis.timing import compute_timing
    rows = [{"t": str(i), "open": 100 + i, "high": 100 + i, "low": 100 + i,
             "close": 100 + i} for i in range(120)]            # 우상향 120봉
    v = compute_timing(rows, [{"date": "2026-07-10", "frgn": 100, "orgn": 50}],
                       [{"frgn": 30, "orgn": 10}], 1000, last_price=240)
    assert v["stance"] is not None                   # 데이터 충분 → 판정
    assert "정배열" in v["reasons"][0]                # 우상향 → 정배열 감지
    assert any(("순매수" in r) or ("유입" in r) for r in v["reasons"])  # 수급 반영


def test_compute_timing_insufficient_candles_is_hold_out():
    from backend.analysis.timing import compute_timing
    rows = [{"t": str(i), "open": 100, "high": 100, "low": 100, "close": 100}
            for i in range(30)]                       # 120봉 미만 → ma120 없음
    assert compute_timing(rows, [], [], None, 100)["stance"] is None
