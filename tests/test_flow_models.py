"""FlowState 스냅샷 모델 테스트."""
import json

from backend.flow.models import FlowState


def _tick(price=2187000, vol=10, side="buy", t="09:30:15"):
    return {"t": t, "price": price, "sign": "down", "change": -41000,
            "rate": -1.84, "vol": vol, "acml_vol": 1179948,
            "acml_value": 2593885000000, "strength": 112.34, "side": side}


def _pgm(net_qty=500, net_value=1093500000, t="09:30:16"):
    return {"t": t, "sell_qty": 1000, "sell_value": 2187000000,
            "buy_qty": 1500, "buy_value": 3280500000,
            "net_qty": net_qty, "net_value": net_value}


def test_snapshot_schema_and_json_safe():
    s = FlowState("000660", "SK하이닉스", "demo")
    s.apply_tick(_tick())
    s.apply_program(_pgm())
    s.set_estimate([{"asof": "10:00", "frgn": -120000, "orgn": 50000, "sum": -70000}])
    s.set_daily([{"date": "2026-07-09", "prsn": 100, "frgn": -200, "orgn": 90,
                  "close": 2186000}])
    s.set_detail({"date": "2026-07-09",
                  "rows": [{"name": "연기금", "qty": 48907, "value": 113357000000}]})
    s.set_status(connected=True, note="")
    snap = s.snapshot()
    assert snap["code"] == "000660" and snap["name"] == "SK하이닉스"
    assert snap["mode"] == "demo"
    m = snap["market"]
    assert m["price"] == 2187000 and m["sign"] == "down" and m["strength"] == 112.34
    assert snap["tape"][0]["price"] == 2187000
    assert snap["program"]["net_qty"] == 500
    assert snap["program"]["points"][-1]["net_value"] == 1093500000
    assert snap["estimate"]["rows"][0]["frgn"] == -120000
    assert snap["daily"][0]["frgn"] == -200
    assert snap["detail"]["date"] == "2026-07-09"
    assert snap["detail"]["rows"][0]["name"] == "연기금"
    assert snap["status"]["connected"] is True
    json.dumps(snap, ensure_ascii=False)  # 직렬화 가능해야 SSE로 나감


def test_set_market_updates_price_without_touching_tape():
    # 웹소켓 공백 시 REST 폴백 — 시세만 갱신하고 체결 테이프는 오염하지 않는다
    s = FlowState("000660", "SK하이닉스", "live")
    s.apply_tick(_tick())
    s.set_market({"price": 2244000, "sign": "up", "change": 58000, "rate": 2.65,
                  "acml_vol": 3317403, "acml_value": 7371903475500,
                  "time": "13:05:00"})
    snap = s.snapshot()
    assert snap["market"]["price"] == 2244000 and snap["market"]["time"] == "13:05:00"
    assert snap["market"]["strength"] == 112.34  # 미제공 필드는 기존값 유지
    assert len(snap["tape"]) == 1  # 테이프 불변


def test_tape_capped_at_30_newest_first():
    s = FlowState("000660", "SK하이닉스", "demo")
    for i in range(40):
        s.apply_tick(_tick(price=2187000 + i, t=f"09:30:{i % 60:02d}"))
    snap = s.snapshot()
    assert len(snap["tape"]) == 30
    assert snap["tape"][0]["price"] == 2187000 + 39  # 최신이 맨 앞


def test_program_events_carry_cumulative_totals():
    # H0STPGM0 이벤트는 당일 '누적치'를 담는다(실측 2026-07-10) — 대입이지 가산이 아니다.
    s = FlowState("000660", "SK하이닉스", "demo")
    for i in range(250):
        cum = (i + 1) * 10
        s.apply_program(_pgm(net_qty=cum, net_value=cum * 100,
                             t=f"10:{i // 60:02d}:{i % 60:02d}"))
    snap = s.snapshot()
    assert snap["program"]["net_qty"] == 2500      # 마지막 누적치 그대로
    assert snap["program"]["net_value"] == 250000
    # 분 단위 버킷(같은 분은 마지막 값으로 교체) — 250초 이벤트 → 10:00~10:04 5버킷
    assert len(snap["program"]["points"]) == 5
    assert snap["program"]["points"][-1]["net_value"] == 250000  # 누적 곡선


def test_program_points_bucketed_per_minute_keep_whole_day():
    # 활발한 날 웹소켓 이벤트가 초당 수건이어도 분당 1점만 유지 — 당일 전체
    # 곡선이 deque 상한에 밀려나지 않는다(P0-1 플랫라인 사고의 근본 원인).
    s = FlowState("000660", "SK하이닉스", "demo")
    for m in range(60):            # 09:00~09:59, 분당 4이벤트
        for sec in (0, 15, 30, 45):
            v = (m * 60 + sec) * 1000
            s.apply_program(_pgm(net_qty=m, net_value=v, t=f"09:{m:02d}:{sec:02d}"))
    pts = s.snapshot()["program"]["points"]
    assert len(pts) == 60                       # 분당 1점
    assert pts[0]["t"] == "09:00:45"            # 각 분의 마지막 이벤트로 교체
    assert pts[-1]["net_value"] == (59 * 60 + 45) * 1000


def test_program_day_range_tracks_all_events_and_backfill():
    # Y축 도메인은 '당일 누적값 전체' min/max — 버킷으로 접힌 중간 극값도 포함
    s = FlowState("000660", "SK하이닉스", "demo")
    s.apply_program(_pgm(net_value=-500, t="09:01:10"))
    s.apply_program(_pgm(net_value=-9000, t="09:01:20"))   # 같은 분의 극값
    s.apply_program(_pgm(net_value=-100, t="09:01:30"))    # 버킷은 이 값으로 교체
    p = s.snapshot()["program"]
    assert len(p["points"]) == 1 and p["points"][0]["net_value"] == -100
    assert p["day_min"] == -9000 and p["day_max"] == -100
    # REST 백필 포인트도 범위에 반영
    s.set_program_total(10, 7000, points=[
        {"t": "09:00:00", "net_qty": 1, "net_value": -12000},
        {"t": "09:30:00", "net_qty": 10, "net_value": 7000}])
    p = s.snapshot()["program"]
    assert p["day_min"] == -12000 and p["day_max"] == 7000


def test_stall_detected_after_threshold(monkeypatch):
    # 마지막 실체결 수신 후 stall_sec(기본 90초) 경과 → 서버가 정지로 판정
    import backend.flow.models as models
    base = 1_700_000_000.0
    monkeypatch.setattr(models.time, "time", lambda: base)
    s = FlowState("000660", "SK하이닉스", "live")
    assert s.snapshot()["stall"] == {"stalled": False, "since": None, "sec": None}
    s.apply_tick(_tick(t="10:15:00"))
    monkeypatch.setattr(models.time, "time", lambda: base + 89)
    assert s.snapshot()["stall"]["stalled"] is False
    monkeypatch.setattr(models.time, "time", lambda: base + 91)
    st = s.snapshot()["stall"]
    assert st["stalled"] is True and st["since"] == "10:15:00" and st["sec"] == 91


def test_rest_fallback_resets_stall_only_on_new_volume(monkeypatch):
    # VI 중엔 REST 시세가 응답해도 누적 거래량이 안 늘어난다 — 정지 판정 유지
    import backend.flow.models as models
    base = 1_700_000_000.0
    monkeypatch.setattr(models.time, "time", lambda: base)
    s = FlowState("000660", "SK하이닉스", "live")
    s.apply_tick(_tick(t="10:15:00"))
    monkeypatch.setattr(models.time, "time", lambda: base + 120)
    s.set_market({"price": 2187000, "acml_vol": 1179948, "time": "10:17:00"})
    st = s.snapshot()["stall"]
    assert st["stalled"] is True                        # 거래량 동일 → 정지 유지
    assert st["since"] == "10:15:00"  # 폴백이 time을 덮어써도 정지 시각은 고정(리뷰)
    s.set_market({"price": 2187000, "acml_vol": 1180000, "time": "10:17:10"})
    assert s.snapshot()["stall"]["stalled"] is False    # 신규 체결 → 해제


def test_volume_gate_requires_increase_not_difference(monkeypatch):
    # 자정 카운터 리셋(감소)·재시작 첫 폴링(이전값 None)은 수신이 아니다(리뷰 확정)
    import backend.flow.models as models
    base = 1_700_000_000.0
    monkeypatch.setattr(models.time, "time", lambda: base)
    s = FlowState("000660", "SK하이닉스", "live")
    s.set_market({"price": 100, "acml_vol": 0, "time": "08:00:00"})   # 재시작 직후
    assert s.snapshot()["stall"]["since"] is None                     # 수신 아님
    s.apply_tick(_tick(t="15:00:00"))          # 실체결(acml_vol=1179948)
    s.reset_intraday()                         # 자정 롤오버 — market.vol은 남는다
    s.set_market({"price": 100, "acml_vol": 0, "time": "08:00:01"})   # 프리오픈 리셋
    assert s.snapshot()["stall"]["since"] is None                     # 수신 오인 금지


def test_market_state_estimation():
    import datetime as dt

    from backend.flow.models import market_state
    mon = dt.datetime(2026, 7, 13, 10, 0)     # 월요일 정규장
    assert market_state(mon, False, True)["state"] == "open"
    assert market_state(mon, True, True)["state"] == "halt"      # 공백 → VI/CB 의심
    assert market_state(mon, True, False)["state"] == "open"     # 데이터 자체가 없으면 대기
    assert market_state(dt.datetime(2026, 7, 11, 10, 0), False, True)["state"] == "closed"  # 토
    assert market_state(dt.datetime(2026, 7, 13, 7, 0), False, True)["state"] == "closed"
    assert market_state(dt.datetime(2026, 7, 13, 8, 30), True, True)["state"] == "pre"
    assert market_state(dt.datetime(2026, 7, 13, 16, 0), True, True)["state"] == "after"
    assert market_state(dt.datetime(2026, 7, 13, 21, 0), False, True)["state"] == "closed"
    # 장마감 동시호가(15:20~30): 체결 공백이 정상 — halt 오탐 금지(리뷰 확정 회귀)
    assert market_state(dt.datetime(2026, 7, 13, 15, 25), True, True)["state"] == "auction"


def test_program_points_thinned_for_sse():
    # 720분 하루치도 스냅샷은 ≤241점(1초마다 전문 재전송 — 대역 절약), 마지막 점 보존
    s = FlowState("000660", "SK하이닉스", "demo")
    for m in range(720):
        s.apply_program(_pgm(net_value=m, t=f"{8 + m // 60:02d}:{m % 60:02d}:00"))
    pts = s.snapshot()["program"]["points"]
    assert len(pts) <= 241
    assert pts[-1]["net_value"] == 719   # 최신 누적치는 반드시 포함
    assert pts == sorted(pts, key=lambda p: p["t"])


def test_adr_snapshot_computes_conversion_and_premium():
    # 환산가 = DR가격 × 비율 × 환율, 괴리율 = (환산-원주)/원주 — 원주가는 틱마다
    # 변하므로 스냅샷 시점 계산
    s = FlowState("000660", "SK하이닉스", "live")
    s.set_adr({"sym": "SKHYV", "usd": 150.0, "base_usd": 149.0, "fx": 1500.0,
               "ratio": 10.0, "us_open": False, "src": "kis", "fetched": "10:00:00"})
    a = s.snapshot()["adr"]
    assert a["converted"] == 2_250_000
    assert a["premium_pct"] is None          # 원주 체결 전 — 판정 보류
    s.apply_tick(_tick(price=2_187_000))
    a = s.snapshot()["adr"]
    assert a["ord_price"] == 2_187_000
    assert a["premium_pct"] == 2.88          # (2.25M/2.187M - 1)*100
    assert FlowState("005930", "삼성전자", "live").snapshot()["adr"] is None


def test_credit_and_shortsale_snapshot_with_signal():
    s = FlowState("000660", "SK하이닉스", "live")
    s.set_credit({"rows": [
        {"date": "2026-07-09", "qty": 3_310_000, "ratio": 0.45, "new": 0,
         "rdmp": 0, "close": 2_110_000, "value": 1, "chg": None},
        {"date": "2026-07-10", "qty": 3_240_000, "ratio": 0.44, "new": 0,
         "rdmp": 0, "close": 2_130_000, "value": 1, "chg": -70_000}],
        "asof": "2026-07-10"})
    s.set_shortsale({"rows": [{"date": "2026-07-10", "qty": 254_632,
                               "vol": 4_827_239, "ratio": 5.27, "value": 1,
                               "close": 2_180_000}], "asof": "2026-07-10"})
    snap = s.snapshot()
    assert snap["credit"]["asof"] == "2026-07-10"
    assert snap["credit"]["signal"]["tone"] in ("good", "info", "warn", "flat")
    assert snap["shortsale"]["rows"][-1]["ratio"] == 5.27
    import json
    json.dumps(snap, ensure_ascii=False)


def test_size_distribution_buckets_by_session_and_side():
    from backend.flow.models import size_signal
    s = FlowState("000660", "SK하이닉스", "live")
    s.apply_tick(_tick(vol=5, side="buy", t="08:30:00"))     # 장전 1-10주
    s.apply_tick(_tick(vol=200, side="sell", t="16:10:00"))  # 장후 100초과
    s.apply_tick(_tick(vol=60, side="buy", t="13:00:00"))    # 정규 51-100주
    z = s.snapshot()["sizes"]
    assert z["pre"]["buy"]["s1"] == {"n": 1, "v": 5 * 2187000}
    assert z["after"]["sell"]["s4"] == {"n": 1, "v": 200 * 2187000}
    assert z["regular"]["buy"]["s3"]["n"] == 1
    assert z["signals"]["after"] is None       # 표본 30건 미만 — 판정 보류
    # 판정: 100주 초과 매도 대금 비중 40%↑ → 기관성 매도(추정)
    for _ in range(40):
        s.apply_tick(_tick(vol=500, side="sell", t="16:20:00"))
        s.apply_tick(_tick(vol=2, side="buy", t="16:20:01"))
    sig = s.snapshot()["sizes"]["signals"]["after"]
    assert sig["text"] == "기관성 매도 우세(추정)" and sig["tone"] == "warn"
    # 개인 소액 중심: 1-10주 건수 70%↑
    ses = {"buy": {k: {"n": 0, "v": 0} for k in ("s1", "s2", "s3", "s4")},
           "sell": {k: {"n": 0, "v": 0} for k in ("s1", "s2", "s3", "s4")}}
    ses["buy"]["s1"] = {"n": 80, "v": 80 * 10}
    ses["sell"]["s2"] = {"n": 20, "v": 20 * 300}
    assert size_signal(ses)["text"] == "개인 소액 물량 중심(추정)"
    # 양쪽 다 40% 초과 시 큰 쪽으로 판정 — 순매수인데 '매도 우세' 오판 방지(리뷰)
    ses2 = {side: {k: {"n": 0, "v": 0} for k in ("s1", "s2", "s3", "s4")}
            for side in ("buy", "sell")}
    ses2["buy"]["s4"] = {"n": 30, "v": 55_0000_0000}
    ses2["sell"]["s4"] = {"n": 25, "v": 42_0000_0000}
    assert size_signal(ses2)["text"] == "기관성 매수 우세(추정)"
    s.reset_intraday()
    z = s.snapshot()["sizes"]
    assert z["after"]["sell"]["s4"]["n"] == 0  # 당일 한정 → 리셋


def test_reset_intraday_clears_exvol_and_member():
    # 거래소별 거래량·거래원은 당일 누적 기반 — 전일 것이 남으면 오도(리뷰 확정)
    s = FlowState("000660", "SK하이닉스", "live")
    s.set_exvol({"krx": {"price": 1, "vol": 1, "pbmn": 1},
                 "nxt": {"price": 1, "vol": 1, "pbmn": 1},
                 "nxt_share_pct": 50.0, "sessions": {}, "warn": None,
                 "asof": "16:00:00"})
    s.set_member({"sell": [], "buy": [], "basis": "UN", "glob": None,
                  "asof": "16:00:00"})
    s.reset_intraday()
    snap = s.snapshot()
    assert snap["exvol"] is None and snap["member"] is None


def test_snapshot_has_kst_clock_fields():
    # 표시 시각의 단일 진실원 — 클라이언트는 로컬 시계 대신 이 값을 쓴다(P0-3)
    import re

    from backend.flow import kst
    snap = FlowState("000660", "SK하이닉스", "live").snapshot()
    assert snap["kst_date"] == kst.today().isoformat()
    assert re.fullmatch(r"\d{2}:\d{2}:\d{2}", snap["kst_time"])
    assert snap["market_state"]["label"]


def test_empty_state_snapshot_has_nulls_not_crash():
    snap = FlowState("000660", "SK하이닉스", "live").snapshot()
    assert snap["market"]["price"] is None
    assert snap["tape"] == [] and snap["daily"] == []
    assert snap["estimate"]["rows"] == []
    assert snap["detail"] == {"date": None, "rows": []}
    assert snap["program"]["net_qty"] == 0
    json.dumps(snap)


def test_short_balance_snapshot_and_signal():
    s = FlowState("000660", "SK하이닉스", "live")
    s.apply_tick(_tick())  # rate=-1.84 (하락)
    s.set_short({"rows": [
        {"date": "2026-07-09", "qty": 14420269, "value": 31522708034000,
         "chg": None, "src": "kofia"},
        {"date": "2026-07-10", "qty": 14140221, "value": 30825681780000,
         "chg": -280048, "src": "kofia"}],
        "asof": "2026-07-10", "source": "kofia",
        "updated": "2026-07-13T09:00:00"})
    snap = s.snapshot()
    sb = snap["short"]
    assert sb["rows"][-1]["qty"] == 14140221 and sb["source"] == "kofia"
    # 주가 하락(-1.84%) × 잔고 감소(-280,048) → 숏커버링 구간
    assert sb["signal"]["text"] == "숏커버링 가능 구간"
    assert sb["signal"]["tone"] == "info"
    json.dumps(snap, ensure_ascii=False)


def test_short_signal_none_without_price_or_rows():
    s = FlowState("000660", "SK하이닉스", "live")
    assert s.snapshot()["short"]["signal"] is None  # 데이터 없음 → 판정 안 함
    s.set_short({"rows": [{"date": "2026-07-10", "qty": 1, "value": 1,
                           "chg": 5, "src": "kofia"}]})
    assert s.snapshot()["short"]["signal"] is None  # 주가 등락 미확보


def test_reset_intraday_clears_day_scoped_keeps_confirmed():
    # 서버가 주말을 넘겨 떠 있으면 전일 잠정이 남는 실사고(2026-07-13) 방지
    s = FlowState("000660", "SK하이닉스", "live")
    s.apply_tick(_tick())
    s.apply_program(_pgm())
    s.set_estimate([{"asof": "14:30", "frgn": -1, "orgn": 1, "sum": 0}])
    s.set_estimate_detail({"asof": "14:30", "rows": [{"name": "투신", "qty": 1,
                           "value": 1}], "etc_qty": 2, "etc_value": 2})
    s.set_daily([{"date": "2026-07-10", "prsn": 1, "frgn": -1, "orgn": 0,
                  "close": 2180000}])
    s.set_detail({"date": "2026-07-10", "rows": [{"name": "연기금", "qty": 1,
                  "value": 1}]})
    s.set_short({"rows": [{"date": "2026-07-10", "qty": 1, "value": 1,
                           "chg": None, "src": "kofia"}]})
    s.reset_intraday()
    snap = s.snapshot()
    assert snap["tape"] == []                          # 당일 한정 → 비움
    assert snap["program"] == {"net_qty": 0, "net_value": 0, "points": [],
                               "day_min": None, "day_max": None}
    assert snap["stall"]["since"] is None              # 정지 판정 기준도 리셋
    assert snap["estimate"]["rows"] == []
    assert snap["estimate_detail"]["rows"] == []
    assert snap["estimate_detail"]["etc_qty"] is None
    assert snap["daily"] and snap["detail"]["rows"]    # 확정 데이터는 유지
    assert snap["short"]["rows"]                       # 대차잔고도 유지(여러 날)
    assert snap["market"]["price"] == 2187000          # 시세는 폴백이 곧 자가수정


# ── 일별 수급 표의 종가: 신뢰 소스로 통일(한 화면 두 값 방지) ──────────────
def test_daily_close_comes_from_trusted_source_not_investor_tr():
    """KIS 투자자 TR(FHKST01010900)의 stck_clpr은 같은 날 공매도 TR·FDR 일봉과
    어긋난다(2026-07-23 실측: 7/21 1,872,000 vs 1,836,000·7/20 1,841,000 vs
    1,764,000). 같은 화면에 종가가 두 값으로 나오지 않게 신뢰 소스로 덮어쓴다."""
    s = FlowState("000660", "SK하이닉스", "live")
    s.set_daily([
        {"date": "2026-07-20", "prsn": 1, "frgn": 2, "orgn": 3, "close": 1841000},
        {"date": "2026-07-21", "prsn": 1, "frgn": 2, "orgn": 3, "close": 1872000},
        {"date": "2026-07-22", "prsn": 1, "frgn": 2, "orgn": 3, "close": 1830000}])
    s.set_shortsale({"rows": [
        {"date": "2026-07-21", "qty": 68549, "vol": 4639208, "ratio": 1.48,
         "value": 1, "close": 1836000},
        {"date": "2026-07-22", "qty": 91472, "vol": 4802637, "ratio": 1.90,
         "value": 1, "close": 1830000}], "asof": "2026-07-22"})
    s.set_credit({"rows": [
        {"date": "2026-07-20", "qty": 3313674, "ratio": 0.45, "new": 0,
         "rdmp": 0, "close": 1764000, "value": 1, "chg": None}],
        "asof": "2026-07-20"})
    assert [r["close"] for r in s.snapshot()["daily"]] == [1764000, 1836000, 1830000]


def test_daily_close_blank_when_no_trusted_source():
    # 신뢰 소스에 없는 날은 틀릴 수 있는 값을 남기지 않고 비운다(화면 '–')
    s = FlowState("000660", "SK하이닉스", "live")
    s.set_daily([{"date": "2026-06-01", "prsn": 1, "frgn": 2, "orgn": 3,
                  "close": 9999000}])
    assert s.snapshot()["daily"][0]["close"] is None


# ── 오늘 수급 요약: 마감 후 잠정 → 확정 승격 ──────────────────────────────
def test_today_flow_prefers_confirmed_row_over_stale_estimate():
    """잠정 API(HHPTJ04160200)는 슬롯이 14:30이 마지막 — 마감 후에도 14:30에 멈춰
    14:30~15:30 물량이 빠진다(2026-07-23 실측: 잠정 외인 +559,000 vs 확정
    +689,696). 같은 화면에 당일 확정치가 이미 있으면 그쪽을 쓴다."""
    from backend.flow.models import today_flow
    daily = [{"date": "2026-07-22", "prsn": 1, "frgn": 640418, "orgn": -564978},
             {"date": "2026-07-23", "prsn": -530255, "frgn": 689696,
              "orgn": -147399}]
    est = [{"asof": "14:30", "frgn": 559000, "orgn": -14000, "sum": 545000}]
    f = today_flow(daily, est, "2026-07-23")
    assert f["src"] == "confirmed" and f["frgn"] == 689696 and f["orgn"] == -147399


def test_today_flow_uses_estimate_while_confirmed_missing():
    from backend.flow.models import today_flow
    est = [{"asof": "11:20", "frgn": -812000, "orgn": 135000, "sum": -677000},
           {"asof": "14:30", "frgn": 559000, "orgn": -14000, "sum": 545000}]
    f = today_flow([{"date": "2026-07-22", "prsn": 1, "frgn": 2, "orgn": 3}],
                   est, "2026-07-23")
    assert f["src"] == "estimate" and f["asof"] == "14:30" and f["frgn"] == 559000
    assert today_flow([], [], "2026-07-23") is None


def test_snapshot_exposes_today_flow(monkeypatch):
    from backend.flow import models
    monkeypatch.setattr(models.kst, "now",
                        lambda: __import__("datetime").datetime(2026, 7, 23, 16, 15))
    s = FlowState("000660", "SK하이닉스", "live")
    s.set_daily([{"date": "2026-07-23", "prsn": -530255, "frgn": 689696,
                  "orgn": -147399, "close": 1919000}])
    s.set_estimate([{"asof": "14:30", "frgn": 559000, "orgn": -14000,
                     "sum": 545000}])
    tf = s.snapshot()["today_flow"]
    assert tf["src"] == "confirmed" and tf["frgn"] == 689696


def _fix_now(monkeypatch, hh, mm):
    import datetime as _dt

    from backend.flow import models
    monkeypatch.setattr(models.kst, "now",
                        lambda: _dt.datetime(2026, 7, 23, hh, mm))


def test_daily_close_today_falls_back_to_krx_regular_close(monkeypatch):
    """마감 직후 오늘 행은 공매도(16시 이후 공표)·신용(T+2)이 아직 없어 비어버린다
    — 같은 화면의 해외·거래소 판정이 쓰는 KRX 정규 종가(div J, 15:30 이후 동결)로
    메워 한 화면 두 값을 막는다."""
    s = FlowState("000660", "SK하이닉스", "live")
    s.set_daily([{"date": "2026-07-23", "prsn": -530255, "frgn": 689696,
                  "orgn": -147399, "close": 1925000}])
    s.set_exvol({"krx": {"price": 1919000, "vol": 4081543, "pbmn": 1},
                 "nxt": {"price": 1912000, "vol": 2402725, "pbmn": 1},
                 "nxt_share_pct": 37.1,
                 "sessions": {"pre": 1, "main": 1, "after": 1},
                 "warn": None, "asof": "15:45:00"})
    _fix_now(monkeypatch, 15, 45)
    assert s.snapshot()["daily"][0]["close"] == 1919000
    # 정규장 종료 전 현재가는 '종가'가 아니다 — 쓰지 않는다
    _fix_now(monkeypatch, 13, 0)
    assert s.snapshot()["daily"][0]["close"] is None


# ── 매수 유의사항(토스) ───────────────────────────────────────────────────

def test_warnings_ride_the_snapshot_and_default_empty():
    """유의사항은 있으면 싣고 없으면 빈 배열 — 키가 사라지면 프런트가 터진다."""
    from backend.flow.models import FlowState
    s = FlowState("000660", "SK하이닉스", "live")
    assert s.snapshot()["warnings"] == []
    s.set_warnings([{"type": "OVERHEATED", "label": "단기과열", "tone": "warn",
                     "exchange": "KRX", "start": "2026-09-01", "end": None}])
    assert [w["label"] for w in s.snapshot()["warnings"]] == ["단기과열"]


def test_warnings_can_be_cleared_when_the_flag_lifts():
    """지정이 풀리면 빈 목록이 와야 배지가 사라진다 — 마지막 값 유지는 오답이다.

    VI는 2~10분이면 풀린다. 다른 패널처럼 '실패 시 이전 값 유지'를 적용하면
    이미 끝난 VI가 화면에 종일 남는다."""
    from backend.flow.models import FlowState
    s = FlowState("000660", "SK하이닉스", "live")
    s.set_warnings([{"type": "VI_STATIC", "label": "VI 발동(정적)",
                     "tone": "info", "exchange": "KRX",
                     "start": None, "end": None}])
    s.set_warnings([])
    assert s.snapshot()["warnings"] == []
