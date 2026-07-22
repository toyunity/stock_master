# 개발 하네스

`python -m harness <verify|test|eval|ops>` — 또는 `make verify|test|eval|ops`.

- **verify** 5화면(라이브·대시보드·스캐너·위젯·로그인)을 아이폰 폭(390/DSF3) 라이트/
  다크로 캡처하고 가로 오버플로를 검출. 산출물 `harness/artifacts/` (미커밋). 헤드리스
  크롬 필요.
- **test** pytest 전체 + node 렌더 스모크(node 없으면 해당 테스트 skip).
- **eval** 순수 판정 매퍼의 `{text,tone}`를 골든과 비교(의미 드리프트 회귀). 의도된
  변경이면 `make eval-update`.
- **ops** 로컬 8000·공개 Funnel·인증 게이트 읽기전용 점검(재기동 안 함).

## 안전
- 데모서버는 항상 `SM_FLOW_MODE=demo`·`SM_AUTH_ENABLED=false`로 뜨고, 하네스가 spawn한
  PID로만 종료한다. **마스터 실서버(8000)를 절대 건드리지 않는다.**
- KIS는 접촉하지 않는다(전부 demo 시드).
