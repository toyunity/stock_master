---
name: verify
description: Stock Master(/live 대시보드) 변경을 실행 검증하는 레시피 — 데모 서버 기동, SSE 스냅샷 캡처, KIS REST 라이브 확인
---

# Stock Master 실행 검증 레시피

## 핵심 제약 (먼저 확인)

- **마스터의 실서버가 8000 포트에 떠 있을 수 있다** (`lsof -nP -iTCP:8000 -sTCP:LISTEN`).
  reload 없이 뜨므로 코드 수정의 영향은 없지만, **절대 죽이지 말 것**.
- **KIS 웹소켓은 1키 1세션** — 검증용 서버를 live 모드로 띄우면 마스터의 실시간
  세션과 충돌한다(ALREADY/EOF). 검증 서버는 반드시 `SM_FLOW_MODE=demo`로.
- **KIS 토큰 재발급 금지** — `data/cache/kis_token.json` 캐시 재사용(발급 1회/분
  제한 + 매번 마스터 폰으로 알림톡). REST 호출 자체는 캐시 토큰으로 안전.
- 인터프리터: 테스트/검증은 `.venv/bin/python`. 마스터의 실서버는 시스템 3.9로
  뜨므로 **Python 3.9 호환 문법만** 사용(zoneinfo OK, match문·`X|Y` 힌트 금지).

## 기동·드라이브

```bash
# 데모 서버(전 패널 시드 포함, KIS 불필요)
SM_FLOW_MODE=demo .venv/bin/python -m backend.cli serve --port 8001 &

curl -s http://127.0.0.1:8001/healthz                  # {"ok":true}
curl -s http://127.0.0.1:8001/live/000660              # 페이지 HTML
# SSE 스냅샷: 첫 이벤트는 시드 전 빈 상태 — 몇 초 받고 마지막 이벤트를 파싱
curl -s -N --max-time 5 http://127.0.0.1:8001/api/live/000660/stream \
  | grep '^data: ' | tail -1 | sed 's/^data: //' | python3 -m json.tool
curl -s "http://127.0.0.1:8001/api/candles/000660?tf=5m"
```

- 렌더 JS 실행 검증은 node 하니스가 이미 있다: `tests/test_live_page_js.py`
  (문자열 검사가 아니라 실제 render(S) 실행 — 패널 채움/오버레이/감시선까지).
- KIS REST 신규 연동은 데모 서버로는 안 돌므로, 모듈 함수를 실 KisClient로 1회
  구동해 실데이터 응답을 캡처한다(웹소켓은 건드리지 않음):
  `adr.get_quote(c, code)` / `credit.get_history(c, code)` / `shortsale.get_history(c, code)`.

## 뒷정리

`pkill -f "backend.cli serve --port 8001"` — 8000(마스터)은 건드리지 않는다.
