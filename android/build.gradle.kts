// AGP 9.x는 Kotlin이 내장이다(org.jetbrains.kotlin.android 적용 금지 — 새 DSL과 비호환).
// Compose 컴파일러 플러그인은 AGP 9.4.0이 쓰는 내장 KGP 2.2.10과 같은 버전이어야 한다(2026-09-04 POM 확인).
plugins {
    id("com.android.application") version "9.4.0" apply false
    id("org.jetbrains.kotlin.plugin.compose") version "2.2.10" apply false
}
