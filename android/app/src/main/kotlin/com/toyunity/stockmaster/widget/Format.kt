package com.toyunity.stockmaster.widget

import java.time.LocalDate
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.format.DateTimeParseException
import java.util.Locale
import kotlin.math.abs

/**
 * 표시 문자열 — 아이폰 Scriptable 위젯(backend/report/widget_setup.py _SCRIPT)의
 * fmtMoney/fmtVal/fmtPnlArrow/fmtChg/statusLabel/sumTotals/planCapacity와 같은 규칙·같은 문자.
 * 순수 함수(안드로이드 의존 0) — JVM 단위테스트 대상.
 */
object Format {
    private const val MINUS = "−"   // 아이폰과 동일한 U+2212

    /** 현재가 — KRW 천단위(원 생략, 공간 절약) · USD $소수 2자리 · null "—". */
    fun money(v: Double?, currency: String): String = when {
        v == null -> "—"
        currency == "USD" -> "$" + String.format(Locale.US, "%.2f", v)
        else -> krw(v)
    }

    /** 평가금액/합계 — '원' 표기. */
    fun value(v: Double?, currency: String): String = when {
        v == null -> "—"
        currency == "USD" -> "$" + String.format(Locale.US, "%.2f", v)
        else -> krw(v) + "원"
    }

    /** 손익 — ▲/▼/· + 금액. 색은 호출부(Colors.UP/DOWN/FLAT). */
    fun pnlArrow(v: Double?, currency: String): String {
        if (v == null) return "—"
        val arrow = if (v > 0) "▲" else if (v < 0) "▼" else "·"
        val a = abs(v)
        return arrow + if (currency == "USD") "$" + String.format(Locale.US, "%.2f", a) else krw(a) + "원"
    }

    /** 보유 수량 — '10주' · 소수 보유(미국 소수점 주식) '1.5주' · 미보유(null/0) "". 마스터 요청 2026-09-04. */
    fun shares(v: Double?): String {
        if (v == null || v <= 0) return ""
        val s = if (v == Math.rint(v)) String.format(Locale.US, "%,d", v.toLong())
                else String.format(Locale.US, "%.4f", v).trimEnd('0').trimEnd('.')
        return s + "주"
    }

    /** 등락률 — 부호 항상(+ / U+2212), 소수 2자리, %. */
    fun change(c: Double?): String {
        if (c == null) return "—"
        val s = if (c > 0) "+" else if (c < 0) MINUS else ""
        return s + String.format(Locale.US, "%.2f", abs(c)) + "%"
    }

    /** 'HH:MM 갱신 · 장중' / 'HH:MM 갱신 · M/D(요일) 마감'. fetched_at을 기기 시간대로 — 오프라인이면 캐시 시각이라 정확. */
    fun status(d: WidgetData, zone: ZoneId = ZoneId.systemDefault()): String {
        val hm = try {
            val t = OffsetDateTime.parse(d.fetchedAt).atZoneSameInstant(zone)
            String.format(Locale.US, "%02d:%02d 갱신", t.hour, t.minute)
        } catch (e: DateTimeParseException) { "갱신 시각 없음" }
        if (d.open) return "$hm · 장중"
        val date = try { LocalDate.parse(d.tradeDate) } catch (e: DateTimeParseException) { return "$hm · 마감" }
        val w = "월화수목금토일"[date.dayOfWeek.value - 1]
        return "$hm · ${date.monthValue}/${date.dayOfMonth}($w) 마감"
    }

    data class Total(val currency: String, val value: Double, val cost: Double) {
        val pnl: Double get() = value - cost
        val pct: Double get() = if (cost > 0) (value / cost - 1) * 100 else 0.0
    }

    /** 통화별 보유 합계 — 통화 혼합은 합산하지 않는다(FX 없음). 가격 없는 행은 제외. 통화명 순(KRW, USD). */
    fun totals(items: List<WidgetItem>): List<Total> =
        items.filter { it.held && it.price != null }
            .groupBy { it.currency }
            .map { (cur, rows) -> Total(cur, rows.sumOf { it.price!! * it.shares!! }, rows.sumOf { it.avg!! * it.shares!! }) }
            .sortedBy { it.currency }

    data class Plan(val drawn: Int, val more: Int)

    /** 세로 예산(dp)에 들어가는 행 수 — 행 rowDp + 구분선 dividerDp(두 번째부터). drawn+more==n(무경고 잘림 금지). */
    fun planCapacity(n: Int, budgetDp: Int, rowDp: Int = 20, dividerDp: Int = 3): Plan {
        var used = 0
        var drawn = 0
        while (drawn < n) {
            val cost = rowDp + if (drawn > 0) dividerDp else 0
            if (used + cost > budgetDp) break
            used += cost
            drawn++
        }
        return Plan(drawn, n - drawn)
    }

    private fun krw(v: Double): String = String.format(Locale.US, "%,d", Math.round(v))
}
