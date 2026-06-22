from __future__ import annotations

# LIVE-UNVALIDATED: tested against mocked DART responses only; verify against
# real API once a key is provided. The corpCode ZIP/XML structure and the
# list.json field names below are implemented to the documented opendart schema
# and exercised only by in-memory fixtures -- not a single live byte has been
# parsed. Re-check the CORPCODE.xml element layout and list.json status codes
# against a real response before trusting disclosures in production.

import datetime as dt
import io
import json
import logging
import os
import zipfile
import xml.etree.ElementTree as ET

import requests

from backend.config import settings
from backend.news.models import Disclosure

log = logging.getLogger(__name__)

CORP_CODE_URL = "https://opendart.fss.or.kr/api/corpCode.xml"
LIST_URL = "https://opendart.fss.or.kr/api/list.json"
DART_VIEWER = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"

_CORP_CACHE_NAME = "dart_corp_map.json"
_CORP_CACHE_MAX_AGE = dt.timedelta(days=7)  # 코드 매핑은 자주 안 바뀜; 주 1회 갱신
_PAGE_COUNT = 100  # list.json 페이지당 최대 건수(스키마 상한)
_MAX_PAGES = 10    # 페이지네이션 폭주 방지 캡(한 종목당 최대 1000건)
_TIMEOUT = 10      # 초; 네트워크 행 방지


def _cache_path(cache_dir: str) -> str:
    return os.path.join(cache_dir, _CORP_CACHE_NAME)


def _read_cached_corp_map(cache_dir: str):
    """디스크 캐시가 있고 신선하면 {stock_code: corp_code}를 반환, 아니면 None."""
    path = _cache_path(cache_dir)
    try:
        mtime = dt.datetime.fromtimestamp(os.path.getmtime(path))
    except OSError:
        return None
    if dt.datetime.now() - mtime > _CORP_CACHE_MAX_AGE:
        return None  # 오래됨 -> 재다운로드
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    return {str(k): str(v) for k, v in data.items()}


def _write_cached_corp_map(cache_dir: str, mapping) -> None:
    try:
        os.makedirs(cache_dir, exist_ok=True)
        with open(_cache_path(cache_dir), "w", encoding="utf-8") as f:
            json.dump(mapping, f, ensure_ascii=False)
    except OSError:
        # 캐시 기록 실패는 치명적이지 않다(다음 호출이 재다운로드할 뿐).
        log.warning("DART corp map 캐시 기록 실패: %s", cache_dir)


def _parse_corp_xml(xml_bytes: bytes) -> dict:
    """CORPCODE.xml 바이트 -> {stock_code: corp_code} (상장사만, 공백 제외)."""
    mapping: dict = {}
    root = ET.fromstring(xml_bytes)
    for node in root.findall("list"):
        stock_code = (node.findtext("stock_code") or "").strip()
        corp_code = (node.findtext("corp_code") or "").strip()
        if not stock_code or not corp_code:
            continue  # 비상장사(빈 stock_code) 제외
        mapping[stock_code] = corp_code
    return mapping


def _download_corp_map(api_key: str, session) -> dict:
    """corpCode.xml ZIP을 받아 메모리에서 풀고 CORPCODE.xml을 파싱한다."""
    resp = session.get(CORP_CODE_URL, params={"crtfc_key": api_key}, timeout=_TIMEOUT)
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        # 스키마상 단일 CORPCODE.xml. 이름 변형에 견디도록 첫 .xml을 집는다.
        names = [n for n in zf.namelist() if n.lower().endswith(".xml")]
        if not names:
            raise ValueError("corpCode ZIP에 XML이 없음")
        xml_bytes = zf.read(names[0])
    return _parse_corp_xml(xml_bytes)


def _load_corp_map(api_key: str, *, session, cache_dir: str) -> dict:
    """{stock_code: corp_code} 매핑을 반환한다.

    디스크 캐시(신선하면 재사용) -> 없으면 1회 다운로드 후 캐시.
    이 함수는 매칭 전략 교체가 쉽도록 독립 헬퍼로 둔다(라이브 검증 시 스왑 지점)."""
    cached = _read_cached_corp_map(cache_dir)
    if cached is not None:
        return cached
    mapping = _download_corp_map(api_key, session)
    _write_cached_corp_map(cache_dir, mapping)
    return mapping


def _fetch_code_disclosures(api_key, stock_code, corp_code, bgn_de, end_de,
                            *, session) -> list:
    """한 종목의 공시를 list.json으로 받아 Disclosure 목록으로 변환한다.

    상태 처리: 000 -> 파싱/페이지네이션, 013 -> 빈 결과, 그 외 -> 소프트 실패(빈 결과).
    실패 격리는 호출부 루프에서 try/except로 감싼다."""
    out: list = []
    page_no = 1
    total_page = 1
    while page_no <= total_page and page_no <= _MAX_PAGES:
        resp = session.get(
            LIST_URL,
            params={
                "crtfc_key": api_key,
                "corp_code": corp_code,
                "bgn_de": bgn_de,
                "end_de": end_de,
                "page_no": page_no,
                "page_count": _PAGE_COUNT,
            },
            timeout=_TIMEOUT,
        )
        data = resp.json()
        # status는 스키마상 zero-padded 문자열("000"/"013"). 라이브가 int(0/13)를
        # 줄 경우의 silent-empty를 막기 위해 정규화한다(블라인드 빌드 방어).
        status = str(data.get("status", "")).strip()
        if status.isdigit():
            status = status.zfill(3)
        if status == "013":
            break  # 데이터 없음(정상 빈 결과)
        if status != "000":
            # 사용한도 초과/인증 오류 등 -> 해당 종목만 조용히 건너뛴다.
            log.info("DART list.json status=%s code=%s", status, stock_code)
            break
        for it in (data.get("list") or []):
            rcept_no = (it.get("rcept_no") or "").strip()
            out.append(
                Disclosure(
                    corp_name=(it.get("corp_name") or "").strip(),
                    stock_code=stock_code,  # 조회한 관심종목 코드를 신뢰(페이로드 X)
                    report_name=(it.get("report_nm") or "").strip(),
                    rcept_no=rcept_no,
                    rcept_dt=(it.get("rcept_dt") or "").strip(),
                    link=DART_VIEWER.format(rcept_no=rcept_no),
                )
            )
        # total_page는 첫 응답에서 확정; 캡(_MAX_PAGES)으로 폭주 방지.
        try:
            total_page = int(data.get("total_page") or 1)
        except (TypeError, ValueError):
            total_page = 1
        page_no += 1
    if total_page > _MAX_PAGES:
        log.info("DART pagination capped at %d pages for %s", _MAX_PAGES, stock_code)
    return out


def fetch_disclosures(api_key, codes, lookback_days, *,
                      cache_dir=None, session=None, today=None):
    """관심종목 코드들의 DART 공시를 최근 lookback_days일치 모아 반환한다.

    - api_key가 비어 있으면 즉시 [] (네트워크 호출 0회) -> 키 없이도 앱 가동.
    - corpCode 매핑은 호출당 최대 1회 다운로드(디스크 캐시 재사용).
    - 종목별 list.json 실패는 해당 종목만 건너뛰고 나머지는 계속한다.
    - corpCode 다운로드/해제 실패는 [] 반환(리포트를 중단시키지 않는다)."""
    # 1) Graceful disable: 다른 어떤 작업보다 먼저.
    if not api_key:
        return []

    session = session or requests
    today = today or dt.date.today()
    cache_dir = cache_dir or settings.cache_dir

    # 2) corp_code 매핑(호출당 1회). 실패하면 공시는 통째로 빈 결과.
    try:
        corp_map = _load_corp_map(api_key, session=session, cache_dir=cache_dir)
    except Exception:
        log.warning("DART corpCode 로드 실패 -> 공시 생략", exc_info=True)
        return []

    # 3) 날짜 창
    end_de = today.strftime("%Y%m%d")
    bgn_de = (today - dt.timedelta(days=lookback_days)).strftime("%Y%m%d")

    # 4) 종목별 수집(실패 격리)
    results: list = []
    for code in codes:
        corp_code = corp_map.get(code)
        if not corp_code:
            continue  # 매핑에 없는 코드는 list.json 호출 없이 건너뛴다.
        try:
            results.extend(
                _fetch_code_disclosures(
                    api_key, code, corp_code, bgn_de, end_de, session=session
                )
            )
        except Exception:
            # 한 종목의 네트워크/파싱 오류가 전체를 망치지 않는다.
            log.info("DART list.json 실패 -> 종목 %s 생략", code, exc_info=True)
            continue
    return results
