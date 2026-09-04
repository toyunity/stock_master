package com.toyunity.stockmaster.widget

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.ZoneId

/** 아이폰 Scriptable 스크립트(widget_setup.py _SCRIPT)의 fmt*·sumTotals·planCapacity와 같은 규칙. */
class FormatTest {
    private fun item(code: String = "005930", currency: String = "KRW", price: Double? = 71200.0,
                     shares: Double? = null, avg: Double? = null) =
        WidgetItem(code, code, if (currency == "USD") "US" else "KR", currency, price, 1.0, shares, avg, null, null, null)

    @Test fun money_krw_thousands_and_usd_two_decimals() {
        assertEquals("71,200", Format.money(71200.0, "KRW"))
        assertEquals("$123.45", Format.money(123.45, "USD"))
        assertEquals("—", Format.money(null, "KRW"))
        assertEquals("12,345,000원", Format.value(12345000.0, "KRW"))
    }

    @Test fun pnl_arrow_and_change_sign_use_same_glyphs_as_iphone() {
        assertEquals("▲12,000원", Format.pnlArrow(12000.0, "KRW"))
        assertEquals("▼$3.21", Format.pnlArrow(-3.21, "USD"))
        assertEquals("·0원", Format.pnlArrow(0.0, "KRW"))
        assertEquals("+1.25%", Format.change(1.25))
        assertEquals("−0.50%", Format.change(-0.5))     // U+2212 minus
        assertEquals("0.00%", Format.change(0.0))
        assertEquals("—", Format.change(null))
    }

    @Test fun shares_label_for_held_items() {   // 마스터 요청 2026-09-04: 보유 수량을 행에 표시
        assertEquals("10주", Format.shares(10.0))
        assertEquals("1,200주", Format.shares(1200.0))
        assertEquals("1.5주", Format.shares(1.5))        // 미국 소수점 주식
        assertEquals("", Format.shares(null))
        assertEquals("", Format.shares(0.0))
    }

    @Test fun status_open_and_closed_labels() {
        val seoul = ZoneId.of("Asia/Seoul")
        val open = WidgetData(true, "2026-09-04", "2026-09-04T10:30:12+09:00", 900, emptyList())
        assertEquals("10:30 갱신 · 장중", Format.status(open, seoul))
        // 2026-07-15는 수요일(2026-07-16 목요일은 tests/test_widget.py 픽스처로 확인된 값)
        val closed = WidgetData(false, "2026-07-15", "2026-07-15T18:02:00+09:00", 21600, emptyList())
        assertEquals("18:02 갱신 · 7/15(수) 마감", Format.status(closed, seoul))
    }

    @Test fun totals_do_not_mix_currencies() {
        val t = Format.totals(listOf(
            item(shares = 10.0, avg = 65000.0),                                   // KRW 712,000 / 650,000
            item(code = "NVDA", currency = "USD", price = 100.0, shares = 2.0, avg = 80.0),   // USD 200 / 160
            item(code = "000660", price = null, shares = 3.0, avg = 200000.0),    // 가격 없음 → 합계에서 제외
            item(code = "035420", shares = null)))                                 // 미보유 → 제외
        assertEquals(listOf("KRW", "USD"), t.map { it.currency })
        assertEquals(712000.0, t[0].value, 0.0); assertEquals(650000.0, t[0].cost, 0.0)
        assertEquals(62000.0, t[0].pnl, 0.0)
        assertEquals(200.0, t[1].value, 0.0); assertEquals(25.0, t[1].pct, 1e-9)
    }

    @Test fun capacity_never_truncates_silently() {   // 아이폰 §137/§207 회귀 규칙: drawn + more == n
        val big = Format.planCapacity(16, 320)
        val mid = Format.planCapacity(16, 120)
        assertEquals(16, big.drawn + big.more); assertTrue(big.more > 0)
        assertEquals(16, mid.drawn + mid.more); assertTrue(mid.more > 0)
        assertTrue(big.drawn > mid.drawn)
        assertEquals(Format.Plan(3, 0), Format.planCapacity(3, 120))      // 20+23+23=66 ≤ 120 → 전부
        assertEquals(Format.Plan(0, 2), Format.planCapacity(2, 10))       // 예산 부족 → 0줄 + "+2종목"
        // 안드로이드 Divider() 는 5dp — 그리는 값과 같은 상수로 계산해야 한다(리뷰 2026-09-04): 20+25+25=70 ≤ 70
        assertEquals(Format.Plan(3, 1), Format.planCapacity(4, 70, dividerDp = 5))
    }
}
