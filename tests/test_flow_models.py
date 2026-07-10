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
    assert snap["status"]["connected"] is True
    json.dumps(snap, ensure_ascii=False)  # 직렬화 가능해야 SSE로 나감


def test_tape_capped_at_30_newest_first():
    s = FlowState("000660", "SK하이닉스", "demo")
    for i in range(40):
        s.apply_tick(_tick(price=2187000 + i, t=f"09:30:{i % 60:02d}"))
    snap = s.snapshot()
    assert len(snap["tape"]) == 30
    assert snap["tape"][0]["price"] == 2187000 + 39  # 최신이 맨 앞


def test_program_accumulates_and_points_capped():
    s = FlowState("000660", "SK하이닉스", "demo")
    for i in range(250):
        s.apply_program(_pgm(net_qty=10, net_value=1000, t=f"10:{i // 60:02d}:{i % 60:02d}"))
    snap = s.snapshot()
    assert snap["program"]["net_qty"] == 2500      # 이벤트 순매수 누적
    assert snap["program"]["net_value"] == 250000
    assert len(snap["program"]["points"]) == 200   # 차트 포인트 상한
    assert snap["program"]["points"][-1]["net_value"] == 250000  # 누적 곡선


def test_empty_state_snapshot_has_nulls_not_crash():
    snap = FlowState("000660", "SK하이닉스", "live").snapshot()
    assert snap["market"]["price"] is None
    assert snap["tape"] == [] and snap["daily"] == []
    assert snap["estimate"]["rows"] == []
    assert snap["program"]["net_qty"] == 0
    json.dumps(snap)
