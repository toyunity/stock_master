package com.toyunity.stockmaster.widget

import java.net.HttpURLConnection
import java.net.URL

sealed class ApiResult {
    data class Ok(val body: String) : ApiResult()
    object Unauthorized : ApiResult()
    data class Failure(val reason: String) : ApiResult()   // "http 503", "SocketTimeoutException" 등 — 토큰 없음
}

/** GET {base}/api/widget — 표준 라이브러리만(요청 1종). 블로킹이므로 IO 스레드에서 부른다. */
object WidgetApi {
    fun fetch(baseUrl: String, token: String): ApiResult {
        var conn: HttpURLConnection? = null
        try {
            conn = URL("$baseUrl/api/widget").openConnection() as HttpURLConnection   // MalformedURL 도 Failure 로(리뷰 2026-09-04)
            // 10초 — 맥 잠자기는 Funnel이 TLS만 받고 매달리는 실패라 타임아웃이 곧 '오프라인' 판정(아이폰과 동일).
            conn.connectTimeout = 10_000
            conn.readTimeout = 10_000
            conn.setRequestProperty("Authorization", "Bearer $token")
            conn.setRequestProperty("Accept", "application/json")
            val code = conn.responseCode
            if (code == 401) return ApiResult.Unauthorized
            if (code != 200) return ApiResult.Failure("http $code")
            return ApiResult.Ok(conn.inputStream.bufferedReader(Charsets.UTF_8).use { it.readText() })
        } catch (e: Exception) {
            return ApiResult.Failure(e.javaClass.simpleName)   // 메시지에 URL/토큰이 섞일 수 있어 클래스명만
        } finally {
            conn?.disconnect()
        }
    }
}
