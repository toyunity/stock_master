"""VKOSPI 일별 지수 — 순수 파싱 + TR 고정. KIS·네트워크 미접촉.

이 파일이 지키는 함정 3개(2026-08-05 실측):
  · 코드는 0503이지 00503이 아니다 — 00503은 rt_cd=0에 0.00이 와서 조용히 틀린다
  · 이력은 output2에 있다(output은 None)
  · 응답은 최신순이라 차트용으로 뒤집어야 한다
"""
import asyncio

from backend.flow import kis


def _js(dates_values, now=("78.55", "-3.50", "-4.27", "5")):
    """실측 응답 모양 — output1=현재 요약(dict), output2=일별(list, 최신순)."""
    px, chg, rate, sign = now
    return {"rt_cd": "0",
            "output1": {"bstp_nmix_prpr": px, "bstp_nmix_prdy_vrss": chg,
                        "bstp_nmix_prdy_ctrt": rate, "prdy_vrss_sign": sign},
            "output2": [{"stck_bsop_date": d, "bstp_nmix_prpr": v}
                        for d, v in dates_values]}


def test_parse_index_daily_reads_output2_and_reverses_to_oldest_first():
    js = _js([("20260805", "78.55"), ("20260804", "82.05"), ("20260803", "80.10")])
    d = kis.parse_index_daily(js)
    assert d["now"]["price"] == 78.55
    assert d["now"]["change"] == -3.50 and d["now"]["rate"] == -4.27
    assert d["now"]["sign"] == "down"
    # 차트는 왼쪽부터 그린다 — 응답의 최신순을 여기서 뒤집는다
    assert [x["d"] for x in d["days"]] == ["20260803", "20260804", "20260805"]
    assert [x["v"] for x in d["days"]] == [80.10, 82.05, 78.55]


def test_parse_index_daily_rejects_error_and_empty():
    assert kis.parse_index_daily({"rt_cd": "1", "msg1": "오류"}) is None
    assert kis.parse_index_daily({"rt_cd": "0", "output2": []}) is None
    assert kis.parse_index_daily({"rt_cd": "0"}) is None
    assert kis.parse_index_daily(None) is None


def test_parse_index_daily_skips_broken_rows_but_keeps_the_rest():
    """값이 비거나 숫자가 아닌 행은 버린다 — 차트에 0이 찍히면 없는 급락이 보인다."""
    js = _js([("20260805", "78.55"), ("20260804", ""), ("20260803", "abc"),
              ("20260802", "80.10")])
    d = kis.parse_index_daily(js)
    assert [x["d"] for x in d["days"]] == ["20260802", "20260805"]


def test_parse_index_daily_survives_missing_output1():
    """이력만 있고 현재 요약이 없어도 차트는 그릴 수 있어야 한다."""
    js = _js([("20260805", "78.55")])
    del js["output1"]
    d = kis.parse_index_daily(js)
    assert d["now"] is None and len(d["days"]) == 1


def test_vkospi_iscd_is_four_digits():
    """마스터(idxcode.mst)는 5자리 00503이지만 API는 4자리다.
    00503을 넣으면 rt_cd=0에 0.00이 와서 **에러 없이 조용히 틀린다**(2026-08-05 실측)."""
    assert kis.VKOSPI_ISCD == "0503"


def test_index_daily_uses_correct_tr_path_and_params():
    seen = {}

    class _C(kis.KisClient):
        async def _get(self, path, tr_id, params, retries=2):
            seen.update({"path": path, "tr": tr_id, "params": params})
            return _js([("20260805", "78.55")])

    c = _C("k", "s", "/tmp")
    d = asyncio.run(c.index_daily(kis.VKOSPI_ISCD, "20260805"))
    assert seen["tr"] == "FHPUP02120000"
    assert seen["path"].endswith("/quotations/inquire-index-daily-price")
    assert seen["params"] == {"FID_COND_MRKT_DIV_CODE": "U",
                              "FID_INPUT_ISCD": "0503",
                              "FID_INPUT_DATE_1": "20260805",
                              "FID_PERIOD_DIV_CODE": "D"}
    assert d["now"]["price"] == 78.55
