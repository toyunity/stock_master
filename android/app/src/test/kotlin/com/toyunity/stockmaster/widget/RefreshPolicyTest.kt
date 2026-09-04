package com.toyunity.stockmaster.widget

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** 스펙 §갱신 정책 표 — 성공 clamp(힌트, 15분, 6h) · 실패 15분 · 401 6h · ↻ 10초 디바운스. */
class RefreshPolicyTest {
    @Test fun success_clamps_server_hint() {
        assertEquals(900L, RefreshPolicy.nextDelaySec(Prefs.OK, 600))       // 미국장 10분 힌트 → 15분 하한
        assertEquals(900L, RefreshPolicy.nextDelaySec(Prefs.OK, 900))
        assertEquals(3600L, RefreshPolicy.nextDelaySec(Prefs.OK, 3600))
        assertEquals(21600L, RefreshPolicy.nextDelaySec(Prefs.OK, 99999))   // 6h 상한
        assertEquals(900L, RefreshPolicy.nextDelaySec(Prefs.OK, null))      // 힌트 없음 → 15분
    }

    @Test fun failure_retries_in_15_minutes() {
        assertEquals(900L, RefreshPolicy.nextDelaySec(Prefs.OFFLINE, 21600))
    }

    @Test fun unauthorized_backs_off_6_hours() {
        assertEquals(21600L, RefreshPolicy.nextDelaySec(Prefs.UNAUTHORIZED, 900))
    }

    @Test fun manual_refresh_debounces_10s() {
        assertFalse(RefreshPolicy.manualAllowed(lastManualAtMs = 100_000, nowMs = 105_000))
        assertTrue(RefreshPolicy.manualAllowed(lastManualAtMs = 100_000, nowMs = 110_000))
        assertTrue(RefreshPolicy.manualAllowed(lastManualAtMs = 0, nowMs = 5_000))   // 첫 탭
    }
}
