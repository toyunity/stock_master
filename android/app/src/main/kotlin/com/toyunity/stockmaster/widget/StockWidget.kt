package com.toyunity.stockmaster.widget

import android.content.Context
import android.content.Intent
import android.net.Uri
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
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
 * SizeMode.Exact: LocalSize = 런처가 준 실제 크기 — 행 수는 실제 높이 예산에서, 글자·행 크기는 실제 폭(k)에서 계산한다.
 * 2026-09-04 Fold 8 실측(Responsive 버킷 시절): 커버 4×3 ≈ 300×177dp 인데 300×150 버킷이 잡혀 아래 1/3이 비었고,
 * 메인 4×2 ≈ 600×160dp 인데 400×150 버킷이라 13sp 글자가 깨알이었다 → 버킷을 버리고 Exact 로.
 * 비용: glance-appwidget 1.2.0 SizeBox.ForEachSize — API 31+ 에선 Exact 도 OPTION_APPWIDGET_SIZES 목록(폴더블 ≤4개)마다
 * 1회 구성해 Responsive 와 같은 RemoteViews 크기맵에 담는다. 크기 변경마다 재구성하는 건 API 30 이하 얘기(minSdk 31).
 */
class StockWidget : GlanceAppWidget() {
    override val sizeMode: SizeMode = SizeMode.Exact

    override suspend fun provideGlance(context: Context, id: GlanceId) {
        val prefs = Prefs(context)
        val state = WidgetState.load(prefs)
        val baseUrl = prefs.baseUrl
        val textScale = prefs.textScale
        provideContent { GlanceTheme { Content(state, baseUrl, textScale) } }
    }
}

private val PAD_V = 9      // dp — 위·아래 패딩(아이폰 setPadding(9,12,9,12)와 동일)
// 아래 높이는 k=1(폭 330dp, 아이폰 위젯 폭) 기준 — 글자(sp)와 같이 k 배로 키운다. 구분선만 진짜 dp 라 고정.
private val HEADER_DP = 22
private val TOTAL_DP = 20
private val ROW_DP = 20
private val MORE_DP = 14
private val DIVIDER_DP = 5   // Divider() = 패딩 2 + 선 1 + 패딩 2
private val DESIGN_W = 330f  // 아이폰 4×2 위젯 폭(pt) — 이 폭에서 13sp 가 적정(마스터 2026-09-04: 메인 화면 600dp 에선 너무 작다)

/** 글자 크기 — 폭 비례 k(≤1.35) × 설정 배율(Prefs.textScale). 폭 상한 근거: 4×2(≈160dp)에서 1.5면 행 예산이 1행+'+N'으로
 *  줄어 다시 '삼성만 보임'처럼 보인다(계산: 142−33−30−5−21=53 < 30+5+30). 더 키우는 건 마스터가 설정에서 고른 값이라 행 수와 맞바꾼다. */
private fun fs(base: Int, k: Float) = (base * k).sp

@Composable
private fun Content(state: WidgetState, baseUrl: String?, textScale: Float) {
    val ctx = LocalContext.current
    val size = LocalSize.current
    val k = (size.width.value / DESIGN_W).coerceIn(1f, 1.35f) * textScale
    // 열은 '글자 크기로 나눈 유효 폭'으로 정한다 — 글자를 키우면 같은 폭에 덜 들어가므로 오른쪽 열부터 접는다.
    // 2 = 수량·손익·수익률 전부, 1 = 수량·손익, 0 = 손익만. 넘치면 weight 를 가진 이름이 먼저 줄어든다.
    val e = size.width.value / k
    val cols = if (e >= 400f) 2 else if (e >= 300f) 1 else 0
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
            state.status == Prefs.UNCONFIGURED -> Message("설정이 필요해요", "탭해서 서버 주소와 토큰을 입력하세요", setup, k)
            state.status == Prefs.UNAUTHORIZED -> Message("토큰이 맞지 않아요", "탭해서 다시 설정하세요 — /widget-setup 에서 토큰 복사", setup, k)
            state.data == null -> Message("서버에 연결할 수 없어요", "↻ 갱신을 탭해 다시 시도하세요", actionRunCallback<RefreshAction>(), k)
            else -> Board(state.data, offline = state.status == Prefs.OFFLINE, cols = cols,
                          heightDp = size.height.value.toInt(), k = k)
        }
    }
}

@Composable
private fun Message(title: String, sub: String, action: Action, k: Float) {
    Column(modifier = GlanceModifier.fillMaxWidth().clickable(action)) {
        Text(title, style = TextStyle(color = GlanceTheme.colors.onSurface, fontSize = fs(13, k), fontWeight = FontWeight.Bold))
        Spacer(GlanceModifier.height(4.dp))
        Text(sub, style = TextStyle(color = Colors.FLAT, fontSize = fs(11, k)), maxLines = 2)
    }
}

@Composable
private fun Board(d: WidgetData, offline: Boolean, cols: Int, heightDp: Int, k: Float) {
    val kh = 1f + (k - 1f) / 2f   // 헤더·'+N'은 절반만 커진다 — 메타 정보라 종목 행에 높이를 양보(마스터 2026-09-04 '글씨 너무 작다' 2차)
    // 헤더: 관심종목 · HH:MM 갱신 · 장중/마감 (· 오프라인) ………… ↻ 갱신
    Row(modifier = GlanceModifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        Text("관심종목", style = TextStyle(color = GlanceTheme.colors.onSurface, fontSize = fs(12, kh), fontWeight = FontWeight.Bold))
        Text("  " + (if (offline) "오프라인·" else "") + Format.status(d),
             style = TextStyle(color = if (offline) Colors.WARN else Colors.FLAT, fontSize = fs(9, kh)), maxLines = 1,
             modifier = GlanceModifier.defaultWeight())
        // ↻ 즉시 갱신 — iOS에선 불가능했던 부분. 자식 clickable이 몸통 탭보다 우선한다.
        Text("↻ 갱신", style = TextStyle(color = Colors.FLAT, fontSize = fs(10, kh), fontWeight = FontWeight.Bold),
             modifier = GlanceModifier.clickable(actionRunCallback<RefreshAction>()))
    }
    Spacer(GlanceModifier.height(3.dp))

    // 통화별 합계(보유가 있을 때만)
    val totals = Format.totals(d.items)
    for (t in totals) {
        Row(modifier = GlanceModifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Text("합계 " + Format.value(t.value, t.currency),
                 style = TextStyle(color = GlanceTheme.colors.onSurface, fontSize = fs(12, k), fontWeight = FontWeight.Bold),
                 maxLines = 1, modifier = GlanceModifier.defaultWeight())
            Text(Format.pnlArrow(t.pnl, t.currency) + " (" + Format.change(t.pct) + ")",
                 style = TextStyle(color = pnlColor(t.pnl), fontSize = fs(11, k)), maxLines = 1)
        }
    }
    if (totals.isNotEmpty()) Divider()

    // 세로 예산 → 행 수(고정 개수 금지). +N 줄은 필요할 때만 예산에서 뺀다.
    val n = d.items.size
    // 텍스트는 sp, 예산은 dp — 시스템 글꼴 배율만큼 예산을 줄여야 마지막 행·+N 줄이 안 잘린다(리뷰 2026-09-04).
    val fontScale = LocalContext.current.resources.configuration.fontScale.coerceAtLeast(1f)
    val rowDp = (ROW_DP * k).toInt()
    val budget = ((heightDp - PAD_V * 2) / fontScale).toInt() - (HEADER_DP * kh).toInt() - (TOTAL_DP * k).toInt() * totals.size -
        (if (totals.isNotEmpty()) DIVIDER_DP else 0)
    var plan = Format.planCapacity(n, budget - (MORE_DP * kh).toInt(), rowDp = rowDp, dividerDp = DIVIDER_DP)   // Divider() 실제 높이(2+1+2)
    if (plan.more == 0) plan = Format.planCapacity(n, budget, rowDp = rowDp, dividerDp = DIVIDER_DP)
    // Glance 컨테이너는 자식 10개까지만 그리고 초과분은 오류 없이 버린다(glance-appwidget 1.2.0 LayoutSelection
    // "Truncated … container from N to 10 elements"; 생성 레이아웃도 *_10children 까지). 2026-09-04 커버 실측:
    // 3행 계획인데 삼성전자 1행+구분선만 보이고 "+N종목"도 사라졌다. 행은 5개씩 Column 으로 묶는다(구분선+행 = 자식 2개 → 10).
    // 바깥 Column = 헤더·간격·합계(≤2)·구분선·묶음(≤4)·+N = 최대 10.
    (0 until plan.drawn).chunked(5).forEach { group ->
        Column(modifier = GlanceModifier.fillMaxWidth()) {
            for (i in group) {
                if (i > 0) Divider()
                ItemRow(d.items[i], cols, k)
            }
        }
    }
    if (plan.more > 0) {
        Text("+${plan.more}종목", style = TextStyle(color = Colors.FLAT, fontSize = fs(9, kh)))   // 실제 그린 개수 기준
    }
}

@Composable
private fun ItemRow(it: WidgetItem, cols: Int, k: Float) {
    val wide = cols >= 2
    val label = if (it.market == "US" && it.name.isNotEmpty() && it.name != it.code) "${it.code} ${it.name}" else it.name
    // 자식 최대 7개(Glance 컨테이너 10개 제한 안쪽). 이름이 weight 를 가져 길면 이름부터 줄임표.
    Row(modifier = GlanceModifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        Text(label, style = TextStyle(color = GlanceTheme.colors.onSurface, fontSize = fs(13, k), fontWeight = FontWeight.Bold),
             maxLines = 1, modifier = GlanceModifier.defaultWeight())
        // 보유 수량 — 가격 앞 열(마스터 요청 2026-09-04). 미보유면 빈 문자열이라 열이 사라진다.
        if (it.held && cols >= 1) Text(Format.shares(it.shares) + "  ", style = TextStyle(color = Colors.FLAT, fontSize = fs(10, k)), maxLines = 1)
        Text(Format.money(it.price, it.currency),
             style = TextStyle(color = GlanceTheme.colors.onSurface, fontSize = fs(13, k), fontWeight = FontWeight.Bold))
        Text(" " + Format.change(it.change),
             style = TextStyle(color = chgColor(it.change), fontSize = fs(11, k), fontWeight = FontWeight.Bold))
        if (it.held) {
            Text(if (wide) "  수익 " else "  ", style = TextStyle(color = Colors.FLAT, fontSize = fs(10, k)))
            Text(Format.pnlArrow(it.pnl, it.currency),
                 style = TextStyle(color = pnlColor(it.pnl), fontSize = fs(11, k), fontWeight = FontWeight.Bold), maxLines = 1)
            if (wide) Text(" (" + Format.change(it.pnlPct) + ")",
                           style = TextStyle(color = pnlColor(it.pnl), fontSize = fs(10, k)), maxLines = 1)
        }
    }
}

/** 2+1+2 = DIVIDER_DP. 부모 자식 수를 1개만 쓰도록 Spacer 대신 padding(위 10개 제한). */
@Composable
private fun Divider() {
    Box(modifier = GlanceModifier.fillMaxWidth().padding(vertical = 2.dp)) {
        Box(modifier = GlanceModifier.fillMaxWidth().height(1.dp)
                .background(Colors.DIVIDER)) {}   // 반투명 실선(아이폰 DIVIDER)
    }
}

private fun chgColor(c: Double?): androidx.glance.unit.ColorProvider =
    if (c == null || c == 0.0) Colors.FLAT else if (c > 0) Colors.UP else Colors.DOWN

/** 수익도 등락과 같은 색규칙: 이익 빨강 / 손실 파랑 / 0·미값 회색. */
private fun pnlColor(v: Double?): androidx.glance.unit.ColorProvider =
    if (v == null || v == 0.0) Colors.FLAT else if (v > 0) Colors.UP else Colors.DOWN
