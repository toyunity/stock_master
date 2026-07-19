from __future__ import annotations

"""주린이 가이드 엔진 — 순수 함수. 신호+재무를 초보용 가이드로 번역한다:
왜 움직였나(Key Moments식) / 지금 볼 포인트 3개 / 다음에 뭘 하면 되나.
LLM 없음·규칙 기반. 참고용·매매 권유 아님(관망 중심). Python 3.9."""

_FILLERS = ("거래량 — 평소보다 크게 늘었는지 보기",
            "차트 흐름 — 오르내림의 방향 보기",
            "뉴스·공시 — 회사에 무슨 일이 있었는지")


def guide(signals: dict, valuation, financials) -> dict:
    v = valuation or {}
    f = (financials or [{}])[0] if financials else {}
    rate = (signals.get("momentum") or {}).get("rate")
    sox = (signals.get("us") or {}).get("sox_rate")
    flow = signals.get("flow") or {}
    fr, o = flow.get("frgn_net"), flow.get("orgn_net")

    # ── 왜 움직였나 ──
    if rate is None:
        why = "오늘 시세 정보가 아직 없어요."
    elif abs(rate) < 1:
        why = "오늘은 %+.1f%%로 큰 변동이 없었어요." % rate
    else:
        drivers = []
        if signals.get("is_semi") and sox is not None and (rate < 0) == (sox < 0) and abs(sox) >= 0.8:
            drivers.append("간밤 미국 반도체(SOX %+.1f%%)" % sox)
        if fr is not None and o is not None:
            if fr < 0 and o < 0 and rate < 0:
                drivers.append("외국인·기관 순매도")
            elif fr > 0 and o > 0 and rate > 0:
                drivers.append("외국인·기관 순매수")
        dword = "하락" if rate < 0 else "상승"
        if drivers:
            why = "오늘 %+.1f%% %s은 %s 영향이 커 보여요." % (rate, dword, " + ".join(drivers))
        else:
            why = ("오늘 %+.1f%% %s했는데 뚜렷한 외부 원인은 안 보여요 — 종목 자체 이슈일 수 있어요."
                   % (rate, dword))

    # ── 지금 볼 포인트(우선순위) ──
    pts = []
    if signals.get("is_semi"):
        pts.append("미국 반도체(SOX) 방향 — 이 종목과 함께 움직이는 편이에요")
    if fr is not None and o is not None:
        st = ("순매도(부담)" if (fr < 0 and o < 0)
              else "순매수(받침)" if (fr > 0 and o > 0) else "엇갈림")
        pts.append("외국인·기관 수급 — 오늘은 %s" % st)
    if signals.get("has_adr"):
        pts.append("나스닥 DR — 밤사이 움직임이 내일 시초가 힌트예요")
    w52 = v.get("w52_pos")
    if w52 is not None:
        where = "고점 부근" if w52 >= 80 else "저점 부근" if w52 <= 20 else "1년 중간쯤"
        pts.append("52주 위치 %g%% — %s인지" % (w52, where))
    per = v.get("per")
    if per is not None and per > 0:
        tag = "싼 편" if per < 10 else "보통" if per < 20 else "다소 비싼 편"
        pts.append("PER %g — %s (이익 대비 가격)" % (per, tag))
    debt = f.get("debt")
    if debt is not None:
        pts.append("부채비율 %g%% — %s" % (debt, "낮아 안정적" if debt < 80 else "높은 편, 주의"))

    points = pts[:3]
    i = 0
    while len(points) < 3 and i < len(_FILLERS):
        if _FILLERS[i] not in points:
            points.append(_FILLERS[i])
        i += 1

    # ── 다음에 뭘 하면 되나(관망 중심, 권유 아님) ──
    if rate is not None and rate <= -5:
        act = ("급락일수록 서두르지 마세요. '왜 빠졌는지' 먼저 확인하고, 관심 있으면 "
               "한 번에 말고 소액부터 나눠서 접근하세요.")
    elif rate is not None and rate >= 7:
        act = "이미 많이 오른 뒤예요. 추격 매수는 위험할 수 있으니 조급해하지 말고 눌림을 지켜보세요."
    else:
        act = ("지금은 뚜렷한 신호가 강하지 않아요. 지켜보며(관망) 공부하는 것도 훌륭한 선택이에요. "
               "살 때도 한 번에 몰지 말고 나눠서.")

    return {"why_moved": why, "points": points, "next_action": act}
