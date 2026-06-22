from __future__ import annotations

import datetime as dt
import io
import zipfile

import backend.ingest.dart_source as src

# ---------------------------------------------------------------------------
# Fakes: a session whose .get(url, params=, timeout=) dispatches by URL.
#   - corpCode.xml  -> object exposing .content (real in-memory zip bytes)
#   - list.json     -> object exposing .json() (the documented JSON body)
# All calls are recorded so tests can assert call counts and params.
# ---------------------------------------------------------------------------

CORP_URL = "https://opendart.fss.or.kr/api/corpCode.xml"
LIST_URL = "https://opendart.fss.or.kr/api/list.json"


def _corp_zip_bytes(rows):
    """rows: list of (corp_code, corp_name, stock_code) -> zip(CORPCODE.xml) bytes."""
    lists = "".join(
        f"<list><corp_code>{cc}</corp_code><corp_name>{cn}</corp_name>"
        f"<stock_code>{sc}</stock_code><modify_date>20260101</modify_date></list>"
        for cc, cn, sc in rows
    )
    xml = f'<?xml version="1.0" encoding="utf-8"?><result>{lists}</result>'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("CORPCODE.xml", xml.encode("utf-8"))
    return buf.getvalue()


class _CorpResp:
    def __init__(self, content):
        self.content = content


class _JsonResp:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class FakeSession:
    """Dispatches .get by URL; records (url, params); supports per-endpoint
    error injection and pagination via a queue of list.json payloads per call."""

    def __init__(self, corp_content=None, list_payloads=None,
                 corp_error=None, list_error_urls=None):
        self.corp_content = corp_content
        # list_payloads: list of payloads returned in order for each LIST_URL GET
        self.list_payloads = list(list_payloads or [])
        self.corp_error = corp_error          # exception to raise on corpCode GET
        self.list_error_urls = list_error_urls or []  # raise on the Nth list call
        self.calls = []                        # [(url, params)]
        self._list_call_idx = 0

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        if url == CORP_URL:
            if self.corp_error is not None:
                raise self.corp_error
            return _CorpResp(self.corp_content)
        if url == LIST_URL:
            idx = self._list_call_idx
            self._list_call_idx += 1
            if idx in self.list_error_urls:
                raise RuntimeError("list.json boom")
            payload = self.list_payloads.pop(0) if self.list_payloads else {
                "status": "013", "message": "데이터 없음", "list": [],
            }
            return _JsonResp(payload)
        raise AssertionError(f"unexpected URL: {url}")

    @property
    def corp_calls(self):
        return [c for c in self.calls if c[0] == CORP_URL]

    @property
    def list_calls(self):
        return [c for c in self.calls if c[0] == LIST_URL]


def _ok_payload(rows, *, total_page=1):
    """rows: list of dicts merged onto a base disclosure shape; status 000."""
    base = {
        "corp_code": "00126380", "corp_name": "삼성전자", "stock_code": "005930",
        "corp_cls": "Y", "report_nm": "주요사항보고서", "rcept_no": "20260102000123",
        "flr_nm": "삼성전자", "rcept_dt": "20260102", "rm": "",
    }
    items = [{**base, **r} for r in rows]
    return {
        "status": "000", "message": "정상", "page_no": 1, "page_count": 100,
        "total_count": len(items), "total_page": total_page, "list": items,
    }


# A standard corp map fixture: two listed + one non-listed (blank stock_code).
_CORP_ROWS = [
    ("00126380", "삼성전자", "005930"),
    ("00164779", "SK하이닉스", "000660"),
    ("00401731", "(주)에이비씨", " "),  # 비상장: blank stock_code -> excluded
]


# ---------------------------------------------------------------------------
# Graceful disable
# ---------------------------------------------------------------------------

def test_no_api_key_returns_empty_and_no_network(tmp_path):
    sess = FakeSession(corp_content=_corp_zip_bytes(_CORP_ROWS))
    out = src.fetch_disclosures("", ["005930"], 2, cache_dir=str(tmp_path), session=sess)
    assert out == []
    assert sess.calls == []  # zero network calls


def test_none_api_key_returns_empty_and_no_network(tmp_path):
    sess = FakeSession(corp_content=_corp_zip_bytes(_CORP_ROWS))
    out = src.fetch_disclosures(None, ["005930"], 2, cache_dir=str(tmp_path), session=sess)
    assert out == []
    assert sess.calls == []


# ---------------------------------------------------------------------------
# corp map parsing
# ---------------------------------------------------------------------------

def test_corp_map_excludes_blank_stock_code(tmp_path):
    sess = FakeSession(corp_content=_corp_zip_bytes(_CORP_ROWS))
    mapping = src._load_corp_map("KEY", session=sess, cache_dir=str(tmp_path))
    assert mapping == {"005930": "00126380", "000660": "00164779"}
    assert " " not in mapping and "" not in mapping  # non-listed dropped


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_happy_path_builds_disclosure(tmp_path):
    payload = _ok_payload([
        {"report_nm": "주요사항보고서(자기주식취득결정)",
         "rcept_no": "20260102000123", "rcept_dt": "20260102",
         "corp_name": "삼성전자"},
    ])
    sess = FakeSession(corp_content=_corp_zip_bytes(_CORP_ROWS), list_payloads=[payload])
    out = src.fetch_disclosures(
        "KEY", ["005930"], 2, cache_dir=str(tmp_path), session=sess,
        today=dt.date(2026, 1, 3),
    )
    assert len(out) == 1
    d = out[0]
    assert d.corp_name == "삼성전자"
    assert d.stock_code == "005930"  # the watchlist code queried, not payload
    assert d.report_name == "주요사항보고서(자기주식취득결정)"
    assert d.rcept_no == "20260102000123"
    assert d.rcept_dt == "20260102"
    assert d.link == "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260102000123"


def test_stock_code_is_watchlist_code_not_payload(tmp_path):
    # payload stock_code differs from the queried code -> queried code wins.
    payload = _ok_payload([{"stock_code": "999999"}])
    sess = FakeSession(corp_content=_corp_zip_bytes(_CORP_ROWS), list_payloads=[payload])
    out = src.fetch_disclosures(
        "KEY", ["005930"], 2, cache_dir=str(tmp_path), session=sess,
        today=dt.date(2026, 1, 3),
    )
    assert out[0].stock_code == "005930"


# ---------------------------------------------------------------------------
# Empty / status handling
# ---------------------------------------------------------------------------

def test_status_013_yields_empty_no_crash(tmp_path):
    payload = {"status": "013", "message": "데이터가 없습니다.", "list": []}
    sess = FakeSession(corp_content=_corp_zip_bytes(_CORP_ROWS), list_payloads=[payload])
    out = src.fetch_disclosures(
        "KEY", ["005930"], 2, cache_dir=str(tmp_path), session=sess,
        today=dt.date(2026, 1, 3),
    )
    assert out == []
    assert len(sess.list_calls) == 1


def test_unknown_status_is_soft_failure(tmp_path):
    payload = {"status": "020", "message": "사용한도 초과", "list": []}
    sess = FakeSession(corp_content=_corp_zip_bytes(_CORP_ROWS), list_payloads=[payload])
    out = src.fetch_disclosures(
        "KEY", ["005930"], 2, cache_dir=str(tmp_path), session=sess,
        today=dt.date(2026, 1, 3),
    )
    assert out == []  # skipped, no crash


# ---------------------------------------------------------------------------
# Code not in corp map -> skipped, no list.json call
# ---------------------------------------------------------------------------

def test_code_not_in_corp_map_skipped(tmp_path):
    sess = FakeSession(corp_content=_corp_zip_bytes(_CORP_ROWS))
    out = src.fetch_disclosures(
        "KEY", ["123456"], 2, cache_dir=str(tmp_path), session=sess,
        today=dt.date(2026, 1, 3),
    )
    assert out == []
    assert sess.list_calls == []  # never queried list.json for unknown code


# ---------------------------------------------------------------------------
# Date window params
# ---------------------------------------------------------------------------

def test_date_window_params(tmp_path):
    payload = _ok_payload([])  # status 000, empty list -> no disclosures
    sess = FakeSession(corp_content=_corp_zip_bytes(_CORP_ROWS), list_payloads=[payload])
    src.fetch_disclosures(
        "KEY", ["005930"], 3, cache_dir=str(tmp_path), session=sess,
        today=dt.date(2026, 1, 10),
    )
    _, params = sess.list_calls[0]
    assert params["end_de"] == "20260110"
    assert params["bgn_de"] == "20260107"  # 2026-01-10 minus 3 days
    assert params["corp_code"] == "00126380"
    assert params["crtfc_key"] == "KEY"


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

def test_pagination_fetches_and_merges_page_two(tmp_path):
    page1 = _ok_payload(
        [{"rcept_no": "20260102000001", "report_nm": "보고서1"}], total_page=2,
    )
    page2 = _ok_payload(
        [{"rcept_no": "20260102000002", "report_nm": "보고서2"}], total_page=2,
    )
    sess = FakeSession(
        corp_content=_corp_zip_bytes(_CORP_ROWS), list_payloads=[page1, page2],
    )
    out = src.fetch_disclosures(
        "KEY", ["005930"], 2, cache_dir=str(tmp_path), session=sess,
        today=dt.date(2026, 1, 3),
    )
    assert len(out) == 2
    rcepts = {d.rcept_no for d in out}
    assert rcepts == {"20260102000001", "20260102000002"}
    # page_no must advance: first call page 1, second call page 2
    assert sess.list_calls[0][1]["page_no"] == 1
    assert sess.list_calls[1][1]["page_no"] == 2


# ---------------------------------------------------------------------------
# corpCode endpoint hit at most once across multiple codes
# ---------------------------------------------------------------------------

def test_corpcode_downloaded_at_most_once_multi_code(tmp_path):
    p1 = _ok_payload([{"rcept_no": "A1"}])
    p2 = _ok_payload([{"rcept_no": "B1"}])
    sess = FakeSession(
        corp_content=_corp_zip_bytes(_CORP_ROWS), list_payloads=[p1, p2],
    )
    out = src.fetch_disclosures(
        "KEY", ["005930", "000660"], 2, cache_dir=str(tmp_path), session=sess,
        today=dt.date(2026, 1, 3),
    )
    assert len(out) == 2
    assert len(sess.corp_calls) == 1  # downloaded once for the whole call


def test_corpcode_uses_disk_cache_on_second_call(tmp_path):
    # First call downloads + caches; second call (new session) must not re-download.
    sess1 = FakeSession(
        corp_content=_corp_zip_bytes(_CORP_ROWS),
        list_payloads=[_ok_payload([{"rcept_no": "A1"}])],
    )
    src.fetch_disclosures(
        "KEY", ["005930"], 2, cache_dir=str(tmp_path), session=sess1,
        today=dt.date(2026, 1, 3),
    )
    assert len(sess1.corp_calls) == 1

    sess2 = FakeSession(
        corp_content=b"SHOULD-NOT-BE-USED",  # would fail to unzip if downloaded
        list_payloads=[_ok_payload([{"rcept_no": "A2"}])],
    )
    out = src.fetch_disclosures(
        "KEY", ["005930"], 2, cache_dir=str(tmp_path), session=sess2,
        today=dt.date(2026, 1, 3),
    )
    assert len(sess2.corp_calls) == 0  # served from disk cache
    assert len(out) == 1


# ---------------------------------------------------------------------------
# Robustness: soft failures
# ---------------------------------------------------------------------------

def test_one_code_list_failure_skipped_other_returns(tmp_path):
    good = _ok_payload([{"rcept_no": "GOOD1"}])
    sess = FakeSession(
        corp_content=_corp_zip_bytes(_CORP_ROWS),
        list_payloads=[good],         # only the good code's payload
        list_error_urls=[0],          # the first list.json GET raises
    )
    out = src.fetch_disclosures(
        "KEY", ["005930", "000660"], 2, cache_dir=str(tmp_path), session=sess,
        today=dt.date(2026, 1, 3),
    )
    # first code raises -> skipped; second code returns GOOD1
    assert len(out) == 1
    assert out[0].rcept_no == "GOOD1"


def test_corpcode_download_failure_returns_empty(tmp_path):
    sess = FakeSession(corp_error=RuntimeError("network down"))
    out = src.fetch_disclosures(
        "KEY", ["005930"], 2, cache_dir=str(tmp_path), session=sess,
        today=dt.date(2026, 1, 3),
    )
    assert out == []
    assert sess.list_calls == []  # never reaches per-code stage


def test_corpcode_bad_zip_returns_empty(tmp_path):
    sess = FakeSession(corp_content=b"not a zip file at all")
    out = src.fetch_disclosures(
        "KEY", ["005930"], 2, cache_dir=str(tmp_path), session=sess,
        today=dt.date(2026, 1, 3),
    )
    assert out == []
    assert sess.list_calls == []
