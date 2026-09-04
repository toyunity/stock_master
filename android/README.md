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
- 2026-09-04: 계획 그대로 첫 시도에 통과 — `./gradlew --console=plain assembleDebug test lint` BUILD SUCCESSFUL(1m 6s, 의존성 다운로드 포함).
  Gradle 9.7.1(brew 9.7.1 → 래퍼 bin) · AGP 9.4.0 · 내장 KGP 2.2.10(`buildEnvironment`로 확인) · Compose 컴파일러 플러그인 2.2.10 ·
  JDK 25.0.2 Temurin(기본 `java`, `org.gradle.java.home` 미설정 — 필요 없었다). `buildFeatures { compose = true }` 경고 없음(그대로 둠).
  Step 7 대응 ①②③ 중 바꾼 것 없음. SmokeTest 1건 통과(org.json 실물). 디버그 APK 13.9MB(미축소 — 3MB 예산은 R8 릴리스 기준, T8).
  lint 0 errors / 10 warnings(OldTargetApi·GradleDependency "compileSdk 37 있음"·DataExtractionRules(allowBackup, Android 12+ 폐기 예고)·
  HardcodedText×3(미리보기 레이아웃)·MonochromeLauncherIcon·ObsoleteSdkInt·Overdraw) — 전부 경고, 게이트 통과.
