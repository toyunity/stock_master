from __future__ import annotations

"""PWA 아이콘 생성 + manifest.

iOS 홈화면 아이콘은 manifest가 아니라 apple-touch-icon(180px PNG)이 결정한다.
Pillow는 컬러 이모지를 못 그리므로(빈 네모) 브랜드색 사각형에 'SM' 텍스트만 그린다.
iOS가 모서리를 알아서 둥글게 처리하므로 둥근 처리는 생략. 인메모리 캐시(요청마다 재생성 X)."""

import io

from PIL import Image, ImageDraw, ImageFont

_BG = (21, 101, 192)   # #1565c0 브랜드 블루
_FG = (255, 255, 255)
_TEXT = "SM"
_SIZES = {180, 192, 512}  # 180=apple-touch, 192/512=manifest(android)

_cache: dict = {}

MANIFEST = {
    "name": "Stock Master",
    "short_name": "StockMaster",
    "start_url": "/",
    "display": "standalone",
    "background_color": "#f7f8fb",
    "theme_color": "#1565c0",
    "icons": [
        {"src": "/icons/icon-192.png", "sizes": "192x192", "type": "image/png"},
        {"src": "/icons/icon-512.png", "sizes": "512x512", "type": "image/png"},
    ],
}

_FONT_PATHS = [
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/Library/Fonts/Arial.ttf",
]


def _load_font(px: int):
    for path in _FONT_PATHS:
        try:
            return ImageFont.truetype(path, px)
        except OSError:
            continue
    return ImageFont.load_default()


def _render_icon(size: int) -> bytes:
    img = Image.new("RGB", (size, size), _BG)
    d = ImageDraw.Draw(img)
    font = _load_font(int(size * 0.42))
    bbox = d.textbbox((0, 0), _TEXT, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    d.text(((size - tw) / 2 - bbox[0], (size - th) / 2 - bbox[1]),
           _TEXT, font=font, fill=_FG)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def get_icon(name: str):
    """'icon-180.png' 형태의 이름 → PNG 바이트(캐시). 모르는 크기면 None."""
    digits = "".join(c for c in name if c.isdigit())
    if not digits:
        return None
    size = int(digits)
    if size not in _SIZES:
        return None
    if size not in _cache:
        _cache[size] = _render_icon(size)
    return _cache[size]
