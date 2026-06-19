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
