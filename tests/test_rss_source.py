from __future__ import annotations

import datetime as dt

import feedparser

import backend.ingest.rss_source as src


def _rss(channel_title, items_xml):
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<rss version="2.0"><channel>'
        f"<title>{channel_title}</title>"
        f"{items_xml}"
        "</channel></rss>"
    )


def _item(title, description, link, pubdate=None):
    pub = f"<pubDate>{pubdate}</pubDate>" if pubdate else ""
    return (
        "<item>"
        f"<title>{title}</title>"
        f"<description>{description}</description>"
        f"<link>{link}</link>"
        f"{pub}"
        "</item>"
    )


def _parser(fixtures):
    """url -> raw XML 매핑을 받아 feedparser.parse로 파싱하는 주입용 parse."""
    return lambda url: feedparser.parse(fixtures[url])


def test_parses_core_fields_from_realistic_feed():
    xml = _rss(
        "한국경제",
        _item(
            "삼성전자 신고가",
            "오늘 삼성전자가 신고가를 기록했다.",
            "https://hankyung.com/news/1",
            "Mon, 22 Jun 2026 09:00:00 GMT",
        ),
    )
    url = "https://hankyung.com/feed"
    out = src.fetch_news([url], parse=_parser({url: xml}))

    assert len(out) == 1
    item = out[0]
    assert item.title == "삼성전자 신고가"
    assert item.summary == "오늘 삼성전자가 신고가를 기록했다."
    assert item.link == "https://hankyung.com/news/1"
    # 09:00 GMT → UTC 09:00 → +9h KST = 18:00
    assert item.published == dt.datetime(2026, 6, 22, 18, 0, 0)
    assert item.source == "한국경제"


def test_published_converted_to_kst_no_date_rollback():
    # 피드가 +0900(KST)로 주면 feedparser가 UTC로 정규화 → 우리는 +9h로 KST 복원.
    # 아침 08:00 KST 기사가 전날로 밀리지 않고 같은 날 08:00로 표시돼야 한다.
    xml = _rss("연합", _item("아침기사", "요약", "https://x/morning",
                            "Mon, 22 Jun 2026 08:00:00 +0900"))
    url = "https://x/feed"
    out = src.fetch_news([url], parse=_parser({url: xml}))
    assert out[0].published == dt.datetime(2026, 6, 22, 8, 0, 0)


def test_summary_strips_html_tags_and_entities():
    # 원문에 <b>, &amp;, <img> 가 섞여 있어도 본문 텍스트만 남아야 한다.
    desc = "&lt;b&gt;긴급&lt;/b&gt; 코스피 &amp;amp; 코스닥 &lt;img src=&quot;x.png&quot;/&gt; 급등"
    xml = _rss("연합뉴스", _item("시황", desc, "https://yna.co.kr/1", "Mon, 22 Jun 2026 08:00:00 GMT"))
    url = "https://yna.co.kr/feed"
    out = src.fetch_news([url], parse=_parser({url: xml}))

    summary = out[0].summary
    assert "<" not in summary and ">" not in summary
    assert "&amp;" not in summary  # 엔티티 unescape 됨
    assert "img" not in summary
    assert summary == "긴급 코스피 & 코스닥 급등"


def test_summary_is_truncated():
    long_text = "가" * 500
    xml = _rss("한경", _item("긴글", long_text, "https://h.com/long", "Mon, 22 Jun 2026 08:00:00 GMT"))
    url = "https://h.com/feed"
    out = src.fetch_news([url], parse=_parser({url: xml}))
    assert len(out[0].summary) <= 210  # ~200자 수준으로 잘림


def test_dedup_by_link_across_feeds_keeps_first():
    shared_link = "https://news.com/shared"
    feed_a = _rss(
        "출처A",
        _item("A 제목", "A 요약", shared_link, "Mon, 22 Jun 2026 10:00:00 GMT"),
    )
    feed_b = _rss(
        "출처B",
        _item("B 제목", "B 요약", shared_link, "Mon, 22 Jun 2026 11:00:00 GMT"),
    )
    url_a, url_b = "https://a/feed", "https://b/feed"
    out = src.fetch_news([url_a, url_b], parse=_parser({url_a: feed_a, url_b: feed_b}))

    assert len(out) == 1
    assert out[0].title == "A 제목"  # 첫 등장(피드 A) 유지
    assert out[0].source == "출처A"


def test_missing_published_yields_none():
    xml = _rss("출처", _item("날짜없음", "요약", "https://x/nopub"))  # pubDate 없음
    url = "https://x/feed"
    out = src.fetch_news([url], parse=_parser({url: xml}))

    assert len(out) == 1
    assert out[0].published is None


def test_bad_feed_skipped_good_feed_returned():
    bad_url = "https://bad/feed"
    good_url = "https://good/feed"
    good_xml = _rss("좋은출처", _item("정상기사", "요약", "https://good/1", "Mon, 22 Jun 2026 09:00:00 GMT"))
    fixtures = {bad_url: "this is not xml at all <<<", good_url: good_xml}

    # 한 피드가 깨져도 나머지는 정상 반환되어야 한다(같은 호출 안에서 검증).
    out = src.fetch_news([bad_url, good_url], parse=_parser(fixtures))

    assert len(out) == 1
    assert out[0].title == "정상기사"


def test_parse_raises_is_skipped():
    def raising_parse(url):
        raise RuntimeError("network blew up")

    out = src.fetch_news(["https://x/feed"], parse=raising_parse)
    assert out == []


def test_sorted_newest_first_none_last():
    xml = _rss(
        "출처",
        _item("오래된글", "요약", "https://x/old", "Mon, 22 Jun 2026 08:00:00 GMT")
        + _item("최신글", "요약", "https://x/new", "Mon, 22 Jun 2026 12:00:00 GMT")
        + _item("날짜없음", "요약", "https://x/none"),  # pubDate 없음 -> None
    )
    url = "https://x/feed"
    out = src.fetch_news([url], parse=_parser({url: xml}))

    assert [i.title for i in out] == ["최신글", "오래된글", "날짜없음"]


def test_default_parse_sends_browser_user_agent(monkeypatch):
    # 한경 등은 feedparser 기본 UA에 403 → 기본 파서가 브라우저 UA를 실어야 한다(라이브 회귀).
    captured = {}

    def fake_parse(url, *args, **kwargs):
        captured["url"] = url
        captured["agent"] = kwargs.get("agent")
        return None  # 반환값은 검증에 쓰지 않음(재귀 방지)

    monkeypatch.setattr(feedparser, "parse", fake_parse)
    src._default_parse("https://www.hankyung.com/feed/finance")
    assert captured["url"] == "https://www.hankyung.com/feed/finance"
    assert captured["agent"] and "Mozilla" in captured["agent"]


def test_source_falls_back_to_hostname_when_no_channel_title():
    # channel <title> 비어있을 때 URL 호스트명(www 제거)으로 출처를 채운다.
    xml = (
        '<?xml version="1.0"?><rss version="2.0"><channel>'
        "<item><title>제목</title><description>요약</description>"
        "<link>https://x/1</link></item>"
        "</channel></rss>"
    )
    url = "https://www.example.com/feed"
    out = src.fetch_news([url], parse=_parser({url: xml}))

    assert len(out) == 1
    assert out[0].source == "example.com"
