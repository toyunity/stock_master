import os

# 테스트 격리: 개발자 .env의 SM_AUTH_ENABLED=true가 모듈 backend.api.app.app 에
# 인증 게이트를 걸면 무관한 라우트 테스트(/, /live, /api/*)가 302/401로 깨진다.
# 게이트는 test_auth.py가 create_app(Settings(auth_enabled=True))로 명시적으로만 켠다.
# os.environ은 .env 파일보다 우선하므로 여기서 강제로 끈다(backend import 전에 실행됨).
os.environ["SM_AUTH_ENABLED"] = "false"
