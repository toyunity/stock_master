from __future__ import annotations

from backend.ingest.fdr_source import fetch_ohlcv as default_source


class PriceAdapter:
    """캐시 우선 가격 조회. source는 주입 가능(테스트/소스교체 대비)."""

    def __init__(self, cache, source=None):
        self.cache = cache
        self.source = source or default_source

    def get_ohlcv(self, code: str, start: str, end: str, force: bool = False):
        if not force:
            cached = self.cache.get(code)
            if cached is not None and len(cached) > 0:
                return cached
        df = self.source(code, start, end)
        self.cache.put(code, df)
        return df
