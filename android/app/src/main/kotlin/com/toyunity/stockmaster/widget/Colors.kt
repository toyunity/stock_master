package com.toyunity.stockmaster.widget

import androidx.compose.ui.graphics.Color
import androidx.glance.color.ColorProvider

/**
 * backend/report/theme.py 토큰의 복사본(2026-09-04). 화면들의 CSS 단일 출처는 theme.py지만
 * 안드로이드는 CSS를 못 읽어 값을 복제한다 — tests/test_android_widget.py 가 theme.py와 대조해
 * 드리프트를 잡는다. 순서는 (라이트, 다크). 배경·본문색은 GlanceTheme(시스템 동적 색)을 쓴다.
 */
object Colors {
    val UP = ColorProvider(Color(0xFFE5342F), Color(0xFFFF5B52))     // --up   상승·이익
    val DOWN = ColorProvider(Color(0xFF1F66E0), Color(0xFF4F8BFF))   // --down 하락·손실
    val FLAT = ColorProvider(Color(0xFF8B93A4), Color(0xFF5F6879))   // --flat 보합·보조
    val WARN = ColorProvider(Color(0xFFDC8400), Color(0xFFF2A83A))   // --warn 오프라인 배지
    val DIVIDER = ColorProvider(Color(0x1F000000), Color(0x29FFFFFF))   // 반투명 구분선(아이폰 DIVIDER 0.12/0.16 — theme 토큰 아님)
}
