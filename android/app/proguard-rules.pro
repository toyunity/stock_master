# Glance·WorkManager consumer 규칙만으로는 부족하다(2026-09-08 실측). Glance 1.2.0 의 규칙은
# `-keep public class * extends ActionCallback` 뿐 — R8 full 모드(AGP 8+ 기본)는 keep 된 클래스의 기본 생성자를
# 암묵적으로 남기지 않아 RefreshAction.<init>() 이 제거됐다(mapping/release/usage.txt). Glance 는
# Class.forName→getDeclaredConstructor()→newInstance() 로 콜백을 만들고 NoSuchMethodException 을 삼키므로
# 릴리스 APK에서만 ↻ 갱신 탭이 조용히 무시됐다(디버그·JVM 테스트로는 재현 안 됨). WorkManager 는 자기 규칙에
# `<init>(...)` 을 넣어 두어 RefreshWorker 는 멀쩡했다. tests/test_android_widget.py 가 이 줄의 존재를 지킨다.
-keep class * extends androidx.glance.appwidget.action.ActionCallback { <init>(); }

# StockWidget 이름 고정 — R8 수평 병합으로 f0 이 되면(2026-09-04 T4 mapping 실측) Glance DataStore 의
# receiver→provider 클래스명 매핑이 빌드마다 달라져 앱 업데이트 직후 updateAll 이 빈 목록일 수 있다.
-keep class com.toyunity.stockmaster.widget.StockWidget
