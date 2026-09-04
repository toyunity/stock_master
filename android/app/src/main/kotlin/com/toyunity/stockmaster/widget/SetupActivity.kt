package com.toyunity.stockmaster.widget

import android.app.Activity
import android.appwidget.AppWidgetManager
import android.content.ComponentName
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.provider.Settings
import android.widget.Button
import android.widget.EditText
import android.widget.TextView

/**
 * 설정 화면 하나(Views — Compose UI는 APK +2MB라 기각, 스펙 §기각한 대안).
 * 진입: 런처 아이콘 · 위젯의 미설정/401 탭 · 딥링크 stockmaster://setup?base=…&token=…(/widget-setup 페이지 버튼).
 */
class SetupActivity : Activity() {
    private lateinit var prefs: Prefs
    private lateinit var baseField: EditText
    private lateinit var tokenField: EditText
    private lateinit var status: TextView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_setup)
        prefs = Prefs(this)
        baseField = findViewById(R.id.base_url)
        tokenField = findViewById(R.id.token)
        status = findViewById(R.id.status)
        baseField.setText(prefs.baseUrl ?: "")
        tokenField.setText(prefs.token ?: "")
        findViewById<Button>(R.id.save).setOnClickListener { saveAndTest() }
        findViewById<Button>(R.id.pin).setOnClickListener { requestPin() }
        findViewById<Button>(R.id.battery).setOnClickListener { openBatteryDialog() }
        // 재생성(폴드 접기/펼치기 = 구성 변경) 때 getIntent()가 원래 딥링크를 돌려줘 입력을 덮어쓰고
        // refreshNow 를 반복하던 결함(리뷰 2026-09-04) — 최초 생성에만 처리한다.
        if (savedInstanceState == null) handleDeepLink(intent)
    }

    override fun onNewIntent(intent: Intent) {   // singleTop — 열려 있는 동안 딥링크가 오면 여기로
        super.onNewIntent(intent)
        setIntent(intent)   // 재생성 시 최신 인텐트가 남도록
        handleDeepLink(intent)
    }

    /** https 주소만 받는다. 채운 뒤 곧바로 저장·연결 확인(초보 최대 실패 지점 = 토큰 옮기기 → 탭 한 번). */
    private fun handleDeepLink(i: Intent?) {
        val u = i?.data ?: return
        if (u.scheme != "stockmaster" || u.host != "setup") return
        val base = u.getQueryParameter("base") ?: return
        val token = u.getQueryParameter("token") ?: return
        if (!base.startsWith("https://")) { status.text = "https 주소만 허용해요"; return }
        baseField.setText(base)
        tokenField.setText(token)
        saveAndTest()
    }

    private fun saveAndTest() {
        val base = baseField.text.toString().trim().trimEnd('/')
        val token = tokenField.text.toString().trim()
        if (!base.startsWith("https://") || token.length < 20) {   // 서버도 20자 미만 토큰을 거부한다(fail-closed)
            status.text = "https 주소와 20자 이상 토큰이 필요해요"
            return
        }
        prefs.baseUrl = base
        prefs.token = token
        status.text = "연결 확인 중…"
        Thread {
            val r = WidgetApi.fetch(base, token)
            val msg = when (r) {
                is ApiResult.Ok -> {
                    val n = runCatching { WidgetJson.parse(r.body).items.size }.getOrNull()
                    if (n != null) "연결 OK · ${n}종목 — 이제 [홈 위젯 추가]" else "응답을 읽을 수 없어요 — 주소를 확인하세요"
                }
                ApiResult.Unauthorized -> "토큰이 맞지 않아요 — /widget-setup 에서 다시 복사하세요"
                is ApiResult.Failure -> if (r.reason == "http 503") "서버가 위젯을 끄거나 시세를 못 가져와요"
                                        else "서버(맥북)에 연결할 수 없어요 — 맥이 깨어 있는지 확인"
            }
            runOnUiThread { status.text = msg }
            Scheduler.refreshNow(this)                     // 위젯도 곧바로 갱신(UNAUTHORIZED 등 상태 전파)
        }.start()
    }

    /** One UI 확인 대화상자로 홈에 위젯을 놓는다. 커버·메인 각각 한 번. 미지원 런처면 수동 경로 안내. */
    private fun requestPin() {
        val m = AppWidgetManager.getInstance(this)
        if (m.isRequestPinAppWidgetSupported) {
            m.requestPinAppWidget(ComponentName(this, StockWidgetReceiver::class.java), null, null)
        } else {
            status.text = "홈 화면을 길게 눌러 위젯 → Stock Master 위젯을 추가하세요"
        }
    }

    /** 안드로이드 표준 배터리 최적화 제외 대화상자(1탭). 삼성 '절전 예외 앱'은 별도(공개 인텐트 없음 → 도움말). */
    private fun openBatteryDialog() {
        startActivity(Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, Uri.parse("package:$packageName")))
    }
}
