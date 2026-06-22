import datetime as dt

import numpy as np
import pandas as pd

import backend.cli as cli
from backend.cli import generate_report
from backend.news.models import NewsItem, Disclosure


def _fake_source(code, start, end):
    idx = pd.date_range("2024-01-01", periods=120, freq="D")
    close = pd.Series(np.linspace(100, 180, 120), index=idx)
    return pd.DataFrame({"Open": close, "High": close*1.01, "Low": close*0.99,
                         "Close": close, "Volume": np.full(120, 1000)}, index=idx)


def test_generate_report_creates_file(tmp_path):
    out = tmp_path / "report.html"
    generate_report(codes=["005930", "000660"], out_path=out,
                    cache_dir=tmp_path, source=_fake_source, with_news=False)
    assert out.exists()
    html = out.read_text(encoding="utf-8")
    assert "005930" in html and "000660" in html


def test_generate_report_wires_news_and_disclosures(tmp_path, monkeypatch):
    """수집기를 주입(monkeypatch)해 매칭된 뉴스/공시가 리포트에 실리는지 확인(네트워크 없음)."""
    news = NewsItem(title="삼성전자, 신제품 공개", summary="요약",
                    link="https://news.example/1",
                    published=dt.datetime(2026, 6, 22, 9, 0), source="한국경제")
    disc = Disclosure(corp_name="삼성전자", stock_code="005930",
                      report_name="주요사항보고서", rcept_no="20260622000001",
                      rcept_dt="20260622", link="https://dart.example/1")
    monkeypatch.setattr(cli, "fetch_news", lambda feeds: [news])
    monkeypatch.setattr(cli, "fetch_disclosures", lambda key, codes, days: [disc])
    out = tmp_path / "r.html"
    generate_report(codes=["005930"], out_path=out, cache_dir=tmp_path,
                    source=_fake_source, with_news=True)
    html = out.read_text(encoding="utf-8")
    assert "삼성전자, 신제품 공개" in html      # 뉴스 제목
    assert "주요사항보고서" in html             # 공시 제목
    assert "관련 이슈" in html                  # 이슈 섹션 라벨


def test_generate_report_collection_failure_is_graceful(tmp_path, monkeypatch):
    """수집기가 예외를 던져도 리포트는 정상 생성되어야 한다(그레이스풀 디그레이드)."""
    def boom(*a, **k):
        raise RuntimeError("network down")
    monkeypatch.setattr(cli, "fetch_news", boom)
    monkeypatch.setattr(cli, "fetch_disclosures", boom)
    out = tmp_path / "r.html"
    generate_report(codes=["005930"], out_path=out, cache_dir=tmp_path,
                    source=_fake_source, with_news=True)
    assert out.exists()
    assert "005930" in out.read_text(encoding="utf-8")
