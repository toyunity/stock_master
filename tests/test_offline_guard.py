"""외부 네트워크 차단 가드(conftest.py) 자체를 검사한다 — 양성 대조.

가드가 없거나 조용히 무력화돼도 나머지 테스트는 전부 초록불이다(원천 모듈이 실패를
폴백으로 흡수하므로). 그래서 "가드가 켜져 있다"가 아니라 **"가드가 실제로 잡는다"**를
직접 확인하는 테스트가 필요하다. 이게 없으면 2026-08-12의 CNBC 누출이 그대로 재발한다.
"""
import socket

import pytest


def test_guard_blocks_and_records_an_external_host(offline_guard_probe):
    """외부 호스트는 DNS 단계에서 막히고, 기록에 남는다."""
    with pytest.raises(RuntimeError) as e:
        socket.getaddrinfo("quote.cnbc.com", 443)
    assert "외부 네트워크" in str(e.value)
    assert ("quote.cnbc.com", 443) in offline_guard_probe


def test_guard_blocks_a_direct_ip_connect(offline_guard_probe):
    """DNS를 건너뛰고 IP로 바로 붙어도 막힌다 — getaddrinfo만 막으면 새는 구멍."""
    s = socket.socket()
    try:
        with pytest.raises(RuntimeError):
            s.connect(("93.184.216.34", 80))
    finally:
        s.close()
    assert offline_guard_probe and offline_guard_probe[0][0] == "93.184.216.34"


def test_guard_lets_loopback_through(offline_guard_probe):
    """로컬은 통과해야 한다 — 하네스 데모서버·auth 테스트가 127.0.0.1을 쓴다."""
    assert socket.getaddrinfo("127.0.0.1", 0)
    assert socket.getaddrinfo("localhost", 0)
    assert offline_guard_probe == [], "로컬 호출이 누출로 기록됐다"


def test_requests_cannot_reach_the_internet(offline_guard_probe):
    """라이브러리를 경유해도 못 나간다 — worldidx·adr이 쓰는 실제 경로."""
    import requests
    with pytest.raises(Exception):
        requests.get("https://quote.cnbc.com/x", timeout=1)
    assert any(h == "quote.cnbc.com" for h, _ in offline_guard_probe)


def test_toss_is_off_in_tests_even_with_real_keys_in_env():
    """테스트에서 토스 경로는 **항상 꺼져 있어야** 한다(conftest가 키를 비운다).

    2026-09-03 실사고: 마스터가 .env에 실 키를 넣자 shortbal._fetch_toss와
    worldidx._active()가 곧바로 실 API로 나가 오프라인 가드에 걸렸다(테스트 3건 ERROR).
    토스는 **재발급이 이전 토큰을 즉시 무효화**하므로, 테스트가 토큰을 한 번 받으면
    8000 실서버가 그 순간 401이 된다 — 가드에 걸리기 전에 이미 늦는 종류의 사고다.
    SM_AUTH_ENABLED를 conftest에서 끄는 것과 같은 이유·같은 자리에서 막는다."""
    import os
    assert os.environ.get("SM_TOSS_CLIENT_ID") == ""
    assert os.environ.get("SM_TOSS_CLIENT_SECRET") == ""
    from backend.config import settings
    assert not settings.toss_client_id and not settings.toss_client_secret
    from backend.flow import toss
    assert toss.get_client() is None, "테스트에서 토스 클라이언트가 살아 있다"
