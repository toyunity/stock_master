from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict

# 프로젝트 루트(= backend/의 상위). cwd에 의존하지 않도록 절대경로 기준점으로 사용.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SM_", env_file=".env", extra="ignore")

    # 관심종목(6자리 코드): 삼성전자, SK하이닉스, NAVER, LG화학, 현대차
    watchlist: list[str] = ["005930", "000660", "035420", "051910", "005380"]
    # 상대경로는 Claude Desktop 실행 시 읽기 전용 cwd로 해석되어 실패하므로 절대경로로 고정.
    cache_dir: str = str(_PROJECT_ROOT / "data" / "cache")
    db_path: str = str(_PROJECT_ROOT / "stock_master.db")
    history_days: int = 400  # 지표 계산용 과거 일수

    # S3 뉴스/공시
    dart_api_key: Optional[str] = None  # SM_DART_API_KEY (없으면 공시 비활성)
    news_feeds: list[str] = [
        "https://www.hankyung.com/feed/finance",  # 한경 증권
        "https://www.yna.co.kr/rss/economy.xml",  # 연합 경제
        "https://www.yna.co.kr/rss/market.xml",   # 연합 마켓+
    ]
    disclosure_lookback_days: int = 7  # DART 공시 조회 기간(일). 2일은 주말이면 0건이라 7일.
    news_max_per_stock: int = 5  # 종목별 뉴스/공시 표시 상한

    # S5 실시간 수급 (KIS 오픈API — 키 없으면 데모 모드로 화면 검증 가능)
    kis_app_key: Optional[str] = None      # SM_KIS_APP_KEY
    kis_app_secret: Optional[str] = None   # SM_KIS_APP_SECRET
    flow_mode: str = ""                    # ''=자동(키 있으면 live) | 'demo'=강제 데모


settings = Settings()
