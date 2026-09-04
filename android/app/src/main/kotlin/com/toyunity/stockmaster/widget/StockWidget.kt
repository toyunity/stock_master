package com.toyunity.stockmaster.widget

import android.content.Context
import androidx.glance.GlanceId
import androidx.glance.appwidget.GlanceAppWidget
import androidx.glance.appwidget.provideContent
import androidx.glance.text.Text

/** T1 스텁 — 매니페스트·빌드 검증용. T4에서 실물로 교체한다. */
class StockWidget : GlanceAppWidget() {
    override suspend fun provideGlance(context: Context, id: GlanceId) {
        provideContent { Text("Stock Master") }
    }
}
