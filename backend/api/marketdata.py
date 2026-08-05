from __future__ import annotations

"""대시보드용 시장 컨텍스트 — 지수(코스피·코스닥) + 관심종목 밸류지표. REST·읽기전용.

시세(빠름)와 달리 지수/밸류는 느리게 변하므로 TTL 캐시로 KIS 호출을 아낀다. 웹소켓
미사용(1키1세션 불가침) — 전부 KisClient REST. 키 없으면 None/빈맵(대시보드가 조용히 생략).
Python 3.9 호환."""

import asyncio
import datetime as dt
import logging
import time

from backend.config import settings
from backend.education import glossary
from backend.signals import nextday

log = logging.getLogger(__name__)

_IDX_TTL = 30.0            # 지수 30초
_FUN_TTL = 300.0          # 밸류 5분(일 단위로만 바뀜)
_SEM = 5                  # KIS 동시 호출 상한(kis.py 실측)
_idx_cache = {"ts": 0.0, "data": None}
_fun_cache: dict = {}     # code -> (ts, dict|None)


def _client():
    if not settings.kis_app_key:
        return None
    try:
        from backend.flow.candles import _get_client
        return _get_client()
    except Exception:
        return None


async def get_indices(client=None):
    """{'kospi':{price,change,rate,sign}, 'kosdaq':{...}} — 30초 캐시. 키없음/실패면 None."""
    client = client or _client()
    if client is None:
        return None
    if _idx_cache["data"] is not None and time.time() - _idx_cache["ts"] < _IDX_TTL:
        return _idx_cache["data"]
    try:
        kospi = await client.index("0001")
        kosdaq = await client.index("1001")
    except Exception:
        return _idx_cache["data"]
    if kospi or kosdaq:
        _idx_cache["ts"], _idx_cache["data"] = time.time(), {"kospi": kospi, "kosdaq": kosdaq}
    return _idx_cache["data"]


_FUT_TTL_LIVE, _FUT_TTL_IDLE = 30.0, 300.0   # 세션 활성 30초 / 비활성 5분
_fut_cache = {"k200": {"ts": 0.0, "data": None}, "nq": {"ts": 0.0, "data": None}}
_FUT_LABEL = {"night": "야간선물"}

_NGT_TR = "H0MFCNT0"   # KRX 야간선물 실시간체결
_NGT_SANE = 0.30       # 틱 가격이 REST 값과 이 비율 넘게 벌어지면 안 쓴다(아래 참조)
_night_tick = None     # 최신 야간 틱(WS) — 없으면 REST 값으로 조용히 강등
_night_reg = None      # 현재 등록된 야간선물 종목코드(월물 롤오버 감지용)


def _night_price(rest_price):
    """실시간 틱 가격을 쓸 수 있으면 (price, rate), 아니면 None.

    **필드 순서를 못 믿기 때문에 있는 관문이다.** H0MFCNT0의 인덱스는 KIS 공식
    예제를 옮긴 것이고 이 저장소에 독립 근거가 없다 — 하나만 어긋나도
    누적거래량(예: 141272)이 가격 자리에 조용히 들어앉는다. 오버나잇 변동이
    아무리 커도 30%를 넘지는 않으므로, 그 밖이면 매핑이 틀렸다고 보고 REST 값을
    쓴다. 틀린 값을 자신 있게 보여주느니 덜 새로운 값을 보여준다."""
    t = _night_tick
    if not t or not t.get("price"):
        return None
    if rest_price:
        if abs(t["price"] - rest_price) / rest_price > _NGT_SANE:
            log.warning("야간 틱 가격 %.2f가 REST %.2f와 %d%% 넘게 벌어짐 — "
                        "H0MFCNT0 필드 매핑 의심, REST 값 사용",
                        t["price"], rest_price, int(_NGT_SANE * 100))
            return None
    return t["price"], t.get("rate")


def _on_night_tick(rec):
    """H0MFCNT0 레코드 → 최신 틱 보관.

    **선물 전용 파서를 쓴다** — 주식(H0STCNT0)용 kis.parse_ccnl은 필드 순서가
    다르고 가격이 정수라 이 레코드에선 아예 예외로 죽는다(tests/test_futures.py).
    파싱 실패(핑퐁·잘린 프레임)는 직전 틱을 덮어쓰지 않는다."""
    global _night_tick
    from backend.flow import futures as fx
    t = fx.parse_ngt_ccnl(rec)
    if t:
        _night_tick = {"price": t["price"], "rate": t["rate"]}


async def _ensure_night_ws(client, code):
    """야간 세션에서만 H0MFCNT0을 등록한다. 월물이 바뀌면 이전 등록을 해제하고 새로 건다.

    등록 실패는 삼킨다 — 실시간은 덤이고 칩 자체는 REST 값으로 살아야 한다.
    실패하면 _night_reg를 비워 다음 폴링(30초 뒤)에 다시 시도한다."""
    global _night_reg
    from backend.flow import wsbus
    if _night_reg == code:
        return
    try:
        bus = wsbus.WsSession.get(client)
        bus.start()
        if _night_reg:
            await bus.unregister(_NGT_TR, _night_reg, _on_night_tick)
        await bus.register(_NGT_TR, code, _on_night_tick)
        _night_reg = code
    except Exception:
        _night_reg = None
        log.warning("야간선물 실시간 등록 실패 — REST 값으로 계속한다", exc_info=True)


async def get_futures(client=None, now=None, fetch=None):
    """{'k200': {label,session,code,name,price,rate,sign,volume,closed,stale?},
        'nq': {label,price,rate,stale?}} — 대시보드 선물 칩 두 개.

    두 칩은 서로 다른 소스(국내선물 전광판 vs FinanceDataReader NQ=F)라 캐시·갱신이
    완전히 독립이다 — 한쪽이 죽어도(raise든 '쓸 행 없음'이든) 다른 쪽은 항상 시도한다
    (칩 단위 독립 실패). 각 칩은 갱신 실패 시 자기 직전 성공값을 그대로 쓰고
    'stale':True를 얹는다(지연 배지 — 체결정체가 아니라 갱신실패 기준). K200은 추가로
    세션이 gap·closed면 'closed':True를 얹어(마감 배지) 직전 종가를 라이브 가격과
    구분되게 보여준다. 키없음이면 None, 둘 다 콜드 상태로 실패하면 {}.

    nq 칩은 KIS가 아니라 FinanceDataReader(NQ=F, Yahoo 배경)를 쓰므로 한국 세션에
    묶인 ttl(day/night=30초, 그 외=300초)을 따르지 않는다 — 나스닥 선물은 거의 24시간
    움직이므로 항상 짧은 TTL(_FUT_TTL_LIVE=30초)로 갱신한다. fetch는 테스트가 실제
    FinanceDataReader 호출 없이 주입하는 훅(기본값 None → 실제 FDR 호출)."""
    from backend.flow import futures as fx
    client = client or _client()
    if client is None:
        return None
    ses = fx.session_of(now)
    ttl = _FUT_TTL_LIVE if ses in ("day", "night") else _FUT_TTL_IDLE
    data = {}
    k200 = await _k200_leg(client, fx, ses, ttl)
    if k200 is not None:
        data["k200"] = k200
    nq = await _nq_leg(client, _FUT_TTL_LIVE, fetch)
    if nq is not None:
        data["nq"] = nq
    return data


def _fut_closed(ses) -> bool:
    return ses in ("gap", "closed")


async def _k200_leg(client, fx, ses, ttl):
    """K200선물 칩 — 자기 슬롯만 보고 자기 슬롯만 채운다(nq 실패와 무관)."""
    slot = _fut_cache["k200"]
    if slot["data"] is not None and time.time() - slot["ts"] < ttl:
        out = dict(slot["data"])
        # 세션에 매인 것은 캐시 히트여도 매번 새로 판정한다. gap의 TTL이 300초라
        # 17:58에 담긴 캐시가 18:01에 그대로 나오면 라벨이 "K200선물"로 남는다
        # (실패 폴백 경로에서 같은 이유로 이미 재라벨링하고 있다).
        out["session"] = ses
        out["label"] = _FUT_LABEL.get(ses, "K200선물")
        out["closed"] = _fut_closed(ses)
        if ses == "night":
            # 등록도 여기서 확인한다 — 안 그러면 야간 개장 후 캐시가 만료될 때까지
            # (최대 5분) 실시간이 안 붙는다. 이미 등록돼 있으면 즉시 반환된다.
            await _ensure_night_ws(client, out.get("code"))
            # 틱은 캐시보다 새롭다 — 안 얹으면 실시간을 달아 놓고도 화면이
            # 30초에 한 번만 움직인다.
            live = _night_price(out.get("price"))
            if live:
                out["price"], out["rate"] = live
        return out
    front = None
    try:
        rows = await client.futures_board(fx.BOARD_CLS)
        front = fx.pick_front_month(rows)
    except Exception:
        front = None                               # 전광망 자체 실패도 '쓸 행 없음'과 동일 취급
    if front is None:
        if slot["data"] is None:
            return None                            # 콜드 + 실패 → 보여줄 게 없다
        out = dict(slot["data"])
        # 실패 폴백은 TTL의 제약을 받지 않고(원인이 계속되는 한) 무한정 오래된 값을 서빙할
        # 수 있다 — 세션 경계를 넘긴 채로(예: 15시 주간에 캐시된 값을 21시 야간에 그대로
        # 서빙) label/session을 얼리면(freeze) "주간선물" 라벨이 야간에 붙는다. 캐시 히트
        # (TTL 30초/300초 이내)와 달리 여기선 매번 재라벨링한다.
        out["session"] = ses
        out["label"] = _FUT_LABEL.get(ses, "K200선물")
        out["closed"] = _fut_closed(ses)
        out["stale"] = True                        # 갱신 실패 → 지연 배지
        return out
    k200 = dict(front)
    k200["session"] = ses
    k200["label"] = _FUT_LABEL.get(ses, "K200선물")
    if ses == "night":
        # 야간 세션가는 전광판(REST)이 15:45 종가에 멈춰 있을 수 있다(G2 미측정) —
        # 실시간 틱이 있으면 그걸 덮어쓴다. 없으면 REST 값 그대로 간다.
        await _ensure_night_ws(client, k200.get("code"))
        live = _night_price(k200.get("price"))
        if live:
            k200["price"], k200["rate"] = live
    slot["ts"], slot["data"] = time.time(), k200    # 캐시엔 closed/stale을 굽지 않는다(매번 재판정)
    out = dict(k200)
    out["closed"] = _fut_closed(ses)
    return out


async def _nq_leg(client, ttl, fetch=None):
    """나스닥 선물(NQ=F) 칩 — K200 성공/실패와 무관하게 항상 시도한다."""
    slot = _fut_cache["nq"]
    if slot["data"] is not None and time.time() - slot["ts"] < ttl:
        return dict(slot["data"])
    nq = await _nq_quote(client, fetch)
    if nq is None:
        if slot["data"] is None:
            return None
        out = dict(slot["data"])
        out["stale"] = True
        return out
    slot["ts"], slot["data"] = time.time(), nq
    return dict(nq)


_NQ_SYMBOL = "NQ=F"
_NQ_LOOKBACK_DAYS = 7   # 주말 + NaN 결측 행을 넉넉히 건너뛸 만큼(약 1주일)


def _fetch_nq(start: str):
    """FinanceDataReader NQ=F(나스닥100 선물, Yahoo 배경·비공식) — 동기·블로킹 호출.
    _nq_quote가 run_in_executor로 스레드풀에 위임해 이벤트루프를 막지 않는다."""
    import FinanceDataReader as fdr
    return fdr.DataReader(_NQ_SYMBOL, start)


async def _nq_quote(client, fetch=None):
    """나스닥 100 선물(NQ=F) 시세 칩 — FinanceDataReader(비공식 Yahoo 경유) 경유.

    KIS 해외선물(CME)은 계좌에 월 유료 구독이 필요해(2026-08-03 G3 실측 EGW00550
    'CME SUB거래소 신청 계좌가 아닙니다') 여전히 막혀 있다. 직전엔 프로덕션 검증필
    QQQ ETF(usquote.price_us)로 대신했으나 QQQ는 현물이라 미국 정규장 시간에만
    움직여, 이 칩의 원래 목적(야간 오버나이트 방향성)을 못 채웠다 — 2026-08-04 QQQ를
    걷어내고 FinanceDataReader의 NQ=F(선물, 거의 24시간 움직임)로 교체했다.

    FDR은 동기 라이브러리라 그대로 부르면 이벤트루프를 막는다 — run_in_executor로
    스레드풀에 위임한다(과거 kis.download_ff_master 호출과 같은 관용구). 응답엔
    거래일인데도 통째로 NaN인 행이 실제로 섞여 나온다(실측) — futures.pick_latest_pair가
    유효값만 걸러 현재가/직전값을 고른다. client는 이 칩에서 쓰지 않지만(FDR은 KIS
    무관) K200과 같은 시그니처를 유지해 _nq_leg 호출부를 단순하게 둔다.

    개인용 한정: FDR의 NQ=F는 비공식 Yahoo Finance 경유라 재배포 허가가 없다 — 이
    앱을 공개로 열면 이 칩은 반드시 제거해야 한다(제한 자체는 실시간 시세 재배포
    금지라는 기존 원칙과 같다).

    어떤 이유로든(임포트 실패·네트워크·빈 프레임·전부 NaN) 실패하면 함수 전체가
    감싸져 있어 이 칩만 죽고 K200 칩은 항상 유지된다."""
    from backend.flow import futures as fx, kst
    try:
        start = (kst.now() - dt.timedelta(days=_NQ_LOOKBACK_DAYS)).strftime("%Y-%m-%d")
        df = await asyncio.get_event_loop().run_in_executor(
            None, fetch or _fetch_nq, start)
        price, prev = fx.pick_latest_pair(list(df["Close"]))
        if price is None:
            return None
        rate = None if prev is None or prev == 0 else (price - prev) / prev * 100
        return {"label": "나스닥 선물", "price": price, "rate": rate}
    except Exception:
        return None


# ── 코스피200 옵션 ─────────────────────────────────────────────────────────
_OPT_RATE = 5.0     # 초당 발사 상한. 개인 계정 한도는 10건/초인데 /live 수급이
                    # 2~4건/초를 이미 쓴다 — 절반만 쓴다. 7.3건/초에서 EGW00201이
                    # 780건 중 6건 났다(2026-08-05 실측).
_OPT_CONC = 3       # 동시 요청 수(같은 실측의 조합: 동시 3 + 페이싱)
_OPT_RETRY = 2      # EGW00201 재시도 횟수
_OPT_BACKOFF = 1.0  # 재시도 첫 대기(초). 매 회 2배 — 테스트가 0으로 덮어쓴다.


async def _collect_chain(client, rows, rate=None, conc=None):
    """옵션 종목 리스트 → (파싱된 행 리스트, 실패 건수). 초당 rate 건을 안 넘는다.

    세마포어만으로는 유량을 못 막는다 — 응답이 빠르면 동시 3으로도 초당 20건이
    나간다. '직전 발사 예정 시각'을 잠금으로 지켜 간격 자체를 강제한다. 페이싱을
    세마포어 **안**에서 하는 이유: 예약 직후 곧바로 발사돼야 예약과 실제 발사가
    어긋나지 않는다(밖에서 하면 세마포어 대기 동안 예약이 밀려 뭉쳐 나간다).

    rate/conc 기본값을 상수로 직접 쓰지 않고 None으로 두는 이유: 기본값은 함수
    정의 시점에 묶여, 테스트가 _OPT_RATE를 바꿔도 안 먹는다.

    실패는 예외로 올리지 않는다 — 1,012건 중 몇 건은 늘 실패하고, 그건 정상
    경로다(스펙 §에러 처리). 대신 **몇 건 실패했는지를 반환해 화면이 밝힌다**."""
    if not rows:
        return [], 0
    rate = _OPT_RATE if rate is None else rate
    conc = _OPT_CONC if conc is None else conc
    interval = 1.0 / max(rate, 0.001)
    sem = asyncio.Semaphore(max(1, conc))
    lock = asyncio.Lock()
    state = {"next": 0.0, "failed": 0}

    async def pace():
        async with lock:
            now = time.monotonic()
            wait = max(0.0, state["next"] - now)
            state["next"] = max(now, state["next"]) + interval
        if wait > 0:
            await asyncio.sleep(wait)

    async def one(row):
        delay = _OPT_BACKOFF
        for attempt in range(_OPT_RETRY + 1):
            async with sem:
                await pace()
                try:
                    q = await client.option_quote(row["code"])
                except Exception:
                    q = None
            if q is not None:
                q["code"], q["side"] = row["code"], row.get("side")
                if not q.get("strike"):
                    q["strike"] = row.get("strike")   # 응답이 비면 마스터 값으로
                return q
            if attempt < _OPT_RETRY and delay:
                await asyncio.sleep(delay)            # 지수 백오프
                delay *= 2
        state["failed"] += 1
        return None

    out = await asyncio.gather(*(one(r) for r in rows))
    return [q for q in out if q is not None], state["failed"]


_OPT_TTL = 3600.0        # 장중 1시간. 회차당 1,012건·약 3.5분이라 더 자주 돌 이유가 없다.
_OPT_FILE = "options_%s.json"
_opt_cache = {"ts": 0.0, "data": None, "busy": False}


def _opt_path(expiry):
    import os
    return os.path.join(settings.cache_dir, _OPT_FILE % expiry)


def _opt_save_disk(data):
    """수집 결과를 디스크에 남긴다 — 서버 재기동에도 직전 보드가 살아 있어야 한다."""
    import json
    import os
    try:
        os.makedirs(settings.cache_dir, exist_ok=True)
        with open(_opt_path(data["expiry"]), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception:
        pass                     # 캐시 저장 실패가 화면을 죽이면 안 된다


def _opt_load_disk():
    """가장 최근에 저장된 보드 하나를 읽는다(만기별 파일 중 mtime 최신). 없으면 None."""
    import glob
    import json
    import os
    try:
        paths = glob.glob(os.path.join(settings.cache_dir, _OPT_FILE % "*"))
        if not paths:
            return None
        with open(max(paths, key=os.path.getmtime), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


async def _pick_expiry(client, rows, today):
    """근월물과 잔존일수 — 마스터로 고르고 **한 건만 찔러 확인**한다.

    만기일 계산(둘째 목요일)은 공휴일로 앞당겨지는 경우를 못 본다. 전 종목 3.5분을
    돌고 나서 '이미 만기였다'를 알면 늦으므로, 체인 한가운데 한 종목만 조회해
    잔존일수를 본다. 음수면 다음 월물로 넘어간다. 프로브가 실패하면(장외 등) 계산값을
    그대로 쓴다 — best effort지 게이트가 아니다."""
    from backend.flow import optmaster as om
    months = [m for m in sorted({r["expiry"] for r in rows})
              if om.expiry_date(m) >= today][:2]
    for m in months:
        ch = om.chain(rows, m)
        pool = ch["calls"] or ch["puts"]
        if not pool:
            continue
        try:
            q = await client.option_quote(pool[len(pool) // 2]["code"])
        except Exception:
            q = None
        if q is None:
            return m, None                       # 프로브 실패 → 계산값 채택
        if (q.get("remain_days") or 0) >= 0:
            return m, q.get("remain_days")
    return (months[0], None) if months else (None, None)


def _opt_pack(rows):
    """행 리스트 → [[행사가, 미결제, 당일증감], ...] (행사가 오름차순).

    1,012행을 dict로 보내면 JSON이 120KB를 넘는다 — 화면이 쓰는 건 이 셋뿐이라
    3튜플로 줄인다(약 20KB). 순서는 응답의 'cols'가 밝힌다."""
    return [[r.get("strike"), r.get("oi") or 0, r.get("oi_chg") or 0]
            for r in sorted(rows, key=lambda x: x.get("strike") or 0.0)
            if r.get("strike")]


async def _collect_options(client):
    """한 회차 전체 수집 — 마스터 → 만기 → 현물 → 콜/풋 전 종목. 실패하면 None."""
    from backend.flow import kst, optmaster as om, options as opt
    rows = await asyncio.get_event_loop().run_in_executor(
        None, om.load, settings.cache_dir)
    if not rows:
        return None
    expiry, remain = await _pick_expiry(client, rows, kst.today())
    if not expiry:
        return None
    ch = om.chain(rows, expiry)
    if not ch["calls"] and not ch["puts"]:
        return None
    # 코스피200 현물 — 스펙은 단건 시세 output3에 딸려 온다고 했지만 그 필드명이
    # 실측으로 기록되지 않았다. 추측한 이름이 빗나가면 spot=0이 되고, spot이 0이면
    # wall()·atm_iv()가 통째로 무의미해진다. 이미 검증된 index("2001")을 쓴다(1건).
    try:
        spot = (await client.index("2001") or {}).get("price")
    except Exception:
        spot = None
    calls, cf = await _collect_chain(client, ch["calls"])
    puts, pf = await _collect_chain(client, ch["puts"])
    if not calls and not puts:
        return None
    if remain is None:
        got = [r.get("remain_days") for r in (calls + puts) if r.get("remain_days")]
        remain = got[0] if got else None
    return {"expiry": expiry, "label": opt.month_label(expiry),
            "remain_days": remain, "spot": spot,
            "cols": ["strike", "oi", "oi_chg"],
            "calls": _opt_pack(calls), "puts": _opt_pack(puts),
            "summary": opt.summarize(calls, puts, spot),
            "failed": cf + pf, "ts": time.time()}


def _opt_fresh(ts, now, live) -> bool:
    """캐시가 아직 쓸 만한가 — 스펙 §데이터 흐름 "정규장 3600초 / 그 외 다음 개장까지".

    마감 후에도 **한 번은 받아야 한다.** 미결제·당일증감은 15:45에 확정되고 그 뒤로
    안 변하며, 장외에도 REST가 마감 스냅샷을 정상 응답한다(2026-08-05 18:40 실측).
    'live일 때만 수집'으로 두면 마감 후 재기동한 저녁 내내 섹션이 텅 빈다."""
    if not ts:
        return False
    if live:
        return (time.time() - ts) < _OPT_TTL
    from backend.flow import options as opt
    return ts >= opt.last_close(now).timestamp()


async def _opt_refresh(client):
    """백그라운드 1회차 — 성공하면 캐시·디스크를 갈아끼우고, 실패하면 직전값을 둔다."""
    try:
        data = await _collect_options(client)
        if data:
            _opt_cache["ts"], _opt_cache["data"] = time.time(), data
            _opt_save_disk(data)
    except Exception:
        pass
    finally:
        _opt_cache["busy"] = False        # 실패해도 반드시 풀린다(안 풀면 영영 안 돈다)


async def get_options(client=None, now=None):
    """코스피200 옵션 보드 — 대시보드 섹션용. 키없음이면 None, 콜드+수집중이면 {}.

    한 회차가 최대 1,012건·약 3.5분이라 **요청을 붙잡지 않는다** — 캐시가 만료돼도
    직전값을 즉시 돌려주고 갱신은 백그라운드로 돌린다('collecting': True). 대차잔고
    최초 백필과 같은 패턴이다. 'stale'은 장중에 TTL이 지났는데 아직 새 값이 없다는
    뜻이고, 마감 후엔 붙이지 않는다(마감은 지연이 아니다 — 선물 칩에서 정한 규칙)."""
    from backend.flow import options as opt
    if not settings.options_enabled:
        # 기본 끔(fail-safe). 한 회차가 KIS 호출 최대 1,012건이고 /live 수급과 같은
        # 키를 나눠 쓴다 — 장중 실측으로 유량이 안전한 게 확인되기 전에는 안 돈다.
        # 디스크에 남은 직전 보드도 서빙하지 않는다(껐으면 화면에서 통째로 사라져야 한다).
        return None
    client = client or _client()
    if client is None:
        return None
    if _opt_cache["data"] is None:
        disk = _opt_load_disk()                   # 재기동 직후에도 직전 보드를 보여준다
        if disk:
            # 수집 시각도 같이 살린다 — 안 살리면 ts=0이라 재기동할 때마다
            # '낡았다'고 판단해 780건을 다시 긁는다.
            _opt_cache["data"] = disk
            _opt_cache["ts"] = disk.get("ts") or 0.0
    live = opt.session_of(now) == "live"
    fresh = _opt_fresh(_opt_cache["ts"], now, live)
    if not fresh and not _opt_cache["busy"]:
        _opt_cache["busy"] = True
        asyncio.ensure_future(_opt_refresh(client))
    data = _opt_cache["data"]
    if data is None:
        return {}
    out = dict(data)
    out["collecting"] = _opt_cache["busy"]
    out["stale"] = bool(live and not fresh)
    return out


_ASK_TTL = 2.0            # 호가 스냅샷 2초(빠르게 변함, 다중 뷰어 폭주만 방지)
_ask_cache: dict = {}     # code -> (ts, dict|None)


async def get_asking(code, client=None):
    """호가 사다리 스냅샷 — 2초 캐시. 키없음/실패면 {}(‌/live가 조용히 생략)."""
    client = client or _client()
    if client is None:
        return {}
    hit = _ask_cache.get(code)
    if hit and time.time() - hit[0] < _ASK_TTL:
        return hit[1] or {}
    try:
        a = await client.asking_price(code)
    except Exception:
        return (hit[1] if hit else {}) or {}
    _ask_cache[code] = (time.time(), a)
    return a or {}


_DETAIL_TTL = 300.0
_detail_cache: dict = {}   # code -> (ts, dict)


async def get_stock_detail(code, client=None):
    """단일 종목 기업 체력 — {'valuation':{per,pbr,w52_pos,...}, 'financials':[분기...],
    'explains':{지표→쉬운말}, 'concepts':{지표→개념설명}}. 5분 캐시.

    /live '기업 체력' 접힘 패널 전용. 밸류·재무는 일/분기 단위로만 바뀌어 폴링하지
    않는다(페이지당 1회). 키없음/실패면 빈 dict(패널이 통째로 숨음)."""
    client = client or _client()
    if client is None:
        return {}
    hit = _detail_cache.get(code)
    if hit and time.time() - hit[0] < _DETAIL_TTL:
        return hit[1]
    try:
        val = await client.fundamentals(code)
        fin = await client.financials(code)
    except Exception:
        return (hit[1] if hit else {})
    data = {"valuation": val, "financials": (fin or [])[:4],   # 최근 4분기
            "explains": _explains(val, fin),                    # 값 인식형 쉬운말(순수)
            "concepts": {k: glossary.concept(k)
                         for k in ("per", "pbr", "w52", "roe", "debt")}}
    _detail_cache[code] = (time.time(), data)
    return data


def _explains(val, fin) -> dict:
    """valuation+financials → 지표 쉬운말 맵(값 없으면 키 생략). 순수·네트워크 없음."""
    v = val or {}
    f = (fin or [{}])[0] if fin else {}
    out = {"per": glossary.read_per(v.get("per")),
           "pbr": glossary.read_pbr(v.get("pbr")),
           "w52": glossary.read_w52_pos(v.get("w52_pos")),
           "roe": glossary.read_roe(f.get("roe")),
           "debt": glossary.read_debt(f.get("debt"))}
    return {k: x for k, x in out.items() if x}


_OUTLOOK_TTL = 60.0
_outlook_cache: dict = {}   # code -> (ts, dict)


async def _gather_signals(code, client) -> dict:
    """내일 예상 신호 수집 — 미국(반도체)·ADR 오버나잇·오늘 수급·모멘텀. 부분 실패 허용.
    세션은 market_status/adr로 판정. 웹소켓 미사용(REST만)."""
    from backend.flow import semi, adr, market_status
    sig = {"us": None, "adr": None, "flow": None, "momentum": None}
    sig["is_semi"] = (code in getattr(settings, "semi_kr", [])
                      or code in getattr(settings, "adr_map", {}))
    us_open = adr.us_market_open()
    kr_open = market_status.wallclock_open()
    sig["session"] = ("kr_open" if kr_open else "us_live" if us_open else "us_closed")
    try:
        ov = await semi.get_overview()
        g = {x.get("sym"): x for x in (ov.get("us") or [])}
        sig["us"] = {"sox_rate": (g.get("SOX") or {}).get("rate"),
                     "nasdaq_rate": (g.get("SOXX") or {}).get("rate"),
                     "us_open": ov.get("us_open")}
    except Exception:
        pass
    try:
        q = await adr.get_quote(client, code)
        if q and q.get("usd") and q.get("base_usd"):
            sig["adr"] = {"overnight_rate": (q["usd"] / q["base_usd"] - 1) * 100}
    except Exception:
        pass
    try:
        rows = await client.daily_investor(code)
        if rows:
            sig["flow"] = {"frgn_net": rows[0].get("frgn"), "orgn_net": rows[0].get("orgn")}
    except Exception:
        pass
    try:
        p = await client.price(code)
        if p and p.get("rate") is not None:
            sig["momentum"] = {"rate": p["rate"], "overheated": p["rate"] >= 10}
    except Exception:
        pass
    return sig


async def get_outlook(code, client=None):
    """단일 종목 내일 예상(풀) — 신호 수집 후 규칙 엔진. 60초 캐시. 신호 전멸이면 None."""
    client = client or _client()
    if client is None:
        return None
    hit = _outlook_cache.get(code)
    if hit and time.time() - hit[0] < _OUTLOOK_TTL:
        return hit[1]
    sig = await _gather_signals(code, client)
    if not any(sig.get(k) for k in ("us", "adr", "flow", "momentum")):
        return None
    o = nextday.outlook(sig)
    _outlook_cache[code] = (time.time(), o)
    return o


async def get_outlook_brief(codes, client=None):
    """관심종목 경량 내일 예상 — code→{direction,reason}. get_outlook 캐시 공유."""
    client = client or _client()
    if client is None or not codes:
        return {}
    out = {}
    for c in codes[:12]:
        o = await get_outlook(c, client)
        if o:
            reason = o["reasons"][0]["text"] if o["reasons"] else o["framing"]
            out[c] = {"direction": o["direction"], "reason": reason}
    return out


_TOPVIEW_TTL = 60.0
_topview_cache = {"ts": 0.0, "data": None}


async def get_top_view(client=None):
    """조회상위(인기) — [{code,name}] 상위 10. 60초 캐시. 코드→이름은 universe 조인."""
    client = client or _client()
    if client is None:
        return []
    if _topview_cache["data"] is not None and time.time() - _topview_cache["ts"] < _TOPVIEW_TTL:
        return _topview_cache["data"]
    try:
        codes = await client.top_view()
    except Exception:
        return _topview_cache["data"] or []
    from backend.market import universe as _universe
    from backend.news.names import resolve_name
    names = _universe.name_map(_universe.get_cached())
    data = [{"code": c, "name": resolve_name(c, names)} for c in codes[:10]]
    if data:
        _topview_cache["ts"], _topview_cache["data"] = time.time(), data
    return data


async def get_fundamentals(codes, client=None):
    """{code: {per,pbr,eps,bps,w52_high,w52_low,w52_pos}} — 코드별 5분 캐시. 실패 코드는 생략."""
    client = client or _client()
    if client is None or not codes:
        return {}
    now = time.time()
    fresh, stale = {}, []
    for c in codes:
        hit = _fun_cache.get(c)
        if hit and now - hit[0] < _FUN_TTL:
            if hit[1]:
                fresh[c] = hit[1]
        else:
            stale.append(c)
    if stale:
        sem = asyncio.Semaphore(_SEM)

        async def one(code):
            async with sem:
                try:
                    return code, await client.fundamentals(code)
                except Exception:
                    return code, None
        for code, f in await asyncio.gather(*(one(c) for c in stale)):
            _fun_cache[code] = (now, f)
            if f:
                fresh[code] = f
    return fresh
