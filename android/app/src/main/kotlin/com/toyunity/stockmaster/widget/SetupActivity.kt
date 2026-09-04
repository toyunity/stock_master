package com.toyunity.stockmaster.widget

import android.app.Activity
import android.os.Bundle
import android.widget.TextView

/** T1 스텁 — 런처·딥링크 인텐트 필터 검증용. T5에서 실물로 교체한다. */
class SetupActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(TextView(this).apply { text = "Stock Master 위젯" })
    }
}
