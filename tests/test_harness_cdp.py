import pytest

from harness.core import cdp

pytestmark = pytest.mark.skipif(cdp.find_chrome() is None,
                                reason="헤드리스 크롬 미설치 — CDP 스모크 생략")


def test_shot_of_file_url(tmp_path):
    html = tmp_path / "p.html"
    html.write_text("<!doctype html><meta name=viewport "
                    "content='width=device-width'><body style='margin:0'>"
                    "<div style='width:390px;height:200px;background:#123'>hi</div>",
                    encoding="utf-8")
    out = tmp_path / "shot.png"
    with cdp.chrome() as base:
        m = cdp.shot(base, "file://" + str(html), str(out), "light")
    assert out.exists() and out.stat().st_size > 0
    assert m["sw"] <= 390  # 가로 오버플로 없음
