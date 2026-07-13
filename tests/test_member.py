"""거래원(회원사) 창구 — 파서·외국계 분류 (픽스처는 2026-07-13 실측 값)."""
from backend.flow.member import FOREIGN_DESKS, _is_foreign, parse_member


def _fixture():
    out = {}
    sell = [("삼성증권", 915123, "11.51", "N"), ("키움증권", 534743, "6.73", "N"),
            ("모간서울", 479029, "6.02", "Y"), ("KB증권", 466882, "5.87", "N"),
            ("미래에셋증권", 463277, "5.83", "N")]
    buy = [("키움증권", 825492, "10.38", "N"), ("삼성증권", 823801, "10.36", "N"),
           ("JP모간", 739909, "9.31", "Y"), ("KB증권", 654514, "8.23", "N"),
           ("미래에셋증권", 613262, "7.71", "N")]
    for i, (n, q, r, g) in enumerate(sell, 1):
        out[f"seln_mbcr_name{i}"] = n
        out[f"total_seln_qty{i}"] = str(q)
        out[f"seln_mbcr_rlim{i}"] = r
        out[f"seln_mbcr_glob_yn_{i}"] = g
    for i, (n, q, r, g) in enumerate(buy, 1):
        out[f"shnu_mbcr_name{i}"] = n
        out[f"total_shnu_qty{i}"] = str(q)
        out[f"shnu_mbcr_rlim{i}"] = r
        out[f"shnu_mbcr_glob_yn_{i}"] = g
    out.update(glob_total_seln_qty="831835", glob_total_shnu_qty="739909",
               glob_ntby_qty="-91926", glob_seln_rlim="10.46",
               glob_shnu_rlim="9.31")
    return {"rt_cd": "0", "output": [out]}  # 1원소 배열 직렬화 관측(실측)


def test_parse_member_real_fixture():
    d = parse_member(_fixture())
    assert [r["name"] for r in d["sell"]][:3] == ["삼성증권", "키움증권", "모간서울"]
    assert d["sell"][2]["foreign"] is True          # glob_yn=Y
    assert d["sell"][0]["foreign"] is False
    assert d["buy"][2] == {"name": "JP모간", "qty": 739909, "rlim": 9.31,
                           "foreign": True}
    assert d["glob"]["ntby"] == -91926 and d["glob"]["seln"] == 831835
    assert parse_member({"rt_cd": "1"}) is None
    assert parse_member({"rt_cd": "0", "output": []}) is None


def test_foreign_desk_constant_backstop():
    # NXT 행은 glob_yn이 전부 N(실측 제약) — 이름 상수로 보완 분류
    assert _is_foreign("모간서울", "N") is True
    assert _is_foreign("골드만삭스증권", "N") is True
    assert _is_foreign("맥쿼리증권", "N") is True
    assert _is_foreign("키움증권", "N") is False
    assert _is_foreign("아무개증권", "Y") is True   # 플래그 우선
    assert len(FOREIGN_DESKS) >= 15
