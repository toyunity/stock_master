package com.toyunity.stockmaster.widget

import android.content.Context
import androidx.glance.appwidget.updateAll
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONException
import org.json.JSONObject

/**
 * 요청 1회 → Prefs 저장 → 모든 위젯 인스턴스(커버·메인) 갱신 → 다음 예약. 실패해도 Result.success():
 * WorkManager 재시도 백오프 대신 스펙 표의 고정 지연(15분)을 쓴다 — 서버 다운 때 두드리는 빈도가 예측 가능.
 */
class RefreshWorker(ctx: Context, params: WorkerParameters) : CoroutineWorker(ctx, params) {
    override suspend fun doWork(): Result = withContext(Dispatchers.IO) {
        val prefs = Prefs(applicationContext)
        val base = prefs.baseUrl
        val token = prefs.token
        if (base.isNullOrBlank() || token.isNullOrBlank()) {
            prefs.lastStatus = Prefs.UNCONFIGURED
            StockWidget().updateAll(applicationContext)
            return@withContext Result.success()          // 예약 없음 — 설정 저장이 refreshNow를 부른다
        }
        var hint: Int? = null
        when (val r = WidgetApi.fetch(base, token)) {
            is ApiResult.Ok -> {
                // 여기선 최소 형태(items 존재)와 갱신 힌트만 본다. 표시용 전체 파싱은 위젯(WidgetJson)이 한다.
                hint = try {
                    val o = JSONObject(r.body)
                    if (o.has("items")) o.optInt("refresh_after_sec", RefreshPolicy.MIN_SEC) else null
                } catch (e: JSONException) { null }
                if (hint != null) {
                    prefs.lastJson = r.body
                    prefs.lastOkAt = System.currentTimeMillis()
                    prefs.lastStatus = Prefs.OK
                } else {
                    prefs.lastStatus = Prefs.OFFLINE      // 200인데 items 없음 = 파싱 실패 → 마지막 값 유지
                }
            }
            ApiResult.Unauthorized -> prefs.lastStatus = Prefs.UNAUTHORIZED
            is ApiResult.Failure -> prefs.lastStatus = Prefs.OFFLINE
        }
        StockWidget().updateAll(applicationContext)
        Scheduler.scheduleNext(applicationContext, RefreshPolicy.nextDelaySec(prefs.lastStatus, hint))
        Result.success()
    }
}
