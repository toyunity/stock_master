# 갤럭시 Z Fold 8 홈 위젯(안드로이드 네이티브, 위젯 전용 앱) — 설계

날짜: 2026-09-04 · 상태: **설계 승인(마스터, 2026-09-04) · 구현 전** — 구현 계획은 `docs/superpowers/plans/2026-09-04-android-widget.md`.

> 이 문서는 "그때 무엇을 왜 결정했나"의 기록이다. 현재 상태는 `README.md`.

## 목적·결정

마스터가 아이폰 16 Pro에서 **갤럭시 Z Fold 8**로 옮긴다. 홈 화면 위젯(관심종목 시세·보유 손익)은
지금 Scriptable(iOS 전용)이 그리고 있어 갤럭시에는 없다. 안드로이드의 PWA는 홈 위젯을 만들 수
없으므로(2026-09-04 기준 크롬·삼성인터넷 모두 미지원) **위젯만 맡는 네이티브 앱**을 하나 만든다.

**마스터 확정 결정 3가지(2026-09-04)**:
1. 방식 = **위젯 전용 네이티브 앱**(Kotlin + Jetpack Glance + WorkManager). PWA는 지금처럼 브라우저·홈화면 PWA로 쓴다.
   KWGT/Tasker 노코드 위젯, PWA 전체의 네이티브화는 기각(§기각한 대안).
2. 빌드 도구 = **이 맥에 Android SDK 커맨드라인 툴 설치**(Android Studio 없음). JDK는 이미 있는 21(Microsoft OpenJDK)을 쓴다.
3. 코드 위치 = **이 리포 `android/` 하위**(Orca 워크트리 `~/orca/workspaces/stock_master/feat-android-widget`, 브랜치 `toyunity/feat-android-widget`). 서버 계약 테스트·설치 페이지·가이드와 한 곳에서 관리한다.

앱이 하는 일은 딱 두 가지다: **위젯 하나**(`/api/widget`을 읽어 그린다), **설정 화면 하나**(서버 주소·토큰 입력).
그 외 화면·기능은 만들지 않는다.

## 제약(고지 완료)

- **기기**: Galaxy Z Fold 8(2026-07-22 공개, 08-07 출시). 커버 5.5" 1972×1248(10:16 — 일반 폰 폭에 가깝다),
  메인 7.6" 2448×1848(4:3), Android 17 · One UI 9, Snapdragon 8 Elite Gen 5, 12GB(2026-09-04 위키백과·GSMArena).
  One UI는 **커버·메인 홈 레이아웃이 따로**라 위젯 인스턴스가 화면마다 생기며 크기도 다르다.
- **위젯은 실시간 티커가 아니다**: 아이폰과 같은 근사치다. WorkManager 최소 주기 15분(장중), 밤·주말은 다음 개장까지 잠든다.
  `updatePeriodMillis`는 OS가 30분 미만을 허용하지 않는다(안드로이드 문서, 2026-09-04 확인).
- **One UI 절전이 함정이다**: "사용하지 않는 앱 절전"이 **안 여는 앱을 며칠 뒤 딥슬립**시켜 백그라운드 갱신을 끊는다.
  이 앱은 원래 열지 않는 앱이라 정확히 그 대상이다 → **"절전 예외 앱" 등록을 설치 단계**로 넣는다(문제해결 각주가 아니라).
  dontkillmyapp(2026-09-04): 펌웨어 업데이트 뒤 목록이 되돌아갈 수 있어 가이드에 "업데이트 후 재확인"을 적는다.
- **맥이 잠자면 위젯도 새 값을 못 받는다**(서버가 맥). 마지막 값 + 수신 시각 + "오프라인" 배지로 멈춤을 가시화한다(빈 화면 금지).
- **서버는 Python 3.9·최소 diff**(CLAUDE.md). `/api/widget` 응답 계약은 **테스트로 고정된 화이트리스트이고 보안 결정**
  (세션·2FA 없는 단일 팩터 토큰 표면)이라 **안드로이드 때문에 필드를 늘리지 않는다**. 큰 화면용 지수·옵션 확장은 범위 밖.
- **KIS = 유일 합규 시세 소스, 개인 이용 한정.** 토큰·APK를 타인과 공유하지 않는다(가이드 첫 줄 경고 그대로).
- 검증 서버·워커는 8000을 건드리지 않고 KIS를 호출하지 않는다. 서버 라우트 추가는 **8000 재기동이 있어야 반영**되며 그 단계는 마스터에게 먼저 묻는다.

---

## 아키텍처 개요

```
갤럭시 홈(커버 / 메인 — 인스턴스 각각, 데이터는 공유)
   │  Glance RemoteViews(텍스트 전용)             ▲ updateAll()
   ▼                                              │
StockWidget(Glance) ◀── Prefs(마지막 JSON·수신시각) ◀── RefreshWorker(WorkManager)
   │ 몸통 탭 → PWA 열기(base URL)                        │  GET /api/widget
   │ ↻ 탭 → RefreshAction → 즉시 1회 작업                 │  Authorization: Bearer <계정 토큰>
   │ 401/미설정 탭 → SetupActivity                        ▼
SetupActivity ◀── stockmaster://setup?base=…&token=…   AuthGate(Bearer, 기존) ──▶ /api/widget(기존, 무변경)
   (딥링크·수동 입력·연결 테스트·위젯 고정 요청)
                                                      /widget-setup(기존 페이지 + 갤럭시 섹션)
                                                      /widget-setup/android.apk(신규, 게이트 뒤)
```

앱은 **서버의 소비자일 뿐**이다. 서버 변경은 설치 페이지 섹션과 APK 다운로드 라우트 두 곳(§서버 변경).

## 앱 구성(`android/`)

Gradle 단일 모듈 `app`. 패키지 `com.toyunity.stockmaster.widget`(launchd 라벨 `com.toyunity.stockmaster.*`와 같은 접두).
외부 의존성은 **AndroidX만**: `androidx.glance:glance-appwidget:1.2.0`(2026-08-26 안정판), `androidx.work:work-runtime-ktx`.
네트워크는 `java.net.HttpURLConnection`, JSON은 `org.json`(안드로이드 내장). Retrofit·OkHttp·직렬화 라이브러리 없음(§기각한 대안).

| 파일 | 책임 | 의존 | JVM 테스트 |
|---|---|---|---|
| `StockWidget.kt` | `GlanceAppWidget`. `provideGlance`에서 Prefs를 읽고 `SizeMode.Responsive` 버킷별 화면을 그린다. 색·폰트·탭 액션 | Prefs, Format, Colors | — (실기기) |
| `StockWidgetReceiver.kt` | `GlanceAppWidgetReceiver`. `onEnabled/onUpdate` → 갱신 작업 예약(KEEP), `onDisabled` → 작업 취소 | RefreshWorker | — |
| `RefreshWorker.kt` | `CoroutineWorker`. 요청 1회 → Prefs 저장 → `updateAll` → **다음 1회성 작업 예약**. 예약 규칙은 순수 함수 `nextDelaySec` | WidgetApi, Prefs | `nextDelaySec` |
| `RefreshAction.kt` | Glance `ActionCallback`. ↻ 탭 → 10초 디바운스 후 즉시 작업(REPLACE, 지연 0) | RefreshWorker, Prefs | — |
| `WidgetApi.kt` | `GET {base}/api/widget`, 10초 연결/읽기 타임아웃, Bearer 헤더. 결과: `Ok(json)` / `Unauthorized`(401) / `Failure(사유)` | — | — (네트워크) |
| `WidgetData.kt` | JSON → `WidgetData(open, tradeDate, fetchedAt, refreshAfterSec, items[])`. 계약 소비 규칙(§데이터 계약) | org.json | ✔ |
| `Format.kt` | 금액·손익·등락률·상태 라벨 포맷, `planCapacity`(행 예산), 통화별 합계 | — | ✔ |
| `Colors.kt` | `theme.py` 토큰 복사(day/night `ColorProvider`) + 출처·날짜 주석 | — | ✔(pytest 드리프트) |
| `Prefs.kt` | `SharedPreferences` 래퍼: `baseUrl, token, lastJson, lastOkAt, lastError, lastManualAt` | — | — |
| `SetupActivity.kt` | Views 레이아웃(EditText 2·버튼 3·상태 텍스트). 딥링크 파싱, 저장, 연결 테스트, `requestPinAppWidget` | Prefs, WidgetApi | — |
| `res/xml/stock_widget_info.xml` | `targetCellWidth=4, targetCellHeight=2`, `minWidth/minHeight`, `resizeMode=horizontal\|vertical`, `updatePeriodMillis=1800000`(백스톱), `widgetCategory=home_screen`, `previewLayout` | — | — |

Compose UI(material3)는 **쓰지 않는다** — 설정 화면 하나에 APK가 2MB 이상 커진다. Glance는 Compose 런타임만 끌어온다.

## 데이터 계약(기존 `/api/widget`을 그대로 소비)

응답(`tests/test_widget.py`가 고정): `open, trade_date, fetched_at, refresh_after_sec,
items[{code, name, market, currency, price, change, shares, avg, pnl, pnl_pct, (US만) us_open}]`.

소비 규칙:
- `price`/`change`/`pnl`/`pnl_pct`는 **null 가능** → "—". 행을 빼지 않는다(서버도 빼지 않는다).
- `us_open`은 **미국 종목에만 있다**(선택 필드). KR 행에서 찾지 않는다.
- **모르는 필드는 무시**한다(서버가 나중에 필드를 더해도 앱이 죽지 않게). 단 `items` 부재 = 파싱 실패.
- `fetched_at`은 ISO(+09:00) → 기기 로컬 시각으로 "HH:MM 갱신". 폴백값(universe mtime)이면 그 시각 그대로 — 서버 설계의 "10:56 종가에 14:00 도장 금지"를 그대로 따른다.
- 통화 혼합은 합산하지 않는다(환율 없음) — 아이폰 `sumTotals`와 동일. 보유 판정 `shares > 0 && avg != null`(아이폰 `hasHolding`).
- 에러 본문 `{"error": "unauthorized"}`는 HTTP 401로 온다 → `Unauthorized`. 503은 `Failure`(서버가 위젯을 끔/시세 불가).

## 갱신 정책 — 성능·배터리의 핵심

WorkManager **이름 있는 1회성 작업 체인** 하나(`sm-refresh`). 주기 작업(Periodic)·알람·포그라운드 서비스·웨이크락은 쓰지 않는다.

| 트리거 | 지연 | 정책 | 비고 |
|---|---|---|---|
| 작업 성공 | `clamp(refresh_after_sec, 900, 21600)` | APPEND_OR_REPLACE(구현 중 수정 2026-09-04: 실행 중 REPLACE는 자기 취소) | 장중 15분 · 밤·주말은 다음 개장까지(서버가 계산, 최대 6h) · 미국장이면 서버가 10분으로 당김 → 15분 하한 |
| 작업 실패(타임아웃·503·파싱) | 900 | REPLACE | 마지막 값 유지 + "오프라인" |
| 401 | 21600 | REPLACE | 재설정 전까지 서버를 두드리지 않는다. 재설정 저장 시 즉시 작업으로 재개 |
| 위젯 추가·부팅·백스톱(`onUpdate`) | 0 | KEEP | 이미 예약된 작업이 있으면 그대로 둔다 |
| ↻ 탭 · 설정 저장 · 딥링크 | 0 | REPLACE | `setExpedited(RUN_AS_NON_EXPEDITED_WORK_REQUEST)`, 10초 디바운스 |
| 마지막 위젯 제거(`onDisabled`) | — | cancel | 위젯이 없으면 네트워크 0 |

- 제약: `NetworkType.CONNECTED`. 오프라인이면 연결 복귀 때 실행된다. 배터리 부족 제약은 걸지 않는다(사용자가 값을 원한다).
- **Doze**: 화면 꺼진 채 방치되면 지연 작업이 유지보수 창까지 미뤄질 수 있다(OS 재량). 폰을 깨우면 대기 작업이 곧 실행된다. 고지된 제약.
- **One UI 딥슬립**은 이 정책으로 못 막는다 → 가이드의 설치 단계(절전 예외 앱).
- 아이폰 위젯과 **동시에** 돌아도 서버 부담은 KIS REST 10건/15분 × 2 — `kis.py`의 20건/초 한도와 무관.

**성능·배터리 예산(설계 목표)**:
- 위젯 = **텍스트 전용 RemoteViews**(비트맵·이미지 0). 런처가 그리고 앱 프로세스는 갱신 뒤 종료된다.
- 갱신 1회 = HTTP 요청 1건(약 5KB JSON), CPU 1초 미만. 하루 요청 ≈ 장중 26건(6.5h/15분) + 미국장 소량 + 야간 1~2건 ≈ **40건 안팎**.
- APK **3MB 이하**(R8 minify + 리소스 축소). 상주 서비스 없음, 알림 없음.
- 반응형 재구성은 크기 버킷이 바뀔 때만(폴드 접기/펼치기 시 인스턴스별 1회).
- 실기기 확인: 설치 24h 뒤 설정 → 배터리 → 앱별 사용량에서 이 앱이 1% 미만이어야 한다.

## 화면 설계(위젯)

정보는 아이폰 위젯과 같다(위→아래):
1. **헤더**: `관심종목` · `HH:MM 갱신 · 장중` 또는 `HH:MM 갱신 · M/D(요일) 마감` · 오프라인이면 `오프라인·` 접두(경고색) · 우측은 안드로이드에선 브랜드 대신 **`↻ 갱신`(탭 타깃)**(구현 중 결정 2026-09-04).
2. **통화별 합계**(보유가 있을 때만): `합계 12,345,000원` · `▲123,000원 (+1.01%)`. USD는 `$` 소수 2자리.
3. **종목당 1줄**: 이름(US는 `NVDA 엔비디아`) · 현재가 · 등락%(색) · 보유 시 `수익 ▲12,000원`(색). 폭 400dp 이상이면 수익률 열 추가, 좁으면 `수익` 라벨 생략.
4. **넘침**: `+N종목` — 실제로 그린 개수 기준(`drawn + more == 전체`, 무경고 잘림 금지 — 아이폰 §137 회귀 규칙 그대로).

**반응형**: `SizeMode.Responsive` 버킷 `{250×110, 300×150, 300×300, 450×150, 450×300}`(dp). 런처가 들어맞는 최대 버킷을 고르고
`LocalSize.current`가 그 값이다. 행 수는 고정 개수가 아니라 **높이 예산**으로 계산한다:
`budget = height − 패딩 − 헤더 − (합계 줄) − (+N 줄)`, 행 20dp + 구분선 3dp(두 번째부터) — 아이폰 `planCapacity`와 같은 규칙, 순수 함수.
커버 4×2(≈380×170dp)와 메인 4×2(≈400×160dp)는 3~4종목, 세로 4×4는 8~10종목이 목표다. 실측 dp는 실기기에서 확인해 주석에 남긴다.

**색**: `backend/report/theme.py`가 화면들의 CSS 단일 출처지만 안드로이드는 CSS를 못 읽는다 → **값을 복사하고 pytest로 드리프트를 잡는다**.

| 토큰 | 라이트 | 다크 | 용도 |
|---|---|---|---|
| `--up` | `#e5342f` | `#ff5b52` | 상승·이익 |
| `--down` | `#1f66e0` | `#4f8bff` | 하락·손실 |
| `--flat` | `#8b93a4` | `#5f6879` | 보합·미보유·보조 텍스트 |
| `--warn` | `#dc8400` | `#f2a83a` | 오프라인 배지 |

배경·본문 텍스트는 `GlanceTheme.colors.widgetBackground / onSurface`(Android 12+ 동적 색, 시스템 다크·라이트 자동). 위젯 모서리는 시스템 라운딩.
등락 부호는 아이폰과 동일 문자(`+`, U+2212 `−`, `▲`, `▼`, 보합 `·`).

## 상호작용

| 동작 | 결과 |
|---|---|
| 몸통 탭 | `ACTION_VIEW base_url` — 크롬/삼성인터넷 또는 설치된 PWA가 열린다 |
| ↻ 탭 | 즉시 갱신(수 초 안에 숫자 반영). **iOS에선 불가능했던 개선.** 10초 안에 재탭은 무시 |
| 401 상태에서 탭 | `SetupActivity`(토큰 재입력) |
| 미설정 상태에서 탭 | `SetupActivity` |

## 보안

- **토큰은 앱 전용 `SharedPreferences`에만.** `android:allowBackup="false"` — Android 자동 백업이 앱 데이터를 구글 드라이브로 올리는 것을 막는다
  (iOS에서 Scriptable의 iCloud 평문 동기화 때문에 Keychain을 쓴 결정의 안드로이드판). `EncryptedSharedPreferences`는 2024년 이후 deprecated이고
  앱 샌드박스 + 기기 암호화로 충분하다(§기각한 대안).
- HTTPS만(`usesCleartextTraffic=false`). 딥링크의 `base`는 `https://`가 아니면 거부한다. 토큰은 로그·토스트·예외 메시지에 찍지 않는다.
- 위젯 리시버는 시스템 브로드캐스트(`APPWIDGET_UPDATE`)만 받는다. `SetupActivity`는 딥링크 수신을 위해 exported지만 인텐트 데이터를 읽어 화면에 채우기만 한다.
- 토큰 재발급(`/widget-setup` [토큰 재발급]) → 구 토큰 401 → 위젯이 재설정 안내로 바뀜 → 새 토큰 입력. 계정 격리·회전은 서버 설계 그대로.
- APK 자체에 비밀은 없다(서버 주소·토큰은 런타임 입력). 다운로드 라우트는 그래도 게이트 뒤에 둔다("모든 경로 잠금" 불변식).

## 설정·온보딩(초보 최대 실패 지점 = 토큰 옮기기 → 탭 한 번으로)

`/widget-setup` 페이지(게이트 뒤)에 **"갤럭시(안드로이드)"** 섹션을 추가한다:
1. **[APK 다운로드]**(`/widget-setup/android.apk`) → 브라우저의 "출처를 알 수 없는 앱 설치 허용" 1회 → 설치.
2. **[앱에 자동 입력]** = `stockmaster://setup?base=<URL인코딩>&token=<URL인코딩>` 링크. 탭하면 앱이 열려 주소·토큰이 채워지고 저장·연결 테스트까지 자동.
   페이지는 이미 토큰을 평문으로 보여주므로 노출이 늘지 않는다. 폴백: [토큰 복사](기존 버튼) → 앱을 열어 붙여넣기.
3. **[홈 위젯 추가]**(앱 안 버튼, `AppWidgetManager.requestPinAppWidget`) → One UI 확인 대화상자 → 홈에 위젯이 놓인다. 커버·메인 각각 한 번.
   폴백: 홈 길게 누르기 → 위젯 → Stock Master.
4. **절전 예외 등록** 두 겹: ① 앱 화면의 [배터리 제한 해제] 버튼 → 안드로이드 표준 `ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS` 시스템 대화상자(1탭; Play 정책은 사이드로드라 무관)
   ② 설정 → 배터리 → 백그라운드 사용 제한 → **절전 예외 앱** → Stock Master Widget 추가(삼성 고유 목록, 공개 인텐트 없음 → 앱 화면에 경로 안내 텍스트).
5. 위젯 ↻ 탭 → 첫 갱신 확인.

`SetupActivity` 상태 문구: 200 → `연결 OK · N종목`, 401 → `토큰이 맞지 않아요`, 503 → `서버가 위젯을 끄거나 시세를 못 가져와요`,
타임아웃·연결 실패 → `서버(맥북)에 연결할 수 없어요`. 저장 성공 시 즉시 갱신 작업을 넣는다.

## 서버 변경(최소 diff, Python 3.9)

1. `backend/report/widget_setup.py` — 템플릿에 갤럭시 섹션. 자리표시자 치환은 **자산 먼저, 데이터(토큰·링크) 마지막** 순서 유지(CLAUDE.md 치환 순서 규칙).
   `render_widget_setup(token, base_url, apk_available=False)` — 기본값 False라 기존 호출·테스트는 그대로 통과. APK가 없으면 다운로드 버튼 대신 "`make android`로 빌드하면 여기에 나타납니다".
2. `backend/api/app.py` — `GET /widget-setup/android.apk`: `settings.android_apk_path`의 파일을 `FileResponse`(media type
   `application/vnd.android.package-archive`, `filename=StockMasterWidget.apk`, `Cache-Control: no-store`)로. 없으면 404 JSON.
3. `backend/config.py` — `android_apk_path: str = <프로젝트루트>/data/android/StockMasterWidget.apk`(`SM_ANDROID_APK_PATH`로 덮어쓰기 가능). `.env.example`에 변수명만.
4. `tests/test_auth.py` `PROTECTED`에 `/widget-setup/android.apk` 추가(무인증 → `/login` 리다이렉트).
5. 색 드리프트 pytest: `theme.py`의 `--up/--down/--flat/--warn`(라이트·다크 8값)을 파싱해 `android/.../Colors.kt`에 모두 있는지 단언.

`/api/widget`·AuthGate·userstore는 **무변경**.

## 빌드·서명·배포

- **툴체인**(마스터 승인): `brew install --cask android-commandlinetools`(SDK 루트 `/opt/homebrew/share/android-commandlinetools`) →
  `yes | sdkmanager --licenses` → `sdkmanager "platform-tools" "platforms;android-36" "build-tools;36.0.0"`.
  `android/local.properties`(gitignore)에 `sdk.dir`. JDK: Gradle 9.7은 17~26에서 돌고 AGP 9.x 최소 17(2026-09-04 확인) — 기본 `java`(Temurin 25)로
  안 되면 `JAVA_HOME=$(/usr/libexec/java_home -v 21)`로 고정. 계획서의 T1이 실제로 무엇이 돌았는지 기록한다.
- **버전**: AGP ≥ 9.2(Gradle ≥ 9.4.1, 빌드툴 36, 컴파일 SDK 최대 37), Kotlin은 AGP 내장, Compose 컴파일러 플러그인 동일 버전,
  `compileSdk=36, targetSdk=36, minSdk=31`(반응형 위젯의 자연 하한; Glance 1.2 하한은 23), Glance 1.2.0, WorkManager 2.10+.
- **서명**: 사이드로드 업데이트는 **같은 키**여야 덮어써진다 → `data/android/release.jks`(gitignore, `keytool -genkeypair`로 1회 생성),
  `android/keystore.properties`(gitignore)로 참조. 파일이 없으면 debug 서명으로 빌드된다(CI·타 기기용). `versionCode`는 릴리스마다 수동 +1.
- **`make android`**: `cd android && ./gradlew --quiet assembleRelease` → `data/android/StockMasterWidget.apk`로 복사 → 8000이 이미 이 경로를 서빙.
  (APK 교체에는 8000 재기동이 필요 없다. 라우트 추가 최초 1회만 재기동.)
- `.gitignore` 추가: `android/.gradle/ android/**/build/ android/.kotlin/ android/local.properties android/keystore.properties`. Gradle 래퍼 jar는 커밋한다.
- GitHub Actions에 안드로이드 빌드는 넣지 않는다(후속 후보).

## 에러 처리 요약

| 상황 | 위젯 표시 | 다음 예약 |
|---|---|---|
| 정상 | 값 + `HH:MM 갱신 · 장중/마감` | `clamp(refresh_after_sec, 15분, 6h)` |
| 401(토큰 불일치·회전) | `토큰이 맞지 않아요 · 탭해서 재설정`(캐시 폴백 없음 — 오프라인 오진단 방지, 아이폰과 동일) | 6h(재설정 시 즉시) |
| 503(위젯 미설정·시세 불가) | 마지막 값 + `오프라인` | 15분 |
| 타임아웃·DNS·TLS 실패(맥 잠자기) | 마지막 값 + `오프라인` | 15분(네트워크 제약으로 연결 복귀 시) |
| 파싱 실패(`items` 없음) | 마지막 값 + `오프라인` | 15분 |
| 주소·토큰 미설정 | `설정이 필요해요 · 탭해서 설정` | 예약 없음 |
| 마지막 값도 없음 + 실패 | `서버에 연결할 수 없어요` 한 줄 | 15분 |
| One UI 딥슬립 | 갱신이 멈추고 `HH:MM`이 낡아간다 | 가이드: 절전 예외 앱 |

## 테스트 계획

- **JVM 단위(에뮬레이터 없음)** — `./gradlew test`:
  `WidgetDataTest`(KR 행·US 행 `us_open`·`price:null`·미지 필드 무시·`items` 부재 실패),
  `FormatTest`(KRW `71,200` / USD `$123.45` / `▲12,000원` / `▼$3.21` / `+1.25%` / `−0.50%` / `10:30 갱신 · 장중` / `7/15(화) 마감` / 통화별 합계 미혼합),
  `CapacityTest`(`drawn + more == n`, 넓은/좁은 버킷, 보유 유무 무관 균일),
  `RefreshPolicyTest`(클램프 하한 900·상한 21600, 실패 900, 401 21600).
- **빌드 게이트**: `./gradlew assembleRelease lint test` 통과, APK 3MB 이하 확인.
- **서버 pytest**: 페이지에 갤럭시 섹션·딥링크(URL 인코딩된 토큰)·APK 버튼(파일 있을 때만) · 스크립트 본문엔 여전히 토큰 없음 ·
  `/widget-setup/android.apk` 404/200(+content-type) · PROTECTED · 색 드리프트. 기존 위젯 테스트 전부 회귀 없음.
- **하네스**: `make test` · `make eval`(무변경 확인) · **`make verify --only widget`**(화면을 고쳤으므로 실렌더·가로 오버플로).
- **실기기 체크리스트(마스터 수동)**: 커버·메인 양쪽 위젯 표시와 크기 변경 · 다크·라이트 · ↻ 즉시 갱신 · 몸통 탭 → PWA ·
  토큰 재발급 후 401 안내 → 재입력 복구 · 맥 잠자기 → 오프라인 배지 · 절전 예외 등록 뒤 다음날 `HH:MM`이 살아 있는지 · 배터리 1% 미만.

## 문서 산출물

- `docs/widget-guide.md`: "갤럭시(안드로이드) 설치" 섹션(5단계 + 절전 예외 + 업데이트 시 같은 서명·재설치 불필요 고지) + 문제해결 표 행 추가.
- `README.md`: `/widget-setup` 화면 설명과 아키텍처 그림에 갤럭시 위젯 앱 추가.
- `.env.example`: `SM_ANDROID_APK_PATH=`.
- 코드 주석: 실측(버킷별 실제 dp, 실기기 배터리, One UI 동작)을 **날짜와 함께**.

## 범위 밖 · 후속

- 위젯 내용 확장(지수·코스피 온도·옵션) — 엔드포인트 화이트리스트가 보안 결정이라 별도 설계가 필요하다.
- Wear OS · 잠금화면 위젯 · Play 스토어 배포(비상업 프로젝트, 재배포 금지).
- PWA의 폴드 메인화면(4:3, ≈650dp 폭) 레이아웃 점검 — 별건.
- GitHub Actions 안드로이드 빌드 잡 — 필요해지면 추가.
- `/api/widget` 서버측 60초 캐시(아이폰+갤럭시 동시 폴링 중복 제거) — 현재 부하로는 불필요.

## 기각한 대안(왜)

| 대안 | 기각 사유 |
|---|---|
| KWGT / Tasker 노코드 위젯 | 유료 앱, 헤더·토큰 처리가 문서상 불명확, 수식이 깨지기 쉬움, 즉시 갱신·401 안내 같은 상태 처리 불가. "새 프로그램" 요청과도 불일치 |
| WebView·비트맵 렌더 위젯 | RemoteViews는 WebView를 못 담는다 → 서버 HTML을 비트맵으로 굽는 구조가 되어 배터리·메모리 낭비 |
| PWA 전체 네이티브화 | 위젯 외에는 PWA가 이미 안드로이드에서 돈다. 범위 과다 |
| Compose UI(material3) 설정 화면 | 화면 하나에 APK +2MB. Views로 충분 |
| Retrofit/OkHttp/kotlinx-serialization | 요청 1종·JSON 1종. 표준 라이브러리로 충분(ponytail) |
| `EncryptedSharedPreferences` | deprecated(2024~). 샌드박스 + `allowBackup=false`가 실제 위협(백업 유출)을 막는다 |
| 주기 작업(PeriodicWork 15분 고정) | 밤·주말에도 15분마다 깨운다. 서버 힌트를 따르는 1회성 체인이 배터리에 낫다 |
| AlarmManager / 포그라운드 서비스 | 배터리·권한 부담. WorkManager로 충분 |
| `SizeMode.Exact` | 크기 변경마다 재구성. 공식 권장은 Responsive |
| 별도 리포 | 서버 계약 테스트·설치 페이지·가이드와 분리되어 드리프트 |
| 별도 진입 없는 debug 키 서명 | `~/.android/debug.keystore`를 잃으면 업데이트 불가 → `data/android/` 릴리스 키 |

## 실측·확인 기록(2026-09-04)

- Fold 8 사양: 위키백과·GSMArena. Glance 1.2.0(2026-08-26): developer.android.com 릴리스 페이지. AGP 9.2 호환표(Gradle 9.4.1+, JDK 17, API 37).
  Gradle 9.7.1 Java 17~26. `updatePeriodMillis` 30분 하한: 안드로이드 위젯 문서. One UI 절전 경로: dontkillmyapp/samsung.
- 이 맥: JDK 25(Temurin)·21(MS)·8 있음, Android SDK·adb·gradle 없음. brew 캐스크 `android-commandlinetools`(SDK 루트 `/opt/homebrew/share/android-commandlinetools`).
- 서버: `make verify`의 화면 목록에 `("widget", "route", "/widget-setup")`가 이미 있다(`harness/cmd/verify.py`).
