# 갤럭시 Z Fold 8 홈 위젯(안드로이드 위젯 전용 앱) — 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> 이 계획은 **Orca 오케스트레이션**으로 실행한다(코디네이터 = 설계 세션, 워커 = 태스크당 1개). 워커 규칙은 맨 아래 §실행.

**Goal:** 갤럭시 Z Fold 8 홈 화면(커버·메인)에 관심종목 시세·보유 손익 위젯을 띄운다 — 기존 `/api/widget`(Bearer 토큰)을 그대로 읽는 Kotlin 위젯 전용 앱 + 설치 페이지의 갤럭시 섹션 + APK 배포 라우트 + 가이드.

**Architecture:** 앱은 서버의 소비자일 뿐이다. `RefreshWorker`(WorkManager 1회성 체인, 서버 힌트 15분~6h)가 JSON을 받아 `Prefs`에 저장하고 `StockWidget`(Glance, 텍스트 전용, `SizeMode.Responsive`)이 그린다. 설정은 `SetupActivity`(딥링크 `stockmaster://setup` 또는 붙여넣기). 서버는 `/widget-setup` 섹션 + `GET /widget-setup/android.apk` 두 곳만 바뀐다.

**Tech Stack:** Kotlin(AGP 9.4.0 내장 Kotlin 2.2.10) · Jetpack Glance 1.2.0 · WorkManager 2.11.2 · HttpURLConnection + org.json · JUnit4(JVM) · Gradle 9.7.1 · Android SDK 36 · FastAPI(Python 3.9) · pytest.

**Spec:** `docs/superpowers/specs/2026-09-04-android-widget-design.md` (커밋 7a26531) — 이 계획은 그 스펙을 구현한다. 표·규칙이 어긋나면 스펙이 정본.

## Global Constraints

- **Python 3.9 문법만**(서버 쪽): `match` 금지, `X | Y` 힌트 금지(`Optional[X]`), 모듈 맨 위 `from __future__ import annotations`. 인터프리터는 `.venv/bin/python`.
- **`/api/widget` 응답 계약 무변경.** 안드로이드 때문에 서버 필드를 늘리지 않는다(화이트리스트 = 보안 결정).
- **"모든 경로 잠금" 불변식**: 새 라우트 `/widget-setup/android.apk`는 `tests/test_auth.py`의 `PROTECTED`에 추가한다.
- **CSS 단일 출처**: `backend/report/*.py`에 헥스 색을 새로 쓰지 않는다(`tests/test_theme.py::test_pages_do_not_hardcode_colors`). 안드로이드 색은 `android/…/Colors.kt`에 복사하고 pytest로 드리프트를 잡는다.
- **템플릿 치환 순서**: 자산(`__PWA_HEAD__`, `__BASE_CSS__`, `__SCRIPT__`) → 그다음 데이터(`__APK_BLOCK__`, `__ANDROID_LINK__`, `__TOKEN__`). 렌더 결과에 `__X__` 자리표시자가 남으면 `tests/test_us_page.py`가 잡는다.
- **안드로이드 의존성은 AndroidX만**: `androidx.glance:glance-appwidget:1.2.0`, `androidx.work:work-runtime:2.11.2`. 테스트 전용 `junit:junit:4.13.2`, `org.json:json:20260814`. Retrofit·OkHttp·직렬화·material3 금지.
- **버전(2026-09-04 확인)**: AGP `9.4.0`(Gradle ≥ 9.6.0, 빌드툴 36.0.0, JDK ≥ 17, 내장 KGP 2.2.10) · Compose 컴파일러 플러그인 `org.jetbrains.kotlin.plugin.compose` **2.2.10**(내장 KGP와 같은 버전이어야 한다) · `compileSdk=36, targetSdk=36, minSdk=31` · 패키지 `com.toyunity.stockmaster.widget`.
- **SDK 경로**: `/opt/homebrew/share/android-commandlinetools`(platform-tools 37.0.1 · platforms;android-36 · build-tools;36.0.0 설치 완료 2026-09-04). JDK 기본 `java`=Temurin 25(Gradle 9.7은 17~26 지원). 문제 시 `~/.gradle/gradle.properties`에 `org.gradle.java.home=/Users/toyunity/Library/Java/JavaVirtualMachines/ms-21.0.7/Contents/Home`.
- **성능 예산**: 위젯 텍스트 전용(이미지 0) · 갱신 1회 = HTTP 1건 · 상주 서비스·알람·웨이크락 0 · 릴리스 APK 3MB 이하(R8 minify + 리소스 축소).
- **보안**: `android:allowBackup="false"`, `usesCleartextTraffic="false"`, 토큰은 `SharedPreferences`에만, 로그·토스트·예외 문구에 토큰 금지, 딥링크 `base`는 `https://`만.
- **표시 문자**: 아이폰 스크립트(`backend/report/widget_setup.py` `_SCRIPT`)와 동일 — 등락 `+`/`−`(U+2212), 손익 `▲`/`▼`/`·`, 미값 `—`.
- **절대 금지**(CLAUDE.md): 포트 8000 재기동·종료 금지, 실 KIS 호출·토큰 발급 금지, 워커는 `git commit/push` 금지(코디네이터가 커밋).
- 실측한 사실은 **날짜와 함께** 주석에 남긴다.

## File Structure

| 파일 | 역할 | 태스크 |
|---|---|---|
| `android/settings.gradle.kts`, `android/build.gradle.kts`, `android/gradle.properties`, `android/gradlew*`, `android/gradle/wrapper/*` | Gradle 프로젝트·래퍼(커밋) | T1 |
| `android/app/build.gradle.kts`, `android/app/proguard-rules.pro` | 앱 모듈: SDK·의존성·서명·R8 | T1 |
| `android/app/src/main/AndroidManifest.xml` | 권한·`SetupActivity`(런처+딥링크)·`StockWidgetReceiver` | T1 |
| `android/app/src/main/res/xml/stock_widget_info.xml` | 위젯 메타(4×2 기본, 리사이즈, 30분 백스톱) | T1 |
| `android/app/src/main/res/layout/widget_preview.xml`, `res/values/strings.xml`, `res/values/colors.xml`, `res/drawable/ic_launcher_fg.xml`, `res/mipmap-anydpi-v26/ic_launcher.xml` | 미리보기·문자열·아이콘 | T1 |
| `android/app/src/main/kotlin/com/toyunity/stockmaster/widget/Colors.kt` | theme.py 토큰 복사(day/night) | T1 |
| `…/widget/StockWidget.kt`, `StockWidgetReceiver.kt`, `SetupActivity.kt` | T1은 컴파일용 스텁, T4·T5가 실물로 교체 | T1→T4/T5 |
| `android/app/src/test/kotlin/com/toyunity/stockmaster/widget/SmokeTest.kt` | JVM 테스트 경로(org.json 실물) 검증 | T1 |
| `android/README.md` | 개발자용 빌드·서명·설치 메모 | T1 |
| `…/widget/WidgetData.kt`, `Format.kt` + `test/…/WidgetDataTest.kt`, `FormatTest.kt` | 계약 파싱·포맷·행 예산·합계(순수 Kotlin) | T2 |
| `…/widget/Prefs.kt`, `WidgetApi.kt`, `Scheduler.kt`, `RefreshWorker.kt` + `test/…/RefreshPolicyTest.kt` | 저장·네트워크·예약 정책·워커 | T3 |
| `…/widget/StockWidget.kt`, `StockWidgetReceiver.kt`, `RefreshAction.kt` | Glance 화면·리시버·↻ 액션 | T4 |
| `…/widget/SetupActivity.kt`, `res/layout/activity_setup.xml`, `res/values/strings.xml`(추가) | 설정 화면·딥링크·위젯 고정·배터리 | T5 |
| `backend/config.py`, `backend/api/app.py`, `backend/report/widget_setup.py`, `tests/test_android_widget.py`, `tests/test_auth.py`, `Makefile`, `.gitignore`, `.env.example` | 서버 섹션·APK 라우트·테스트·빌드 타깃 | T6 |
| `docs/widget-guide.md`, `README.md` | 갤럭시 설치 가이드·문서 지도 | T7 |
| (코디네이터) `data/android/release.jks`, `android/keystore.properties`(둘 다 gitignore) | 릴리스 서명·APK 산출·통합 검증 | T8 |

**태스크 의존(DAG)**: T1 → {T2, T3, T6, T7} 병렬 → T4(T2+T3), T5(T2+T3) 병렬 → T8(전부).
T3는 T2에 의존하지 않도록 `refresh_after_sec` 힌트만 `org.json`으로 직접 읽는다(전체 파싱은 T4가 `WidgetJson.parse`로).
T6의 색 드리프트 테스트는 T1이 만드는 `Colors.kt`를 읽는다.

---

### Task 1: 툴체인 + 빌드되는 스켈레톤(스텁 3개·아이콘·위젯 메타·JVM 테스트 경로)

**Files:**
- Create: `android/settings.gradle.kts`, `android/build.gradle.kts`, `android/gradle.properties`, `android/local.properties`(gitignore), `android/app/build.gradle.kts`, `android/app/proguard-rules.pro`
- Create: `android/app/src/main/AndroidManifest.xml`, `android/app/src/main/res/xml/stock_widget_info.xml`, `res/layout/widget_preview.xml`, `res/values/strings.xml`, `res/values/colors.xml`, `res/drawable/ic_launcher_fg.xml`, `res/mipmap-anydpi-v26/ic_launcher.xml`
- Create: `android/app/src/main/kotlin/com/toyunity/stockmaster/widget/{Colors,StockWidget,StockWidgetReceiver,SetupActivity}.kt`(뒤 셋은 스텁)
- Create: `android/app/src/test/kotlin/com/toyunity/stockmaster/widget/SmokeTest.kt`, `android/README.md`
- Modify: `.gitignore`(루트) — 안드로이드 빌드 산출물 무시

**Interfaces:**
- Produces: 빌드 명령 `cd android && ./gradlew assembleDebug test lint` 가 통과하는 프로젝트. 클래스명 고정: `StockWidget`, `StockWidgetReceiver`, `SetupActivity`(매니페스트가 참조). `Colors.UP/DOWN/FLAT/WARN: androidx.glance.unit.ColorProvider`.
- Produces: 문자열 리소스 `app_name`, `widget_description`. 위젯 메타 `@xml/stock_widget_info`.

- [ ] **Step 1: Gradle 설치·래퍼 생성(실패 확인 = `./gradlew`가 없음)**

```bash
which gradle || brew install gradle          # 9.7.1 (2026-09-04 brew)
mkdir -p android && cd android
gradle wrapper --gradle-version 9.7.1 --distribution-type bin
ls gradlew gradle/wrapper/gradle-wrapper.jar gradle/wrapper/gradle-wrapper.properties
```
Expected: 세 파일 존재. (래퍼 jar는 커밋한다 — 표준 관행.)

- [ ] **Step 2: 루트 `.gitignore`에 추가**(리포 루트 `.gitignore` 끝에)

```
# android/ (갤럭시 위젯 앱) 빌드 산출물·로컬 설정
android/.gradle/
android/**/build/
android/.kotlin/
android/local.properties
android/keystore.properties
```

- [ ] **Step 3: Gradle 설정 파일 작성**

`android/settings.gradle.kts`:
```kotlin
pluginManagement {
    repositories { google(); mavenCentral(); gradlePluginPortal() }
}
dependencyResolutionManagement {
    repositories { google(); mavenCentral() }
}
rootProject.name = "StockMasterWidget"
include(":app")
```

`android/build.gradle.kts`:
```kotlin
// AGP 9.x는 Kotlin이 내장이다(org.jetbrains.kotlin.android 적용 금지 — 새 DSL과 비호환).
// Compose 컴파일러 플러그인은 AGP 9.4.0이 쓰는 내장 KGP 2.2.10과 같은 버전이어야 한다(2026-09-04 POM 확인).
plugins {
    id("com.android.application") version "9.4.0" apply false
    id("org.jetbrains.kotlin.plugin.compose") version "2.2.10" apply false
}
```

`android/gradle.properties`:
```
org.gradle.jvmargs=-Xmx2g -Dfile.encoding=UTF-8
android.useAndroidX=true
```

`android/local.properties`(gitignore — 이 맥 전용):
```
sdk.dir=/opt/homebrew/share/android-commandlinetools
```

`android/app/proguard-rules.pro`:
```
# Glance·WorkManager는 consumer 규칙을 동봉한다. 앱 자체 규칙은 없음(2026-09-04).
```

`android/app/build.gradle.kts`:
```kotlin
import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.plugin.compose")
}

// 릴리스 서명 — android/keystore.properties(gitignore)가 있으면 그 키, 없으면 debug 키.
// 사이드로드 업데이트는 같은 키여야 덮어써진다(스펙 §빌드·서명). 키스토어 실물은 data/android/(gitignore).
val keystoreProps = Properties().apply {
    val f = rootProject.file("keystore.properties")
    if (f.exists()) f.inputStream().use { load(it) }
}

android {
    namespace = "com.toyunity.stockmaster.widget"
    compileSdk = 36

    defaultConfig {
        applicationId = "com.toyunity.stockmaster.widget"
        minSdk = 31          // 반응형 위젯(Android 12+)의 자연 하한. 기기(Fold 8)는 Android 17.
        targetSdk = 36
        versionCode = 1      // 릴리스마다 수동 +1(같은 번호 재설치도 되지만 관례).
        versionName = "1.0"
    }

    signingConfigs {
        if (keystoreProps.isNotEmpty()) {
            create("release") {
                storeFile = file(keystoreProps.getProperty("storeFile"))
                storePassword = keystoreProps.getProperty("storePassword")
                keyAlias = keystoreProps.getProperty("keyAlias")
                keyPassword = keystoreProps.getProperty("keyPassword")
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            signingConfig = if (keystoreProps.isNotEmpty()) signingConfigs.getByName("release")
                            else signingConfigs.getByName("debug")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17   // 내장 Kotlin의 jvmTarget이 이 값을 따른다.
    }

    buildFeatures { compose = true }
}

dependencies {
    implementation("androidx.glance:glance-appwidget:1.2.0")   // 2026-08-26 안정판
    implementation("androidx.work:work-runtime:2.11.2")         // -ktx는 2.9부터 빈 껍데기
    testImplementation("junit:junit:4.13.2")
    // 안드로이드 SDK의 org.json은 JVM 단위테스트에서 스텁("not mocked")이라 실물을 테스트 classpath에 넣는다.
    testImplementation("org.json:json:20260814")
}
```
`buildFeatures { compose = true }`가 AGP 9.4에서 "deprecated/불필요" 경고를 내면 그 줄을 지운다(빌드 로그 그대로 따른다). 지운 뒤에도 `@Composable`이 컴파일돼야 한다.

- [ ] **Step 4: 매니페스트·리소스**

`android/app/src/main/AndroidManifest.xml`:
```xml
<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android">
    <uses-permission android:name="android.permission.INTERNET" />
    <!-- 사이드로드 개인 앱 — Play 정책 무관. 설정 화면의 [배터리 제한 해제]가 시스템 대화상자를 띄운다. -->
    <uses-permission android:name="android.permission.REQUEST_IGNORE_BATTERY_OPTIMIZATIONS" />

    <!-- allowBackup=false: 자동 백업이 토큰(SharedPreferences)을 구글 드라이브로 올리는 것을 막는다(스펙 §보안). -->
    <application
        android:label="@string/app_name"
        android:icon="@mipmap/ic_launcher"
        android:allowBackup="false"
        android:usesCleartextTraffic="false"
        android:theme="@android:style/Theme.DeviceDefault.DayNight">

        <activity
            android:name=".SetupActivity"
            android:exported="true"
            android:launchMode="singleTop">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
            </intent-filter>
            <!-- /widget-setup 페이지의 [앱에 자동 입력] = stockmaster://setup?base=…&token=… -->
            <intent-filter>
                <action android:name="android.intent.action.VIEW" />
                <category android:name="android.intent.category.DEFAULT" />
                <category android:name="android.intent.category.BROWSABLE" />
                <data android:scheme="stockmaster" android:host="setup" />
            </intent-filter>
        </activity>

        <receiver
            android:name=".StockWidgetReceiver"
            android:exported="true">
            <intent-filter>
                <action android:name="android.appwidget.action.APPWIDGET_UPDATE" />
            </intent-filter>
            <meta-data
                android:name="android.appwidget.provider"
                android:resource="@xml/stock_widget_info" />
        </receiver>
    </application>
</manifest>
```

`android/app/src/main/res/xml/stock_widget_info.xml`:
```xml
<?xml version="1.0" encoding="utf-8"?>
<!-- 기본 4×2. 커버(5.5" 10:16)·메인(7.6" 4:3) 양쪽에서 리사이즈 가능.
     updatePeriodMillis는 OS 하한 30분 — 백스톱 전용(실제 주기는 RefreshWorker가 서버 힌트로 예약). -->
<appwidget-provider xmlns:android="http://schemas.android.com/apk/res/android"
    android:minWidth="250dp"
    android:minHeight="110dp"
    android:targetCellWidth="4"
    android:targetCellHeight="2"
    android:minResizeWidth="180dp"
    android:minResizeHeight="60dp"
    android:maxResizeWidth="600dp"
    android:maxResizeHeight="500dp"
    android:resizeMode="horizontal|vertical"
    android:updatePeriodMillis="1800000"
    android:widgetCategory="home_screen"
    android:description="@string/widget_description"
    android:previewLayout="@layout/widget_preview"
    android:initialLayout="@layout/glance_default_loading_layout" />
```

`android/app/src/main/res/layout/widget_preview.xml`(위젯 선택기 미리보기 — 정적):
```xml
<?xml version="1.0" encoding="utf-8"?>
<LinearLayout xmlns:android="http://schemas.android.com/apk/res/android"
    android:layout_width="match_parent"
    android:layout_height="match_parent"
    android:orientation="vertical"
    android:padding="12dp"
    android:background="?android:attr/colorBackground">
    <TextView android:layout_width="match_parent" android:layout_height="wrap_content"
        android:text="관심종목  10:30 갱신 · 장중" android:textSize="12sp" android:textStyle="bold"
        android:textColor="?android:attr/textColorPrimary" />
    <TextView android:layout_width="match_parent" android:layout_height="wrap_content"
        android:text="삼성전자                 71,200  +1.25%" android:textSize="13sp"
        android:textColor="?android:attr/textColorPrimary" />
    <TextView android:layout_width="match_parent" android:layout_height="wrap_content"
        android:text="SK하이닉스              412,000  −0.48%" android:textSize="13sp"
        android:textColor="?android:attr/textColorPrimary" />
</LinearLayout>
```

`android/app/src/main/res/values/strings.xml`:
```xml
<?xml version="1.0" encoding="utf-8"?>
<resources>
    <string name="app_name">Stock Master 위젯</string>
    <string name="widget_description">관심종목 시세와 보유 손익(Stock Master)</string>
</resources>
```

`android/app/src/main/res/values/colors.xml`(아이콘 배경 — theme.py `--primary` iris):
```xml
<?xml version="1.0" encoding="utf-8"?>
<resources>
    <color name="ic_bg">#6A4FF0</color>
</resources>
```

`android/app/src/main/res/drawable/ic_launcher_fg.xml`(캔들 세 개):
```xml
<?xml version="1.0" encoding="utf-8"?>
<vector xmlns:android="http://schemas.android.com/apk/res/android"
    android:width="108dp" android:height="108dp"
    android:viewportWidth="108" android:viewportHeight="108">
    <path android:fillColor="#FFFFFF"
        android:pathData="M36,40h8v32h-8z M50,28h8v56h-8z M64,46h8v20h-8z" />
</vector>
```

`android/app/src/main/res/mipmap-anydpi-v26/ic_launcher.xml`(minSdk 31이라 adaptive만으로 충분):
```xml
<?xml version="1.0" encoding="utf-8"?>
<adaptive-icon xmlns:android="http://schemas.android.com/apk/res/android">
    <background android:drawable="@color/ic_bg" />
    <foreground android:drawable="@drawable/ic_launcher_fg" />
</adaptive-icon>
```

- [ ] **Step 5: Colors.kt + 스텁 3개**

`android/app/src/main/kotlin/com/toyunity/stockmaster/widget/Colors.kt`:
```kotlin
package com.toyunity.stockmaster.widget

import androidx.compose.ui.graphics.Color
import androidx.glance.color.ColorProvider

/**
 * backend/report/theme.py 토큰의 복사본(2026-09-04). 화면들의 CSS 단일 출처는 theme.py지만
 * 안드로이드는 CSS를 못 읽어 값을 복제한다 — tests/test_android_widget.py 가 theme.py와 대조해
 * 드리프트를 잡는다. 순서는 (라이트, 다크). 배경·본문색은 GlanceTheme(시스템 동적 색)을 쓴다.
 */
object Colors {
    val UP = ColorProvider(Color(0xFFE5342F), Color(0xFFFF5B52))     // --up   상승·이익
    val DOWN = ColorProvider(Color(0xFF1F66E0), Color(0xFF4F8BFF))   // --down 하락·손실
    val FLAT = ColorProvider(Color(0xFF8B93A4), Color(0xFF5F6879))   // --flat 보합·보조
    val WARN = ColorProvider(Color(0xFFDC8400), Color(0xFFF2A83A))   // --warn 오프라인 배지
}
```

`…/widget/StockWidget.kt`(스텁 — T4가 교체):
```kotlin
package com.toyunity.stockmaster.widget

import android.content.Context
import androidx.glance.GlanceId
import androidx.glance.appwidget.GlanceAppWidget
import androidx.glance.appwidget.provideContent
import androidx.glance.text.Text

/** T1 스텁 — 매니페스트·빌드 검증용. T4에서 실물로 교체한다. */
class StockWidget : GlanceAppWidget() {
    override suspend fun provideGlance(context: Context, id: GlanceId) {
        provideContent { Text("Stock Master") }
    }
}
```

`…/widget/StockWidgetReceiver.kt`(스텁 — T4가 교체):
```kotlin
package com.toyunity.stockmaster.widget

import androidx.glance.appwidget.GlanceAppWidget
import androidx.glance.appwidget.GlanceAppWidgetReceiver

class StockWidgetReceiver : GlanceAppWidgetReceiver() {
    override val glanceAppWidget: GlanceAppWidget = StockWidget()
}
```

`…/widget/SetupActivity.kt`(스텁 — T5가 교체):
```kotlin
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
```

- [ ] **Step 6: JVM 테스트 경로 검증 테스트(org.json 실물이 classpath에 있어야 통과)**

`android/app/src/test/kotlin/com/toyunity/stockmaster/widget/SmokeTest.kt`:
```kotlin
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
```

- [ ] **Step 7: 빌드·테스트·린트 통과 확인**

Run: `cd android && ./gradlew --console=plain assembleDebug test lint`
Expected: `BUILD SUCCESSFUL`. `app/build/outputs/apk/debug/app-debug.apk` 존재. 첫 빌드는 의존성 다운로드로 수 분.
실패 대응(로그 그대로 따른다): ① Compose 컴파일러/Kotlin 버전 불일치 → `./gradlew buildEnvironment | grep kotlin-gradle-plugin`으로 실제 KGP 버전을 읽어 루트 `build.gradle.kts`의 compose 플러그인 버전을 그 값으로 맞춘다. ② JDK 관련 오류 → `~/.gradle/gradle.properties`에 `org.gradle.java.home=/Users/toyunity/Library/Java/JavaVirtualMachines/ms-21.0.7/Contents/Home`. ③ `buildFeatures.compose` 경고 → 줄 삭제. 무엇을 바꿨든 `android/README.md`에 날짜와 함께 적는다.

- [ ] **Step 8: `android/README.md`**

```markdown
# Stock Master 위젯(안드로이드) — 개발 메모

갤럭시 홈 위젯 전용 앱. 서버 `/api/widget`(Bearer 토큰)의 소비자일 뿐이다. 설계: `docs/superpowers/specs/2026-09-04-android-widget-design.md`.

## 빌드(이 맥, Android Studio 없음)
- SDK: `/opt/homebrew/share/android-commandlinetools`(`brew install --cask android-commandlinetools` + `sdkmanager "platform-tools" "platforms;android-36" "build-tools;36.0.0"`). `android/local.properties`의 `sdk.dir`.
- JDK: 기본 `java`(Temurin 25). 문제 시 `~/.gradle/gradle.properties`에 `org.gradle.java.home=…/ms-21.0.7/Contents/Home`.
- `cd android && ./gradlew assembleDebug test lint` · 릴리스는 리포 루트에서 `make android`(→ `data/android/StockMasterWidget.apk`).

## 서명
- `data/android/release.jks`(gitignore) + `android/keystore.properties`(gitignore, storeFile/storePassword/keyAlias/keyPassword). 없으면 debug 키.
- 사이드로드 업데이트는 **같은 키**여야 덮어써진다. 키를 잃으면 폰에서 삭제 후 재설치(토큰 재입력).

## 실측 기록
- 2026-09-04: (T1 워커가 실제로 돈 AGP/Gradle/JDK/KGP 버전과 바꾼 것을 여기에 적는다)
```

- [ ] **Step 9: 완료 보고**(커밋 금지 — 코디네이터가 한다). `worker_done` 본문에 실제 빌드에 쓰인 Gradle/AGP/KGP/JDK 버전과 Step 7에서 바꾼 것을 적는다. `--files-modified`에 만든 파일 전부.

---
### Task 2: 계약 파싱·포맷·행 예산·합계(순수 Kotlin) + JVM 테스트

**Files:**
- Create: `android/app/src/main/kotlin/com/toyunity/stockmaster/widget/WidgetData.kt`, `…/widget/Format.kt`
- Test: `android/app/src/test/kotlin/com/toyunity/stockmaster/widget/WidgetDataTest.kt`, `…/widget/FormatTest.kt`

**Interfaces:**
- Consumes: T1 프로젝트(`org.json` 테스트 실물 포함).
- Produces: `data class WidgetItem(code, name, market, currency, price: Double?, change: Double?, shares: Double?, avg: Double?, pnl: Double?, pnlPct: Double?, usOpen: Boolean?)` + `val held: Boolean`; `data class WidgetData(open: Boolean, tradeDate: String, fetchedAt: String, refreshAfterSec: Int, items: List<WidgetItem>)`; `object WidgetJson { fun parse(text: String): WidgetData }`(실패 시 `IllegalArgumentException`).
- Produces: `object Format { fun money(v: Double?, currency: String): String; fun value(v: Double?, currency: String): String; fun pnlArrow(v: Double?, currency: String): String; fun change(c: Double?): String; fun status(d: WidgetData, zone: ZoneId = ZoneId.systemDefault()): String; data class Total(currency, value, cost){ pnl, pct }; fun totals(items: List<WidgetItem>): List<Total>; data class Plan(drawn: Int, more: Int); fun planCapacity(n: Int, budgetDp: Int, rowDp: Int = 20, dividerDp: Int = 3): Plan }`.

- [ ] **Step 1: 실패하는 테스트 작성**

`android/app/src/test/kotlin/com/toyunity/stockmaster/widget/WidgetDataTest.kt`:
```kotlin
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
```

`android/app/src/test/kotlin/com/toyunity/stockmaster/widget/FormatTest.kt`:
```kotlin
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
    }
}
```

- [ ] **Step 2: 실패 확인**

Run: `cd android && ./gradlew --console=plain test`
Expected: FAIL — `Unresolved reference: WidgetJson` 등 컴파일 오류.

- [ ] **Step 3: 구현**

`android/app/src/main/kotlin/com/toyunity/stockmaster/widget/WidgetData.kt`:
```kotlin
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
```

`android/app/src/main/kotlin/com/toyunity/stockmaster/widget/Format.kt`:
```kotlin
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
```

- [ ] **Step 4: 통과 확인**

Run: `cd android && ./gradlew --console=plain test`
Expected: `BUILD SUCCESSFUL`, `WidgetDataTest`·`FormatTest`·`SmokeTest` 전부 통과(리포트 `app/build/reports/tests/testDebugUnitTest/index.html`).

- [ ] **Step 5: 완료 보고**(커밋 금지). 테스트가 구현 전에 실제로 빨갰는지(Step 2) 보고에 적는다.

---

### Task 3: 저장(Prefs) · 네트워크(WidgetApi) · 예약 정책(Scheduler) · RefreshWorker + 정책 테스트

**Files:**
- Create: `android/app/src/main/kotlin/com/toyunity/stockmaster/widget/Prefs.kt`, `…/widget/WidgetApi.kt`, `…/widget/Scheduler.kt`, `…/widget/RefreshWorker.kt`
- Test: `android/app/src/test/kotlin/com/toyunity/stockmaster/widget/RefreshPolicyTest.kt`

**Interfaces:**
- Consumes: T1의 `StockWidget`(스텁이어도 `updateAll` 호출 가능).
- Produces: `class Prefs(context) { var baseUrl: String?; var token: String?; var lastJson: String?; var lastOkAt: Long; var lastStatus: String; var lastManualAt: Long; val configured: Boolean; companion { OK="ok", OFFLINE="offline", UNAUTHORIZED="unauthorized", UNCONFIGURED="unconfigured" } }`
- Produces: `sealed class ApiResult { data class Ok(body: String); object Unauthorized; data class Failure(reason: String) }`, `object WidgetApi { fun fetch(baseUrl: String, token: String): ApiResult }`(블로킹 — 호출부가 IO 스레드).
- Produces: `object RefreshPolicy { const MIN_SEC=900, MAX_SEC=21600, AUTH_FAIL_SEC=21600; fun nextDelaySec(status: String, refreshAfterSec: Int?): Long; fun manualAllowed(lastManualAtMs: Long, nowMs: Long): Boolean }`, `object Scheduler { const val WORK="sm-refresh"; fun scheduleNext(ctx, delaySec: Long); fun ensureScheduled(ctx); fun refreshNow(ctx); fun cancel(ctx) }`.

- [ ] **Step 1: 실패하는 테스트 작성**

`android/app/src/test/kotlin/com/toyunity/stockmaster/widget/RefreshPolicyTest.kt`:
```kotlin
package com.toyunity.stockmaster.widget

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** 스펙 §갱신 정책 표 — 성공 clamp(힌트, 15분, 6h) · 실패 15분 · 401 6h · ↻ 10초 디바운스. */
class RefreshPolicyTest {
    @Test fun success_clamps_server_hint() {
        assertEquals(900L, RefreshPolicy.nextDelaySec(Prefs.OK, 600))       // 미국장 10분 힌트 → 15분 하한
        assertEquals(900L, RefreshPolicy.nextDelaySec(Prefs.OK, 900))
        assertEquals(3600L, RefreshPolicy.nextDelaySec(Prefs.OK, 3600))
        assertEquals(21600L, RefreshPolicy.nextDelaySec(Prefs.OK, 99999))   // 6h 상한
        assertEquals(900L, RefreshPolicy.nextDelaySec(Prefs.OK, null))      // 힌트 없음 → 15분
    }

    @Test fun failure_retries_in_15_minutes() {
        assertEquals(900L, RefreshPolicy.nextDelaySec(Prefs.OFFLINE, 21600))
    }

    @Test fun unauthorized_backs_off_6_hours() {
        assertEquals(21600L, RefreshPolicy.nextDelaySec(Prefs.UNAUTHORIZED, 900))
    }

    @Test fun manual_refresh_debounces_10s() {
        assertFalse(RefreshPolicy.manualAllowed(lastManualAtMs = 100_000, nowMs = 105_000))
        assertTrue(RefreshPolicy.manualAllowed(lastManualAtMs = 100_000, nowMs = 110_000))
        assertTrue(RefreshPolicy.manualAllowed(lastManualAtMs = 0, nowMs = 5_000))   // 첫 탭
    }
}
```

- [ ] **Step 2: 실패 확인**

Run: `cd android && ./gradlew --console=plain test`
Expected: FAIL — `Unresolved reference: RefreshPolicy` / `Prefs`.

- [ ] **Step 3: 구현**

`…/widget/Prefs.kt`:
```kotlin
package com.toyunity.stockmaster.widget

import android.content.Context
import android.content.SharedPreferences

/**
 * 앱 전용 SharedPreferences — 토큰의 유일한 저장소. allowBackup=false(매니페스트)라 기기 밖으로 안 나간다.
 * EncryptedSharedPreferences는 deprecated(2024~)이고 샌드박스+기기 암호화로 충분(스펙 §보안).
 */
class Prefs(context: Context) {
    private val sp: SharedPreferences = context.getSharedPreferences("sm_widget", Context.MODE_PRIVATE)

    var baseUrl: String?
        get() = sp.getString("base_url", null)?.trimEnd('/')
        set(v) { sp.edit().putString("base_url", v?.trim()?.trimEnd('/')).apply() }

    var token: String?
        get() = sp.getString("token", null)
        set(v) { sp.edit().putString("token", v?.trim()).apply() }

    /** 마지막으로 성공 수신한 /api/widget 본문(오프라인 렌더용). */
    var lastJson: String?
        get() = sp.getString("last_json", null)
        set(v) { sp.edit().putString("last_json", v).apply() }

    var lastOkAt: Long
        get() = sp.getLong("last_ok_at", 0L)
        set(v) { sp.edit().putLong("last_ok_at", v).apply() }

    /** OK | OFFLINE | UNAUTHORIZED | UNCONFIGURED — 위젯이 어떤 얼굴을 할지 결정. */
    var lastStatus: String
        get() = sp.getString("last_status", UNCONFIGURED) ?: UNCONFIGURED
        set(v) { sp.edit().putString("last_status", v).apply() }

    var lastManualAt: Long
        get() = sp.getLong("last_manual_at", 0L)
        set(v) { sp.edit().putLong("last_manual_at", v).apply() }

    val configured: Boolean get() = !baseUrl.isNullOrBlank() && !token.isNullOrBlank()

    companion object {
        const val OK = "ok"
        const val OFFLINE = "offline"
        const val UNAUTHORIZED = "unauthorized"
        const val UNCONFIGURED = "unconfigured"
    }
}
```

`…/widget/WidgetApi.kt`:
```kotlin
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
        val conn = URL("$baseUrl/api/widget").openConnection() as HttpURLConnection
        try {
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
            conn.disconnect()
        }
    }
}
```

`…/widget/Scheduler.kt`:
```kotlin
package com.toyunity.stockmaster.widget

import android.content.Context
import androidx.work.Constraints
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.OutOfQuotaPolicy
import androidx.work.WorkManager
import java.util.concurrent.TimeUnit

/** 스펙 §갱신 정책 표. 순수 함수 — JVM 테스트 대상. */
object RefreshPolicy {
    const val MIN_SEC = 900          // 15분 — WorkManager가 실질적으로 보장하는 최소 간격
    const val MAX_SEC = 21600        // 6h — 서버 힌트 상한과 동일
    const val AUTH_FAIL_SEC = 21600  // 401: 재설정 전까지 두드리지 않는다(재설정 저장이 즉시 작업을 넣는다)
    private const val MANUAL_DEBOUNCE_MS = 10_000L

    fun nextDelaySec(status: String, refreshAfterSec: Int?): Long = when (status) {
        Prefs.OK -> (refreshAfterSec ?: MIN_SEC).coerceIn(MIN_SEC, MAX_SEC).toLong()
        Prefs.UNAUTHORIZED -> AUTH_FAIL_SEC.toLong()
        else -> MIN_SEC.toLong()
    }

    /** ↻ 탭 디바운스 — 10초 안에 재탭은 무시(KIS를 두드리지 않는다). */
    fun manualAllowed(lastManualAtMs: Long, nowMs: Long): Boolean = nowMs - lastManualAtMs >= MANUAL_DEBOUNCE_MS
}

/** 이름 있는 1회성 작업 체인 하나("sm-refresh"). 주기 작업·알람·포그라운드 서비스 없음(배터리, 스펙 §갱신 정책). */
object Scheduler {
    const val WORK = "sm-refresh"
    private val online = Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()

    /** 작업 완료 후 다음 예약 — REPLACE(이 체인이 유일한 예약자). */
    fun scheduleNext(ctx: Context, delaySec: Long) {
        val req = OneTimeWorkRequestBuilder<RefreshWorker>()
            .setInitialDelay(delaySec, TimeUnit.SECONDS)
            .setConstraints(online)
            .build()
        WorkManager.getInstance(ctx).enqueueUniqueWork(WORK, ExistingWorkPolicy.REPLACE, req)
    }

    /** 위젯 추가·부팅·30분 백스톱(onUpdate) — 이미 예약된 작업이 있으면 그대로(KEEP). */
    fun ensureScheduled(ctx: Context) {
        val req = OneTimeWorkRequestBuilder<RefreshWorker>().setConstraints(online).build()
        WorkManager.getInstance(ctx).enqueueUniqueWork(WORK, ExistingWorkPolicy.KEEP, req)
    }

    /** ↻·설정 저장·딥링크 — 즉시(REPLACE, expedited; 지연 없음이 expedited의 조건). */
    fun refreshNow(ctx: Context) {
        val req = OneTimeWorkRequestBuilder<RefreshWorker>()
            .setConstraints(online)
            .setExpedited(OutOfQuotaPolicy.RUN_AS_NON_EXPEDITED_WORK_REQUEST)
            .build()
        WorkManager.getInstance(ctx).enqueueUniqueWork(WORK, ExistingWorkPolicy.REPLACE, req)
    }

    /** 마지막 위젯 제거 — 위젯이 없으면 네트워크 0. */
    fun cancel(ctx: Context) { WorkManager.getInstance(ctx).cancelUniqueWork(WORK) }
}
```

`…/widget/RefreshWorker.kt`:
```kotlin
package com.toyunity.stockmaster.widget

import android.content.Context
import androidx.glance.appwidget.updateAll
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONException
import org.json.JSONObject

/**
 * 요청 1회 → Prefs 저장 → 모든 위젯 인스턴스(커버·메인) 갱신 → 다음 예약. 실패해도 Result.success():
 * WorkManager 재시도 백오프 대신 스펙 표의 고정 지연(15분)을 쓴다 — 서버 다운 때 두드리는 빈도가 예측 가능.
 */
class RefreshWorker(ctx: Context, params: WorkerParameters) : CoroutineWorker(ctx, params) {
    override suspend fun doWork(): Result = withContext(Dispatchers.IO) {
        val prefs = Prefs(applicationContext)
        val base = prefs.baseUrl
        val token = prefs.token
        if (base.isNullOrBlank() || token.isNullOrBlank()) {
            prefs.lastStatus = Prefs.UNCONFIGURED
            StockWidget().updateAll(applicationContext)
            return@withContext Result.success()          // 예약 없음 — 설정 저장이 refreshNow를 부른다
        }
        var hint: Int? = null
        when (val r = WidgetApi.fetch(base, token)) {
            is ApiResult.Ok -> {
                // 여기선 최소 형태(items 존재)와 갱신 힌트만 본다. 표시용 전체 파싱은 위젯(WidgetJson)이 한다.
                hint = try {
                    val o = JSONObject(r.body)
                    if (o.has("items")) o.optInt("refresh_after_sec", RefreshPolicy.MIN_SEC) else null
                } catch (e: JSONException) { null }
                if (hint != null) {
                    prefs.lastJson = r.body
                    prefs.lastOkAt = System.currentTimeMillis()
                    prefs.lastStatus = Prefs.OK
                } else {
                    prefs.lastStatus = Prefs.OFFLINE      // 200인데 items 없음 = 파싱 실패 → 마지막 값 유지
                }
            }
            ApiResult.Unauthorized -> prefs.lastStatus = Prefs.UNAUTHORIZED
            is ApiResult.Failure -> prefs.lastStatus = Prefs.OFFLINE
        }
        StockWidget().updateAll(applicationContext)
        Scheduler.scheduleNext(applicationContext, RefreshPolicy.nextDelaySec(prefs.lastStatus, hint))
        Result.success()
    }
}
```

- [ ] **Step 4: 통과 확인**

Run: `cd android && ./gradlew --console=plain test assembleDebug`
Expected: `BUILD SUCCESSFUL`, `RefreshPolicyTest` 4개 통과, 컴파일(WorkManager·Glance import) OK.

- [ ] **Step 5: 완료 보고**(커밋 금지).

---

### Task 4: Glance 위젯 화면(반응형) · 리시버 예약 · ↻ 즉시 갱신

**Files:**
- Modify(전체 교체): `android/app/src/main/kotlin/com/toyunity/stockmaster/widget/StockWidget.kt`, `…/widget/StockWidgetReceiver.kt`
- Create: `…/widget/RefreshAction.kt`

**Interfaces:**
- Consumes: T2 `WidgetJson.parse`, `Format.*`, `WidgetItem.held`; T3 `Prefs`(상태 상수), `Scheduler.ensureScheduled/cancel/refreshNow`, `RefreshPolicy.manualAllowed`; T1 `Colors`, `SetupActivity`.
- Produces: `class StockWidget : GlanceAppWidget`(T3 `RefreshWorker`가 `updateAll`), `class RefreshAction : ActionCallback`.
- 실기기 검증은 T8(마스터) — 이 태스크의 게이트는 컴파일·lint.

- [ ] **Step 1: 구현 — `StockWidget.kt` 전체 교체**

```kotlin
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
```
컴파일 오류가 나면 Glance 1.2.0 API 이름을 IDE 없이 확인하는 법: `find ~/.gradle/caches -name "glance-appwidget-1.2.0*.jar" | head -1` 을 `unzip -l`로 열어 클래스명을 보거나, `./gradlew :app:dependencies`로 버전을 확인한다. 이름만 바뀐 경우(예: `actionStartActivity` 패키지) 최소 수정으로 맞추고 주석에 날짜와 함께 적는다.

- [ ] **Step 2: `StockWidgetReceiver.kt` 전체 교체 + `RefreshAction.kt`**

```kotlin
package com.toyunity.stockmaster.widget

import android.appwidget.AppWidgetManager
import android.content.Context
import androidx.glance.appwidget.GlanceAppWidget
import androidx.glance.appwidget.GlanceAppWidgetReceiver

/** 위젯 추가·부팅·30분 백스톱(updatePeriodMillis) → 예약 보장(KEEP). 마지막 위젯 제거 → 취소(네트워크 0). */
class StockWidgetReceiver : GlanceAppWidgetReceiver() {
    override val glanceAppWidget: GlanceAppWidget = StockWidget()

    override fun onUpdate(context: Context, appWidgetManager: AppWidgetManager, appWidgetIds: IntArray) {
        super.onUpdate(context, appWidgetManager, appWidgetIds)
        Scheduler.ensureScheduled(context)
    }

    override fun onDisabled(context: Context) {
        super.onDisabled(context)
        Scheduler.cancel(context)
    }
}
```

`…/widget/RefreshAction.kt`:
```kotlin
package com.toyunity.stockmaster.widget

import android.content.Context
import androidx.glance.GlanceId
import androidx.glance.action.ActionParameters
import androidx.glance.appwidget.action.ActionCallback

/** ↻ 탭 — 10초 디바운스 뒤 즉시 작업(expedited). 위젯 숫자는 수 초 안에 바뀐다. */
class RefreshAction : ActionCallback {
    override suspend fun onAction(context: Context, glanceId: GlanceId, parameters: ActionParameters) {
        val prefs = Prefs(context)
        val now = System.currentTimeMillis()
        if (!RefreshPolicy.manualAllowed(prefs.lastManualAt, now)) return
        prefs.lastManualAt = now
        Scheduler.refreshNow(context)
    }
}
```

- [ ] **Step 3: 빌드·린트·기존 테스트 통과 확인**

Run: `cd android && ./gradlew --console=plain assembleDebug lint test`
Expected: `BUILD SUCCESSFUL`. lint 에러 0(경고는 보고에 적는다). 릴리스 크기 예비 확인: `./gradlew assembleRelease && ls -la app/build/outputs/apk/release/` — debug 서명 폴백으로도 빌드돼야 하고 3MB 이하.

- [ ] **Step 4: 완료 보고**(커밋 금지). API 이름을 바꿨으면 무엇을 무엇으로, 근거(jar 클래스명)와 함께.

---

### Task 5: SetupActivity — 딥링크·붙여넣기·연결 테스트·홈 위젯 추가·배터리 제한 해제

**Files:**
- Modify(전체 교체): `android/app/src/main/kotlin/com/toyunity/stockmaster/widget/SetupActivity.kt`
- Create: `android/app/src/main/res/layout/activity_setup.xml`
- Modify: `android/app/src/main/res/values/strings.xml`(문자열 추가)

**Interfaces:**
- Consumes: T3 `Prefs`, `WidgetApi.fetch`, `ApiResult`, `Scheduler.refreshNow`; T2 `WidgetJson.parse`; T1 `StockWidgetReceiver`(위젯 고정 요청 대상).
- Produces: 런처 아이콘으로 열리는 설정 화면, `stockmaster://setup?base=…&token=…` 처리.

- [ ] **Step 1: 레이아웃·문자열**

`android/app/src/main/res/layout/activity_setup.xml`:
```xml
<?xml version="1.0" encoding="utf-8"?>
<ScrollView xmlns:android="http://schemas.android.com/apk/res/android"
    android:layout_width="match_parent" android:layout_height="match_parent">
    <LinearLayout
        android:layout_width="match_parent" android:layout_height="wrap_content"
        android:orientation="vertical" android:padding="24dp">
        <TextView android:layout_width="match_parent" android:layout_height="wrap_content"
            android:text="@string/setup_title" android:textSize="20sp" android:textStyle="bold" />
        <TextView android:layout_width="match_parent" android:layout_height="wrap_content"
            android:layout_marginTop="6dp" android:text="@string/setup_intro" android:textSize="13sp" />

        <EditText android:id="@+id/base_url" android:layout_width="match_parent" android:layout_height="wrap_content"
            android:layout_marginTop="18dp" android:hint="@string/hint_base_url"
            android:inputType="textUri" android:importantForAutofill="no" android:minHeight="48dp" />
        <EditText android:id="@+id/token" android:layout_width="match_parent" android:layout_height="wrap_content"
            android:layout_marginTop="8dp" android:hint="@string/hint_token"
            android:inputType="textPassword" android:importantForAutofill="no" android:minHeight="48dp" />
        <Button android:id="@+id/save" android:layout_width="match_parent" android:layout_height="wrap_content"
            android:layout_marginTop="12dp" android:text="@string/btn_save" />
        <TextView android:id="@+id/status" android:layout_width="match_parent" android:layout_height="wrap_content"
            android:layout_marginTop="8dp" android:textSize="14sp" />

        <Button android:id="@+id/pin" android:layout_width="match_parent" android:layout_height="wrap_content"
            android:layout_marginTop="20dp" android:text="@string/btn_pin" />
        <Button android:id="@+id/battery" android:layout_width="match_parent" android:layout_height="wrap_content"
            android:layout_marginTop="8dp" android:text="@string/btn_battery" />
        <TextView android:layout_width="match_parent" android:layout_height="wrap_content"
            android:layout_marginTop="12dp" android:text="@string/setup_help" android:textSize="12sp" />
    </LinearLayout>
</ScrollView>
```

`android/app/src/main/res/values/strings.xml`에 추가(기존 두 줄 유지):
```xml
    <string name="setup_title">Stock Master 위젯 설정</string>
    <string name="setup_intro">사파리/크롬으로 서버의 /widget-setup 을 열고 [앱에 자동 입력]을 탭하면 아래가 자동으로 채워집니다. 안 되면 [토큰 복사] 값을 붙여넣으세요.</string>
    <string name="hint_base_url">서버 주소 (https://…)</string>
    <string name="hint_token">위젯 토큰</string>
    <string name="btn_save">저장하고 연결 확인</string>
    <string name="btn_pin">홈 위젯 추가</string>
    <string name="btn_battery">배터리 제한 해제</string>
    <string name="setup_help">위젯을 커버·메인 화면에 각각 추가하세요.\n\n⚠ One UI는 안 여는 앱을 며칠 뒤 잠들게 해 갱신이 멈춥니다. [배터리 제한 해제]를 누른 뒤, 설정 → 배터리 → 백그라운드 사용 제한 → 절전 예외 앱에 “Stock Master 위젯”을 추가하세요. 펌웨어 업데이트 뒤엔 목록을 다시 확인하세요.\n\n토큰·APK를 타인과 공유하지 마세요(KIS 시세 제3자 제공은 약관 위반, 보유·손익 노출).</string>
```

- [ ] **Step 2: `SetupActivity.kt` 전체 교체**

```kotlin
package com.toyunity.stockmaster.widget

import android.app.Activity
import android.appwidget.AppWidgetManager
import android.content.ComponentName
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.provider.Settings
import android.widget.Button
import android.widget.EditText
import android.widget.TextView

/**
 * 설정 화면 하나(Views — Compose UI는 APK +2MB라 기각, 스펙 §기각한 대안).
 * 진입: 런처 아이콘 · 위젯의 미설정/401 탭 · 딥링크 stockmaster://setup?base=…&token=…(/widget-setup 페이지 버튼).
 */
class SetupActivity : Activity() {
    private lateinit var prefs: Prefs
    private lateinit var baseField: EditText
    private lateinit var tokenField: EditText
    private lateinit var status: TextView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_setup)
        prefs = Prefs(this)
        baseField = findViewById(R.id.base_url)
        tokenField = findViewById(R.id.token)
        status = findViewById(R.id.status)
        baseField.setText(prefs.baseUrl ?: "")
        tokenField.setText(prefs.token ?: "")
        findViewById<Button>(R.id.save).setOnClickListener { saveAndTest() }
        findViewById<Button>(R.id.pin).setOnClickListener { requestPin() }
        findViewById<Button>(R.id.battery).setOnClickListener { openBatteryDialog() }
        handleDeepLink(intent)
    }

    override fun onNewIntent(intent: Intent) {   // singleTop — 열려 있는 동안 딥링크가 오면 여기로
        super.onNewIntent(intent)
        handleDeepLink(intent)
    }

    /** https 주소만 받는다. 채운 뒤 곧바로 저장·연결 확인(초보 최대 실패 지점 = 토큰 옮기기 → 탭 한 번). */
    private fun handleDeepLink(i: Intent?) {
        val u = i?.data ?: return
        if (u.scheme != "stockmaster" || u.host != "setup") return
        val base = u.getQueryParameter("base") ?: return
        val token = u.getQueryParameter("token") ?: return
        if (!base.startsWith("https://")) { status.text = "https 주소만 허용해요"; return }
        baseField.setText(base)
        tokenField.setText(token)
        saveAndTest()
    }

    private fun saveAndTest() {
        val base = baseField.text.toString().trim().trimEnd('/')
        val token = tokenField.text.toString().trim()
        if (!base.startsWith("https://") || token.length < 20) {   // 서버도 20자 미만 토큰을 거부한다(fail-closed)
            status.text = "https 주소와 20자 이상 토큰이 필요해요"
            return
        }
        prefs.baseUrl = base
        prefs.token = token
        status.text = "연결 확인 중…"
        Thread {
            val r = WidgetApi.fetch(base, token)
            val msg = when (r) {
                is ApiResult.Ok -> {
                    val n = runCatching { WidgetJson.parse(r.body).items.size }.getOrNull()
                    if (n != null) "연결 OK · ${n}종목 — 이제 [홈 위젯 추가]" else "응답을 읽을 수 없어요 — 주소를 확인하세요"
                }
                ApiResult.Unauthorized -> "토큰이 맞지 않아요 — /widget-setup 에서 다시 복사하세요"
                is ApiResult.Failure -> if (r.reason == "http 503") "서버가 위젯을 끄거나 시세를 못 가져와요"
                                        else "서버(맥북)에 연결할 수 없어요 — 맥이 깨어 있는지 확인"
            }
            runOnUiThread { status.text = msg }
            Scheduler.refreshNow(this)                     // 위젯도 곧바로 갱신(UNAUTHORIZED 등 상태 전파)
        }.start()
    }

    /** One UI 확인 대화상자로 홈에 위젯을 놓는다. 커버·메인 각각 한 번. 미지원 런처면 수동 경로 안내. */
    private fun requestPin() {
        val m = AppWidgetManager.getInstance(this)
        if (m.isRequestPinAppWidgetSupported) {
            m.requestPinAppWidget(ComponentName(this, StockWidgetReceiver::class.java), null, null)
        } else {
            status.text = "홈 화면을 길게 눌러 위젯 → Stock Master 위젯을 추가하세요"
        }
    }

    /** 안드로이드 표준 배터리 최적화 제외 대화상자(1탭). 삼성 '절전 예외 앱'은 별도(공개 인텐트 없음 → 도움말). */
    private fun openBatteryDialog() {
        startActivity(Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, Uri.parse("package:$packageName")))
    }
}
```

- [ ] **Step 3: 빌드·린트 통과 확인**

Run: `cd android && ./gradlew --console=plain assembleDebug lint test`
Expected: `BUILD SUCCESSFUL`, lint 에러 0. (`REQUEST_IGNORE_BATTERY_OPTIMIZATIONS` 관련 lint는 Play 정책 경고라 에러가 아니다 — 에러로 뜨면 `lint.xml`이 아니라 해당 줄에 `@SuppressLint("BatteryLife")`를 붙이고 사이드로드 개인 앱이라는 주석을 단다.)

- [ ] **Step 4: 완료 보고**(커밋 금지).

---
### Task 6: 서버 — 설치 페이지 갤럭시 섹션 · APK 라우트 · 설정 · 테스트 · Makefile · .env.example

**Files:**
- Modify: `backend/config.py`(`widget_token` 필드 아래), `backend/api/app.py`(`widget_setup_page` + `/widget-setup/rotate` 아래 새 라우트), `backend/report/widget_setup.py`(CSS·템플릿·`render_widget_setup` 시그니처), `tests/test_auth.py:115-119`(PROTECTED), `Makefile`, `.env.example`
- Create: `tests/test_android_widget.py`

**Interfaces:**
- Consumes: T1의 `android/app/src/main/kotlin/com/toyunity/stockmaster/widget/Colors.kt`(색 드리프트 테스트가 읽는다).
- Produces: `settings.android_apk_path: str`(기본 `<루트>/data/android/StockMasterWidget.apk`, env `SM_ANDROID_APK_PATH`); `GET /widget-setup/android.apk`(200 파일 / 404 JSON, 게이트 뒤); `render_widget_setup(token, base_url, apk_available=False)`; `make android`.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_android_widget.py`(신규):
```python
"""갤럭시(안드로이드) 위젯 — 설치 페이지 갤럭시 섹션·APK 라우트·theme.py 색 드리프트.

설계: docs/superpowers/specs/2026-09-04-android-widget-design.md
- 딥링크 stockmaster://setup?base=…&token=… 는 페이지(게이트 뒤)에만 있고 스크립트 블록엔 토큰이 없다.
- APK 버튼은 파일이 있을 때만(없으면 `make android` 안내). 라우트는 파일 없으면 404, 있으면 APK MIME.
- Colors.kt는 theme.py 토큰의 복사본 — 값이 어긋나면 여기서 먼저 깨진다.
"""
import html as _html
import os
import re
import urllib.parse

TOKEN = "t" * 32
BASE = "https://example.ts.net"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COLORS_KT = os.path.join(ROOT, "android", "app", "src", "main", "kotlin",
                         "com", "toyunity", "stockmaster", "widget", "Colors.kt")


def _page(apk=False):
    from backend.report.widget_setup import render_widget_setup
    return render_widget_setup(TOKEN, BASE, apk_available=apk)


def test_android_section_has_deeplink_with_encoded_token_and_base():
    page = _page()
    link = "stockmaster://setup?base=%s&token=%s" % (
        urllib.parse.quote(BASE, safe=""), urllib.parse.quote(TOKEN, safe=""))
    assert _html.escape(link) in page                 # href는 HTML 이스케이프(& → &amp;)
    assert "갤럭시" in page and "절전 예외 앱" in page


def test_apk_button_only_when_file_exists():
    assert 'href="/widget-setup/android.apk"' not in _page(apk=False)
    assert "make android" in _page(apk=False)
    assert 'href="/widget-setup/android.apk"' in _page(apk=True)


def test_script_block_still_has_no_token():
    """갤럭시 섹션(토큰이 든 링크)이 스크립트 블록을 오염시키지 않는다 — 치환 순서 규칙."""
    m = re.search(r'<pre id="script">([\s\S]*?)</pre>', _page(apk=True))
    assert m and TOKEN not in _html.unescape(m.group(1))


def _client(tmp_path, monkeypatch, apk_path):
    from fastapi.testclient import TestClient
    from backend.config import Settings, settings as gs
    from backend.api.app import create_app
    monkeypatch.setattr(gs, "cache_dir", str(tmp_path))
    monkeypatch.setattr(gs, "default_account", "master@gmail.com")
    s = Settings(cache_dir=str(tmp_path), flow_mode="demo", default_account="master@gmail.com",
                 android_apk_path=apk_path, kis_app_key=None, kis_app_secret=None, dart_api_key=None)
    return TestClient(create_app(s))


def test_apk_route_404_without_file_then_200_with_file(tmp_path, monkeypatch):
    apk = tmp_path / "StockMasterWidget.apk"
    c = _client(tmp_path, monkeypatch, str(apk))
    assert c.get("/widget-setup/android.apk").status_code == 404
    assert 'href="/widget-setup/android.apk"' not in c.get("/widget-setup").text   # 파일 없으면 버튼도 없다
    apk.write_bytes(b"PK\x03\x04fake-apk")
    r = c.get("/widget-setup/android.apk")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/vnd.android.package-archive")
    assert r.content == b"PK\x03\x04fake-apk"
    assert 'href="/widget-setup/android.apk"' in c.get("/widget-setup").text


def _theme_tokens():
    """theme.py의 --up/--down/--flat/--warn 값 — 첫 두 개가 (라이트, 다크)."""
    from backend.report import theme
    src = open(theme.__file__, encoding="utf-8").read()
    found = {}
    for name, hexv in re.findall(r"--(up|down|flat|warn):\s*(#[0-9a-fA-F]{6})", src):
        found.setdefault(name, []).append(hexv.lower())
    return found


def test_kotlin_colors_match_theme_tokens():
    assert os.path.isfile(COLORS_KT), COLORS_KT
    kt = open(COLORS_KT, encoding="utf-8").read().lower()
    tokens = _theme_tokens()
    for name in ("up", "down", "flat", "warn"):
        assert len(tokens[name]) >= 2, name                      # 라이트 + 다크
        for hexv in tokens[name][:2]:
            assert "0xff" + hexv[1:] in kt, "%s %s 가 Colors.kt에 없음" % (name, hexv)
```

`tests/test_auth.py` PROTECTED 목록에 추가(기존 항목 유지):
```python
PROTECTED = ["/", "/live/000660", "/api/live/000660/stream",
             "/api/candles/000660", "/scanner", "/api/scanner", "/api/semi",
             "/api/worldidx",
             "/api/watch/000660", "/api/widget", "/widget-setup",
             "/widget-setup/rotate", "/widget-setup/android.apk", "/api/watchlist"]
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_android_widget.py tests/test_auth.py -q -p no:warnings`
Expected: `test_android_widget.py` — `TypeError: render_widget_setup() got an unexpected keyword argument 'apk_available'` 등으로 실패, PROTECTED의 `/widget-setup/android.apk`는 404(라우트 없음 → 게이트는 302를 내야 하는데… 게이트가 먼저라 302가 날 수도 있다 — 그 경우 이 항목만 먼저 통과하는 것은 정상). 색 드리프트 테스트는 T1의 Colors.kt가 있으면 통과할 수 있다(그래도 둔다 — 회귀 방어용).

- [ ] **Step 3: 구현**

`backend/config.py` — `widget_token` 필드(85행) 바로 아래:
```python
    # 갤럭시 위젯 APK 배포 경로 — GET /widget-setup/android.apk 가 이 파일을 내려준다(게이트 뒤).
    # `make android`가 여기로 복사한다. data/는 gitignore. 없으면 404 + 설치 페이지에 안내(설계 2026-09-04).
    android_apk_path: str = str(_PROJECT_ROOT / "data" / "android" / "StockMasterWidget.apk")   # SM_ANDROID_APK_PATH
```

`backend/api/app.py` — `widget_setup_page`의 마지막 `return`을 아래로(`import os`는 함수 안에서):
```python
        import os
        # no-store — 스크립트가 바뀌면 사파리가 옛 페이지를 서빙해 옛 스크립트를 복사하는 것 방지.
        return HTMLResponse(render_widget_setup(token, "%s://%s" % (scheme, host),
                                                apk_available=os.path.isfile(settings.android_apk_path)),
                            headers={"Cache-Control": "no-store"})
```
`/widget-setup/rotate` 라우트 바로 아래에 추가:
```python
    @app.get("/widget-setup/android.apk")
    def widget_setup_apk():
        """갤럭시 위젯 APK — 게이트 뒤(test_auth PROTECTED). 파일은 `make android`가 data/android/에 둔다.
        APK에 비밀은 없지만(주소·토큰은 런타임 입력) '모든 경로 잠금' 불변식 때문에 공개 예외로 두지
        않는다(설계 2026-09-04). 교체는 8000 재기동 없이 파일만 바꾸면 된다."""
        import os
        from fastapi.responses import FileResponse
        p = settings.android_apk_path
        if not (p and os.path.isfile(p)):
            return JSONResponse({"error": "APK가 없어요 — 맥에서 `make android`로 빌드하세요"}, status_code=404)
        return FileResponse(p, media_type="application/vnd.android.package-archive",
                            filename="StockMasterWidget.apk", headers={"Cache-Control": "no-store"})
```

`backend/report/widget_setup.py`:
1. 상단 import에 `from urllib.parse import quote` 추가.
2. `<style>` 블록의 `button.copy{…}` 선택자를 `button.copy,a.copy{…}`로 바꾸고 그 아래 한 줄 추가(색 없음 — theme 테스트):
```
a.copy{display:inline-block;line-height:24px;text-decoration:none}
```
3. 템플릿의 5단계 `</div>` 다음, `<script>` 앞에 삽입:
```html
<h2 style="margin:24px 0 4px;font-size:17px">🤖 갤럭시(안드로이드) 위젯</h2>
<p style="margin:0 0 6px;font-size:13px;color:var(--text-2)">아이폰의 Scriptable 대신 위젯 전용 앱 하나를 설치합니다.
자세한 사용법: docs/widget-guide.md</p>
<div class="step"><h3>A. APK 설치</h3>
<p>__APK_BLOCK__</p>
<p>다운로드 후 열기 → “출처를 알 수 없는 앱” 허용(브라우저에 1회) → 설치.
업데이트도 같은 방법입니다(같은 서명이라 덮어써짐).</p></div>
<div class="step"><h3>B. 앱에 서버 주소·토큰 자동 입력</h3>
<p><a class="copy" href="__ANDROID_LINK__">앱에 자동 입력</a></p>
<p>탭하면 위젯 앱이 열려 주소·토큰이 저장되고 연결을 확인합니다.
안 열리면 앱을 직접 열고 위 [토큰 복사] 값을 붙여넣으세요.</p></div>
<div class="step"><h3>C. 홈 위젯 추가 → 절전 예외 등록</h3>
<p>앱의 <b>[홈 위젯 추가]</b>로 커버·메인 화면에 각각 추가합니다. 그다음 <b>[배터리 제한 해제]</b>를 누르고,
설정 → 배터리 → 백그라운드 사용 제한 → <b>절전 예외 앱</b>에 “Stock Master 위젯”을 추가하세요 —
One UI는 안 여는 앱을 며칠 뒤 잠들게 해 갱신이 멈춥니다.</p></div>
```
4. 모듈 상수 두 개(템플릿 아래):
```python
_APK_LINK = '<a class="copy" href="/widget-setup/android.apk">APK 다운로드</a>'
_APK_MISSING = ('<span style="color:var(--text-2)">APK가 아직 없어요 — 맥에서 <code>make android</code>를 '
                '실행하면 여기에 다운로드 버튼이 생깁니다.</span>')
```
5. `render_widget_setup` 교체:
```python
def render_widget_setup(token: str, base_url: str, apk_available: bool = False) -> str:
    """설치 페이지 HTML — 토큰은 이 페이지(게이트 뒤)에만, 스크립트엔 절대 없음.
    apk_available: data/android/에 APK가 있을 때만 다운로드 버튼(없으면 `make android` 안내)."""
    base = base_url.rstrip("/")
    script = _SCRIPT.replace("__BASE_URL__", base)
    # 갤럭시 앱 딥링크 — 페이지가 이미 토큰을 평문으로 보여주므로 노출이 늘지 않는다(설계 2026-09-04).
    link = "stockmaster://setup?base=%s&token=%s" % (quote(base, safe=""), quote(token, safe=""))
    return (_TEMPLATE
            .replace("__PWA_HEAD__", _PWA_HEAD)
            .replace("__BASE_CSS__", _BASE_CSS)
            .replace("__SCRIPT__", escape(script))
            # ── 여기부터 데이터. 자산 치환 뒤여야 한다(치환 순서 규칙, CLAUDE.md) ──
            .replace("__APK_BLOCK__", _APK_LINK if apk_available else _APK_MISSING)
            .replace("__ANDROID_LINK__", escape(link))
            .replace("__TOKEN__", escape(token)))
```

`Makefile` 전체:
```make
PY := .venv/bin/python

.PHONY: verify test eval eval-update ops ci android
verify:      ; $(PY) -m harness verify
test:        ; $(PY) -m harness test
eval:        ; $(PY) -m harness eval
eval-update: ; $(PY) -m harness eval --update
ops:         ; $(PY) -m harness ops
ci: test eval
# 갤럭시 위젯 APK — android/keystore.properties 가 있으면 릴리스 키, 없으면 debug 키(설계 2026-09-04).
# 산출물은 data/android/(gitignore). 8000이 /widget-setup/android.apk 로 바로 서빙한다(재기동 불필요).
android:     ; cd android && ./gradlew --quiet assembleRelease && mkdir -p ../data/android && cp app/build/outputs/apk/release/app-release.apk ../data/android/StockMasterWidget.apk && ls -la ../data/android/StockMasterWidget.apk
```

`.env.example` — `SM_WIDGET_TOKEN` 블록의 섹션 제목을 `# ── 위젯(아이폰·갤럭시) / 계정 ─…`로 바꾸고 `SM_DEFAULT_ACCOUNT=` 위에 추가(주석 처리 — 빈 값이면 기본 경로가 아니라 빈 문자열이 되므로 `# SM_AUTH_ENABLED=true` 선례처럼 주석으로):
```
# 갤럭시 위젯 APK 경로. 기본 data/android/StockMasterWidget.apk(`make android`가 만든다) — 보통 건드리지 않는다.
# SM_ANDROID_APK_PATH=/path/to/StockMasterWidget.apk
```

- [ ] **Step 4: 통과 확인(표적 테스트만 — 같은 워크트리에서 다른 워커가 일하고 있다)**

Run: `.venv/bin/python -m pytest tests/test_android_widget.py tests/test_widget_setup.py tests/test_auth.py tests/test_us_page.py tests/test_theme.py -q -p no:warnings`
Expected: 전부 passed. 특히 `test_theme.py::test_pages_do_not_hardcode_colors`(새 헥스 없음)와 `test_us_page.py`(자리표시자 잔존 없음).

- [ ] **Step 5: 실렌더 검증(화면을 고쳤다 — 8000은 건드리지 않는다)**

Run: `.venv/bin/python -m harness verify --only widget`
Expected: 통과, 가로 오버플로 없음(`scrollWidth == clientWidth == 390`). 캡처 `harness/artifacts/widget-{light,dark}.png` — **실 토큰이 찍히므로 README·공유 자료에 넣지 않는다.**

- [ ] **Step 6: 완료 보고**(커밋 금지). Step 2에서 실제로 빨갰던 테스트, verify 결과(오버플로 유무)를 적는다.

---

### Task 7: 문서 — 위젯 가이드 갤럭시 섹션 · README

**Files:**
- Modify: `docs/widget-guide.md`, `README.md`

**Interfaces:**
- Consumes: T5·T6의 사용자 흐름(버튼 이름 `[앱에 자동 입력]`, `[홈 위젯 추가]`, `[배터리 제한 해제]`, 설정 경로).

- [ ] **Step 1: `docs/widget-guide.md`**

제목을 `# 홈 위젯 — 설치·사용 가이드(아이폰 · 갤럭시)`로. `## 설치 (5단계, 약 5분)`을 `## 아이폰 설치 (5단계, 약 5분)`로 바꾸고, 그 섹션이 끝난 뒤(`## 사용법` 앞)에 삽입:
```markdown
## 갤럭시(안드로이드) 설치 (5단계, 약 5분)

갤럭시는 Scriptable이 없어 **위젯 전용 앱**을 설치합니다(앱은 서버의 `/api/widget`만 읽고, PWA는 지금처럼 브라우저로 씁니다).

1. **폰 브라우저로 `https://<내-머신>.ts.net/widget-setup` 접속** — 본인 계정으로 구글 로그인 + 2FA.
2. **[APK 다운로드] → 열기 → “출처를 알 수 없는 앱” 허용(브라우저에 1회) → 설치.**
   버튼이 없고 “APK가 아직 없어요”가 보이면 맥에서 `make android`를 먼저 실행합니다.
3. **[앱에 자동 입력] 탭** → 위젯 앱이 열리며 서버 주소·토큰이 저장되고 “연결 OK · N종목”이 뜹니다.
   안 열리면 앱을 직접 열어 [토큰 복사] 값을 붙여넣고 [저장하고 연결 확인].
4. **앱의 [홈 위젯 추가]** → 확인 → 홈에 위젯이 놓입니다. **커버 화면과 메인 화면은 홈이 따로**라 각각 한 번씩.
   (수동: 홈 길게 누르기 → 위젯 → Stock Master 위젯.) 크기는 원하는 대로 늘려도 됩니다 — 행 수가 높이에 맞춰 바뀝니다.
5. **절전 예외 등록(빼먹으면 며칠 뒤 갱신이 멈춥니다)** — 앱의 **[배터리 제한 해제]**(시스템 대화상자 → 허용) 그리고
   **설정 → 배터리 → 백그라운드 사용 제한 → 절전 예외 앱 → “Stock Master 위젯” 추가.**
   One UI는 안 여는 앱을 자동으로 잠들게 하는데, 위젯 앱은 원래 열지 않는 앱이라 정확히 그 대상입니다. 펌웨어 업데이트 뒤 목록을 다시 확인하세요.

**업데이트**: 같은 페이지에서 새 APK를 내려받아 설치하면 덮어써집니다(같은 서명). 토큰 재입력은 필요 없습니다.
```

`## 사용법` 표 아래(`- **갱신 주기**` 항목 앞)에 추가:
```markdown
- **갤럭시 위젯의 ↻ 갱신은 즉시 반영**됩니다(수 초 안에 숫자가 바뀜 — iOS와 다른 점). 몸통 탭은 PWA를 엽니다.
  자동 갱신은 장중 15분·장외엔 다음 개장까지 잠들며, 맥이 잠자면 “오프라인·”이 붙습니다.
```

`## 문제 해결` 표에 행 추가:
```markdown
| (갤럭시) 위젯이 며칠째 같은 시각 | 절전에 걸렸을 가능성 — 설정 → 배터리 → 백그라운드 사용 제한 → 절전 예외 앱에 있는지 확인(펌웨어 업데이트가 목록을 되돌리기도 함) |
| (갤럭시) “설정이 필요해요” | 앱을 열어 주소·토큰 입력(또는 /widget-setup의 [앱에 자동 입력]) |
| (갤럭시) APK 설치가 막힘 | 다운로드한 브라우저에 “출처를 알 수 없는 앱” 설치 권한 부여 → 다시 열기. 업데이트가 막히면 서명이 다른 것 — 삭제 후 재설치(토큰 재입력) |
```

`## 실기기 검증 체크리스트` 끝에 추가:
```markdown
- [ ] (갤럭시) 커버·메인 양쪽에 위젯 표시, 크기 변경 시 행 수가 따라옴, 다크·라이트 색(상승 빨강/하락 파랑)
- [ ] (갤럭시) ↻ 탭 → 수 초 안에 갱신시각이 바뀜 · 몸통 탭 → PWA
- [ ] (갤럭시) [토큰 재발급] 후 위젯이 “토큰이 맞지 않아요”로 바뀌고, 앱에서 새 토큰 저장 시 복구
- [ ] (갤럭시) 절전 예외 등록 뒤 다음 날에도 갱신시각이 살아 있음 · 설정 → 배터리의 앱 사용량 1% 미만
```

- [ ] **Step 2: `README.md`**

- `### \`/widget-setup\` — 아이폰 홈 위젯 설치` 제목을 `### \`/widget-setup\` — 홈 위젯 설치(아이폰 Scriptable · 갤럭시 앱)`로 바꾸고 문단 끝에 추가:
```markdown
갤럭시는 **위젯 전용 앱**(`android/`, Kotlin + Jetpack Glance)을 이 페이지에서 APK로 내려받아 설치하고,
[앱에 자동 입력] 링크(`stockmaster://setup`)로 주소·토큰을 넣는다. 앱은 `/api/widget`만 읽는 소비자다 —
서버 힌트를 따르는 WorkManager 1회성 체인으로 장중 15분마다 1건 요청, 탭하면 즉시 갱신(iOS엔 없는 기능).
설계: `docs/superpowers/specs/2026-09-04-android-widget-design.md`.
```
- 아키텍처 그림 첫 줄 `아이폰 사파리 / 홈화면 PWA`를 `아이폰 사파리 / 홈화면 PWA  ·  위젯(아이폰 Scriptable · 갤럭시 앱 android/)`로.
- `### 검증` 코드블록 마지막에 한 줄:
```bash
make android  # 갤럭시 위젯 APK 빌드 → data/android/StockMasterWidget.apk (8000 재기동 불필요)
```

- [ ] **Step 3: 확인·보고**

Run: `grep -n "갤럭시" docs/widget-guide.md README.md | head` — 섹션·행이 들어갔는지 눈으로 확인. 문서 변경이라 테스트 없음(CLAUDE.md 예외). 완료 보고(커밋 금지).

---

### Task 8 (코디네이터 직접): 서명 키 · 릴리스 APK · 전체 검증 · 리뷰 · 커밋 · 병합

**Files:** `data/android/release.jks`, `android/keystore.properties`(둘 다 gitignore, 절대 커밋 금지), 커밋·병합.

- [ ] **Step 1: 릴리스 키스토어 1회 생성**(비밀번호는 파일에만 — 채팅·로그·보고에 찍지 않는다)

```bash
mkdir -p /Users/toyunity/dev/stock_master/data/android
PW=$(python3 -c "import secrets; print(secrets.token_urlsafe(24))")
keytool -genkeypair -v -keystore /Users/toyunity/dev/stock_master/data/android/release.jks \
  -alias stockmaster -keyalg RSA -keysize 2048 -validity 10000 \
  -storepass "$PW" -keypass "$PW" -dname "CN=Stock Master Widget, O=toyunity"
umask 077; cat > <워크트리>/android/keystore.properties <<EOF
storeFile=/Users/toyunity/dev/stock_master/data/android/release.jks
storePassword=$PW
keyAlias=stockmaster
keyPassword=$PW
EOF
unset PW
```
병합 뒤 메인 체크아웃(`/Users/toyunity/dev/stock_master/android/keystore.properties`)에도 같은 파일을 복사한다(gitignore라 병합으로 안 온다).

- [ ] **Step 2: 릴리스 빌드·크기**

Run(워크트리 루트): `make android`
Expected: `data/android/StockMasterWidget.apk` 생성, 크기 3MB 이하(`ls -la`). 서명 확인: `/opt/homebrew/share/android-commandlinetools/build-tools/36.0.0/apksigner verify --print-certs data/android/StockMasterWidget.apk | head -3` → `CN=Stock Master Widget`.

- [ ] **Step 3: 전체 검증**

```bash
make test && make eval && make verify            # verify는 widget 화면 포함 6화면
cd android && ./gradlew --console=plain lint test
```
Expected: 전부 통과. eval 골든은 변경 없음(판정 문구를 건드리지 않았다).

- [ ] **Step 4: 커밋(태스크 묶음별, 트레일러 포함) → 코드 리뷰 → 병합**

```bash
git add android/ .gitignore && git commit -m "feat(android): 갤럭시 위젯 전용 앱 — Glance 반응형 위젯 + WorkManager 1회성 체인 + 설정 화면(딥링크)"
git add backend/ tests/ Makefile .env.example && git commit -m "feat(widget-setup): 갤럭시 섹션·딥링크·APK 배포 라우트(게이트 뒤) + theme 색 드리프트 테스트"
git add docs/ README.md && git commit -m "docs(widget): 갤럭시 설치 가이드 — 절전 예외 앱 등록을 설치 단계로"
```
리뷰는 `superpowers:requesting-code-review`(스펙 대비 누락·보안·CLAUDE.md 규칙), 지적 반영 후 `superpowers:finishing-a-development-branch`로 `main`에 병합(`/Users/toyunity/dev/stock_master`에서 `git merge --no-ff toyunity/feat-android-widget`).

- [ ] **Step 5: 배포(마스터 승인 필요한 단계 — 먼저 묻는다)**

1. **8000 재기동**(새 라우트 반영) — `.venv/bin/python`으로, `docs`의 서버 운영 메모·`server-restart-ops` 절차. **묻지 않고 하지 않는다.**
2. 메인 체크아웃에서 `make android` → `data/android/StockMasterWidget.apk` → `/widget-setup`에 [APK 다운로드]가 보이는지 `make ops`/브라우저로 확인.
3. 마스터: 폰에서 가이드 5단계 → 실기기 체크리스트 → 실측(커버·메인 실제 dp 버킷, 24h 배터리 %)을 `StockWidget.kt` 주석과 `android/README.md`에 날짜와 함께 기록.

---

## 실행 — Orca 오케스트레이션(코디네이터 메모)

**Run**: `orca orchestration run-create --objective "갤럭시 Z Fold 8 위젯 전용 앱 — docs/superpowers/plans/2026-09-04-android-widget.md 구현" --json`
**워크트리**: `1ce39499-24ba-44d6-b64a-4cbb474e0fde::/Users/toyunity/orca/workspaces/stock_master/feat-android-widget`(브랜치 `toyunity/feat-android-widget`, `.venv`는 메인 체크아웃 심링크). 워커 전부 이 워크트리, `--agent claude`.

**DAG**: T1 → {T2, T3, T6, T7} → {T4(T2+T3), T5(T2+T3)} → T8(코디네이터). 웨이브마다 `check --wait --types worker_done,escalation,question`, 완료된 워커는 즉시 `worker-release`(다음 태스크가 같은 에이전트면 `worker-start --terminal`로 이관).

**워커 브리프 골격**(태스크 스펙 앞에 붙인다):
```
[태스크 N] <제목> — docs/superpowers/plans/2026-09-04-android-widget.md 의 "Task N" 을 그대로 구현한다.
스펙(정본): docs/superpowers/specs/2026-09-04-android-widget-design.md. CLAUDE.md 를 먼저 읽어라.

## 절대 금지
- 포트 8000 을 죽이거나 재기동하지 마라(마스터 실서비스). 실 KIS 호출·토큰 발급 금지.
- git commit / git push 금지 — 같은 워크트리에서 다른 워커가 동시에 일한다. 커밋은 코디네이터가 한다.
- 계획에 없는 파일을 만들거나 다른 태스크의 파일을 고치지 마라(충돌). 필요하면 ask 로 물어라.
- 새 의존성·새 추상화 금지. 가장 짧은 diff. Python 은 3.9 문법만. 실측한 사실은 날짜와 함께 주석에.

## 테스트
- 안드로이드: cd android && ./gradlew --console=plain <계획의 명령>. 첫 빌드는 느리다(의존성 다운로드) — 기다려라.
- 서버: 전체 make test 금지(다른 워커의 편집 중간 상태를 본다). 계획에 적힌 표적 pytest 만.
- TDD: 먼저 실패하는 테스트를 쓰고 실제로 빨간지 확인한 뒤 최소 수정(문서 태스크는 예외).

## 끝나면
worker_done 으로 보고: 무엇을 바꿨는지 · 테스트가 수정 전에 실제로 빨갰는지 · 빌드에 실제로 쓰인 버전/바꾼 것 ·
남은 것/걱정. --files-modified 에 건드린 파일 전부.
```
