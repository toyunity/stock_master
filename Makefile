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
