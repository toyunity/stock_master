from __future__ import annotations

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
        df = pd.read_parquet(p)
        df.index = pd.to_datetime(df.index)
        return df

    def put(self, code: str, df: pd.DataFrame) -> None:
        df.to_parquet(self._path(code))
