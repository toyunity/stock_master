from __future__ import annotations

"""내일장 방향 규칙 엔진 — 순수 함수. 신호(미국장·ADR·수급·모멘텀)를 가중 합산해
방향 배지 + 근거 + 주의를 만든다. LLM 없음: 규칙 하나 = 근거 한 줄. 개인용·참고용.
Python 3.9 호환."""

from typing import Optional

_UP, _DOWN = 2, -2   # 방향 임계값

_FRAMING = {
    "kr_closed_us_pending": "오늘 마감 기준 · 오늘 밤 미국장이 변수예요",
    "us_live": "미국장 진행 중 흐름 반영",
    "us_closed": "간밤 미국·ADR 반영",
    "kr_open": "오늘 장중 흐름",
}


def _rate(d: Optional[dict], *keys):
    for k in keys:
        v = (d or {}).get(k)
        if v is not None:
            return v
    return None


def outlook(signals: dict) -> dict:
    session = signals.get("session", "us_closed")
    reasons, caution, score = [], [], 0

    # 1) ADR 오버나잇(가장 직접적) — ADR 종목·데이터 있을 때
    adr = signals.get("adr")
    if adr and adr.get("overnight_rate") is not None:
        r = adr["overnight_rate"]
        w = 2 if r > 1.5 else 1 if r > 0.5 else -2 if r < -1.5 else -1 if r < -0.5 else 0
        if w:
            score += w
            reasons.append({"text": "나스닥 DR이 밤새 %+.1f%% — 내일 갭%s 여지" % (
                r, "업" if w > 0 else "다운"), "dir": "up" if w > 0 else "down"})

    # 2) 미국 반도체/나스닥 — 반도체·수출 상관 종목
    us = signals.get("us")
    if us and signals.get("is_semi"):
        sr = _rate(us, "sox_rate", "nasdaq_rate")
        if sr is not None and session != "kr_closed_us_pending":
            w = 2 if sr > 2 else 1 if sr > 1 else -2 if sr < -2 else -1 if sr < -1 else 0
            if w:
                score += w
                reasons.append({"text": "간밤 미국 반도체 %s(SOX %+.1f%%)" % (
                    "강세" if w > 0 else "약세", sr), "dir": "up" if w > 0 else "down"})
        elif sr is not None:
            caution.append("오늘 밤 미국 반도체 방향이 큰 변수예요")

    # 3) 수급(오늘)
    flow = signals.get("flow")
    if flow:
        f, o = flow.get("frgn_net") or 0, flow.get("orgn_net") or 0
        if f > 0 and o > 0:
            score += 1
            reasons.append({"text": "오늘 외국인·기관 쌍끌이 순매수(받침)", "dir": "up"})
        elif f < 0 and o < 0:
            score -= 1
            reasons.append({"text": "오늘 외국인·기관 동반 순매도(부담)", "dir": "down"})

    # 4) 모멘텀(오늘) — 과열은 0점 + 되돌림 주의
    mo = signals.get("momentum")
    if mo and mo.get("rate") is not None:
        if mo.get("overheated"):
            caution.append("오늘 급등 — 내일 되돌림(차익실현) 나올 수 있어요")
        elif mo["rate"] > 3:
            score += 1
            reasons.append({"text": "오늘 강한 상승 흐름 지속", "dir": "up"})
        elif mo["rate"] < -3:
            score -= 1
            reasons.append({"text": "오늘 약세 흐름", "dir": "down"})

    direction = "up" if score >= _UP else "down" if score <= _DOWN else "neutral"
    # 방향과 반대인 근거는 주의로
    opp = [r["text"] for r in reasons if r["dir"] != direction and direction != "neutral"]
    if opp:
        caution.append("다만 " + opp[0] + " 는 반대 요인")
    caution.append("예상일 뿐 빗나갈 수 있어요 · 참고용")

    return {"direction": direction, "score": score, "reasons": reasons,
            "caution": " · ".join(caution), "session": session,
            "framing": _FRAMING.get(session, _FRAMING["us_closed"])}
