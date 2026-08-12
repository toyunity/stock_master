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
