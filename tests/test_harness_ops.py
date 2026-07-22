from harness.cmd import ops


def test_local_status_shape():
    st = ops.local_status()
    assert set(st.keys()) == {"listening", "pid", "healthz"}
    assert isinstance(st["listening"], bool)


def test_main_readonly_returns_zero():
    # 읽기전용 점검은 서버 유무와 무관하게 정상 종료(0)
    assert ops.main(["--no-public"]) == 0
