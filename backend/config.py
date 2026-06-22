from __future__ import annotations

from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SM_", env_file=".env", extra="ignore")

    # 관심종목(6자리 코드): 삼성전자, SK하이닉스, NAVER, LG화학, 현대차
    watchlist: list[str] = ["005930", "000660", "035420", "051910", "005380"]
    cache_dir: str = "data/cache"
    db_path: str = "stock_master.db"
    history_days: int = 400  # 지표 계산용 과거 일수

    # S3 뉴스/공시
    dart_api_key: Optional[str] = None  # SM_DART_API_KEY (없으면 공시 비활성)
    news_feeds: list[str] = [
        "https://www.hankyung.com/feed/finance",  # 한경 증권
        "https://www.yna.co.kr/rss/economy.xml",  # 연합 경제
        "https://www.yna.co.kr/rss/market.xml",   # 연합 마켓+
    ]
    news_lookback_days: int = 2  # 공시 조회 기간(일)
    news_max_per_stock: int = 5  # 종목별 뉴스/공시 표시 상한


settings = Settings()
