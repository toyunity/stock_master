package com.toyunity.stockmaster.widget

import android.content.Context
import androidx.glance.GlanceId
import androidx.glance.action.ActionParameters
import androidx.glance.appwidget.action.ActionCallback

/** ↻ 탭 — 10초 디바운스 뒤 즉시 작업(expedited). 위젯 숫자는 수 초 안에 바뀐다. */
class RefreshAction : ActionCallback {
    override suspend fun onAction(context: Context, glanceId: GlanceId, parameters: ActionParameters) {
        val prefs = Prefs(context)
        val now = System.currentTimeMillis()
        if (!RefreshPolicy.manualAllowed(prefs.lastManualAt, now)) return
        prefs.lastManualAt = now
        Scheduler.refreshNow(context)
    }
}
