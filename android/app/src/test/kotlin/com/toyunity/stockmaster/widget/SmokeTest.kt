package com.toyunity.stockmaster.widget

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Test

/** 안드로이드 SDK의 org.json은 JVM 단위테스트에서 스텁이라 실물(testImplementation)이 없으면 여기서 죽는다. */
class SmokeTest {
    @Test fun org_json_is_real_on_test_classpath() {
        assertEquals(1, JSONObject("""{"a": 1}""").getInt("a"))
    }
}
