"""토스증권 Open API 어댑터 — 순수 파서 + 토큰 게이트/직렬화.

네트워크 미접촉(conftest 오프라인 가드가 실제로 잡는다). 픽스처는 공식 스펙
openapi.json v1.2.14의 응답 예제를 그대로 옮긴 것이다 — 값 모양이 바뀌면
여기서 먼저 깨져야 한다.
"""
import asyncio
import json
import time

import pytest

from backend.flow import toss


# ── 토큰: 키 게이트 + 발급 1회 ────────────────────────────────────────────

def test_no_key_refuses_even_with_valid_cached_token(tmp_path):
    """키가 비면 디스크에 멀쩡한 토큰이 있어도 거절한다.

    KIS와 같은 이유이자 토스에선 더 급하다 — 하네스는 SM_TOSS_*를 비워 '토스 미접촉'을
    보장하는데, 캐시 토큰으로 인증이 통과하면 검증 서버가 실 API를 때린다. 그리고
    토스는 **client당 토큰 1개**라, 검증 서버가 재발급하는 순간 실서버가 401이 된다."""
    (tmp_path / "toss_token.json").write_text(json.dumps(
        {"token": "cached-and-valid", "expires_at": time.time() + 9999}))
    client = toss.TossClient("", "", str(tmp_path))
    with pytest.raises(RuntimeError):
        asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
            client.token())


def test_cached_token_is_reused_without_issuing(tmp_path):
    (tmp_path / "toss_token.json").write_text(json.dumps(
        {"token": "cached", "expires_at": time.time() + 9999}))
    client = toss.TossClient("id", "secret", str(tmp_path))
    client._issue_token = _boom
    assert asyncio.run(client.token()) == "cached"


async def _boom(*a, **k):
    raise AssertionError("발급이 일어나면 안 된다")


def test_concurrent_token_calls_issue_only_once(tmp_path):
    """만료 찰나에 동시 호출이 겹쳐도 발급은 한 번.

    토스는 재발급이 이전 토큰을 **즉시 무효화**하므로, 발급이 두 번 나가면 먼저 받은
    코루틴이 들고 있던 토큰이 그 자리에서 죽는다(KIS의 알림톡 4통 사고보다 나쁘다)."""
    client = toss.TossClient("id", "secret", str(tmp_path))
    calls = []

    async def _issue():
        calls.append(1)
        await asyncio.sleep(0)          # 다른 코루틴에 양보 — 경합을 실제로 만든다
        return {"access_token": "t-%d" % len(calls), "expires_in": 86400}

    client._issue_token = _issue

    async def _run():
        return await asyncio.gather(*(client.token() for _ in range(5)))

    got = asyncio.run(_run())
    assert len(calls) == 1, "동시 호출이 각자 발급했다"
    assert set(got) == {"t-1"}


# ── 순수 파서 ─────────────────────────────────────────────────────────────

_BOND_JS = {"result": {"candles": [
    {"timestamp": "2026-09-02T09:00:00+09:00", "openPrice": "2.71",
     "highPrice": "2.74", "lowPrice": "2.70", "closePrice": "2.73",
     "volume": "0"},
    {"timestamp": "2026-09-01T09:00:00+09:00", "openPrice": "2.68",
     "highPrice": "2.70", "lowPrice": "2.66", "closePrice": "2.69",
     "volume": "0"},
], "nextBefore": "2026-09-01T09:00:00+09:00"}}


def test_parse_indicator_candles_is_ascending_and_numeric():
    """응답은 최신순이다(스펙 예제 실물) — 오름차순으로 뒤집어 내린다."""
    rows = toss.parse_indicator_candles(_BOND_JS)
    assert [r["date"] for r in rows] == ["2026-09-01", "2026-09-02"]
    assert rows[-1]["close"] == 2.73 and isinstance(rows[-1]["close"], float)


def test_parse_indicator_candles_survives_empty_and_broken():
    assert toss.parse_indicator_candles({"result": {"candles": []}}) == []
    assert toss.parse_indicator_candles({}) == []
    assert toss.parse_indicator_candles(
        {"result": {"candles": [{"timestamp": "", "closePrice": "x"}]}}) == []


_LENDING_JS = {"result": {"nextUntil": "2026-07-15", "records": [
    {"date": "2026-07-17", "updatedAt": "2026-07-17T19:03:21+09:00",
     "executionQuantity": "210500", "repaymentQuantity": "185300",
     "balanceQuantity": "15234000", "balanceAmount": "1218720000000"},
    {"date": "2026-07-16", "updatedAt": "2026-07-16T19:02:45+09:00",
     "executionQuantity": "198200", "repaymentQuantity": "201400",
     "balanceQuantity": "15208800", "balanceAmount": "1216704000000"},
]}}


def test_parse_lending_ascending_with_daily_change():
    """대차잔고 — 최신순 응답을 오름차순으로, 전일 대비(chg)까지.

    shortbal(KOFIA/SEIBro)은 이종 원천이 섞여 전일 대비를 계산하지 못했다.
    단일 원천이라 여기선 계산할 수 있다 — 그게 이 API를 들이는 이유다."""
    rows = toss.parse_lending(_LENDING_JS)
    assert [r["date"] for r in rows] == ["2026-07-16", "2026-07-17"]
    assert rows[0]["chg"] is None                    # 첫 행은 비교 대상이 없다
    assert rows[1]["chg"] == 15234000 - 15208800
    assert rows[1]["qty"] == 15234000
    assert rows[1]["exec"] == 210500 and rows[1]["rdmp"] == 185300
    assert rows[1]["value"] == 1218720000000         # 응답의 잔고금액 그대로(원)


def test_parse_lending_survives_empty():
    assert toss.parse_lending({"result": {"records": [], "nextUntil": None}}) == []
    assert toss.parse_lending({}) == []


_WARN_JS = {"result": [
    {"warningType": "OVERHEATED", "exchange": "KRX",
     "startDate": "2026-03-20", "endDate": "2026-03-27"},
    {"warningType": "VI_STATIC", "exchange": "KRX",
     "startDate": "2026-03-26", "endDate": None},
]}


def test_parse_warnings_labels_in_korean():
    rows = toss.parse_warnings(_WARN_JS)
    assert [r["label"] for r in rows] == ["단기과열", "VI 발동(정적)"]
    assert rows[0]["type"] == "OVERHEATED"
    assert rows[1]["end"] is None


def test_parse_warnings_tone_is_decided_by_the_backend():
    """색 판정은 백엔드가 한다(이 리포의 관행) — 프런트는 칠하기만 한다.

    VI는 '지금 2~10분 멈춤'이라 정보, 투자경고/위험·정리매매는 돈이 걸린 경고다."""
    rows = toss.parse_warnings(_WARN_JS)
    assert rows[0]["tone"] == "warn"      # 단기과열
    assert rows[1]["tone"] == "info"      # VI 정적
    assert toss.parse_warnings(
        {"result": [{"warningType": "INVESTMENT_RISK"}]})[0]["tone"] == "warn"


def test_parse_warnings_unknown_code_is_treated_as_a_warning():
    """모르는 코드는 안전측으로 경고 — 새 유형이 생겼을 때 조용히 회색으로 묻히지 않게."""
    assert toss.parse_warnings(
        {"result": [{"warningType": "SOMETHING_NEW"}]})[0]["tone"] == "warn"


def test_parse_warnings_keeps_unknown_codes():
    """스펙이 'unknown code 를 허용하도록 구현해야 한다'고 명시 — 버리지 않는다."""
    rows = toss.parse_warnings({"result": [{"warningType": "SOMETHING_NEW"}]})
    assert len(rows) == 1 and rows[0]["type"] == "SOMETHING_NEW"
    assert rows[0]["label"]          # 라벨이 비면 화면에 빈 배지가 뜬다


def test_parse_warnings_empty():
    assert toss.parse_warnings({"result": []}) == []
    assert toss.parse_warnings({}) == []


# ── 응답 envelope ────────────────────────────────────────────────────────

def test_unwrap_rejects_error_envelope():
    """실패 응답은 result 대신 error를 담는다 — 조용히 빈 값으로 흡수하지 않는다."""
    with pytest.raises(RuntimeError) as e:
        toss.unwrap({"error": {"code": "unsupported-symbol",
                               "message": "지원하지 않는 심볼"}})
    assert "unsupported-symbol" in str(e.value)
