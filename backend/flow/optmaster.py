from __future__ import annotations

"""코스피200 옵션 종목마스터 — 코드↔만기↔행사가. 파싱은 순수, 다운로드만 네트워크.

옵션은 만기·행사가마다 종목이 따로 있고 근월물 하나가 1,012개까지 간다. 전광판
TR(FHPIF05030100)은 행사가 내림차순 **상위 100행만** 주고 파라미터로 창이 안
움직인다(2026-08-05 실측) — 전 구간을 보려면 마스터에서 코드를 얻어 단건 시세를
도는 수밖에 없다. Python 3.9 호환."""

import datetime as dt
import io
import os
import re
import time
import zipfile
from typing import List, Optional

MST_URL = "https://new.real.download.dws.co.kr/common/master/fo_idx_code.mst.zip"
_MST_NAME = "fo_idx_code.mst"
_TTL_SEC = 86400.0        # 하루 1회만 새로 받는다(종목이 일 단위로 추가될 뿐이다)

# 이름 필드 예: 'C 202608   625.0' · 'P 202609 1,300.0'
# 만기·행사가는 **코드가 아니라 이름**에 있다 — 코드의 '01608'은 상품+연월 축약이라
# "202608"로 검색하면 한 건도 안 걸린다(초안 작성 때 이걸로 헤맸다).
_NAME_RE = re.compile(r"^([CP])\s+(\d{6})\s+([\d,]+\.\d+)")


def parse_master(lines) -> List[dict]:
    """마스터 행(str) 시퀀스 → [{code, side, expiry, strike}].

    고정폭: [0]=구분(5=콜·6=풋) · [1:10]=단축코드 · [10:22]=ISIN · [22:]=이름.
    구분이 5/6이 아닌 행(선물 등)과 이름이 형식에 안 맞는 행은 조용히 버린다 —
    마스터엔 옵션 말고도 여러 상품이 함께 들어 있다. 콜/풋 판정은 구분자가 아니라
    이름의 C/P로 한다(실측으로 확인한 쪽이 이쪽이다)."""
    out = []
    for line in lines:
        if not line or line[:1] not in ("5", "6") or len(line) < 23:
            continue
        m = _NAME_RE.match(line[22:])
        if not m:
            continue
        code = line[1:10].strip()
        if not code:
            continue
        out.append({"code": code,
                    "side": "call" if m.group(1) == "C" else "put",
                    "expiry": m.group(2),
                    "strike": float(m.group(3).replace(",", ""))})
    return out


def expiry_date(yyyymm: str) -> dt.date:
    """만기일 = 그 달의 **두 번째 목요일**(코스피200 옵션 규정).

    공휴일이면 직전 영업일로 앞당겨지지만 여기선 보지 않는다. 그 차이는 만기 당일
    하루에만 영향을 주고, 화면의 '만기 N일'은 KIS가 주는 잔존일수(hts_rmnn_dynu)를
    쓰므로 표기가 어긋나지 않는다. 이 함수는 '근월물이 이미 지났는가'의 근사 판정용이고,
    실제 롤오버는 marketdata의 만기 프로브가 한 번 더 확인한다."""
    y, m = int(yyyymm[:4]), int(yyyymm[4:6])
    first = dt.date(y, m, 1)
    first_thu = 1 + (3 - first.weekday()) % 7      # weekday: 월=0 … 목=3
    return dt.date(y, m, first_thu + 7)


def front_month(rows, today: dt.date) -> Optional[str]:
    """근월물 만기 'YYYYMM' — 만기일이 오늘 이후(당일 포함)인 것 중 가장 이른 것.
    만기 당일도 장이 열려 거래되므로 포함한다. 없으면 None."""
    for m in sorted({r["expiry"] for r in rows}):
        try:
            if expiry_date(m) >= today:
                return m
        except ValueError:
            continue                                # 형식이 깨진 만기는 건너뛴다
    return None


def chain(rows, expiry: str) -> dict:
    """만기 하나의 전 종목 → {'calls': [...], 'puts': [...]} (행사가 오름차순)."""
    sel = [r for r in rows if r.get("expiry") == expiry]

    def _key(r):
        return r.get("strike") or 0.0

    return {"calls": sorted([r for r in sel if r["side"] == "call"], key=_key),
            "puts": sorted([r for r in sel if r["side"] == "put"], key=_key)}


def _download() -> bytes:
    """마스터 zip → 첫 엔트리 bytes. 동기·블로킹 — 호출부가 run_in_executor로 위임한다."""
    import httpx
    r = httpx.get(MST_URL, timeout=60, follow_redirects=True)
    r.raise_for_status()
    z = zipfile.ZipFile(io.BytesIO(r.content))
    return z.read(z.namelist()[0])


def load(cache_dir: str, force: bool = False, fetch=None) -> List[dict]:
    """마스터 → 행 리스트. 캐시가 하루 안이면 재사용, 아니면 새로 받는다.

    다운로드가 실패하면 **낡은 캐시라도 그대로 쓴다** — 만기·행사가는 하루 사이에
    바뀌지 않고 종목이 추가될 뿐이라 stale이 무응답보다 낫다(해외선물 마스터에서
    쓰던 관행 그대로). 캐시도 없고 다운로드도 실패하면 빈 리스트 → 호출부가 섹션을
    통째로 생략한다. fetch는 테스트가 네트워크 없이 주입하는 훅(bytes 반환)."""
    path = os.path.join(cache_dir, _MST_NAME)
    try:
        fresh = (time.time() - os.path.getmtime(path)) < _TTL_SEC
    except OSError:
        fresh = False
    if force or not fresh:
        try:
            raw = (fetch or _download)()
            os.makedirs(cache_dir, exist_ok=True)
            with open(path, "wb") as f:
                f.write(raw)
        except Exception:
            pass                                    # 아래에서 낡은 캐시로 폴백
    try:
        with open(path, "rb") as f:
            lines = [ln.decode("cp949", errors="replace").rstrip("\r\n") for ln in f]
    except OSError:
        return []
    return parse_master(lines)
