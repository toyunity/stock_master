# Glance·WorkManager는 consumer 규칙을 동봉한다. 앱 자체 규칙은 없음(2026-09-04).
# StockWidget 이름 고정 — R8 수평 병합으로 f0 이 되면(2026-09-04 T4 mapping 실측) Glance DataStore 의
# receiver→provider 클래스명 매핑이 빌드마다 달라져 앱 업데이트 직후 updateAll 이 빈 목록일 수 있다.
-keep class com.toyunity.stockmaster.widget.StockWidget
