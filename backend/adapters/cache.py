from __future__ import annotations

import os
from pathlib import Path
import pandas as pd


class OHLCVCache:
    """종목별 OHLCV를 parquet으로 저장/조회한다. 인덱스는 DatetimeIndex."""

    def __init__(self, cache_dir):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, code: str) -> Path:
        return self.cache_dir / f"{code}.parquet"

    def get(self, code: str):
        p = self._path(code)
        if not p.exists():
            return None
        try:
            df = pd.read_parquet(p)
            df.index = pd.to_datetime(df.index)
        except Exception:  # noqa: BLE001 — 손상 파일. None을 주면 곧바로 재수집·재기록된다.
            return None    # 안 그러면 PriceAdapter가 fetch보다 먼저 여기서 터져
        return df          # 그 종목 차트가 손으로 파일을 지울 때까지 영영 안 나온다

    def put(self, code: str, df: pd.DataFrame) -> None:
        p = self._path(code)
        tmp = p.with_name(p.name + ".tmp")   # watch.py·userstore.py와 같은 관용구 —
        df.to_parquet(tmp)                   # 쓰다 죽어도 멀쩡한 캐시를 반쪽으로 덮지 않게
        os.replace(tmp, p)
