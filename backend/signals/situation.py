from __future__ import annotations

"""오늘 현황 서술 엔진 — 순수 함수. 신호(등락·수급·미국·ADR)+재무를 초보용 문장으로
종합한다(사실 + 일반적 해석). 내일예상(nextday)이 '방향'이라면 이건 '지금 상황'.
ADR 유무(has_adr)로 DR 언급을 제어. LLM 없음. 참고용·매매권유 아님. Python 3.9."""


def commentary(signals: dict, valuation, financials) -> dict:
    v = valuation or {}
    f = (financials or [{}])[0] if financials else {}
    s = []

    # 오늘 등락
    rate = (signals.get("momentum") or {}).get("rate")
    if rate is not None:
        if rate <= -5:
            s.append("오늘 %.1f%% 크게 하락했어요." % rate)
        elif rate <= -1:
            s.append("오늘 %.1f%% 약세로 마감했어요." % rate)
        elif rate >= 5:
            s.append("오늘 %+.1f%% 크게 올랐어요." % rate)
        elif rate >= 1:
            s.append("오늘 %+.1f%% 강세로 마감했어요." % rate)
        else:
            s.append("오늘은 %+.1f%%로 큰 변동 없이 마감했어요." % rate)

    # 수급(외국인·기관)
    flow = signals.get("flow")
    if flow:
        fr, o = flow.get("frgn_net") or 0, flow.get("orgn_net") or 0
        if fr < 0 and o < 0:
            s.append("외국인·기관이 함께 순매도해 수급이 부담이에요.")
        elif fr > 0 and o > 0:
            s.append("외국인·기관이 함께 순매수해 수급이 받쳐줬어요.")
        else:
            s.append("외국인·기관 수급은 엇갈렸어요.")

    # 미국 반도체(반도체 상관 종목만)
    us = signals.get("us")
    if us and signals.get("is_semi") and us.get("sox_rate") is not None:
        sr = us["sox_rate"]
        if sr <= -1:
            s.append("간밤 미국 반도체(SOX %.1f%%)도 약해 분위기가 무거워요." % sr)
        elif sr >= 1:
            s.append("간밤 미국 반도체(SOX %+.1f%%)가 강해 우호적이에요." % sr)

    # ADR — 보유(has_adr) 종목만
    adr = signals.get("adr")
    if signals.get("has_adr") and adr and adr.get("overnight_rate") is not None:
        s.append("나스닥 DR은 밤새 %+.1f%%예요(내일 시초가 참고)." % adr["overnight_rate"])

    # 재무 체력
    roe, debt = f.get("roe"), f.get("debt")
    if roe is not None and debt is not None:
        if roe >= 15 and debt < 80:
            s.append("다만 부채가 %g%%로 낮고 ROE가 %g%%로 높아 회사 체력 자체는 튼튼해요."
                     % (debt, roe))
        elif debt >= 150:
            s.append("부채비율이 %g%%로 높은 편이라 재무 부담은 유의해야 해요." % debt)

    # 밸류
    per, w52 = v.get("per"), v.get("w52_pos")
    if per is not None and per > 0:
        tag = "이익 대비 싼 편" if per < 10 else "보통 수준" if per < 20 else "다소 비싼 편"
        extra = ""
        if w52 is not None:
            where = "고점 부근" if w52 >= 80 else "저점 부근" if w52 <= 20 else "중간쯤"
            extra = " 52주 %s 위치예요." % where
        s.append("밸류로 보면 PER %g로 %s이에요.%s" % (per, tag, extra))

    return {"sentences": s,
            "caution": "이 해설은 사실과 일반적 해석이에요 · 참고용이며 매매 권유가 아니에요."}
