# Stock Master — 구현 계획서 (MVP: S0–S2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 과거 시세(FDR) → 지표(`ta`) → 검증(백테스트)된 매매 신호 → HTML 일일 리포트까지, **KIS 계좌 없이 EOD로 동작하는 MVP**를 완성한다.

**Architecture:** 단일 책임 모듈 + 데이터 어댑터/캐시 레이어. 데이터 소스(FDR)는 주입 가능(injectable)하게 추상화해 테스트가 네트워크에 의존하지 않게 하고, 스크래퍼가 깨져도 상위 모듈이 영향받지 않게 한다. 모든 신호는 백테스트 게이트를 통과해야 "조언"으로 노출된다.

**Tech Stack:** Python 3.13, finance-datareader, pandas, `ta`, pyarrow(parquet), Jinja2, pydantic-settings, pytest.

**관련 문서:** 설계 = `docs/design.md`. 본 계획은 설계의 로드맵 S0(기반)·S1(MVP)·S2(백테스트 게이트)를 구현한다. S3~S6은 본 문서 말미 §후속 계획에 개요로 둔다.

---

## 진행 원칙
- **TDD**: 실패 테스트 → 최소 구현 → 통과 → 커밋. (각 step 2~5분)
- ⚠️ **예시 테스트·합성 데이터는 "미실행 출발점"이다.** 본 계획의 코드/테스트는 아직 한 번도 실행되지 않았다. 각 step의 "Expected: PASS"는 *의도*이지 *검증된 사실*이 아니다. 첫 실행에서 빨간불이 나면 "뭔가 고장났다"가 아니라 **"이 출발 테스트의 데이터/로직을 다듬으라는 신호"**로 해석한다. (특히 합성 데이터가 지표 임계값과 어떻게 상호작용하는지는 실행해 봐야 확실해진다 — Task 1.3의 ⚠️ 참고.)
- **DRY / YAGNI**: 지금 MVP에 필요한 것만.
- **병렬 표시**: 각 Task 머리에 `[병렬: 가능 — 선행 Task X 이후]` 또는 `[병렬: 불가 — 선행 의존]`을 명시. 같은 묶음(병렬 그룹)으로 표시된 Task는 서로 독립이라 별도 에이전트/워크트리에서 동시에 진행 가능.
- **커밋**: 각 Task 끝에 1커밋. (저장소는 Task 0.1에서 `git init`)

## 파일 구조 (이 계획이 만드는 것)

```
stock_master/
├── pyproject.toml                 # 의존성·도구 설정
├── .gitignore
├── backend/
│   ├── __init__.py
│   ├── config.py                  # 설정(관심종목, 경로 등)
│   ├── cli.py                     # 진입점: `python -m backend.cli report`
│   ├── adapters/
│   │   ├── __init__.py
│   │   ├── cache.py               # OHLCVCache (parquet)
│   │   ├── prices.py              # PriceAdapter (캐시 우선)
│   │   └── db.py                  # SQLite 초기화/접근
│   ├── ingest/
│   │   ├── __init__.py
│   │   └── fdr_source.py          # FinanceDataReader 래퍼(주입 가능)
│   ├── analysis/
│   │   ├── __init__.py
│   │   ├── indicators.py          # add_indicators()
│   │   └── backtest.py            # backtest_strategy()
│   ├── signals/
│   │   ├── __init__.py
│   │   └── rules.py               # Signal, evaluate(), advice gate
│   └── report/
│       ├── __init__.py
│       ├── render.py              # render_daily_report()
│       └── templates/daily.html.j2
└── tests/
    ├── __init__.py
    ├── test_cache.py
    ├── test_prices.py
    ├── test_indicators.py
    ├── test_rules.py
    ├── test_backtest.py
    ├── test_gate.py
    └── test_render.py
```

---

# 슬라이스 S0 — 기반

## Task 0.1: 프로젝트 스캐폴드 + 의존성 + pytest 동작 확인
`[병렬: 불가 — 모든 작업의 선행. 가장 먼저.]`

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `backend/__init__.py`, `tests/__init__.py`, `tests/test_smoke.py`

- [ ] **Step 1: 저장소 초기화 & 디렉터리 생성**

```bash
cd /Users/toyunity/dev/stock_master
git init
mkdir -p backend/adapters backend/ingest backend/analysis backend/signals backend/report/templates tests data/cache
touch backend/__init__.py backend/adapters/__init__.py backend/ingest/__init__.py backend/analysis/__init__.py backend/signals/__init__.py backend/report/__init__.py tests/__init__.py
```

- [ ] **Step 2: `pyproject.toml` 작성**

```toml
[project]
name = "stock-master"
version = "0.1.0"
description = "한국 주식 실시간 분석·매매조언 PWA (개인용)"
# MVP(S0~S2) 의존성은 모두 3.9+ 호환. 실행 환경에 3.13이 없어 3.9로 진행한다.
# S3의 OpenDartReader(3.13 요구)는 'DART REST 직접 호출'로 우회하므로 3.13 불필요.
requires-python = ">=3.9"
dependencies = [
    "finance-datareader>=0.9.101",
    "pandas>=2.2",
    "ta>=0.11.0",
    "pyarrow>=15.0",
    "jinja2>=3.1",
    "pydantic-settings>=2.2",
]

[project.optional-dependencies]
dev = ["pytest>=8.0"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q"

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"
```

- [ ] **Step 3: `.gitignore` 작성**

```gitignore
__pycache__/
*.pyc
.venv/
data/cache/*.parquet
stock_master.db
.env
docs/report.html
```
> 참고: `docs/design.md`·`docs/implementation-plan.md`는 추적, 생성물(report.html, db, parquet)은 제외.

- [ ] **Step 4: 가상환경 + 설치**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e ".[dev]"
```
Expected: 설치 성공. (이 환경은 Python 3.9.6 — MVP 의존성은 3.9 호환. 3.13이 있으면 그걸 써도 무방.)

- [ ] **Step 5: 스모크 테스트 작성 `tests/test_smoke.py`**

```python
def test_imports():
    import backend
    assert backend is not None
```

- [ ] **Step 6: 실행해서 통과 확인**

Run: `pytest tests/test_smoke.py -v`
Expected: PASS (1 passed)

- [ ] **Step 7: 커밋**

```bash
git add pyproject.toml .gitignore backend tests docs
git commit -m "chore: scaffold project, deps, pytest smoke test"
```

---

## Task 0.2: 설정 모듈 `backend/config.py`
`[병렬: 가능 — Task 0.1 이후, 0.3/0.5와 동시 진행 가능]`

**Files:**
- Create: `backend/config.py`, `tests/test_config.py`

- [ ] **Step 1: 실패 테스트 `tests/test_config.py`**

```python
from backend.config import Settings

def test_defaults_have_watchlist_and_paths():
    s = Settings()
    assert isinstance(s.watchlist, list)
    assert len(s.watchlist) >= 5
    assert all(code.isdigit() and len(code) == 6 for code in s.watchlist)
    assert s.cache_dir.endswith("cache")
    assert s.db_path.endswith(".db")

def test_env_override(monkeypatch):
    monkeypatch.setenv("SM_DB_PATH", "/tmp/x.db")
    s = Settings()
    assert s.db_path == "/tmp/x.db"
```

- [ ] **Step 2: 실패 확인** — Run: `pytest tests/test_config.py -v` → FAIL (No module named backend.config)

- [ ] **Step 3: 구현 `backend/config.py`**

```python
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SM_", env_file=".env", extra="ignore")

    # 관심종목(6자리 코드): 삼성전자, SK하이닉스, NAVER, LG화학, 현대차
    watchlist: list[str] = ["005930", "000660", "035420", "051910", "005380"]
    cache_dir: str = "data/cache"
    db_path: str = "stock_master.db"
    history_days: int = 400  # 지표 계산용 과거 일수

settings = Settings()
```

- [ ] **Step 4: 통과 확인** — Run: `pytest tests/test_config.py -v` → PASS

- [ ] **Step 5: 커밋** — `git add backend/config.py tests/test_config.py && git commit -m "feat: settings module with watchlist defaults"`

---

## Task 0.3: OHLCV parquet 캐시 `backend/adapters/cache.py`
`[병렬: 가능 — Task 0.1 이후, 0.2/0.5와 동시 진행 가능]`

**Files:**
- Create: `backend/adapters/cache.py`, `tests/test_cache.py`

- [ ] **Step 1: 실패 테스트 `tests/test_cache.py`**

```python
import pandas as pd
from pathlib import Path
from backend.adapters.cache import OHLCVCache

def _frame():
    idx = pd.date_range("2024-01-01", periods=3, freq="D")
    return pd.DataFrame(
        {"Open": [1, 2, 3], "High": [1, 2, 3], "Low": [1, 2, 3],
         "Close": [1.0, 2.0, 3.0], "Volume": [10, 20, 30]}, index=idx)

def test_put_then_get_roundtrip(tmp_path):
    cache = OHLCVCache(tmp_path)
    df = _frame()
    cache.put("005930", df)
    got = cache.get("005930")
    assert got is not None
    pd.testing.assert_frame_equal(got, df)

def test_get_missing_returns_none(tmp_path):
    cache = OHLCVCache(tmp_path)
    assert cache.get("000000") is None
```

- [ ] **Step 2: 실패 확인** — Run: `pytest tests/test_cache.py -v` → FAIL

- [ ] **Step 3: 구현 `backend/adapters/cache.py`**

```python
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
```

- [ ] **Step 4: 통과 확인** — Run: `pytest tests/test_cache.py -v` → PASS

- [ ] **Step 5: 커밋** — `git add backend/adapters/cache.py tests/test_cache.py && git commit -m "feat: parquet OHLCV cache"`

---

## Task 0.4: 가격 어댑터(캐시 우선) `backend/adapters/prices.py`
`[병렬: 불가 — Task 0.3 의존]`

**Files:**
- Create: `backend/adapters/prices.py`, `tests/test_prices.py`

- [ ] **Step 1: 실패 테스트 `tests/test_prices.py`**

```python
import pandas as pd
from backend.adapters.cache import OHLCVCache
from backend.adapters.prices import PriceAdapter

def _frame():
    idx = pd.date_range("2024-01-01", periods=3, freq="D")
    return pd.DataFrame(
        {"Open": [1, 2, 3], "High": [1, 2, 3], "Low": [1, 2, 3],
         "Close": [1.0, 2.0, 3.0], "Volume": [10, 20, 30]}, index=idx)

def test_fetches_from_source_on_miss_then_caches(tmp_path):
    calls = []
    def fake_source(code, start, end):
        calls.append(code)
        return _frame()
    adapter = PriceAdapter(OHLCVCache(tmp_path), source=fake_source)

    df1 = adapter.get_ohlcv("005930", "2024-01-01", "2024-01-03")
    df2 = adapter.get_ohlcv("005930", "2024-01-01", "2024-01-03")

    assert len(df1) == 3
    assert calls == ["005930"]  # 두 번째는 캐시에서 → source 1회만 호출

def test_force_refresh_bypasses_cache(tmp_path):
    calls = []
    def fake_source(code, start, end):
        calls.append(code); return _frame()
    adapter = PriceAdapter(OHLCVCache(tmp_path), source=fake_source)
    adapter.get_ohlcv("005930", "2024-01-01", "2024-01-03")
    adapter.get_ohlcv("005930", "2024-01-01", "2024-01-03", force=True)
    assert calls == ["005930", "005930"]
```

- [ ] **Step 2: 실패 확인** — Run: `pytest tests/test_prices.py -v` → FAIL

- [ ] **Step 3: 구현 `backend/adapters/prices.py`**

```python
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
```
> ⚠️ `backend/ingest/fdr_source.py`는 Task 1.1에서 만든다. 이 Task에서는 `source`를 주입하므로 테스트는 통과한다. 단, import가 실패하지 않도록 **Task 1.1을 먼저 하거나**, 임시로 `fdr_source.py`에 `def fetch_ohlcv(*a, **k): raise NotImplementedError`만 만들어 두고 Task 1.1에서 채운다. (권장: Task 1.1을 먼저 수행)

- [ ] **Step 4: 통과 확인** — Run: `pytest tests/test_prices.py -v` → PASS

- [ ] **Step 5: 커밋** — `git add backend/adapters/prices.py tests/test_prices.py && git commit -m "feat: cache-first price adapter with injectable source"`

---

## Task 0.5: SQLite 초기화 `backend/adapters/db.py`
`[병렬: 가능 — Task 0.1 이후, 0.2/0.3과 동시 진행 가능]`

**Files:**
- Create: `backend/adapters/db.py`, `tests/test_db.py`

- [ ] **Step 1: 실패 테스트 `tests/test_db.py`**

```python
from backend.adapters.db import init_db, get_conn

def test_init_creates_tables(tmp_path):
    db = tmp_path / "t.db"
    init_db(str(db))
    conn = get_conn(str(db))
    names = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert {"signals", "watchlist", "backtest_results"} <= names
    conn.close()
```

- [ ] **Step 2: 실패 확인** — Run: `pytest tests/test_db.py -v` → FAIL

- [ ] **Step 3: 구현 `backend/adapters/db.py`**

```python
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS watchlist (
    code TEXT PRIMARY KEY, name TEXT, added_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT, action TEXT, confidence INTEGER, reasons TEXT,
    advice INTEGER DEFAULT 0, created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS backtest_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy TEXT, trades INTEGER, win_rate REAL, payoff REAL,
    max_drawdown REAL, passed INTEGER, created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""

def get_conn(db_path: str) -> sqlite3.Connection:
    return sqlite3.connect(db_path)

def init_db(db_path: str) -> None:
    conn = get_conn(db_path)
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()
```

- [ ] **Step 4: 통과 확인** — Run: `pytest tests/test_db.py -v` → PASS

- [ ] **Step 5: 커밋** — `git add backend/adapters/db.py tests/test_db.py && git commit -m "feat: sqlite schema (signals, watchlist, backtest_results)"`

---

# 슬라이스 S1 — MVP (KIS 불필요 · EOD)

## Task 1.1: FDR 소스 래퍼 `backend/ingest/fdr_source.py`
`[병렬: 불가 — Task 0.4보다 먼저(또는 동시) 권장]`

**Files:**
- Create: `backend/ingest/fdr_source.py`, `tests/test_fdr_source.py`

- [ ] **Step 1: 실패 테스트 `tests/test_fdr_source.py`** (네트워크 없이 호출 규약만 검증)

```python
import pandas as pd
import backend.ingest.fdr_source as src

def test_fetch_ohlcv_normalizes_columns(monkeypatch):
    raw = pd.DataFrame(
        {"Open": [1], "High": [2], "Low": [0.5], "Close": [1.5],
         "Volume": [100], "Change": [0.01]},
        index=pd.to_datetime(["2024-01-02"]))
    monkeypatch.setattr(src.fdr, "DataReader", lambda code, start, end: raw)

    out = src.fetch_ohlcv("005930", "2024-01-01", "2024-01-03")
    assert list(out.columns) == ["Open", "High", "Low", "Close", "Volume"]
    assert isinstance(out.index, pd.DatetimeIndex)
```

- [ ] **Step 2: 실패 확인** — Run: `pytest tests/test_fdr_source.py -v` → FAIL

- [ ] **Step 3: 구현 `backend/ingest/fdr_source.py`**

```python
import pandas as pd
import FinanceDataReader as fdr

OHLCV_COLS = ["Open", "High", "Low", "Close", "Volume"]

def fetch_ohlcv(code: str, start: str, end: str):
    """FinanceDataReader로 일봉을 받아 표준 컬럼만 반환한다."""
    df = fdr.DataReader(code, start, end)
    df = df[[c for c in OHLCV_COLS if c in df.columns]].copy()
    df.index = pd.to_datetime(df.index)
    return df
```
> 참고: 테스트는 `src.fdr.DataReader`를 monkeypatch하므로 모듈 경로(`backend.ingest.fdr_source.fdr`)가 유지되어야 한다.

- [ ] **Step 4: 통과 확인** — Run: `pytest tests/test_fdr_source.py -v` → PASS

- [ ] **Step 5: 커밋** — `git add backend/ingest/fdr_source.py tests/test_fdr_source.py && git commit -m "feat: FDR OHLCV source wrapper"`

---

## Task 1.2: 지표 엔진 `backend/analysis/indicators.py`
`[병렬: 가능 — Task 1.1 이후, 1.4(템플릿)와 동시 진행 가능]`

**Files:**
- Create: `backend/analysis/indicators.py`, `tests/test_indicators.py`

- [ ] **Step 1: 실패 테스트 `tests/test_indicators.py`**

```python
import numpy as np
import pandas as pd
from backend.analysis.indicators import add_indicators

def _trending_frame(n=120):
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    close = pd.Series(np.linspace(100, 200, n), index=idx)  # 우상향
    return pd.DataFrame({"Open": close, "High": close * 1.01,
                         "Low": close * 0.99, "Close": close,
                         "Volume": np.full(n, 1000)}, index=idx)

def test_adds_expected_columns():
    out = add_indicators(_trending_frame())
    for col in ["ma20", "ma60", "rsi14", "macd", "macd_signal"]:
        assert col in out.columns

def test_uptrend_has_high_rsi():
    out = add_indicators(_trending_frame())
    assert out["rsi14"].iloc[-1] > 60  # 꾸준한 상승 → 높은 RSI
```

- [ ] **Step 2: 실패 확인** — Run: `pytest tests/test_indicators.py -v` → FAIL

- [ ] **Step 3: 구현 `backend/analysis/indicators.py`**

```python
from ta.trend import SMAIndicator, MACD
from ta.momentum import RSIIndicator

def add_indicators(df):
    """OHLCV DataFrame에 지표 컬럼을 추가해 반환한다(원본 비파괴)."""
    out = df.copy()
    close = out["Close"]
    out["ma20"] = SMAIndicator(close=close, window=20).sma_indicator()
    out["ma60"] = SMAIndicator(close=close, window=60).sma_indicator()
    out["rsi14"] = RSIIndicator(close=close, window=14).rsi()
    macd = MACD(close=close)
    out["macd"] = macd.macd()
    out["macd_signal"] = macd.macd_signal()
    return out
```

- [ ] **Step 4: 통과 확인** — Run: `pytest tests/test_indicators.py -v` → PASS

- [ ] **Step 5: 커밋** — `git add backend/analysis/indicators.py tests/test_indicators.py && git commit -m "feat: ta-based indicator engine (MA/RSI/MACD)"`

---

## Task 1.3: 신호 규칙 `backend/signals/rules.py`
`[병렬: 불가 — Task 1.2 의존]`

**Files:**
- Create: `backend/signals/rules.py`, `tests/test_rules.py`

- [ ] **Step 1: 실패 테스트 `tests/test_rules.py`**

```python
import numpy as np
import pandas as pd
from backend.analysis.indicators import add_indicators
from backend.signals.rules import evaluate, Signal

def _golden_cross_frame():
    # 하락 후 급반등 → 단기선이 장기선을 상향 돌파하도록 구성
    idx = pd.date_range("2024-01-01", periods=120, freq="D")
    close = pd.concat([
        pd.Series(np.linspace(200, 100, 80)),
        pd.Series(np.linspace(100, 180, 40)),
    ], ignore_index=True)
    close.index = idx
    return pd.DataFrame({"Open": close, "High": close * 1.01,
                         "Low": close * 0.99, "Close": close,
                         "Volume": np.full(120, 1000)}, index=idx)

def test_evaluate_returns_signal_dataclass():
    df = add_indicators(_golden_cross_frame())
    sig = evaluate(df, "005930")
    assert isinstance(sig, Signal)
    assert sig.action in ("buy", "sell", "hold")
    assert 1 <= sig.confidence <= 5
    assert isinstance(sig.reasons, list)

def test_golden_cross_yields_buy():
    df = add_indicators(_golden_cross_frame())
    sig = evaluate(df, "005930")
    assert sig.action == "buy"
    assert any("골든크로스" in r for r in sig.reasons)
```

- [ ] **Step 2: 실패 확인** — Run: `pytest tests/test_rules.py -v` → FAIL

- [ ] **Step 3: 구현 `backend/signals/rules.py`**

```python
from dataclasses import dataclass, field

@dataclass
class Signal:
    code: str
    action: str               # "buy" | "sell" | "hold"
    confidence: int           # 1~5
    reasons: list[str] = field(default_factory=list)
    advice: bool = False      # 백테스트 게이트 통과 시 True (S2에서 설정)

def _crossed_up(short, long_, lookback: int = 5) -> bool:
    """최근 lookback 봉 안에서 단기선이 장기선을 상향 돌파(신선한 골든크로스)."""
    event = (short.shift(1) <= long_.shift(1)) & (short > long_)
    return bool(event.iloc[-lookback:].any())

def _crossed_down(short, long_, lookback: int = 5) -> bool:
    """최근 lookback 봉 안에서 단기선이 장기선을 하향 돌파(신선한 데드크로스)."""
    event = (short.shift(1) >= long_.shift(1)) & (short < long_)
    return bool(event.iloc[-lookback:].any())

def evaluate(df, code: str) -> Signal:
    """지표가 채워진 DataFrame을 받아 매매 신호를 산출한다."""
    buy, sell = [], []
    ma20, ma60, rsi = df["ma20"], df["ma60"], df["rsi14"]

    if _crossed_up(ma20, ma60):
        buy.append("20일선이 60일선을 상향 돌파(골든크로스)")
    if _crossed_down(ma20, ma60):
        sell.append("20일선이 60일선을 하향 돌파(데드크로스)")
    last_rsi = rsi.iloc[-1]
    if last_rsi < 30:
        buy.append(f"RSI {last_rsi:.0f} (과매도 — 반등 가능 참고)")
    if last_rsi > 70:
        sell.append(f"RSI {last_rsi:.0f} (과매수 — 과열 주의)")

    if len(buy) >= len(sell) and buy:
        action, reasons = "buy", buy
    elif sell:
        action, reasons = "sell", sell
    else:
        action, reasons = "hold", ["뚜렷한 신호 없음 — 관망"]

    confidence = max(1, min(5, len(reasons)))
    return Signal(code=code, action=action, confidence=confidence, reasons=reasons)
```

- [ ] **Step 4: 통과 확인** — Run: `pytest tests/test_rules.py -v` → PASS 의도

> ⚠️ **알려진 함정 (실행 시 확인할 것):** `test_golden_cross_yields_buy`의 합성 데이터(80봉 하락→40봉 급등)는 두 가지 이유로 **첫 실행에서 실패할 수 있다**: ① 골든크로스 이벤트가 마지막 봉이 아니라 상승 *중간*에 발생 → `lookback=5`로 못 잡을 수 있음. ② 40봉 연속 급등 → RSI14 > 70 → 과매수 *sell* 이유가 붙음. 이는 **버그가 아니라 출발 테스트가 다듬어져야 한다는 신호**다. 권장 대응(택1): (a) `_crossed_up`의 `lookback`을 키워 최근 크로스를 포착, **또는** (b) 합성 데이터를 *완만하고 최근에* 크로스가 마지막 봉 근처에서 일어나고 RSI가 70 미만에 머물도록 재구성, **또는** (c) "신선한 골든크로스"의 정의(이벤트 vs ma20>ma60 상태)를 의도에 맞게 확정. **이 신호가 앱의 핵심(매수)이므로 실행 시 trace로 직접 검증하고 확정할 것.**

- [ ] **Step 5: 커밋** — `git add backend/signals/rules.py tests/test_rules.py && git commit -m "feat: rule-based signal engine (golden/dead cross + RSI)"`

---

## Task 1.4: HTML 일일 리포트 `backend/report/render.py`
`[병렬: 가능 — Task 1.2와 동시(템플릿 작성은 독립). 렌더 테스트는 Signal 타입 필요 → Task 1.3 이후 통과]`

**Files:**
- Create: `backend/report/templates/daily.html.j2`, `backend/report/render.py`, `tests/test_render.py`

- [ ] **Step 1: 템플릿 `backend/report/templates/daily.html.j2`**

```html
<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Stock Master 일일 리포트 {{ date }}</title>
<style>
 body{font-family:-apple-system,"Apple SD Gothic Neo","Malgun Gothic",sans-serif;
   max-width:760px;margin:0 auto;padding:16px;color:#1a1a2e;background:#f7f8fb}
 h1{font-size:20px} .card{border:1px solid #e0e3eb;border-radius:12px;
   padding:14px;margin:12px 0;background:#fff}
 .buy{border-left:5px solid #1565c0} .sell{border-left:5px solid #c62828}
 .hold{border-left:5px solid #9e9e9e}
 .badge{font-size:12px;padding:2px 8px;border-radius:10px;color:#fff}
 .b-buy{background:#1565c0} .b-sell{background:#c62828} .b-hold{background:#9e9e9e}
 .disc{font-size:12px;color:#666;background:#fff3cd;border:1px solid #ffe69c;
   padding:10px;border-radius:8px;margin-top:16px}
 ul{margin:6px 0 0 0;padding-left:18px} li{font-size:14px}
</style></head><body>
<h1>📊 Stock Master 일일 리포트 <small>{{ date }}</small></h1>
{% for s in signals %}
<div class="card {{ s.action }}">
  <span class="badge b-{{ s.action }}">{{ s.action_ko }}</span>
  <strong>{{ s.code }}</strong> · 신뢰도 {{ "★" * s.confidence }}{{ "☆" * (5 - s.confidence) }}
  {% if s.advice %}<span class="badge b-buy">검증됨</span>{% endif %}
  <ul>{% for r in s.reasons %}<li>{{ r }}</li>{% endfor %}</ul>
</div>
{% endfor %}
<div class="disc">⚠️ 본 정보는 참고용이며 투자 판단과 책임은 본인에게 있습니다.
과거 성과는 미래 수익을 보장하지 않습니다.</div>
</body></html>
```

- [ ] **Step 2: 실패 테스트 `tests/test_render.py`**

```python
from pathlib import Path
from backend.signals.rules import Signal
from backend.report.render import render_daily_report

def test_render_writes_html_with_signals(tmp_path):
    sigs = [Signal(code="005930", action="buy", confidence=3,
                   reasons=["골든크로스"], advice=True)]
    out = tmp_path / "r.html"
    render_daily_report(sigs, "2026-06-19", out)
    html = out.read_text(encoding="utf-8")
    assert "005930" in html
    assert "골든크로스" in html
    assert "참고용" in html  # 고지문 포함
    assert "매수" in html    # action_ko 변환
```

- [ ] **Step 3: 실패 확인** — Run: `pytest tests/test_render.py -v` → FAIL

- [ ] **Step 4: 구현 `backend/report/render.py`**

```python
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, select_autoescape

_ACTION_KO = {"buy": "매수 관심", "sell": "매도 고려", "hold": "관망"}
_TEMPLATES = Path(__file__).parent / "templates"

def render_daily_report(signals, date: str, out_path) -> Path:
    env = Environment(loader=FileSystemLoader(str(_TEMPLATES)),
                      autoescape=select_autoescape(["html"]))
    tmpl = env.get_template("daily.html.j2")
    view = [{"code": s.code, "action": s.action,
             "action_ko": _ACTION_KO[s.action], "confidence": s.confidence,
             "reasons": s.reasons, "advice": s.advice} for s in signals]
    html = tmpl.render(signals=view, date=date)
    out = Path(out_path)
    out.write_text(html, encoding="utf-8")
    return out
```

- [ ] **Step 5: 통과 확인** — Run: `pytest tests/test_render.py -v` → PASS

- [ ] **Step 6: 커밋** — `git add backend/report tests/test_render.py && git commit -m "feat: Jinja2 daily HTML report"`

---

## Task 1.5: CLI 진입점 `backend/cli.py`
`[병렬: 불가 — Task 1.1~1.4 통합. S1 마지막]`

**Files:**
- Create: `backend/cli.py`, `tests/test_cli.py`

- [ ] **Step 1: 실패 테스트 `tests/test_cli.py`** (FDR 소스를 주입해 네트워크 차단)

```python
import numpy as np
import pandas as pd
from pathlib import Path
from backend.cli import generate_report

def _fake_source(code, start, end):
    idx = pd.date_range("2024-01-01", periods=120, freq="D")
    close = pd.Series(np.linspace(100, 180, 120), index=idx)
    return pd.DataFrame({"Open": close, "High": close*1.01, "Low": close*0.99,
                         "Close": close, "Volume": np.full(120, 1000)}, index=idx)

def test_generate_report_creates_file(tmp_path):
    out = tmp_path / "report.html"
    generate_report(codes=["005930", "000660"], out_path=out,
                    cache_dir=tmp_path, source=_fake_source)
    assert out.exists()
    html = out.read_text(encoding="utf-8")
    assert "005930" in html and "000660" in html
```

- [ ] **Step 2: 실패 확인** — Run: `pytest tests/test_cli.py -v` → FAIL

- [ ] **Step 3: 구현 `backend/cli.py`**

```python
import argparse
import datetime as dt
from pathlib import Path

from backend.config import settings
from backend.adapters.cache import OHLCVCache
from backend.adapters.prices import PriceAdapter
from backend.analysis.indicators import add_indicators
from backend.signals.rules import evaluate
from backend.report.render import render_daily_report

def generate_report(codes, out_path, cache_dir, source=None, history_days=400):
    adapter = PriceAdapter(OHLCVCache(cache_dir), source=source)
    end = dt.date.today()
    start = end - dt.timedelta(days=history_days)
    signals = []
    for code in codes:
        df = adapter.get_ohlcv(code, start.isoformat(), end.isoformat())
        df = add_indicators(df)
        signals.append(evaluate(df, code))
    return render_daily_report(signals, end.isoformat(), out_path)

def main():
    p = argparse.ArgumentParser(prog="stock-master")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("report", help="관심종목 일일 HTML 리포트 생성")
    args = p.parse_args()
    if args.cmd == "report":
        out = generate_report(settings.watchlist, "docs/report-daily.html",
                              settings.cache_dir, history_days=settings.history_days)
        print(f"리포트 생성: {out}")

if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 통과 확인** — Run: `pytest tests/test_cli.py -v` → PASS

- [ ] **Step 5: 실제 동작 확인(네트워크)** — Run: `python -m backend.cli report` → `docs/report-daily.html` 생성. 브라우저로 열어 관심종목 카드 확인.
> ⚠️ 실패 시: KRX 로그인/스크래퍼 이슈일 수 있음(설계 §7.3). FDR 버전(`pip show finance-datareader` ≥ 0.9.101) 확인.

- [ ] **Step 6: 커밋** — `git add backend/cli.py tests/test_cli.py && git commit -m "feat: CLI report command wires MVP pipeline end-to-end"`

> ✅ **S1 완료기준:** `python -m backend.cli report` 한 번에 관심종목 HTML 리포트가 생성된다.

---

# 슬라이스 S2 — 백테스트 게이트

## Task 2.1: 백테스트 엔진 `backend/analysis/backtest.py`
`[병렬: 가능 — Task 1.2 이후, 다른 S2 작업과 별개로 시작 가능]`

**Files:**
- Create: `backend/analysis/backtest.py`, `tests/test_backtest.py`

- [ ] **Step 1: 실패 테스트 `tests/test_backtest.py`**

```python
import numpy as np
import pandas as pd
from backend.analysis.indicators import add_indicators
from backend.analysis.backtest import backtest_strategy, BacktestResult

def _wavy_frame(n=300):
    idx = pd.date_range("2023-01-01", periods=n, freq="D")
    t = np.arange(n)
    close = pd.Series(150 + 40*np.sin(t/15.0), index=idx)  # 주기적 등락
    return pd.DataFrame({"Open": close, "High": close*1.01, "Low": close*0.99,
                         "Close": close, "Volume": np.full(n, 1000)}, index=idx)

def test_backtest_returns_result_with_metrics():
    df = add_indicators(_wavy_frame())
    res = backtest_strategy(df, "golden_cross")
    assert isinstance(res, BacktestResult)
    assert res.trades >= 0
    assert 0.0 <= res.win_rate <= 1.0
    assert isinstance(res.passed, bool)

def test_zero_trades_does_not_pass():
    df = add_indicators(_wavy_frame())
    # 신호가 절대 안 나는 전략 키 → trades 0 → passed False
    res = backtest_strategy(df, "never")
    assert res.trades == 0
    assert res.passed is False
```

- [ ] **Step 2: 실패 확인** — Run: `pytest tests/test_backtest.py -v` → FAIL

- [ ] **Step 3: 구현 `backend/analysis/backtest.py`**

```python
from dataclasses import dataclass

@dataclass
class BacktestResult:
    strategy: str
    trades: int
    win_rate: float
    payoff: float          # 평균이익/평균손실
    max_drawdown: float    # 0~1
    passed: bool

def _entry_signals(df, strategy: str):
    """전략별 매수 진입 시점(불리언 시리즈)을 반환."""
    if strategy == "golden_cross":
        s, l = df["ma20"], df["ma60"]
        return (s.shift(1) <= l.shift(1)) & (s > l)
    if strategy == "rsi_oversold":
        return df["rsi14"] < 30
    return df["Close"] < 0  # "never": 항상 False

def backtest_strategy(df, strategy: str, hold_days: int = 10,
                      min_trades: int = 5, min_win_rate: float = 0.5) -> BacktestResult:
    """진입 후 hold_days 뒤 종가로 청산하는 단순 백테스트."""
    entries = _entry_signals(df, strategy).fillna(False)
    close = df["Close"].reset_index(drop=True)
    rets = []
    idxs = [i for i, v in enumerate(entries.values) if v]
    for i in idxs:
        j = i + hold_days
        if j < len(close):
            rets.append((close[j] - close[i]) / close[i])
    trades = len(rets)
    if trades == 0:
        return BacktestResult(strategy, 0, 0.0, 0.0, 0.0, passed=False)
    wins = [r for r in rets if r > 0]
    losses = [-r for r in rets if r < 0]
    win_rate = len(wins) / trades
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 1e-9
    payoff = avg_win / avg_loss if avg_loss else 0.0
    # 단순 자본곡선 MDD
    equity, peak, mdd = 1.0, 1.0, 0.0
    for r in rets:
        equity *= (1 + r); peak = max(peak, equity)
        mdd = max(mdd, (peak - equity) / peak)
    passed = trades >= min_trades and win_rate >= min_win_rate
    return BacktestResult(strategy, trades, win_rate, payoff, mdd, passed)
```
- [ ] **Step 4: 통과 확인** — Run: `pytest tests/test_backtest.py -v` → PASS

- [ ] **Step 5: 커밋** — `git add backend/analysis/backtest.py tests/test_backtest.py && git commit -m "feat: simple backtest engine with pass/fail gate metrics"`

---

## Task 2.2: 조언 게이트 `backend/signals/rules.py` 확장
`[병렬: 불가 — Task 2.1 + 1.3 의존]`

**Files:**
- Modify: `backend/signals/rules.py` (evaluate에 백테스트 게이트 적용)
- Create: `tests/test_gate.py`

- [ ] **Step 1: 실패 테스트 `tests/test_gate.py`**

```python
import numpy as np
import pandas as pd
from backend.analysis.indicators import add_indicators
from backend.signals.rules import evaluate_with_gate

def _frame(n=300):
    idx = pd.date_range("2023-01-01", periods=n, freq="D")
    t = np.arange(n)
    close = pd.Series(150 + 40*np.sin(t/15.0), index=idx)
    return pd.DataFrame({"Open": close, "High": close*1.01, "Low": close*0.99,
                         "Close": close, "Volume": np.full(n, 1000)}, index=idx)

def test_advice_only_when_backtest_passes():
    df = add_indicators(_frame())
    sig = evaluate_with_gate(df, "005930")
    # buy 신호이면서 백테스트 통과해야만 advice=True
    if sig.action == "buy":
        assert sig.advice == sig._backtest_passed
    else:
        assert sig.advice is False
```

- [ ] **Step 2: 실패 확인** — Run: `pytest tests/test_gate.py -v` → FAIL

- [ ] **Step 3: 구현 — `backend/signals/rules.py`에 추가**

```python
from backend.analysis.backtest import backtest_strategy

# 신호 이유 문구 → 검증할 전략 키 매핑
_REASON_TO_STRATEGY = {"골든크로스": "golden_cross", "과매도": "rsi_oversold"}

def evaluate_with_gate(df, code: str):
    """evaluate() 결과에 백테스트 게이트를 적용. 통과 시에만 advice=True."""
    sig = evaluate(df, code)
    passed = False
    if sig.action == "buy":
        for reason in sig.reasons:
            for key, strat in _REASON_TO_STRATEGY.items():
                if key in reason and backtest_strategy(df, strat).passed:
                    passed = True
    sig.advice = passed
    sig._backtest_passed = passed  # 테스트 가시성용
    return sig
```
> `Signal` 데이터클래스에 `_backtest_passed: bool = False` 필드를 추가한다(Task 1.3 정의 확장). 필드명·시그니처를 1.3과 일치시킬 것.

- [ ] **Step 4: 통과 확인** — Run: `pytest tests/test_gate.py tests/test_rules.py -v` → PASS (기존 1.3 테스트도 깨지지 않아야 함)

- [ ] **Step 5: 커밋** — `git add backend/signals/rules.py tests/test_gate.py && git commit -m "feat: backtest gate — advice only for validated buy signals"`

---

## Task 2.3: CLI/리포트에 게이트 연결
`[병렬: 불가 — Task 2.2 의존. S2 마지막]`

**Files:**
- Modify: `backend/cli.py` (`evaluate` → `evaluate_with_gate`)

- [ ] **Step 1: `backend/cli.py` 수정** — import와 호출 교체:

```python
from backend.signals.rules import evaluate_with_gate
# ...
        signals.append(evaluate_with_gate(df, code))
```

- [ ] **Step 2: 회귀 테스트** — Run: `pytest -q` (전체) → 모두 PASS

- [ ] **Step 3: 실제 동작** — Run: `python -m backend.cli report` → 리포트에서 "검증됨" 배지가 백테스트 통과 매수신호에만 붙는지 확인.

- [ ] **Step 4: 커밋** — `git add backend/cli.py && git commit -m "feat: wire backtest gate into report pipeline"`

> ✅ **S2 완료기준:** 매수 신호는 백테스트를 통과했을 때만 "조언(검증됨)"으로 리포트에 노출된다.

---

# 자체 검수 (Self-Review)

- **스펙 커버리지(설계 §13 S0~S2):** S0(0.1~0.5: 스캐폴드·설정·캐시·어댑터·DB) ✅ / S1(1.1~1.5: FDR·지표·신호·리포트·CLI) ✅ / S2(2.1~2.3: 백테스트·게이트·연결) ✅. 설계 §16 고지문은 리포트 템플릿(1.4)에 포함 ✅.
- **플레이스홀더:** 모든 step에 실제 코드/명령 포함. "적절히 처리" 류 없음.
- **타입 일관성:** `Signal`(code/action/confidence/reasons/advice/_backtest_passed), `BacktestResult`(strategy/trades/win_rate/payoff/max_drawdown/passed), `PriceAdapter.get_ohlcv(code,start,end,force)`, `add_indicators(df)`, `evaluate(df,code)`/`evaluate_with_gate(df,code)`, `render_daily_report(signals,date,out_path)`, `generate_report(codes,out_path,cache_dir,source,history_days)` — Task 간 시그니처 일치 확인.
- **알려진 보완점:** Task 0.4가 Task 1.1 산출물을 import → 실행 순서는 **1.1 → 0.4** 권장(또는 0.4에서 임시 스텁). 본 계획 실행 시 이 순서를 지킬 것.

---

# 후속 계획 (S3~S6 개요 — 각자 별도 계획서로 확장)

> 아래는 MVP 검증 후 **각 슬라이스를 본 계획서처럼 TDD 작업 단위로 확장**할 대상이다. (KIS 키 발급 완료 가정)

### S3 — 뉴스/이슈 레이어 `[슬라이스 내부 ⫽ 병렬]`
- `[⫽]` `backend/ingest/rss_source.py` — feedparser로 한경 등 RSS 수집(제목/요약/링크/시각만)
- `[⫽]` `backend/ingest/dart_source.py` — DART 공시 수집(Python 3.13 / OpenDartReader 또는 REST)
- `[⫽]` (선택) `backend/ingest/naver_search.py` — 네이버 검색 API(키워드)
- `backend/news/match.py` — 뉴스↔종목 매핑·호재/악재 태깅 → 리포트 뉴스 섹션
- 완료기준: 리포트에 종목별 최신 뉴스·공시가 붙는다.

### S4 — 시장 스캐너
- `backend/scanner/scan.py` — KIS 순위 API(등락률/거래량 Top30) 또는 FDR EOD로 이슈종목 선별 → 파이프라인 투입
- 완료기준: 관심종목 외 "오늘의 추천" 후보 자동 생성.

### S5 — 실시간 (KIS 웹소켓)
- `backend/realtime/kis_auth.py` — OAuth 토큰/approval_key 발급·캐시
- `backend/realtime/ws_hub.py` — 웹소켓 허브(관심종목 ~10~20, 체결/호가)
- `backend/realtime/live_signals.py` — 장중 신호 평가 → 알림 트리거
- 완료기준: 장중 신호 발생 시 푸시 도착.

### S6 — PWA 프론트 + 교육 + 알림 `[슬라이스 내부 ⫽ 병렬]`
- `[⫽]` `frontend/` — PWA(manifest, service worker), Lightweight Charts 차트 화면
- `[⫽]` 추천/리포트 화면
- `[⫽]` `backend/education/` — 용어집/교육 콘텐츠(설계 §17 데이터)
- `[⫽]` `backend/api/push.py` — pywebpush(VAPID) 웹푸시
- `backend/api/app.py` — FastAPI REST+WS+정적 서빙 통합
- 완료기준: 아이폰 홈화면 아이콘으로 실시간 화면·알림 사용.

---

## 실행 방법 (Execution Handoff)

**옵션 1 — 서브에이전트 구동 (권장):** Task별 신선한 서브에이전트 + 단계 간 리뷰. `superpowers:subagent-driven-development` 사용.
**옵션 2 — 인라인 실행:** 현재 세션에서 체크포인트 단위 배치 실행. `superpowers:executing-plans` 사용.

병렬 그룹 안내: S0의 `{0.2, 0.3, 0.5}`, S1의 `{1.2, 1.4-템플릿}`, S3·S6의 `[⫽]` 표시 작업은 독립 워크트리/에이전트로 동시 진행 가능.
