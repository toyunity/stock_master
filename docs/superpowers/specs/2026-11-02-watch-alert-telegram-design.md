# 서버 쪽 감시선 알림 — 앱을 닫아도 폰에 온다 (2026-11-02)

## 왜

감시선 알림은 `/live` 페이지 JS(`checkWatch`)에만 산다. 비프음과 브라우저 Notification은
탭이 열려 있을 때만 울리고, 아이폰 PWA는 백그라운드에서 SSE가 끊긴다. 폰을 주머니에 넣는
순간 "실시간 조언"이 멈춘다. 감시선을 서버가 보고, 폰이 잠겨 있어도 도착하는 채널로 보낸다.

## 채널 결정: 텔레그램 봇

- 새 의존성 0 — Bot API `sendMessage`는 `httpx`(이미 설치) POST 한 번.
- 잠금 화면 알림·소리·진동이 OS가 해준다. 아이폰·갤럭시 둘 다.
- 마스터 쪽 준비: BotFather로 봇 하나, 그 봇에게 메시지 한 번 보내 `chat_id` 확보.
  `.env`에 `SM_TELEGRAM_BOT_TOKEN`·`SM_TELEGRAM_CHAT_ID`.

기각한 대안(근거를 남긴다):
- **Web Push**: iOS는 16.4+ 홈화면 설치 PWA만, VAPID 키·서비스워커(현재 없음)·`pywebpush`
  (새 의존성, cryptography 동반) — 같은 결과에 열 배 diff. 제3자 서버를 빼고 싶어지면 그때.
- **ntfy**: 공개 토픽은 토픽명이 곧 비밀이고, 자체 호스팅은 맥북에 프로세스 하나 더.
- **Android 앱 FCM / iOS APNs**: 네이티브 앱 작업. 위젯 앱은 소비자일 뿐 푸시 수신기가 아니다.

주의: 메시지(종목명·감시선 라벨·가격)가 텔레그램 서버를 거친다. 보유수량·평단·손익은
**절대 싣지 않는다**. 봇 토큰은 `.env`에만.

## 목표 · 비목표

목표: 감시선에 ±0.5% 진입하거나 선을 가로지르면 30초 안에 폰에 메시지가 온다. 같은 선은
0.7% 밖으로 벗어났다 다시 들어올 때까지 다시 울리지 않는다(페이지 JS와 같은 규칙).

비목표: 조건식 알림(거래량·수급 조건), 알림 이력 화면, 계정별 채널(마스터 계정
`default_account()`만 — 다른 계정은 `ponytail:` 주석으로 상한을 적는다), 페이지 JS 알림 제거
(둘 다 울려도 된다 — 페이지가 열려 있으면 비프, 폰은 텔레그램).

실패 조건: 데모 서버·테스트가 텔레그램이나 KIS로 나간다 · KIS 토큰을 새로 발급한다 ·
장외 시간에 폴링한다 · 같은 선이 30초마다 반복 울린다 · 폴러 예외 하나로 루프가 죽는다.

## 구조

`backend/flow/watchalert.py` (신규):

```
step(state, prices, lines) -> (state, events)        # 순수 함수, I/O 없음
poll_once(email, client) -> events                    # 시세 조회 + step + 전송
run_forever()                                         # 30초 루프, 세션 밖이면 60초 대기
send_telegram(text) -> bool                           # httpx POST, 실패 False
```

- **기동**: `backend/api/app.py`의 `@app.on_event("startup")`(기존 shutdown과 같은 스타일 —
  lifespan 이전은 이 작업 범위 밖)에서 `asyncio.create_task(run_forever())`.
  조건 세 가지가 전부 참일 때만: 토큰·chat_id 둘 다 있음 · `settings.flow_mode != "demo"` ·
  `settings.kis_app_key` 있음. 하나라도 빠지면 로그 한 줄 남기고 기동 안 함.
  하네스 데모 서버는 `SM_FLOW_MODE=demo`라 자동으로 꺼진다. **pytest는 저절로 꺼지지 않는다**
  (검토에서 확인): `conftest.py`는 `SM_AUTH_ENABLED`·`SM_TOSS_*`만 비우고 `.env`의 KIS 키·
  `SM_FLOW_MODE`는 그대로 읽히므로, 마스터가 `.env`에 텔레그램 변수를 넣는 순간 `with
  TestClient(app)`의 startup에서 폴러가 떠 장중이면 오프라인 가드에 걸린다. **필수**:
  `conftest.py`의 토스 자리에 `os.environ["SM_TELEGRAM_BOT_TOKEN"] = ""` 한 줄 + 그 사실을
  확인하는 테스트(`test_offline_guard.py`의 토스 테스트와 같은 꼴).
- **시세**: KR은 `backend.cli.fetch_live_prices(codes)` 재사용(세마포어 5, 실패 코드 생략).
  US는 `usquote.price_us(client, sym)`. 클라이언트는 `candles._get_client()` 싱글턴 —
  토큰 디스크 캐시를 공유하므로 **새 발급이 없다**([[kis-token-issue-race]] 참조).
- **세션 게이트**: KR 코드는 `session.is_session_open(now, settings.market_div)`,
  US 코드는 `adr.us_market_open()`. 둘 다 닫혀 있으면 조회 0건, 60초 대기.
  **NXT 확장 시간(실서버 `UN` = 08:00~20:00)을 포함한다** — 검토 질문에 대한 Claude의 결정.
  `/api/prices`·홈 현재가 덮어쓰기·`/live` 엔진이 전부 같은 창을 "열림"으로 쓰므로 알림만
  정규장으로 좁히면 "화면은 움직이는데 알림은 안 오는" 구간이 생긴다. 프리·애프터의 얇은
  체결이 오경보를 내면 그때 `"J"`로 한 줄 바꾼다(`ponytail:` 주석으로 그 자리를 표시).
  미실측 하나: `KisClient.price()`(div=UN)가 프리장에 NXT 가격을 주는지 전일 종가를 주는지
  모른다 — 첫 배포 아침 08:00~09:00에 한 번 재서 `kis.py` 해당 함수에 날짜와 함께 적는다.
- **대상**: `userstore.get_watchlist(email)`의 항목 중 `userstore.get_lines(email, code)`가
  비어 있지 않은 코드만 조회. 감시선 없는 종목에 호출을 쓰지 않는다.
- **규칙(`step`)**: 페이지 JS `checkWatch`의 이식. 선마다 상태 `{armed, last}`를
  키 `(code, price)`로 둔다(인덱스가 아니라 가격 — 편집으로 줄이 밀려도 엉뚱한 선이 안 울린다).
  `dist = |p − w| / w`, `crossed = last와 p가 w의 반대편`.
  `(dist ≤ 0.005 or crossed) and armed` → 이벤트 + `armed=False`. `dist > 0.007` → `armed=True`.
  상태는 메모리. 재기동하면 재무장 → 밴드 안에 있던 선은 최대 1번 중복 울림(허용).
- **전송 실패**: `send_telegram`이 False면 **무장 상태를 유지**해 다음 틱에 다시 시도.
  실패는 `log.warning` 한 줄(스택 포함). 루프 본문 전체는 `except Exception`으로 감싸 계속 돈다.
- **유량**: 감시선 있는 종목 10개 × 2회/분. KIS 18건/초 대비 무시할 수준.
  폴링 간격은 `SM_WATCH_ALERT_SEC`(기본 30).

## 메시지

```
🔔 SK하이닉스 · 손절선 400,000원 ±0.5% 진입
현재가 401,200원 (−1.8%) · 14:21
https://<SM_PUBLIC_URL>/live/000660
```

이름은 `universe.name_map`(KR) / 기존 `_us_name`(US). 링크는 `settings.public_url`이 있을 때만.
미국은 `$` 소수 2자리(감시선 `_round_price`와 같은 정밀도).

## 설정 검증

`python -m backend.cli alert-test` — 설정된 채널로 "Stock Master 알림 연결 확인" 한 통.
라우트가 아니라 CLI인 이유: 인증·게이트 코드 0줄, 마스터만 쓴다.

## 테스트 (먼저 빨간 뒤 통과)

`tests/test_watchalert.py`
- `step`: 밴드 진입 1회 울림 → 밴드 안에 머무는 동안 침묵 → 0.7% 밖 → 재진입에 다시 울림.
- `step`: 1틱 사이에 선을 건너뛴 급변(`crossed`)도 울림.
- `step`: 편집으로 선 가격이 바뀌면 새 키로 무장 상태 시작.
- `send_telegram`: httpx를 스텁해 URL·payload(`chat_id`,`text`) 확인. 비정상 응답 → False.
- 전송 False면 `armed`가 유지된다.
- 기동 조건: 토큰 없음 / demo / KIS 키 없음 각각에서 태스크가 만들어지지 않는다.
- 세션 밖에서는 시세 조회 함수가 호출되지 않는다(스텁 호출 횟수 0).

## 빌더에게 맡기는 것

- `state`의 정확한 자료구조와 `events`의 모양.
- 로그 메시지 문구, 메시지의 줄바꿈·이모지.
- `fetch_live_prices`를 `cli`에서 그대로 import할지 얇은 래퍼로 감쌀지(새 추상화는 금지 —
  import가 기본).

## 운영

- `.env`에 두 변수를 넣고 **8000 재기동**(마스터 확인 후). `.env.example`에 변수명만 추가.
- 재기동 창에서 `alert-test`로 도착 확인 → 감시선 하나를 현재가 근처로 옮겨 실제 울림 확인.
- 다른 두 설계([[2026-11-02-verdict-ledger-design]], [[2026-11-02-portfolio-line-design]])와
  한 번의 재기동으로 묶는다.
