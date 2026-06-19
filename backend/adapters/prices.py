from __future__ import annotations
import pandas as pd
from backend.ingest.fdr_source import fetch_ohlcv as default_source


class PriceAdapter:
    """캐시 우선 가격 조회. 단, 캐시가 요청 end 날짜를 커버할 때만 사용(stale 방지)."""

    def __init__(self, cache, source=None):
        self.cache = cache
        self.source = source or default_source

    @staticmethod
    def _covers_end(cached, end) -> bool:
        return cached is not None and len(cached) > 0 and cached.index.max() >= pd.Timestamp(end)

    def get_ohlcv(self, code: str, start: str, end: str, force: bool = False):
        if not force:
            cached = self.cache.get(code)
            if self._covers_end(cached, end):
                return cached
        df = self.source(code, start, end)
        self.cache.put(code, df)
        return df
