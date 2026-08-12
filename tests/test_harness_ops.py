from pathlib import Path

from harness.cmd import ops


def test_public_url_not_hardcoded_in_source():
    """실 공개 호스트명을 소스에 박지 않는다 — 리포가 public이 되는 순간
    마스터의 맥북을 24시간 가리키는 고정 표적이 되고, 포크한 누구든 `make ops`로
    마스터 서버에 GET을 날린다. 값은 .env(SM_PUBLIC_URL)에만 둔다."""
    src = Path(ops.__file__).read_text(encoding="utf-8")
    assert "ts.net" not in src


def test_public_status_skips_without_env(monkeypatch):
    """SM_PUBLIC_URL 미설정이면 네트워크를 건드리지 않고 '생략'으로 끝난다."""
    monkeypatch.setattr(ops.settings, "public_url", None)
    assert "skipped" in ops.public_status()


def test_local_status_shape():
    st = ops.local_status()
    assert set(st.keys()) == {"listening", "pid", "healthz"}
    assert isinstance(st["listening"], bool)


def test_main_readonly_returns_zero():
    # 읽기전용 점검은 서버 유무와 무관하게 정상 종료(0)
    assert ops.main(["--no-public"]) == 0
