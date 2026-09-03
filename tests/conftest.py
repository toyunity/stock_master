import os
import socket

import pytest

# 테스트 격리: 개발자 .env의 SM_AUTH_ENABLED=true가 모듈 backend.api.app.app 에
# 인증 게이트를 걸면 무관한 라우트 테스트(/, /live, /api/*)가 302/401로 깨진다.
# 게이트는 test_auth.py가 create_app(Settings(auth_enabled=True))로 명시적으로만 켠다.
# os.environ은 .env 파일보다 우선하므로 여기서 강제로 끈다(backend import 전에 실행됨).
os.environ["SM_AUTH_ENABLED"] = "false"

# 같은 이유로 토스 키도 비운다 — 이쪽은 더 급하다.
# 2026-09-03 실사고: 마스터가 .env에 실 키를 넣자 shortbal._fetch_toss·worldidx._active()가
# 곧바로 실 API로 나가 아래 오프라인 가드에 걸렸다(테스트 3건 ERROR). 가드가 잡아준 건
# 운이 좋았던 것이다 — **토스는 재발급이 이전 토큰을 즉시 무효화**하므로, 테스트가 토큰을
# 한 번 받아내면 그 순간 8000 실서버가 401이 된다. 하네스(harness/core/server.py)는 spawn한
# 데모서버의 env를 비우지만, pytest는 이 프로세스에서 바로 settings를 읽으므로 여기가 필요하다.
# 회귀 방지: test_offline_guard.py::test_toss_is_off_in_tests_even_with_real_keys_in_env
os.environ["SM_TOSS_CLIENT_ID"] = ""
os.environ["SM_TOSS_CLIENT_SECRET"] = ""


# ── 외부 네트워크 차단 가드 ───────────────────────────────────────────────
#
# "테스트는 전부 오프라인"은 지금까지 **파일마다 따로 있는 autouse 스텁**으로 지켜졌다.
# 한 벌이 빠지면 조용히 샌다 — 2026-08-12에 실제로 그랬다: worldidx에 CNBC 원천을
# 더하면서 스텁을 test_worldidx.py에만 깔았더니, _treasury_group을 직접 도는
# test_worldidx_api.py·test_worldidx_bp.py가 남의 사설 API(quote.cnbc.com)로 **실제
# HTTP 요청을 보냈다**. 그 자리를 한 군데서 막는다.
#
# **차단만으로는 부족하다.** worldidx·adr 같은 원천 모듈은 실패를 `except Exception`으로
# 흡수해 폴백하도록 설계돼 있어서, 여기서 예외를 던져도 프로덕션 코드가 조용히 삼킨다 —
# 테스트는 그대로 초록불이고 누출은 안 보인다. 그래서 **시도를 기록하고 테스트를
# 실패시킨다**. 기록이 없으면 이 가드는 아무것도 증명하지 못한다.

_LOOPBACK = frozenset(("127.0.0.1", "::1", "localhost", "0.0.0.0", "", None))
_leaks = []                    # [(host, port|None)] — 매 테스트마다 비운다
_real_connect = socket.socket.connect
_real_getaddrinfo = socket.getaddrinfo


def _blocked(host, port):
    _leaks.append((str(host), port))
    return RuntimeError(
        "테스트가 외부 네트워크로 나가려 했다: %s:%s — 이 원천의 스텁이 빠졌다. "
        "실호출을 허용하지 말고 픽스처를 주입하라." % (host, port))


def _host_of(address):
    if isinstance(address, (tuple, list)) and address:
        return address[0]
    return address


def _guarded_connect(self, address):
    host = _host_of(address)
    if host not in _LOOPBACK:
        raise _blocked(host, address[1] if isinstance(address, tuple) and
                       len(address) > 1 else None)
    return _real_connect(self, address)


def _guarded_getaddrinfo(host, port, *a, **kw):
    # DNS 단계에서 먼저 막는다 — 호스트 **이름**이 남아 메시지가 쓸모 있고(연결 단계에선
    # 이미 IP로 바뀐다), 실제 DNS 질의도 안 나간다.
    if host not in _LOOPBACK:
        raise _blocked(host, port)
    return _real_getaddrinfo(host, port, *a, **kw)


socket.socket.connect = _guarded_connect
socket.getaddrinfo = _guarded_getaddrinfo


@pytest.fixture(autouse=True)
def _no_external_network():
    """누출이 있었으면 그 테스트를 실패시킨다 — 폴백에 삼켜져도 여기서 드러난다."""
    del _leaks[:]
    yield
    if _leaks:
        seen = sorted(set("%s:%s" % (h, p) for h, p in _leaks))
        pytest.fail("외부 네트워크 호출 시도 %d건: %s" % (len(_leaks), ", ".join(seen)))
    del _leaks[:]


@pytest.fixture(autouse=True)
def _cold_marketdata():
    """marketdata 모듈 전역 캐시를 매 테스트 앞에 콜드로 — 네트워크 가드와 같은 이유다.

    파일마다 손으로 리셋하면 새 캐시가 생길 때마다 빠뜨릴 자리가 늘고, 빠뜨리면 앞
    테스트가 남긴 값이 TTL 안에 반환돼 가짜 클라이언트를 한 번도 안 부르고 통과한다
    (실행 순서에 따라 결과가 갈린다). 되돌리기만 한 곳으로 모은다."""
    from backend.api import marketdata
    marketdata.reset_caches()


@pytest.fixture
def offline_guard_probe():
    """가드 자체를 검사하는 테스트 전용 — 기록을 소비해 위 autouse가 안 물게 한다.

    이 픽스처의 teardown이 autouse보다 **먼저** 돈다(autouse가 더 바깥이다).
    양성 대조가 없으면 '가드가 켜져 있다'와 '가드가 아무것도 안 한다'를 구분 못 한다."""
    del _leaks[:]
    yield _leaks
    del _leaks[:]
