package com.toyunity.stockmaster.widget

import org.json.JSONException
import org.json.JSONObject

/**
 * /api/widget 응답(스펙 §데이터 계약, 서버 tests/test_widget.py ITEM_KEYS가 고정).
 * 규칙: 모르는 필드는 무시 · null 가격은 null 그대로(행을 빼지 않는다) · us_open은 US 행에만 있는 선택 필드.
 */
data class WidgetItem(
    val code: String,
    val name: String,
    val market: String,      // "KR" | "US"
    val currency: String,    // "KRW" | "USD"
    val price: Double?,
    val change: Double?,     // 등락률 %
    val shares: Double?,
    val avg: Double?,
    val pnl: Double?,
    val pnlPct: Double?,
    val usOpen: Boolean?,
) {
    /** 보유 = 수량>0 && 평균가 존재(아이폰 hasHolding과 같은 술어). 가격 실패(pnl null)여도 유지. */
    val held: Boolean get() = (shares ?: 0.0) > 0.0 && avg != null
}

data class WidgetData(
    val open: Boolean,
    val tradeDate: String,        // "YYYY-MM-DD"
    val fetchedAt: String,        // ISO-8601(+09:00) — 폴백값이면 universe mtime 시각 그대로
    val refreshAfterSec: Int,
    val items: List<WidgetItem>,
)

object WidgetJson {
    /** items가 없거나 JSON이 아니면 IllegalArgumentException — 호출부가 '오프라인'으로 처리한다. */
    fun parse(text: String): WidgetData {
        val o = try { JSONObject(text) } catch (e: JSONException) { throw IllegalArgumentException("JSON 아님") }
        val arr = o.optJSONArray("items") ?: throw IllegalArgumentException("items 없음")
        val items = (0 until arr.length()).map { i ->
            val it = arr.getJSONObject(i)
            val code = it.optString("code", "")
            WidgetItem(
                code = code,
                name = it.optString("name", code).ifEmpty { code },
                market = it.optString("market", "KR"),
                currency = it.optString("currency", "KRW"),
                price = it.num("price"),
                change = it.num("change"),
                shares = it.num("shares"),
                avg = it.num("avg"),
                pnl = it.num("pnl"),
                pnlPct = it.num("pnl_pct"),
                usOpen = if (it.has("us_open") && !it.isNull("us_open")) it.getBoolean("us_open") else null,
            )
        }
        return WidgetData(
            open = o.optBoolean("open", false),
            tradeDate = o.optString("trade_date", ""),
            fetchedAt = o.optString("fetched_at", ""),
            refreshAfterSec = o.optInt("refresh_after_sec", 900),
            items = items,
        )
    }

    private fun JSONObject.num(key: String): Double? =
        if (!has(key) || isNull(key)) null else optDouble(key).takeUnless { it.isNaN() }
}
