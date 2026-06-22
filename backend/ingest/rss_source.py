from __future__ import annotations

import datetime as dt
import html
import re
from urllib.parse import urlparse

import feedparser

from backend.news.models import NewsItem

# 태그 제거 + 공백 정규화용 정규식
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_SUMMARY_MAX = 200

# 일부 언론사(예: 한경)는 feedparser 기본 UA에 403을 준다 → 브라우저 UA 필요.
# (라이브 e2e에서 한경 피드가 403으로 조용히 누락되던 것을 발견해 추가.)
_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def _default_parse(url):
    """프로덕션 기본 파서: 차단 회피용 브라우저 User-Agent를 실어 보낸다."""
    return feedparser.parse(url, agent=_UA)


def _clean_summary(raw: str) -> str:
    """RSS 요약의 HTML 태그/엔티티/잉여 공백을 제거하고 ~200자로 자른다.

    순서가 중요하다: (1) 태그 제거 -> (2) 엔티티 unescape -> (3) 공백 정규화.
    태그를 먼저 지워야 `&lt;script&gt;` 같은 escape된 태그가 unescape 후
    다시 살아나지 않는다."""
    text = _TAG_RE.sub(" ", raw)        # <b>, <img ...> 등 제거
    text = html.unescape(text)          # &amp; &lt; &quot; 등 복원
    text = _WS_RE.sub(" ", text).strip()  # 연속 공백/개행 정리
    return text[:_SUMMARY_MAX]


def _source_name(result, url: str) -> str:
    """피드 채널 제목을 출처로 쓰고, 없으면 URL 호스트명(www 제거)으로 대체한다."""
    title = (result.feed.get("title") or "").strip()
    if title:
        return title
    host = urlparse(url).hostname or url
    return host[4:] if host.startswith("www.") else host


def _to_datetime(parsed) -> dt.datetime | None:
    """feedparser의 published_parsed(time.struct_time, UTC)를 naive datetime으로.

    없거나 파싱 실패 시 None."""
    if not parsed:
        return None
    try:
        return dt.datetime(*parsed[:6])
    except (TypeError, ValueError):
        return None


def fetch_news(feed_urls, *, parse=_default_parse) -> list[NewsItem]:
    """여러 RSS 피드를 파싱해 NewsItem 목록을 반환한다.

    - parse: 주입 가능한 파서(기본 feedparser.parse). 테스트에서 교체.
    - link 기준 중복 제거(첫 등장 유지).
    - published 최신순 정렬(None은 맨 뒤).
    - 한 피드가 예외를 던지거나 항목이 없어도 나머지는 계속 수집한다(저작권상 본문 미저장).
    """
    items: list[NewsItem] = []
    seen_links: set[str] = set()

    for url in feed_urls:
        try:
            result = parse(url)
            entries = getattr(result, "entries", None) or []
        except Exception:
            # 하나의 불량 피드가 전체를 중단시키지 않는다.
            continue

        source = _source_name(result, url)
        for entry in entries:
            link = (entry.get("link") or "").strip()
            if not link or link in seen_links:
                continue
            seen_links.add(link)

            raw_summary = entry.get("summary") or entry.get("description") or ""
            items.append(
                NewsItem(
                    title=(entry.get("title") or "").strip(),
                    summary=_clean_summary(raw_summary),
                    link=link,
                    published=_to_datetime(entry.get("published_parsed")),
                    source=source,
                )
            )

    items.sort(key=lambda it: it.published or dt.datetime.min, reverse=True)
    return items
