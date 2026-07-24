from __future__ import annotations

"""매매 타이밍 판정 — 이평(20/60/120) 추세 × 수급을 보수적으로 결합.

순수 함수(테스트 용이). 추세·수급이 함께 확실할 때만 매수/매도, 나머지는 관망.
설계: docs/superpowers/specs/2026-07-14-timing-panel-design.md
"""

from typing import List, Optional

_OVERHEAT_RSI = 75.0
_WORD = {"inflow": "순매수", "outflow": "순매도"}


def _net(row: dict) -> float:
    return (row.get("frgn") or 0) + (row.get("orgn") or 0)


def summarize_flows(daily: List[dict], estimate_rows: List[dict],
                    program_net: Optional[float]) -> dict:
    """확정 수급(주) + 오늘 잠정(확인)을 방향으로 요약.

    확정: 최근 5거래일 외인+기관 순매수 합의 부호 + 연속일수.
    잠정: 오늘 마지막 슬롯 부호. 확정과 같으면 강화, 엇갈리면 중립으로 완충.
    """
    rows = sorted([r for r in (daily or []) if r.get("date") is not None],
                  key=lambda r: r["date"])[-5:]
    nets = [_net(r) for r in rows]
    net5 = sum(nets)
    confirmed = "inflow" if net5 > 0 else "outflow" if net5 < 0 else "neutral"
    # 연속일수: 가장 최근일과 같은 부호가 이어지는 일수
    streak = 0
    recent = None                                  # streak 자신의 방향
    if nets:
        sign = (nets[-1] > 0) - (nets[-1] < 0)
        if sign:
            recent = "inflow" if sign > 0 else "outflow"
            for n in reversed(nets):
                if (n > 0) - (n < 0) == sign:
                    streak += 1
                else:
                    break

    today = None
    if estimate_rows:
        t = _net(estimate_rows[-1])
        today = "inflow" if t > 0 else "outflow" if t < 0 else None

    if confirmed == "neutral":
        direction = today or "neutral"
    elif today is None:
        direction = confirmed
    elif today == confirmed:
        direction = confirmed
    else:
        direction = "neutral"                      # 상충 → 완충

    reasons = []
    # 연속일수에 붙는 단어는 streak 자신(recent)의 방향에서 온다. 5일 합계
    # (confirmed) 부호를 붙이면 최근 3일이 모두 순매수인 구간에 '3일 연속 순매도'가
    # 찍힌다(2026-07-23 SK하이닉스 실사고). 둘이 엇갈리면 전환 구간으로 함께 알린다.
    # 이때 화면이 말하는 기준선(base)도 streak 쪽으로 옮긴다 — 기준이 어긋난 채
    # '오늘 잠정은 반대 방향'을 붙이면, 잠정이 streak과 같은 방향인데도 반대라고
    # 말하는 두 번째 모순이 생긴다(리뷰 지적).
    base = recent if (streak >= 2 and recent) else confirmed
    if streak >= 2 and recent:
        reasons.append(f"외인·기관 {streak}일 연속 {_WORD[recent]}")
        if confirmed != "neutral" and confirmed != recent:
            reasons.append(f"5일 합계는 {_WORD[confirmed]} — 방향 전환 구간(중립 처리)")
    elif confirmed != "neutral":
        reasons.append(f"외인·기관 최근 {_WORD[confirmed]} 우위")
    if today and base != "neutral" and today != base:
        reasons.append("오늘 잠정은 반대 방향 — 상충(중립 처리)")
    elif today:
        reasons.append(f"오늘 잠정도 {_WORD[today]}")
    if program_net:
        reasons.append("프로그램 순매수" if program_net > 0 else "프로그램 순매도")

    return {"dir": direction, "streak": streak, "reasons": reasons}


def compute_timing(candle_rows: List[dict], daily: List[dict],
                   estimate_rows: List[dict], program_net: Optional[float],
                   last_price: Optional[float]) -> dict:
    """일봉 캔들 + 수급 → 타이밍 판정(엔진 글루의 테스트 가능한 순수 버전).

    캔들로 ma20/60/120·rsi·골든/데드크로스를 구하고 summarize_flows와 결합해
    assess_timing에 넘긴다. 캔들 부족 시 ma120이 비어 assess가 '판정 보류'를 낸다.
    """
    import pandas as pd

    from backend.analysis.indicators import add_indicators
    from backend.signals.rules import _crossed_down, _crossed_up

    flow = summarize_flows(daily, estimate_rows, program_net)
    if not candle_rows:
        return assess_timing({"ma20": None, "ma60": None, "ma120": None},
                             flow, last_price)
    df = pd.DataFrame(candle_rows).rename(
        columns={"open": "Open", "high": "High", "low": "Low", "close": "Close"})
    if "Volume" not in df.columns:
        df["Volume"] = 0
    ind = add_indicators(df)
    last = ind.iloc[-1]

    def _f(x):
        return None if pd.isna(x) else float(x)

    ind_row = {"ma20": _f(last.get("ma20")), "ma60": _f(last.get("ma60")),
               "ma120": _f(last.get("ma120")), "rsi14": _f(last.get("rsi14")),
               "golden_fresh": _crossed_up(ind["ma20"], ind["ma60"]),
               "dead_fresh": _crossed_down(ind["ma20"], ind["ma60"])}
    return assess_timing(ind_row, flow, last_price)


def _trend(ind: dict, last_price: Optional[float]) -> Optional[str]:
    ma20, ma60, ma120 = ind.get("ma20"), ind.get("ma60"), ind.get("ma120")
    if None in (ma20, ma60, ma120) or last_price is None:
        return None                                 # 데이터 부족
    if last_price > ma20 > ma60 > ma120:
        return "up"                                 # 정배열
    if last_price < ma20 < ma60 < ma120:
        return "down"                               # 역배열
    return "neutral"                                # 혼조


_HEADLINE = {"buy": "🟢 매수 우호", "watch": "🟡 관찰",
             "sell": "🔴 매도/회피", "hold": "⚪ 관망"}
_TONE = {"buy": "good", "watch": "info", "sell": "warn", "hold": "flat"}


def assess_timing(ind: dict, flow: dict, last_price: Optional[float]) -> dict:
    """추세 × 수급 → {stance, tone, headline, comment, reasons, entry_hint,
    overheated, confidence, asof}. 데이터 부족 시 stance=None(판정 보류)."""
    trend = _trend(ind, last_price)
    fdir = (flow or {}).get("dir", "neutral")
    if trend is None:
        return {"stance": None, "tone": "flat", "headline": "판정 보류",
                "comment": "데이터 부족 — 일봉(120)·수급 확보 후 표시",
                "reasons": [], "entry_hint": "", "overheated": False,
                "confidence": 0}

    golden = bool(ind.get("golden_fresh"))
    dead = bool(ind.get("dead_fresh"))
    rsi = ind.get("rsi14")
    overheated = rsi is not None and rsi >= _OVERHEAT_RSI

    # 기본 매트릭스(보수적)
    if trend == "up":
        stance = "buy" if fdir == "inflow" else "hold"
    elif trend == "down":
        stance = "watch" if fdir == "inflow" else "sell"
    else:
        stance = "hold" if fdir == "neutral" else "watch"

    strong = (golden and fdir == "inflow") or (dead and fdir == "outflow")
    if golden and fdir == "inflow":
        stance = "buy"
    if dead and fdir == "outflow":
        stance = "sell"

    # 과열 가드: 매수 신호라도 RSI 과열이면 추격 자제(관망 강등)
    if stance == "buy" and overheated:
        stance = "hold"

    confidence = 0
    if trend != "neutral":
        confidence += 1
    if fdir != "neutral":
        confidence += 1
    if strong:
        confidence += 1
    confidence = min(confidence, 3)

    # 코멘트
    if stance == "buy":
        comment = ("골든크로스 + 수급 유입 — 강한 매수 타이밍" if golden
                   else "상승추세 + 수급 유입 — 매수 우호, 20일선 눌림목 분할 접근")
    elif stance == "sell":
        comment = ("데드크로스 + 수급 이탈 — 매도 신호" if dead
                   else "하락추세 + 수급 이탈 — 신규매수 자제·보유분 관리")
    elif stance == "watch":
        if trend == "down":
            comment = "하락추세지만 수급 유입 — 바닥 다지기 가능, 반등 확인 후"
        else:
            comment = ("방향 모호, 수급 우호 — 정배열 전환 확인 후" if fdir == "inflow"
                       else "방향 모호 + 수급 이탈 — 관망")
    else:  # hold
        if trend == "up" and overheated:
            comment = "상승추세+수급 유입이나 과열(RSI↑) — 추격 자제, 눌림 대기"
        elif trend == "up":
            comment = ("상승추세지만 수급 이탈 — 차익 주의·관망" if fdir == "outflow"
                       else "상승추세지만 수급 뒷받침 약함 — 눌림 확인")
        else:
            comment = "뚜렷한 신호 없음 — 관망"

    reasons = []
    reasons.append({"up": "정배열(현재가>20일>60일>120일)",
                    "down": "역배열(현재가<20일<60일<120일)",
                    "neutral": "이평 혼조(추세 불명확)"}[trend])
    reasons.extend((flow or {}).get("reasons") or
                   [{"inflow": "수급 유입", "outflow": "수급 이탈",
                     "neutral": "수급 중립"}[fdir]])
    if golden:
        reasons.append("20일선이 60일선 상향 돌파(골든크로스)")
    if dead:
        reasons.append("20일선이 60일선 하향 돌파(데드크로스)")
    if overheated:
        reasons.append(f"RSI {rsi:.0f} 과열")

    entry_hint = ""
    if stance == "buy" and ind.get("ma20") is not None:
        entry_hint = f"20일선 {ind['ma20']:,.0f}원 눌림목 지지 확인 시 분할"

    return {"stance": stance, "tone": _TONE[stance], "headline": _HEADLINE[stance],
            "comment": comment, "reasons": reasons, "entry_hint": entry_hint,
            "overheated": overheated, "confidence": confidence}
