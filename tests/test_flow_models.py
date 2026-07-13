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
    assert len(snap["program"]["points"]) == 200   # 차트 포인트 상한
    assert snap["program"]["points"][-1]["net_value"] == 250000  # 누적 곡선


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
    assert snap["program"] == {"net_qty": 0, "net_value": 0, "points": []}
    assert snap["estimate"]["rows"] == []
    assert snap["estimate_detail"]["rows"] == []
    assert snap["estimate_detail"]["etc_qty"] is None
    assert snap["daily"] and snap["detail"]["rows"]    # 확정 데이터는 유지
    assert snap["short"]["rows"]                       # 대차잔고도 유지(여러 날)
    assert snap["market"]["price"] == 2187000          # 시세는 폴백이 곧 자가수정
