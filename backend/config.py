from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SM_", env_file=".env", extra="ignore")

    # 관심종목(6자리 코드): 삼성전자, SK하이닉스, NAVER, LG화학, 현대차
    watchlist: list[str] = ["005930", "000660", "035420", "051910", "005380"]
    cache_dir: str = "data/cache"
    db_path: str = "stock_master.db"
    history_days: int = 400  # 지표 계산용 과거 일수


settings = Settings()
