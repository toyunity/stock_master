from harness.core import bake, server


def test_bake_live_injects_stubs():
    with server.demo_server() as h:
        html = bake.bake_live(h.base, "000660")
    assert "window.__SNAP__" in html
    assert "window.EventSource=function" in html
    assert html.count("<body>") == 1  # 스텁이 <body>를 새로 만들지 않음
    # 스냅샷이 빈 객체가 아니라 실제 시드 데이터
    assert "__SNAP__={}" not in html


def test_js_safe_escapes_script_close():
    from harness.core import bake
    assert bake._js_safe('a</script>b') == 'a<\\/script>b'
    assert bake._js_safe('null') == 'null'
    assert bake._js_safe('{"x":1}') == '{"x":1}'
