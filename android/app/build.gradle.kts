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
        versionCode = 5      // 릴리스마다 수동 +1(같은 번호 재설치도 되지만 관례). 2 = 2026-09-04 실기기 1차 · 3 = 글자 크기 설정 · 4 = 줄 높이 실측 보정 · 5 = 패딩·구분선 축소
        versionName = "1.4"
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
