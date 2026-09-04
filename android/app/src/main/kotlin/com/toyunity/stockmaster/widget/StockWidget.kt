package com.toyunity.stockmaster.widget

import android.content.Context
import android.content.Intent
import android.net.Uri
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.DpSize
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.glance.GlanceId
import androidx.glance.GlanceModifier
import androidx.glance.GlanceTheme
import androidx.glance.LocalContext
import androidx.glance.LocalSize
import androidx.glance.action.Action
import androidx.glance.action.clickable
import androidx.glance.appwidget.GlanceAppWidget
import androidx.glance.appwidget.SizeMode
import androidx.glance.appwidget.action.actionRunCallback
import androidx.glance.appwidget.action.actionStartActivity
import androidx.glance.appwidget.appWidgetBackground
import androidx.glance.appwidget.cornerRadius
import androidx.glance.appwidget.provideContent
import androidx.glance.background
import androidx.glance.color.ColorProvider
import androidx.glance.layout.Alignment
import androidx.glance.layout.Box
import androidx.glance.layout.Column
import androidx.glance.layout.Row
import androidx.glance.layout.Spacer
import androidx.glance.layout.fillMaxSize
import androidx.glance.layout.fillMaxWidth
import androidx.glance.layout.height
import androidx.glance.layout.padding
import androidx.glance.text.FontWeight
import androidx.glance.text.Text
import androidx.glance.text.TextStyle

/** Prefs → 위젯이 그릴 상태. 마지막 JSON은 여기서 파싱(실패 시 data=null → 연결 실패 얼굴). */
data class WidgetState(val status: String, val data: WidgetData?) {
    companion object {
        fun load(prefs: Prefs): WidgetState {
            val data = prefs.lastJson?.let { runCatching { WidgetJson.parse(it) }.getOrNull() }
            return WidgetState(prefs.lastStatus, data)
        }
    }
}

/**
 * 텍스트 전용 Glance 위젯. 정보·순서·문자는 아이폰 위젯과 동일(스펙 §화면 설계).
 * Responsive 버킷: 런처가 들어맞는 최대 버킷을 고르고 LocalSize가 그 값 — 행 수는 높이 예산에서 계산한다.
 * 커버(≈380×170dp)·메인(≈400×160dp) 4×2와 세로 4×4가 목표. 실측 dp는 실기기에서 확인해 아래 주석에 남긴다.
 */
class StockWidget : GlanceAppWidget() {
    override val sizeMode: SizeMode = SizeMode.Responsive(
        setOf(DpSize(250.dp, 110.dp), DpSize(300.dp, 150.dp), DpSize(300.dp, 300.dp),
              DpSize(450.dp, 150.dp), DpSize(450.dp, 300.dp)))

    override suspend fun provideGlance(context: Context, id: GlanceId) {
        val prefs = Prefs(context)
        val state = WidgetState.load(prefs)
        val baseUrl = prefs.baseUrl
        provideContent { GlanceTheme { Content(state, baseUrl) } }
    }
}

private val PAD_V = 9      // dp — 위·아래 패딩(아이폰 setPadding(9,12,9,12)와 동일)
private val HEADER_DP = 22
private val TOTAL_DP = 20
private val MORE_DP = 14

@Composable
private fun Content(state: WidgetState, baseUrl: String?) {
    val ctx = LocalContext.current
    val size = LocalSize.current
    val wide = size.width >= 400.dp                       // 메인 화면 넓은 버킷 → 수익률 열 추가
    val setup: Action = actionStartActivity(Intent(ctx, SetupActivity::class.java))
    // 몸통 탭: PWA(base URL). 미설정이면 설정 화면.
    val body: Action = if (!baseUrl.isNullOrBlank())
        actionStartActivity(Intent(Intent.ACTION_VIEW, Uri.parse(baseUrl))) else setup

    Column(
        modifier = GlanceModifier.fillMaxSize().appWidgetBackground()
            .background(GlanceTheme.colors.widgetBackground).cornerRadius(16.dp)
            .padding(horizontal = 12.dp, vertical = PAD_V.dp)
            .clickable(body)
    ) {
        when {
            state.status == Prefs.UNCONFIGURED -> Message("설정이 필요해요", "탭해서 서버 주소와 토큰을 입력하세요", setup)
            state.status == Prefs.UNAUTHORIZED -> Message("토큰이 맞지 않아요", "탭해서 다시 설정하세요 — /widget-setup 에서 토큰 복사", setup)
            state.data == null -> Message("서버에 연결할 수 없어요", "↻ 갱신을 탭해 다시 시도하세요", actionRunCallback<RefreshAction>())
            else -> Board(state.data, offline = state.status == Prefs.OFFLINE, wide = wide,
                          heightDp = size.height.value.toInt())
        }
    }
}

@Composable
private fun Message(title: String, sub: String, action: Action) {
    Column(modifier = GlanceModifier.fillMaxWidth().clickable(action)) {
        Text(title, style = TextStyle(color = GlanceTheme.colors.onSurface, fontSize = 13.sp, fontWeight = FontWeight.Bold))
        Spacer(GlanceModifier.height(4.dp))
        Text(sub, style = TextStyle(color = Colors.FLAT, fontSize = 11.sp), maxLines = 2)
    }
}

@Composable
private fun Board(d: WidgetData, offline: Boolean, wide: Boolean, heightDp: Int) {
    // 헤더: 관심종목 · HH:MM 갱신 · 장중/마감 (· 오프라인) ………… ↻ 갱신
    Row(modifier = GlanceModifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        Text("관심종목", style = TextStyle(color = GlanceTheme.colors.onSurface, fontSize = 12.sp, fontWeight = FontWeight.Bold))
        Text("  " + (if (offline) "오프라인·" else "") + Format.status(d),
             style = TextStyle(color = if (offline) Colors.WARN else Colors.FLAT, fontSize = 9.sp), maxLines = 1,
             modifier = GlanceModifier.defaultWeight())
        // ↻ 즉시 갱신 — iOS에선 불가능했던 부분. 자식 clickable이 몸통 탭보다 우선한다.
        Text("↻ 갱신", style = TextStyle(color = Colors.FLAT, fontSize = 10.sp, fontWeight = FontWeight.Bold),
             modifier = GlanceModifier.clickable(actionRunCallback<RefreshAction>()))
    }
    Spacer(GlanceModifier.height(3.dp))

    // 통화별 합계(보유가 있을 때만)
    val totals = Format.totals(d.items)
    for (t in totals) {
        Row(modifier = GlanceModifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Text("합계 " + Format.value(t.value, t.currency),
                 style = TextStyle(color = GlanceTheme.colors.onSurface, fontSize = 12.sp, fontWeight = FontWeight.Bold),
                 maxLines = 1, modifier = GlanceModifier.defaultWeight())
            Text(Format.pnlArrow(t.pnl, t.currency) + " (" + Format.change(t.pct) + ")",
                 style = TextStyle(color = pnlColor(t.pnl), fontSize = 11.sp), maxLines = 1)
        }
    }
    if (totals.isNotEmpty()) Divider()

    // 세로 예산 → 행 수(고정 개수 금지). +N 줄은 필요할 때만 예산에서 뺀다.
    val n = d.items.size
    val budget = heightDp - PAD_V * 2 - HEADER_DP - TOTAL_DP * totals.size - (if (totals.isNotEmpty()) 5 else 0)
    var plan = Format.planCapacity(n, budget - MORE_DP)
    if (plan.more == 0) plan = Format.planCapacity(n, budget)
    for (i in 0 until plan.drawn) {
        if (i > 0) Divider()
        ItemRow(d.items[i], wide)
    }
    if (plan.more > 0) {
        Text("+${plan.more}종목", style = TextStyle(color = Colors.FLAT, fontSize = 9.sp))   // 실제 그린 개수 기준
    }
}

@Composable
private fun ItemRow(it: WidgetItem, wide: Boolean) {
    val label = if (it.market == "US" && it.name.isNotEmpty() && it.name != it.code) "${it.code} ${it.name}" else it.name
    Row(modifier = GlanceModifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        Text(label, style = TextStyle(color = GlanceTheme.colors.onSurface, fontSize = 13.sp, fontWeight = FontWeight.Bold),
             maxLines = 1, modifier = GlanceModifier.defaultWeight())
        Text(Format.money(it.price, it.currency),
             style = TextStyle(color = GlanceTheme.colors.onSurface, fontSize = 13.sp, fontWeight = FontWeight.Bold))
        Text(" " + Format.change(it.change),
             style = TextStyle(color = chgColor(it.change), fontSize = 11.sp, fontWeight = FontWeight.Bold))
        if (it.held) {
            Text(if (wide) "  수익 " else "  ", style = TextStyle(color = Colors.FLAT, fontSize = 10.sp))
            Text(Format.pnlArrow(it.pnl, it.currency),
                 style = TextStyle(color = pnlColor(it.pnl), fontSize = 11.sp, fontWeight = FontWeight.Bold), maxLines = 1)
            if (wide) Text(" (" + Format.change(it.pnlPct) + ")",
                           style = TextStyle(color = pnlColor(it.pnl), fontSize = 10.sp), maxLines = 1)
        }
    }
}

@Composable
private fun Divider() {
    Spacer(GlanceModifier.height(2.dp))
    Box(modifier = GlanceModifier.fillMaxWidth().height(1.dp)
            .background(ColorProvider(Color(0x1F000000), Color(0x29FFFFFF)))) {}   // 반투명 실선(아이폰 DIVIDER)
    Spacer(GlanceModifier.height(2.dp))
}

private fun chgColor(c: Double?): androidx.glance.unit.ColorProvider =
    if (c == null || c == 0.0) Colors.FLAT else if (c > 0) Colors.UP else Colors.DOWN

/** 수익도 등락과 같은 색규칙: 이익 빨강 / 손실 파랑 / 0·미값 회색. */
private fun pnlColor(v: Double?): androidx.glance.unit.ColorProvider =
    if (v == null || v == 0.0) Colors.FLAT else if (v > 0) Colors.UP else Colors.DOWN
