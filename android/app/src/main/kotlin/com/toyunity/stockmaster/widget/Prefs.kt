package com.toyunity.stockmaster.widget

import android.content.Context
import android.content.SharedPreferences

/**
 * 앱 전용 SharedPreferences — 토큰의 유일한 저장소. allowBackup=false(매니페스트)라 기기 밖으로 안 나간다.
 * EncryptedSharedPreferences는 deprecated(2024~)이고 샌드박스+기기 암호화로 충분(스펙 §보안).
 */
class Prefs(context: Context) {
    private val sp: SharedPreferences = context.getSharedPreferences("sm_widget", Context.MODE_PRIVATE)

    var baseUrl: String?
        get() = sp.getString("base_url", null)?.trimEnd('/')
        set(v) { sp.edit().putString("base_url", v?.trim()?.trimEnd('/')).apply() }

    var token: String?
        get() = sp.getString("token", null)
        set(v) { sp.edit().putString("token", v?.trim()).apply() }

    /** 마지막으로 성공 수신한 /api/widget 본문(오프라인 렌더용). */
    var lastJson: String?
        get() = sp.getString("last_json", null)
        set(v) { sp.edit().putString("last_json", v).apply() }

    var lastOkAt: Long
        get() = sp.getLong("last_ok_at", 0L)
        set(v) { sp.edit().putLong("last_ok_at", v).apply() }

    /** OK | OFFLINE | UNAUTHORIZED | UNCONFIGURED — 위젯이 어떤 얼굴을 할지 결정. */
    var lastStatus: String
        get() = sp.getString("last_status", UNCONFIGURED) ?: UNCONFIGURED
        set(v) { sp.edit().putString("last_status", v).apply() }

    var lastManualAt: Long
        get() = sp.getLong("last_manual_at", 0L)
        set(v) { sp.edit().putLong("last_manual_at", v).apply() }

    val configured: Boolean get() = !baseUrl.isNullOrBlank() && !token.isNullOrBlank()

    companion object {
        const val OK = "ok"
        const val OFFLINE = "offline"
        const val UNAUTHORIZED = "unauthorized"
        const val UNCONFIGURED = "unconfigured"
    }
}
