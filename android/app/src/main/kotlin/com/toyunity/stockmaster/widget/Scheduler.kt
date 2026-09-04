package com.toyunity.stockmaster.widget

import android.content.Context
import androidx.work.Constraints
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.OutOfQuotaPolicy
import androidx.work.WorkManager
import java.util.concurrent.TimeUnit

/** 스펙 §갱신 정책 표. 순수 함수 — JVM 테스트 대상. */
object RefreshPolicy {
    const val MIN_SEC = 900          // 15분 — WorkManager가 실질적으로 보장하는 최소 간격
    const val MAX_SEC = 21600        // 6h — 서버 힌트 상한과 동일
    const val AUTH_FAIL_SEC = 21600  // 401: 재설정 전까지 두드리지 않는다(재설정 저장이 즉시 작업을 넣는다)
    private const val MANUAL_DEBOUNCE_MS = 10_000L

    fun nextDelaySec(status: String, refreshAfterSec: Int?): Long = when (status) {
        Prefs.OK -> (refreshAfterSec ?: MIN_SEC).coerceIn(MIN_SEC, MAX_SEC).toLong()
        Prefs.UNAUTHORIZED -> AUTH_FAIL_SEC.toLong()
        else -> MIN_SEC.toLong()
    }

    /**
     * ↻ 탭 디바운스 — 10초 안에 재탭은 무시(KIS를 두드리지 않는다).
     * lastManualAtMs == 0 은 Prefs 기본값(한 번도 탭 안 함) → 첫 탭은 항상 허용(RefreshPolicyTest "첫 탭", 2026-09-04).
     */
    fun manualAllowed(lastManualAtMs: Long, nowMs: Long): Boolean =
        lastManualAtMs == 0L || nowMs - lastManualAtMs >= MANUAL_DEBOUNCE_MS
}

/** 이름 있는 1회성 작업 체인 하나("sm-refresh"). 주기 작업·알람·포그라운드 서비스 없음(배터리, 스펙 §갱신 정책). */
object Scheduler {
    const val WORK = "sm-refresh"
    private val online = Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()

    /**
     * 작업 완료 후 다음 예약. RefreshWorker 가 **실행 중에** 자기 이름으로 넣으므로 REPLACE 는 자기 자신을
     * 취소한다(실행이 CANCELLED 로 기록, T3 워커 발견 2026-09-04). APPEND_OR_REPLACE 는 지금 도는 작업의
     * 자식으로 붙어 그 성공 뒤에 초기 지연이 시작된다(lastEnqueueTime 이 선행 완료 시각). 완료 노드는
     * WorkManager 가 DB 열 때(=매 프로세스 기동) 주기적으로 정리한다. 실기기 확인: adb shell dumpsys jobscheduler.
     */
    fun scheduleNext(ctx: Context, delaySec: Long) {
        val req = OneTimeWorkRequestBuilder<RefreshWorker>()
            .setInitialDelay(delaySec, TimeUnit.SECONDS)
            .setConstraints(online)
            .build()
        WorkManager.getInstance(ctx).enqueueUniqueWork(WORK, ExistingWorkPolicy.APPEND_OR_REPLACE, req)
    }

    /** 위젯 추가·부팅·30분 백스톱(onUpdate) — 이미 예약된 작업이 있으면 그대로(KEEP). */
    fun ensureScheduled(ctx: Context) {
        val req = OneTimeWorkRequestBuilder<RefreshWorker>().setConstraints(online).build()
        WorkManager.getInstance(ctx).enqueueUniqueWork(WORK, ExistingWorkPolicy.KEEP, req)
    }

    /** ↻·설정 저장·딥링크 — 즉시(REPLACE, expedited; 지연 없음이 expedited의 조건). */
    fun refreshNow(ctx: Context) {
        val req = OneTimeWorkRequestBuilder<RefreshWorker>()
            .setConstraints(online)
            .setExpedited(OutOfQuotaPolicy.RUN_AS_NON_EXPEDITED_WORK_REQUEST)
            .build()
        WorkManager.getInstance(ctx).enqueueUniqueWork(WORK, ExistingWorkPolicy.REPLACE, req)
    }

    /** 마지막 위젯 제거 — 위젯이 없으면 네트워크 0. */
    fun cancel(ctx: Context) { WorkManager.getInstance(ctx).cancelUniqueWork(WORK) }
}
