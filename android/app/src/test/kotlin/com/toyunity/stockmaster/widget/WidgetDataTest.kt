package com.toyunity.stockmaster.widget

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** /api/widget 계약 소비 규칙(스펙 §데이터 계약). 샘플은 tests/test_widget.py의 ITEM_KEYS와 같은 모양. */
class WidgetDataTest {
    private val sample = """
    {"open": true, "trade_date": "2026-09-04", "fetched_at": "2026-09-04T10:30:12+09:00",
     "refresh_after_sec": 900, "future_field": {"x": 1},
     "items": [
       {"code":"005930","name":"삼성전자","market":"KR","currency":"KRW","price":71200,"change":1.25,
        "shares":10,"avg":65000,"pnl":62000,"pnl_pct":9.54},
       {"code":"NVDA","name":"엔비디아","market":"US","currency":"USD","price":123.45,"change":-0.5,
        "shares":null,"avg":null,"pnl":null,"pnl_pct":null,"us_open":false},
       {"code":"000660","name":"SK하이닉스","market":"KR","currency":"KRW","price":null,"change":null,
        "shares":3,"avg":200000,"pnl":null,"pnl_pct":null}
     ]}"""

    @Test fun parses_top_level_and_kr_row() {
        val d = WidgetJson.parse(sample)
        assertTrue(d.open)
        assertEquals("2026-09-04", d.tradeDate)
        assertEquals(900, d.refreshAfterSec)
        val kr = d.items[0]
        assertEquals(71200.0, kr.price!!, 0.0)
        assertEquals(1.25, kr.change!!, 0.0)
        assertEquals("KRW", kr.currency)
        assertTrue(kr.held)
        assertNull(kr.usOpen)                       // KR 행엔 us_open이 없다(선택 필드)
    }

    @Test fun us_row_has_us_open_and_is_not_held() {
        val us = WidgetJson.parse(sample).items[1]
        assertEquals("US", us.market)
        assertEquals(false, us.usOpen)
        assertFalse(us.held)                        // shares null → 시세만
        assertEquals("USD", us.currency)
    }

    @Test fun null_price_row_is_kept_not_dropped() {   // 서버도 빼지 않는다(price:null 유지) — "—"로 그린다
        val d = WidgetJson.parse(sample)
        assertEquals(3, d.items.size)
        assertNull(d.items[2].price)
        assertTrue(d.items[2].held)                 // 가격 실패여도 보유 판정은 수량·평균가로
    }

    @Test fun unknown_fields_are_ignored() {        // future_field가 있어도 파싱된다
        assertEquals(3, WidgetJson.parse(sample).items.size)
    }

    @Test(expected = IllegalArgumentException::class)
    fun missing_items_fails() { WidgetJson.parse("""{"error":"unauthorized"}""") }

    @Test(expected = IllegalArgumentException::class)
    fun non_json_fails() { WidgetJson.parse("<html>") }
}
