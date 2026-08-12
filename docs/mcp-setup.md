# Stock Master MCP 서버 — 연결 가이드

우리 분석 엔진(시세·신호·뉴스·공시·차트)을 **MCP 도구**로 노출한다.
Claude 앱에서 "내 관심종목 어때?" 처럼 물으면 Claude가 이 도구를 호출해
**라이브 데이터로 답하고 대시보드/차트도 만들어** 준다.

제공 도구 5개:
- `watchlist_summary` — 관심종목 전체 오늘 분석(신호·현재가·근거·뉴스/공시)
- `dashboard_data` — 위와 같은 범위를 JSON으로 한 번에(대시보드·차트 아티팩트용)
- `stock_detail(code)` — 특정 종목 상세
- `search_stocks(query)` — 전체 KRX 종목 이름/코드 검색(현재가 포함)
- `chart_data(code)` — 최근 120일 캔들(차트 시각화용)

---

## A. Claude Desktop 로컬 연결 (무료 · 비공개 · 권장)

로컬 stdio로 연결한다. 데이터는 **이 맥 안에서만** 처리되고 인터넷에 노출되지 않는다.

### 1) 설정 파일 열기/만들기
macOS 경로:
```
~/Library/Application Support/Claude/claude_desktop_config.json
```
(없으면 새로 만든다.)

### 2) 아래 내용을 넣고 저장
```json
{
  "mcpServers": {
    "stock-master": {
      "command": "<repo>/.venv/bin/python",
      "args": ["-m", "backend.mcp.server"],
      "cwd": "<repo>"
    }
  }
}
```
> 이미 `mcpServers`에 다른 항목이 있으면 `"stock-master": {...}` 만 그 안에 추가.

### 3) Claude Desktop 완전 종료 후 다시 실행
(메뉴 → 종료(Cmd+Q) → 재실행. 새로고침만으론 안 잡힐 수 있음.)

### 4) 확인
새 대화에서 도구(🔌/망치 아이콘)에 `stock-master`의 5개 도구가 보이면 성공.
예시로 물어보기:
- "내 관심종목 오늘 어때?" → `watchlist_summary`
- "삼성전자(005930) 자세히 봐줘" → `stock_detail`
- "하이닉스 검색해줘" → `search_stocks`
- "SK하이닉스 최근 차트 그려줘" → `chart_data` (Claude가 캔들로 차트 아티팩트 생성)

### 안 잡힐 때
- Claude Desktop을 **완전 종료(Cmd+Q)** 후 재실행했는지.
- 경로가 정확한지: 위 `command`/`cwd`의 `<repo>`는 이 저장소의 **절대경로**로 바꿔 넣어야 함.
- 서버 단독 점검(터미널):
  ```
  echo '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | .venv/bin/python -m backend.mcp.server
  ```
  → tools 목록 JSON이 나오면 서버 정상.

---

## B. Cowork 라이브 아티팩트 (공개 호스팅 — 별도/유료)

진짜 "Cowork 라이브 아티팩트"(자동 갱신 패널)는 같은 MCP 서버를 **공개 HTTPS 주소로
호스팅**해야 한다(Anthropic 클라우드가 접속). localhost 불가.

필요 단계(전부 마스터 본인 수행):
1. MCP 서버를 **HTTP 전송**으로 감싸 공개 호스트(Render/Railway/Fly 등)에 배포 — **유료 or 무료티어**.
2. **OAuth** 인증 구성.
3. Cowork 설정 → **커넥터 추가(Add custom connector)** → 서버 URL 등록 → 인증.
4. Cowork에서 라이브 아티팩트 생성 → 이 커넥터 데이터 사용.

⚠️ 트레이드오프: **유료** + **데이터 인터넷 노출**(인증보호) — 우리 초기 원칙(무료·비공개)과 충돌.
그래서 A(로컬)를 먼저 권장한다. B로 갈 경우 HTTP 전송 래퍼를 추가 작성해 드릴 수 있다.
