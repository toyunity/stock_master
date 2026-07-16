"""아이폰 위젯 — 토큰 설정·데이터 조립·응답 계약(화이트리스트).

설계: docs/superpowers/specs/2026-07-16-iphone-widget-design.md
⚠ Settings는 .env를 자동 로드하므로 '미설정' 시나리오는 widget_token=None을 명시한다.
"""
import pytest

from backend.config import Settings

TOKEN = "w" * 32   # 유효 토큰(20자 이상)


def _settings(tmp_path, **over):
    base = dict(cache_dir=str(tmp_path), flow_mode="demo",
                widget_token=TOKEN, kis_app_key=None, kis_app_secret=None,
                dart_api_key=None)
    base.update(over)
    return Settings(**base)


def test_short_widget_token_refuses_boot(tmp_path):
    """약한 토큰이 유일 방어선이 되는 것을 차단 — 20자 미만이면 기동 거부(fail-closed)."""
    from backend.api.app import create_app
    with pytest.raises(RuntimeError):
        create_app(_settings(tmp_path, widget_token="short"))


def test_valid_or_absent_widget_token_boots(tmp_path):
    from backend.api.app import create_app
    create_app(_settings(tmp_path))                       # 32자 → OK
    create_app(_settings(tmp_path, widget_token=None))    # 미설정 → OK(위젯만 꺼짐)
