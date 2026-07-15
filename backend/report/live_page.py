from __future__ import annotations

"""실시간 수급 화면(/live/{code}) — 자기완결 HTML (영웅문 '종목별 수급' 축소판).

정보구조: 단일 세로 스크롤(전 패널 항상 표시 — 한 화면에서 긁어 분석). 상단 sticky
히어로(가격·판정·경보) + 그룹 구분 헤더(요약/수급/위험/시세)로 묶고, 각 패널은
정보 밀도를 높인 표현(발산형 막대·인라인 스파크라인 등)을 쓴다. 데이터는
SSE(/api/live/{code}/stream)로 1초마다 전체 스냅샷을 받아 그린다(엔진 불변).

핵심 제약(수정 시 준수):
- 패널은 DOM에서 제거·숨김 금지 — render()가 매 틱 ~60개 getElementById().textContent를
  돌려, 제거하면 라이브 피드가 통째로 죽는다. 또 사용자는 '한눈에 전부' 보길 원함.
- 봉주기(.tf[data-tf])·세션탭(#sz-tabs .tf)은 .tf 공유 — 전체 '.tf' 셀렉터 잡기 금지.
- 감시선 편집은 서버 저장(/api/watch) + live-mutation(let WATCH·priceLines[]·rearm()).
- 스파크라인은 차트 인스턴스가 아니라 인라인 SVG(스냅샷 rows에서 직접) — 성능·0폭 회피.
"""

from html import escape

from backend.report.dashboard import (_BASE_CSS, _CHART_THEME_JS, _DISCLAIMER,
                                      _LIB_PATH, _NAV_LOADER, _PWA_HEAD, _TABBAR)

_TEMPLATE = """<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>__NAME__ 실시간 수급 — Stock Master</title>
__PWA_HEAD__
<style>
__BASE_CSS__
/* ── /live 고유 스타일 ── */
.hero{position:sticky;top:0;z-index:20;background:var(--bg);margin:0 -16px 4px;
  padding:6px 16px 10px;
  padding-left:max(16px,env(safe-area-inset-left));padding-right:max(16px,env(safe-area-inset-right));
  border-bottom:1px solid var(--border)}
.hero .htop{display:flex;align-items:center;flex-wrap:wrap;gap:5px 8px}
.hero .hname{font-size:18px;font-weight:800;letter-spacing:-.01em}
.hero .price{font-size:30px;margin:4px 0 0}
.hero .sig{margin-top:8px}
#pmeta{margin-top:8px}
#pmeta .fresh{display:inline;margin:0}
#chart{height:180px}
#pchart{height:230px}
.chartwrap{position:relative}
.stall{display:none;position:absolute;inset:0;
  background:color-mix(in srgb,var(--surface) 88%,transparent);z-index:5;
  align-items:center;justify-content:center;font-size:13px;font-weight:600;color:var(--warn);
  text-align:center;padding:0 16px;border-radius:var(--r)}
.stall.on{display:flex}
/* 이평선(이동평균) 토글 줄 */
.marow{display:flex;align-items:center;gap:6px;margin:2px 0 10px;flex-wrap:wrap}
.marow .ma-lb{font-size:12px;font-weight:700;color:var(--text-2);margin-right:2px}
.marow .ma-hint{font-size:11px;color:var(--text-3);margin-left:2px}
.ma-btn{min-height:36px;padding:0 14px;border-radius:var(--r-pill);border:1px solid var(--border);
  background:var(--surface);color:var(--text-3);font-size:12.5px;font-weight:800;cursor:pointer;
  -webkit-tap-highlight-color:transparent;font-variant-numeric:tabular-nums}
.ma-btn:active{opacity:.7}
.ma-btn[data-ma="20"].on{background:#f59e0b;border-color:#f59e0b;color:#fff}
.ma-btn[data-ma="60"].on{background:#22c55e;border-color:#22c55e;color:#fff}
.ma-btn[data-ma="120"].on{background:#ec4899;border-color:#ec4899;color:#fff}
.ma-btn:disabled,.ma-btn.na{opacity:.32;cursor:not-allowed;background:var(--surface);
  border-color:var(--border);color:var(--text-3);box-shadow:none}
.szrow{display:flex;align-items:center;gap:8px;font-size:11px;margin:3px 0}
.szlbl{width:92px;flex:0 0 auto;color:var(--text-2);text-align:right;white-space:nowrap}
.szbar{height:14px;border-radius:4px;min-width:2px;flex:0 0 auto}
.szbuy{background:var(--up)} .szsell{background:var(--down)}
.szval{color:var(--text-3);white-space:nowrap;font-variant-numeric:tabular-nums}
.fgn{color:#a855f7;font-weight:700}
#mb-tbl th:nth-child(3),#mb-tbl td:nth-child(3){text-align:left}
/* 섹션 구분 헤더 — 단일 스크롤에서 그룹을 라벨로만 구분(숨기지 않음) */
.sechd{font-size:12.5px;font-weight:800;color:var(--text-3);letter-spacing:.04em;
  margin:26px 2px 0;padding-top:16px;border-top:1px solid var(--border)}
/* 인라인 스파크라인 */
.sparkwrap{display:flex;align-items:center;gap:10px;margin:12px 0 2px}
.sparkwrap .sk-cap{font-size:11px;font-weight:600;color:var(--text-3);white-space:nowrap;flex:0 0 auto}
.sparkwrap .sk-svg{flex:1;min-width:0;display:block}
.spark{width:100%;height:34px;display:block}
/* 발산형 막대(순매수 방향·크기) */
.dv{display:flex;align-items:center;gap:8px;margin:7px 0}
.dv-lb{width:70px;flex:0 0 auto;font-size:12px;font-weight:600;color:var(--text-2);
  text-align:right;white-space:nowrap}
.dv-track{flex:1;min-width:0;position:relative;height:18px;background:var(--surface-2);
  border-radius:5px;border:1px solid var(--border-2)}
.dv-track::before{content:'';position:absolute;left:50%;top:0;bottom:0;width:1px;background:var(--border)}
.dv-bar{position:absolute;top:2px;bottom:2px;border-radius:3px;min-width:1px;transition:width .3s}
.dv-buy{background:var(--up)} .dv-sell{background:var(--down)}
.dv-val{width:82px;flex:0 0 auto;text-align:right;font-size:12.5px;font-weight:800;
  font-variant-numeric:tabular-nums}
/* 2분할 비중 바 */
.pb{margin:12px 0 2px}
.pb-track{display:flex;height:20px;border-radius:6px;overflow:hidden;background:var(--surface-2)}
.pb-a{background:var(--primary)} .pb-b{background:#a855f7}
.pb-lg{display:flex;justify-content:space-between;margin-top:6px;font-size:11.5px;
  color:var(--text-2);font-weight:600}
.pb-dot{display:inline-block;width:8px;height:8px;border-radius:2px;margin-right:5px;vertical-align:middle}
.pb-da{background:var(--primary)} .pb-db{background:#a855f7}
/* 한눈 요약 스트립 */
.glance{display:flex;gap:8px;overflow-x:auto;margin:12px 0 2px;padding-bottom:2px;
  -webkit-overflow-scrolling:touch}
.glance::-webkit-scrollbar{height:0}
.glance:empty{display:none}
.gl{flex:0 0 auto;min-width:86px;background:var(--surface);border:1px solid var(--border);
  border-radius:var(--r);padding:9px 13px;box-shadow:var(--shadow-sm)}
.gl-lb{font-size:10.5px;color:var(--text-3);font-weight:700;white-space:nowrap;letter-spacing:.01em}
.gl-vl{font-size:15px;font-weight:800;font-variant-numeric:tabular-nums;margin-top:3px;
  white-space:nowrap;letter-spacing:-.01em}
.gl-vl.up{color:var(--up)} .gl-vl.down{color:var(--down)} .gl-vl.flat{color:var(--text)}
/* 감시선 편집기 + 내 라인 칩 */
.mylines{display:flex;flex-wrap:wrap;gap:6px;margin-top:12px}
.myline{display:inline-flex;align-items:center;gap:6px;font-size:12px;font-weight:600;
  padding:5px 11px;border-radius:var(--r-pill);background:var(--surface-2);
  border:1px solid var(--border-2);color:var(--text-2);font-variant-numeric:tabular-nums}
.myline .dot{width:8px;height:8px;border-radius:50%;background:#a855f7;flex:0 0 auto}
.myline.add{color:var(--primary);cursor:pointer;border:1px dashed var(--border);background:transparent}
.wl-preset{display:flex;gap:6px;flex-wrap:wrap;margin:2px 0 10px}
.wl-chip{min-height:34px;padding:0 13px;border-radius:var(--r-pill);border:1px dashed var(--border);
  background:transparent;color:var(--text-2);font-size:12px;font-weight:700;cursor:pointer}
.wl-chip:active{opacity:.6}
.wl-row{display:flex;gap:6px;align-items:center;margin:7px 0}
.wl-row input{min-height:42px;padding:0 11px;border:1px solid var(--border);
  border-radius:var(--r-sm);background:var(--surface-2);color:var(--text);font-size:16px}
.wl-row .wl-label{flex:1;min-width:0}
.wl-row .wl-price{width:120px;flex:0 0 auto;text-align:right;font-variant-numeric:tabular-nums}
.wl-del{min-height:42px;min-width:42px;flex:0 0 auto;border:1px solid var(--border);
  border-radius:var(--r-sm);background:var(--surface);color:var(--up);font-size:16px;cursor:pointer}
.wl-actions{display:flex;gap:8px;align-items:center;margin-top:12px;flex-wrap:wrap}
.wl-status{font-size:12px;color:var(--text-3);font-weight:600}
</style></head><body>
<div class="hero">
  <div class="htop"><a class="back" href="/" style="margin:0">← 목록</a>
    <span class="hname">__NAME__</span> <span class="code">__CODE__</span>
    <span id="mode" class="badge b-__MODE_CLS__">__MODE__</span>
    <span id="conn" class="badge b-off">연결 중…</span>
    <span id="mstate" class="badge b-off">상태 확인 중</span></div>
  <div class="price" id="price">–</div>
  <div class="sig sig-flat" id="tm-headline"></div>
  <div class="note" id="walert"></div>
</div>

<div class="glance" id="glance"></div>
<div class="meta" id="pmeta">체결 대기 중 <span class="fresh">· 실시간</span></div>
<div class="note" id="note"></div>

<div class="panel">
  <h2>📈 가격 차트 <span class="fresh" id="pc-fresh">· 불러오는 중</span></h2>
  <div class="tfrow">
    <button class="tf" data-tf="1m">1분</button>
    <button class="tf on" data-tf="5m">5분</button>
    <button class="tf" data-tf="15m">15분</button>
    <button class="tf" data-tf="60m">60분</button>
    <button class="tf" data-tf="1d">일봉</button>
    <button class="tf" id="notifbtn" style="display:none">🔔 감시선 알림 허용</button>
  </div>
  <div class="marow">
    <span class="ma-lb">이평선</span>
    <button class="ma-btn on" data-ma="20">20</button>
    <button class="ma-btn on" data-ma="60">60</button>
    <button class="ma-btn" data-ma="120">120</button>
    <span class="ma-hint">봉 이동평균 · 켜고 끄기</span>
  </div>
  <div class="chartwrap"><div id="pchart"></div><div class="stall" id="pstall"></div></div>
  <div class="mylines" id="mylines"></div>
</div>

<details class="panel" id="wl-panel">
  <summary><h2>🎯 감시선·예약매도선 설정</h2></summary>
  <div class="meta" style="margin:2px 0 10px">차트에 표시할 수평선을 추가·편집합니다. 가격이 닿으면
  소리+화면 알림. 라벨은 자유(절대선/예약매도선/손절 등) — <b>실제 주문이 아니라 표시·알림용</b>.
  차트를 탭해도 그 가격에 선이 추가됩니다. 저장하면 다른 기기에도 반영됩니다.</div>
  <div class="wl-preset">
    <button class="wl-chip" type="button" onclick="wlAddRow('감시선')">＋ 감시선</button>
    <button class="wl-chip" type="button" onclick="wlAddRow('절대선')">＋ 절대선</button>
    <button class="wl-chip" type="button" onclick="wlAddRow('예약매도선')">＋ 예약매도선</button>
  </div>
  <div id="wl-rows"></div>
  <div class="wl-actions">
    <button class="refresh" type="button" onclick="saveLines()">저장</button>
    <span class="wl-status" id="wl-status"></span>
  </div>
</details>

<div class="sechd">📋 요약 · 지금 뭘 하나</div>
<div class="panel">
  <h2>🧭 매매 타이밍 <span class="fresh" id="tm-fresh">· 참고용(추정)</span></h2>
  <div id="tm-comment" style="font-size:14px;margin:2px 0 6px"></div>
  <table id="tm-reasons"></table>
  <div class="meta" id="tm-note">20·60·120일선 배열(추세)과 수급을 결합한 <b>참고용 추정</b> —
  매매 조언이 아니며 투자 판단·책임은 본인에게 있습니다. 확정 수급은 T+1 반영.</div>
</div>

<div class="panel">
  <h2>💰 투자자별 순매수 (장중 추정)</h2>
  <div class="fresh" id="est-fresh">잠정 · 갱신 대기 · 장중 추정치는 익일 확정과 다를 수 있음</div>
  <div id="est-bars" style="margin:8px 0 4px"></div>
  <div class="tbl-wrap"><table id="est-hist" style="margin-top:8px"></table></div>
  <div class="meta" id="est-note">*개인+기타법인 = −(외국인+기관) 역산 — 장중 개인 집계는 어디에도 없어
  "전체 매매 합계는 0" 원리로 추정한 값</div>
  <div class="tbl-wrap"><table id="est-detail" style="margin-top:8px"></table></div>
  <div class="meta" id="est-detail-note"></div>
</div>

<div class="panel">
  <h2>🤖 프로그램매매 <span class="fresh" id="pgm-fresh">· 실시간</span></h2>
  <div class="grid3" style="margin-bottom:8px">
    <div><div class="lbl">순매수 수량</div><div class="val" id="pgm-qty">–</div></div>
    <div><div class="lbl">순매수 금액</div><div class="val" id="pgm-val">–</div></div>
  </div>
  <div class="chartwrap"><div id="chart"></div><div class="stall" id="cstall"></div></div>
  <div class="meta">당일 누적 순매수 금액 추이(억원) — Y축은 당일 전체 범위 고정</div>
</div>
<div class="sechd">💰 수급 · 누가 사고파나</div>
<details class="panel" open>
  <summary><h2>📅 일별 확정 수급 <span class="fresh">· 전일까지 확정치</span></h2></summary>
  <div class="tbl-wrap"><table id="daily"><tr><th>날짜</th><th>개인</th><th>외국인</th><th>기관</th><th>종가</th><th>대차잔고</th></tr></table></div>
</details>

<details class="panel" open>
  <summary><h2>🏛️ 기관 세부 수급 (연기금·투신·금융투자 …)</h2></summary>
  <div class="fresh" id="dt-fresh">확정 · 기준일 대기 · 기관계를 주체별로 분해한 확정치</div>
  <div class="tbl-wrap"><table id="detail"></table></div>
</details>

<div class="panel">
  <h2>🏦 거래원(회원사) 창구 분석 <span class="fresh" id="mb-fresh">· 데이터 대기</span></h2>
  <div class="tbl-wrap"><table id="mb-tbl"></table></div>
  <div class="sig" id="mb-sig"></div>
  <div class="meta" id="mb-note">상위 5 창구(KRX+NXT 통합) · <span class="fgn">보라색</span> = 외국계 창구.
  외국계 합계는 정규장(KRX) 기준(NXT 외국계 집계 미제공). 창구≠주체 — 외국인이 국내
  창구를 쓸 수 있어 <b>추정치(정확한 주체 식별 불가)</b>. 확정 수급은 T+1 09:30 이후.</div>
</div>
<div class="sechd">⚠️ 위험 신호 · 떨어질 연료</div>
<div class="panel">
  <h2>🩳 대차잔고 (공매도 선행지표) <span class="fresh" id="sb-fresh">· 데이터 대기</span></h2>
  <div class="grid3">
    <div><div class="lbl">잔고 주수</div><div class="val" id="sb-qty">–</div></div>
    <div><div class="lbl">전일 대비</div><div class="val" id="sb-chg">–</div></div>
    <div><div class="lbl">잔고 금액</div><div class="val" id="sb-val">–</div></div>
  </div>
  <div class="sparkwrap"><span class="sk-cap">대차 20일</span><span class="sk-svg" id="sb-spark"></span></div>
  <div class="sig" id="sb-sig"></div>
  <details class="inline" style="margin-top:8px">
    <summary>최근 20거래일 추이</summary>
    <div class="tbl-wrap"><table id="sb-hist" style="margin-top:6px"></table></div>
  </details>
  <div class="meta" id="sb-note">대차잔고 = 공매도 등을 위해 빌려간 뒤 아직 갚지 않은 주식 수(T+1 공시).
  늘어나면 공매도 대기 물량 증가, 줄어들면 상환(숏 청산) 신호로 읽는다.</div>
</div>

<div class="panel">
  <h2>🎯 공매도 일별 체결 <span class="fresh" id="ss-fresh">· 데이터 대기</span></h2>
  <div class="grid3">
    <div><div class="lbl">공매도 체결</div><div class="val" id="ss-qty">–</div></div>
    <div><div class="lbl">거래량 비중</div><div class="val" id="ss-ratio">–</div></div>
    <div><div class="lbl">대차잔고 대비</div><div class="val" id="ss-vs">–</div></div>
  </div>
  <div class="sparkwrap"><span class="sk-cap">공매도 20일</span><span class="sk-svg" id="ss-spark"></span></div>
  <details class="inline" style="margin-top:8px">
    <summary>최근 20거래일 추이</summary>
    <div class="tbl-wrap"><table id="ss-hist" style="margin-top:6px"></table></div>
  </details>
  <div class="meta" id="ss-note">위 대차잔고가 '빌린 물량'이라면 이것은 '실제로 쏜 물량'(T+1 확정).
  비중 = 그날 전체 거래량 중 공매도 비율.</div>
</div>

<div class="panel">
  <h2>💳 신용융자 잔고 (반대매매 연료) <span class="fresh" id="cr-fresh">· 데이터 대기</span></h2>
  <div class="grid3">
    <div><div class="lbl">잔고 주수</div><div class="val" id="cr-qty">–</div></div>
    <div><div class="lbl">전일 대비</div><div class="val" id="cr-chg">–</div></div>
    <div><div class="lbl">잔고 금액≈</div><div class="val" id="cr-val">–</div></div>
  </div>
  <div class="sparkwrap"><span class="sk-cap">신용 20일</span><span class="sk-svg" id="cr-spark"></span></div>
  <div class="sig" id="cr-sig"></div>
  <details class="inline" style="margin-top:8px">
    <summary>최근 20거래일 추이</summary>
    <div class="tbl-wrap"><table id="cr-hist" style="margin-top:6px"></table></div>
  </details>
  <div class="meta" id="cr-note">신용융자 = 빚내서 산 주식. 급락하면 증거금 부족분이 다음 날 아침
  반대매매(강제청산)로 쏟아진다 — 잔고가 클수록 하락 가속 연료. 금액은 주수×종가 환산(≈).</div>
</div>
<div class="sechd">🌐 시세 · 해외·거래소·체결</div>
<div class="panel">
  <h2>🌐 ADR 환산가·괴리율 <span class="fresh" id="adr-fresh">· 데이터 대기</span></h2>
  <div class="grid3">
    <div><div class="lbl" id="adr-usd-lbl">DR 가격($)</div><div class="val" id="adr-usd">–</div></div>
    <div><div class="lbl">환산가(원)</div><div class="val" id="adr-conv">–</div></div>
    <div><div class="lbl">원주 현재가</div><div class="val" id="adr-ord">–</div></div>
  </div>
  <div class="sig" id="adr-sig"></div>
  <div class="meta" id="adr-note">환산가 = DR가격 × 전환비율 × USD/KRW — 미국 시장이 매긴
  SK하이닉스 값을 원화로 환산. 원주보다 비싸면(+, 적색) 미국 프리미엄.</div>
</div>

<div class="panel">
  <h2>🔀 거래소별 거래량 (KRX vs NXT) <span class="fresh" id="xv-fresh">· 데이터 대기</span></h2>
  <div class="grid3">
    <div><div class="lbl">KRX(정규)</div><div class="val" id="xv-krx">–</div></div>
    <div><div class="lbl">NXT 합계</div><div class="val" id="xv-nxt">–</div></div>
    <div><div class="lbl">NXT 비중</div><div class="val" id="xv-share">–</div></div>
  </div>
  <div id="xv-propbar"></div>
  <div class="tbl-wrap"><table id="xv-ses" style="margin-top:8px"></table></div>
  <div class="sig" id="xv-sig"></div>
  <div class="meta" id="xv-note">세션별 NXT 거래량 — 장전(08:00~08:50) / 본장(09:00~15:20) /
  장후(15:30~20:00). KRX 거래량은 전부 정규장. 진행 중이거나 경계 미통과 세션은 '–'.
  시간외 가격 변동 대비 거래량이 극히 적으면 유동성 부족 왜곡 경고.</div>
</div>

<div class="panel">
  <h2>📏 체결 규모 분포 — 주체 추정 <span class="fresh" id="sz-fresh">· 실시간 집계 대기</span></h2>
  <div class="tfrow" id="sz-tabs">
    <button class="tf" data-ses="pre">장전</button>
    <button class="tf" data-ses="regular">정규장</button>
    <button class="tf" data-ses="after">장후(NXT)</button>
  </div>
  <div id="sz-bars"></div>
  <div class="sig" id="sz-sig"></div>
  <div class="meta">체결량 구간별 건수·거래대금 비중 — <b>추정치(정확한 주체 식별 불가)</b>.
  100주 초과 대금 비중↑ = 기관성, 1-10주 건수 비중↑ = 개인 중심. 시장이 얇은
  시간외 구간일수록 판별력이 높다. 투자자별 순매수 <b>확정치는 T+1 09:30 이후</b> 제공.</div>
</div>

<details class="panel" open>
  <summary><h2>⚡ 실시간 체결 <span class="fresh">· 최근 30건</span></h2></summary>
  <div class="tbl-wrap"><table id="tape"><tr><th>시각</th><th>체결가</th><th>체결량</th><th>구분</th></tr></table></div>
</details>
<div class="disc">__DISCLAIMER__ 실시간 수급의 외국인/기관 수치는 장중 <b>추정치(잠정)</b>이며
확정치는 다음 영업일에 제공됩니다. 데이터 출처: 한국투자증권 오픈API(국내·해외 시세, 환율,
신용잔고, 공매도)·금융투자협회(대차잔고)·네이버(폴백). 모든 표시 시각은 KST(Asia/Seoul) 기준.</div>

<script>__LIB__</script>
<script>
const CODE='__CODE__';
let WATCH=__WATCH__; // 감시선 [{price,label}] — 서버 저장(/api/watch)에서 주입, 편집 시 가변
const num=n=>n==null?'–':Math.round(n).toLocaleString('ko-KR');
const won=n=>n==null?'–':num(n)+'원';
const shares=n=>n==null?'–':(n>0?'+':'')+num(n)+'주';
const eok=n=>n==null?'–':(n>0?'+':'')+(n/1e8).toLocaleString('ko-KR',{maximumFractionDigits:1})+'억';
const cls=n=>n>0?'up':(n<0?'down':'flat');
const esc=s=>(s==null?'':String(s)).replace(/[&<>"]/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[m]));
const sgn={up:'▲',down:'▼',flat:''};

// ── 인라인 SVG 스파크라인(차트 인스턴스 아님 — 스냅샷 rows에서 직접) ──
function spark(vals,color){
  vals=(vals||[]).map(Number).filter(v=>!isNaN(v));
  if(vals.length<2)return '<span class="meta">추이 표본 부족</span>';
  const W=200,H=34,pad=3;
  let mn=Math.min.apply(null,vals),mx=Math.max.apply(null,vals);const rng=(mx-mn)||Math.abs(mx)||1;
  const xy=i=>[pad+i*(W-2*pad)/(vals.length-1),H-pad-(vals[i]-mn)/rng*(H-2*pad)];
  const pts=vals.map((v,i)=>{const p=xy(i);return p[0].toFixed(1)+','+p[1].toFixed(1);}).join(' ');
  const c=color||'var(--primary)';
  const last=xy(vals.length-1);
  const area='M'+pad+','+(H-pad)+' L'+pts.replace(/ /g,' L')+' L'+(W-pad)+','+(H-pad)+' Z';
  return '<svg class="spark" viewBox="0 0 '+W+' '+H+'" preserveAspectRatio="none" aria-hidden="true">'
    +'<path d="'+area+'" fill="'+c+'" opacity="0.10"/>'
    +'<polyline points="'+pts+'" fill="none" stroke="'+c+'" stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round"/>'
    +'<circle cx="'+last[0].toFixed(1)+'" cy="'+last[1].toFixed(1)+'" r="2.4" fill="'+c+'"/></svg>';
}
// ── 발산형 막대(중앙 0선 기준, 매수=적/매도=청) ──
function divbar(label,val,maxAbs){
  const half=(maxAbs&&val!=null)?Math.min(50,Math.abs(val)/maxAbs*50):0;
  const pos=val>0, side=pos?('left:50%'):('right:50%');
  return '<div class="dv"><span class="dv-lb">'+esc(label)+'</span>'
    +'<div class="dv-track"><div class="dv-bar '+(pos?'dv-buy':'dv-sell')+'" style="'+side+';width:'+half.toFixed(1)+'%"></div></div>'
    +'<span class="dv-val '+cls(val)+'">'+shares(val)+'</span></div>';
}
// ── 한눈 요약 칩 ──
function glchip(lb,val,c){
  return '<div class="gl"><div class="gl-lb">'+esc(lb)+'</div><div class="gl-vl '+(c||'flat')+'">'+val+'</div></div>';
}
// ── 2분할 비중 바(A|B 구성비) ──
function propbar(aLabel,aVal,bLabel,bVal){
  const tot=(aVal||0)+(bVal||0)||1;
  const ap=(aVal||0)/tot*100, bp=(bVal||0)/tot*100;
  return '<div class="pb"><div class="pb-track">'
    +'<div class="pb-a" style="width:'+ap.toFixed(1)+'%"></div>'
    +'<div class="pb-b" style="width:'+bp.toFixed(1)+'%"></div></div>'
    +'<div class="pb-lg"><span><i class="pb-dot pb-da"></i>'+esc(aLabel)+' '+ap.toFixed(1)+'%</span>'
    +'<span><i class="pb-dot pb-db"></i>'+esc(bLabel)+' '+bp.toFixed(1)+'%</span></div></div>';
}

__CHART_THEME_JS__
const _pt=chartTheme();
const chart=LightweightCharts.createChart(document.getElementById('chart'),{autoSize:true,height:180,
  layout:_pt.layout,grid:_pt.grid,
  rightPriceScale:{borderColor:_pt.rightPriceScale.borderColor},
  timeScale:{borderColor:_pt.timeScale.borderColor,timeVisible:true,secondsVisible:false}});
registerChart(chart);
// Y축 도메인: 당일 누적 전체 min/max ±5% 고정(P0-1) — 자동 축소로 최근 몇 분
// 범위만 잡혀 플랫라인으로 보이던 사고 방지. null이면 기본 오토스케일.
let pgmRange=null;
const series=chart.addBaselineSeries({baseValue:{type:'price',price:0},
  topLineColor:'#c62828',topFillColor:'rgba(198,40,40,.15)',
  bottomLineColor:'#1565c0',bottomFillColor:'rgba(21,101,192,.15)',lineWidth:2,
  autoscaleInfoProvider:()=>pgmRange?{priceRange:pgmRange}:null});
let KDATE=null, KTIME=null; // 서버가 준 KST 기준일/시각 — 클라이언트 시계 사용 금지(P0-3)
function toTs(t,ds){
  // Lightweight Charts는 epoch을 UTC로 포맷 → KST 벽시계를 UTC epoch인 척 만들어
  // 라벨이 서버(KST) 시각 그대로 보이게 한다. 로컬 오프셋 보정(구현)은 서울 외
  // 타임존 클라이언트에서 어긋나 폐기(P0-3). 날짜도 서버 제공(KDATE/응답 date)만 쓴다.
  const p=(ds||KDATE||'1970-01-01').split('-').map(Number);
  const[h,m,s]=t.split(':').map(Number);
  return Date.UTC(p[0],p[1]-1,p[2],h,m,s||0)/1000;}

// ── 가격 차트 (봉 주기 선택) ──
const _pt2=chartTheme();
const pchart=LightweightCharts.createChart(document.getElementById('pchart'),{autoSize:true,height:230,
  layout:_pt2.layout,grid:_pt2.grid,
  rightPriceScale:{borderColor:_pt2.rightPriceScale.borderColor},
  timeScale:{borderColor:_pt2.timeScale.borderColor,timeVisible:true,secondsVisible:false}});
registerChart(pchart);
const pseries=pchart.addCandlestickSeries({upColor:'#c62828',downColor:'#1565c0',
  borderVisible:false,wickUpColor:'#c62828',wickDownColor:'#1565c0'});
// 이동평균선(20/60/120봉) — 켜고 끄기. addLineSeries 없는 node 하니스에선 가드로 생략.
const MA_COLORS={20:'#f59e0b',60:'#22c55e',120:'#ec4899'};
let maOn={20:true,60:true,120:false};
let maSeries={};
if(pchart.addLineSeries){[20,60,120].forEach(function(n){
  maSeries[n]=pchart.addLineSeries({color:MA_COLORS[n],lineWidth:1.5,
    priceLineVisible:false,lastValueVisible:false,crosshairMarkerVisible:false,visible:maOn[n]});
});}
let TF='5m', tfSeq=0;
const TF_KO={'1m':'당일 1분봉','5m':'당일 5분봉','15m':'당일 15분봉','60m':'당일 60분봉','1d':'일봉 120일'};
async function loadCandles(fit){
  // fit=true일 때만 전체 보기로 맞춘다(최초 로드·타임프레임 전환). 60초 자동 갱신은
  // fit=false로 사용자의 확대/이동 뷰를 보존(실사고: 갱신마다 초기화).
  const seq=++tfSeq, tf=TF; // 연타로 주기를 바꿔도 마지막 요청만 반영(경합 방지)
  try{
    const r=await fetch('/api/candles/'+CODE+'?tf='+tf);
    if(seq!==tfSeq)return;
    if(!r.ok){document.getElementById('pc-fresh').textContent='· 차트 조회 실패';return;}
    const d=await r.json();
    if(seq!==tfSeq)return;
    if(!d.candles.length){document.getElementById('pc-fresh').textContent='· 데이터 없음(장전이거나 조회 실패)';return;}
    pseries.setData(d.candles.map(c=>({time:tf==='1d'?c.t:toTs(c.t,d.date),
      open:c.open,high:c.high,low:c.low,close:c.close})));
    // 이평선: 데이터 세팅 + 봉주기별 사용 가능 여부로 버튼 활성화.
    // 짧은 봉(5분 79개 등)엔 120봉 표본이 없어 선이 안 그려짐 → 버튼 비활성+안내(무반응 오해 방지).
    var _na=[];
    [20,60,120].forEach(function(n){
      var key='ma'+n, has=d.candles.some(function(c){return c[key]!=null;});
      if(pchart.addLineSeries&&maSeries[n]){
        maSeries[n].setData(has?d.candles.filter(function(c){return c[key]!=null;})
          .map(function(c){return {time:tf==='1d'?c.t:toTs(c.t,d.date), value:c[key]};}):[]);
      }
      if(!has)_na.push(n);
    });
    document.querySelectorAll('.ma-btn').forEach(function(btn){
      var has=_na.indexOf(+btn.getAttribute('data-ma'))<0;
      btn.disabled=!has; btn.classList.toggle('na',!has);
    });
    document.querySelectorAll('.ma-hint').forEach(function(h){
      h.textContent=_na.length?('이평 · '+_na.join('/')+'봉은 표본 부족(일봉에서 전부 표시)')
        :'봉 이동평균 · 켜고 끄기';
    });
    pchart.applyOptions({timeScale:{timeVisible:tf!=='1d'}});
    if(fit)pchart.timeScale().fitContent();
    const lastT=d.candles[d.candles.length-1].t;
    document.getElementById('pc-fresh').textContent='· '+TF_KO[tf]+' · 기준 '
      +lastT+(tf==='1d'?'':' (KST) · 60초 자동 갱신');
  }catch(e){console.error(e);}
}
// [data-tf]로 한정 — 세션 탭(#sz-tabs, data-ses)·알림 버튼도 .tf 클래스를 쓰므로
// 전체 '.tf'를 잡으면 하이라이트를 서로 지운다(리뷰 확정)
document.querySelectorAll('.tf[data-tf]').forEach(b=>b.onclick=()=>{
  document.querySelectorAll('.tf[data-tf]').forEach(x=>x.classList.remove('on'));
  b.classList.add('on'); TF=b.dataset.tf; loadCandles(true);
});
// 이평선 토글 — .ma-btn[data-ma] 전용(봉주기 .tf 셀렉터와 분리)
document.querySelectorAll('.ma-btn').forEach(function(b){b.onclick=function(){
  const n=+b.getAttribute('data-ma');
  maOn[n]=!maOn[n]; b.classList.toggle('on',maOn[n]);
  if(maSeries[n])maSeries[n].applyOptions({visible:maOn[n]});
};});
loadCandles(true);
setInterval(()=>{if(TF!=='1d')loadCandles(false);},60000);
function nextSlot(){
  // 잠정치 발표 슬롯(±10분): 외국인 09:30~, 기관 10:00~ — 다음 예상 시점 안내.
  // 기준 시각은 서버 KST(KTIME) — 클라이언트 로컬 시계 금지(P0-3)
  const slots=['09:30','10:00','11:20','13:20','14:30'];
  const cur=(KTIME||'00:00:00').slice(0,5);
  for(const s of slots) if(s>cur) return '~'+s+' (±10분)';
  return '다음 영업일 09:30';
}

// ── 감시선(P1-8): 라벨 수평선 + ±0.5% 진입 알림. 편집 시 live-mutation(재렌더·재무장) ──
let priceLines=[];             // 생성된 IPriceLine 핸들 — 재렌더 시 removePriceLine
let armed=WATCH.map(()=>true); // 알림 무장 배열 — WATCH 변경마다 rearm()로 재생성
let ac=null, lastWatchPrice=null;
function renderWatchLines(){
  for(let i=0;i<priceLines.length;i++){try{pseries.removePriceLine(priceLines[i]);}catch(e){}}
  priceLines=[];
  for(let j=0;j<WATCH.length;j++){const w=WATCH[j];
    try{priceLines.push(pseries.createPriceLine({price:w.price,title:w.label,
      color:'#a855f7',lineWidth:1,lineStyle:2,axisLabelVisible:true}));}catch(e){}}
}
function rearm(){armed=WATCH.map(()=>true);}
function unlockAudio(){try{
  ac=ac||new (window.AudioContext||window.webkitAudioContext)();
  if(ac&&ac.state==='suspended')ac.resume(); // 제스처 전 생성된 컨텍스트는 suspended(자동재생 정책)
}catch(e){}}
// 아무 탭 터치/클릭이든 첫 제스처에서 오디오 잠금 해제 — 알림 버튼을 안 눌러도 비프가 울리게
try{if(typeof document.addEventListener==='function')
  document.addEventListener('pointerdown',unlockAudio,{once:true});}catch(e){}
function beep(){try{unlockAudio();
  const o=ac.createOscillator(),g=ac.createGain();
  o.connect(g);g.connect(ac.destination);o.frequency.value=880;
  g.gain.setValueAtTime(.25,ac.currentTime);
  g.gain.exponentialRampToValueAtTime(.001,ac.currentTime+.5);
  o.start();o.stop(ac.currentTime+.5);}catch(e){}}
function notifyWatch(w,price){
  const msg=w.label+' '+won(w.price)+' ±0.5% 진입 — 현재가 '+won(price);
  document.getElementById('walert').textContent='🔔 '+msg;
  try{if(typeof Notification!=='undefined'&&Notification.permission==='granted')
    new Notification('감시선 접근: '+w.label,{body:msg});}catch(e){}}
function checkWatch(price){
  WATCH.forEach((w,i)=>{
    const dist=Math.abs(price-w.price)/w.price;
    // 스냅샷(1초) 사이에 밴드를 건너뛴 급변도 놓치지 않게 부호 교차를 함께 판정
    const crossed=lastWatchPrice!=null&&(lastWatchPrice-w.price)*(price-w.price)<0;
    if(dist<=0.005||crossed){if(armed[i]){armed[i]=false;beep();notifyWatch(w,price);}}
    else if(dist>0.007){armed[i]=true;}
  });
  lastWatchPrice=price;}
(function(){const b=document.getElementById('notifbtn');
  if(WATCH.length&&typeof Notification!=='undefined'&&Notification.permission==='default'){
    b.style.display='';
    b.onclick=()=>{unlockAudio();Notification.requestPermission().finally(()=>{b.style.display='none';});};
  }})();

// ── 감시선 편집기(내 라인 칩 + 편집 패널 + 차트 탭 추가 + 서버 저장) ──
let wlDraft=WATCH.map(w=>({price:w.price,label:w.label}));
function renderMyLines(){
  const el=document.getElementById('mylines'); if(!el)return;
  let h=WATCH.map(w=>'<span class="myline"><span class="dot"></span>'+esc(w.label)+' '+won(w.price)+'</span>').join('');
  h+='<span class="myline add" onclick="openWlEditor()">＋ 라인 추가</span>';
  el.innerHTML=h;
}
function openWlEditor(){const d=document.getElementById('wl-panel'); if(d)d.open=true;
  try{d.scrollIntoView({behavior:'smooth',block:'nearest'});}catch(e){}}
function wlStatus(t){const s=document.getElementById('wl-status'); if(s)s.textContent=t;}
function renderWlDraft(){
  const el=document.getElementById('wl-rows'); if(!el)return;
  el.innerHTML=wlDraft.map((w,i)=>'<div class="wl-row">'
    +'<input class="wl-label" data-i="'+i+'" data-k="label" type="text" maxlength="20" placeholder="라벨(예: 절대선)" value="'+esc(w.label)+'">'
    +'<input class="wl-price" data-i="'+i+'" data-k="price" type="number" inputmode="numeric" placeholder="가격" value="'+(w.price===''||w.price==null?'':w.price)+'">'
    +'<button class="wl-del" type="button" data-del="'+i+'">✕</button></div>').join('');
  // 인라인 oninput은 최상위 let(wlDraft) 바인딩을 못 찾을 수 있어(전역 프로퍼티 아님)
  // addEventListener로 확실히 바인딩 — 편집이 draft에 반영되지 않는 무증상 버그 방지.
  if(!el.querySelectorAll)return;
  el.querySelectorAll('input').forEach(inp=>inp.addEventListener('input',function(){
    const i=+this.getAttribute('data-i'), k=this.getAttribute('data-k');
    if(wlDraft[i])wlDraft[i][k]=this.value;
  }));
  el.querySelectorAll('.wl-del').forEach(btn=>btn.addEventListener('click',function(){
    wlDelRow(+this.getAttribute('data-del'));
  }));
}
function wlDelRow(i){wlDraft.splice(i,1); renderWlDraft();}
function wlAddRow(label){wlDraft.push({price:'',label:label||''}); renderWlDraft(); openWlEditor();}
function saveLines(){
  const lines=[];
  for(let i=0;i<wlDraft.length;i++){const w=wlDraft[i];
    const p=parseFloat(w.price), l=(w.label||'').trim();
    if(!(p>0)||!l)continue; lines.push({price:Math.round(p),label:l});}
  wlStatus('저장 중…');
  fetch('/api/watch/'+CODE,{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({lines:lines})})
    .then(r=>r.json().then(d=>({ok:r.ok,d:d})))
    .then(res=>{
      if(res.ok){WATCH=res.d.lines; wlDraft=WATCH.map(w=>({price:w.price,label:w.label}));
        renderWatchLines(); rearm(); renderWlDraft(); renderMyLines();
        wlStatus('저장됨 ✓ ('+WATCH.length+'개 · 기기 간 반영)');}
      else{wlStatus((res.d&&res.d.error)||'저장 실패');}
    }).catch(()=>wlStatus('저장 실패 — 네트워크 확인 후 재시도'));
}
// 차트 탭 → 그 가격에 감시선 초안 추가(명시 저장 전까진 표시만)
try{if(pchart&&pchart.subscribeClick)pchart.subscribeClick(param=>{
  try{if(param&&param.point){const price=pseries.coordinateToPrice(param.point.y);
    if(price!=null&&price>0){wlDraft.push({price:Math.round(price),label:'감시선'});
      renderWlDraft(); openWlEditor(); wlStatus('차트에서 고른 가격 추가됨 — 라벨 확인 후 저장');}}}catch(e){}
});}catch(e){}

// ── 체결 규모 분포(주체 추정): 세션 토글 + 방향×구간 막대 ──
let SZ_SES=null, LAST_S=null; // SZ_SES null=자동(현재 세션 추종)
const SES_KO={pre:'장전(8:00~9:00)',regular:'정규장',after:'장후 NXT(15:30~20:00)'};
function curSession(){const t=KTIME||'12:00:00';
  return t<'09:00:00'?'pre':(t<='15:30:00'?'regular':'after');}
document.querySelectorAll('#sz-tabs .tf').forEach(b=>b.onclick=()=>{
  SZ_SES=b.dataset.ses; if(LAST_S)renderSizes(LAST_S);});
function renderSizes(S){
  const ses=SZ_SES||curSession();
  document.querySelectorAll('#sz-tabs .tf').forEach(x=>x.classList.toggle('on',x.dataset.ses===ses));
  const Z=(S.sizes||{})[ses];
  const el=document.getElementById('sz-bars'), sg=document.getElementById('sz-sig');
  const fresh=document.getElementById('sz-fresh');
  if(!Z){el.innerHTML='';sg.textContent='';fresh.textContent='· 데이터 없음';return;}
  const KO={s1:'1-10주',s2:'11-50주',s3:'51-100주',s4:'100주 초과'};
  let tot=0,n=0;
  for(const side of ['buy','sell'])for(const k in Z[side]){tot+=Z[side][k].v;n+=Z[side][k].n;}
  if(!tot){
    el.innerHTML='<div class="meta">이 세션 체결 수신 없음 (서버 기동 이후 집계분만 포함)</div>';
    sg.textContent=''; sg.className='sig';
    fresh.textContent='· '+SES_KO[ses]+' · 표본 0건';return;
  }
  el.innerHTML=['sell','buy'].map(side=>
    ['s4','s3','s2','s1'].map(k=>{const c=Z[side][k];const pct=c.v/tot*100;
      return '<div class="szrow"><span class="szlbl">'+(side==='buy'?'매수':'매도')+' '+KO[k]
        +'</span><div class="szbar '+(side==='buy'?'szbuy':'szsell')+'" style="width:'
        +Math.max(2,pct*2.6)+'px"></div><span class="szval">'+c.n.toLocaleString('ko-KR')
        +'건 · '+pct.toFixed(1)+'%</span></div>';}).join('')).join('');
  const sig=(S.sizes.signals||{})[ses];
  if(sig){sg.textContent='판정: '+sig.text; sg.className='sig sig-'+sig.tone;}
  else{sg.textContent='판정 보류 — 표본 30건 미만(추정 불가)'; sg.className='sig sig-flat';}
  fresh.textContent='· '+SES_KO[ses]+' · 표본 '+n.toLocaleString('ko-KR')+'건 · 추정치';
}

function render(S){
  KDATE=S.kst_date; KTIME=S.kst_time; // 모든 표시 시각의 기준(서버 KST)
  LAST_S=S; renderSizes(S);
  const mode=document.getElementById('mode');
  mode.textContent=S.mode.toUpperCase();
  mode.className='badge '+(S.mode==='live'?'b-live':'b-demo');
  const conn=document.getElementById('conn');
  conn.textContent=S.status.connected?'수신 중':'재연결 중';
  conn.className='badge '+(S.status.connected?'b-live':'b-off');
  // 시장 상태 배지(P1-7) + 수신 정지 오버레이(P0-2) — 판정은 서버가 한다
  const ms=S.market_state||{};
  const mb=document.getElementById('mstate');
  mb.textContent=ms.label||'–';
  mb.className='badge b-'+({live:'live',warn:'warn',info:'info',off:'off'}[ms.tone]||'off');
  const halted=ms.state==='halt';
  const stxt=halted?'⏸ 수신 정지 ('+(S.stall&&S.stall.since?S.stall.since:'--:--:--')
    +' 이후) — VI·서킷브레이커·장중단 가능성. 마지막 값이 이어져 보이는 것에 주의':'';
  for(const id of ['pstall','cstall']){
    const el=document.getElementById(id);
    el.className='stall'+(halted?' on':'');
    el.textContent=stxt;
  }
  if(S.market.price==null){
    document.getElementById('price').textContent=S.status.connected?'체결 대기 중':'실시간 연결 중…';
  }
  document.getElementById('note').textContent=S.status.note||'';
  const M=S.market;
  if(M.price!=null){
    const p=document.getElementById('price');
    p.textContent=won(M.price)+' '+sgn[M.sign]+' '+(M.rate!=null?Math.abs(M.rate).toFixed(2)+'%':'');
    p.className='price '+M.sign;
    document.getElementById('pmeta').innerHTML='거래량 '+num(M.vol)+'주 · 거래대금 '+eok(M.value).replace('+','')
      +' · 체결강도 '+(M.strength==null?'–':M.strength.toFixed(1))+' · 기준 '+esc(M.time||'')+' (KST) <span class="fresh">· 실시간 · __MKT__</span>';
    checkWatch(M.price); // 감시선 ±0.5% 진입 알림(P1-8)
  }
  const ED=S.estimate_detail;
  const E=S.estimate;
  if(E.rows.length){
    const last=E.rows[E.rows.length-1];
    document.getElementById('est-fresh').textContent='잠정 · '+last.asof+' 기준 · 다음 갱신 '+nextSlot()+' · 익일 확정';
    const combined=r=>-(r.frgn+r.orgn); // 개인+기타 역산(합계 0 원리)
    // 기타법인 잠정(상위30 가집계)이 있으면 개인 단독까지 분리
    const canSplit = ED.etc_qty!=null && ED.rows.length>0;
    const pv = canSplit ? combined(last)-ED.etc_qty : combined(last);
    document.getElementById('est-note').textContent = canSplit
      ? '개인 = −(외국인+기관+기타법인) 역산 · 기타법인 '+shares(ED.etc_qty)+' (장중 가집계, 1,000주 단위) · 아래 이력 표의 개인+기타는 슬롯별 역산값'
      : '*개인+기타법인 = −(외국인+기관) 역산 — 장중 개인 집계는 어디에도 없어 "전체 매매 합계는 0" 원리로 추정한 값';
    // 순매수 방향·크기를 발산형 막대로(중앙 0선 기준, 매수=적/매도=청)
    const mA=Math.max(Math.abs(pv||0),Math.abs(last.frgn||0),Math.abs(last.orgn||0))||1;
    document.getElementById('est-bars').innerHTML=
      divbar(canSplit?'개인(추정)':'개인+기타',pv,mA)
      +divbar('외국인',last.frgn,mA)+divbar('기관',last.orgn,mA);
    document.getElementById('est-hist').innerHTML='<tr><th>기준</th><th>개인+기타*</th><th>외국인</th><th>기관</th></tr>'
      +E.rows.slice().reverse().map(r=>'<tr><td>'+esc(r.asof)+'</td><td class="'+cls(combined(r))+'">'+shares(combined(r))
      +'</td><td class="'+cls(r.frgn)+'">'+shares(r.frgn)
      +'</td><td class="'+cls(r.orgn)+'">'+shares(r.orgn)+'</td></tr>').join('');
  }else{
    // 날짜가 바뀌어 서버가 당일 상태를 비우면(전일 잠정 잔존 방지) 화면도 함께 비운다
    document.getElementById('est-fresh').textContent='잠정 · 오늘 발표 전 — 첫 잠정치 '+nextSlot()+' · 익일 확정';
    document.getElementById('est-note').textContent='*개인+기타법인 = −(외국인+기관) 역산 — 장중 개인 집계는 어디에도 없어 "전체 매매 합계는 0" 원리로 추정한 값';
    document.getElementById('est-bars').innerHTML='<div class="meta">오늘 발표 전 — 데이터 대기</div>';
    document.getElementById('est-hist').innerHTML='';
  }
  const P=S.program;
  const q=document.getElementById('pgm-qty');
  q.textContent=shares(P.net_qty); q.className='val '+cls(P.net_qty);
  const v=document.getElementById('pgm-val');
  v.textContent=eok(P.net_value); v.className='val '+cls(P.net_value);
  // Y축 도메인: 당일 누적 전체 min/max ±5%(P0-1) — 극값이 접혀도 서버가 별도 추적
  if(P.day_min!=null&&P.day_max!=null){
    const lo=P.day_min/1e8, hi=P.day_max/1e8;
    const pad=((hi-lo)||Math.max(Math.abs(hi),1))*0.05; // 단일값이면 |값|의 5%로 폭 확보
    pgmRange={minValue:lo-pad,maxValue:hi+pad};
  }else{pgmRange=null;}
  if(P.points.length){
    const seen={},pts=[];
    for(const pt of P.points){const ts=toTs(pt.t);
      if(!seen[ts]){seen[ts]=1;pts.push({time:ts,value:pt.net_value/1e8});}}
    series.setData(pts); chart.timeScale().fitContent();
    document.getElementById('pgm-fresh').textContent='· 실시간 · 기준 '
      +P.points[P.points.length-1].t+' (KST)';
  }else{
    // 자정 리셋 후 열려 있는 탭에서 전일 곡선이 '실시간'으로 남는 회귀 방지
    series.setData([]);
    document.getElementById('pgm-fresh').textContent='· 실시간 · 오늘 데이터 대기';
  }
  if(ED.rows.length){
    document.getElementById('est-detail').innerHTML='<tr><th>↳ 기관 내역(잠정)</th><th>순매수</th><th>금액</th></tr>'
      +ED.rows.map(r=>'<tr><td>'+esc(r.name)+'</td><td class="'+cls(r.qty)+'">'+shares(r.qty)
      +'</td><td class="'+cls(r.value)+'">'+eok(r.value)+'</td></tr>').join('');
    document.getElementById('est-detail-note').textContent=(ED.asof?ED.asof+' 조회 · ':'')
      +'1,000주 단위 가집계 · 금융투자/사모 미포함 · 수급 상위30 진입 시 제공';
  }else{
    document.getElementById('est-detail').innerHTML='';
    document.getElementById('est-detail-note').textContent='기관 내역(투신/연기금 등)은 이 종목이 외인/기관 수급 상위30에 들 때만 장중 제공(거래소 제약). 확정 내역은 아래 패널에 항상 표시.';
  }
  const DT=S.detail;
  if(DT.rows.length){
    document.getElementById('dt-fresh').textContent='확정 · '+DT.date+' 기준 · 장중 세부 분해는 제공되지 않음(거래소 확정 후 반영)';
    document.getElementById('detail').innerHTML='<tr><th>주체</th><th>순매수</th><th>금액</th></tr>'
      +DT.rows.map(r=>'<tr><td>'+esc(r.name)+'</td><td class="'+cls(r.qty)+'">'+shares(r.qty)
      +'</td><td class="'+cls(r.value)+'">'+eok(r.value)+'</td></tr>').join('');
  }
  const SB=S.short||{rows:[]};
  const sbm={}; SB.rows.forEach(r=>{sbm[r.date]=r;});
  document.getElementById('daily').innerHTML='<tr><th>날짜</th><th>개인</th><th>외국인</th><th>기관</th><th>종가</th><th>대차잔고</th></tr>'
    +S.daily.map(d=>{const m=sbm[d.date];
    return '<tr><td>'+esc(d.date.slice(5))+'</td><td class="'+cls(d.prsn)+'">'+shares(d.prsn)
    +'</td><td class="'+cls(d.frgn)+'">'+shares(d.frgn)+'</td><td class="'+cls(d.orgn)+'">'+shares(d.orgn)
    +'</td><td>'+won(d.close)+'</td><td class="'+(m&&m.chg!=null?cls(m.chg):'flat')+'">'
    +(m?num(m.qty):'–')+'</td></tr>';}).join('');
  // ── 대차잔고 패널: 최신 잔고·증감(증가=적색/감소=청색)·판정 시그널·20일 추이 ──
  const jo=n=>n==null?'–':(Math.abs(n)>=1e12?(n/1e12).toLocaleString('ko-KR',{maximumFractionDigits:1})+'조':eok(n).replace('+',''));
  const srcKo={kofia:'금융투자협회',seibro:'예탁결제원(SEIBro)',demo:'데모(시뮬레이션)'};
  if(SB.rows.length){
    const last=SB.rows[SB.rows.length-1];
    // 협회·예탁원은 집계 범위가 달라 절대치가 다르다 — 혼합 시 행별 출처 표기
    const srcShort={kofia:'협회',seibro:'예탁원',demo:'데모'};
    const mixed=new Set(SB.rows.map(r=>r.src)).size>1;
    document.getElementById('sb-fresh').textContent='확정 · '+last.date+' 기준 · T+1 공시 · 출처 '
      +(srcKo[last.src]||last.src)+(mixed?' · ⚠ 기간 내 출처 혼합(추이 표의 출처 열 참조)':'');
    document.getElementById('sb-qty').textContent=num(last.qty)+'주';
    const sc=document.getElementById('sb-chg');
    sc.textContent=last.chg==null?'–':shares(last.chg);
    sc.className='val '+(last.chg==null?'flat':cls(last.chg));
    document.getElementById('sb-val').textContent=jo(last.value);
    // 20일 대차잔고 추이 스파크라인 — 증가=공매도 연료↑(경계) / 감소=상환(완화)
    const _sq=SB.rows.map(r=>r.qty);
    document.getElementById('sb-spark').innerHTML=
      spark(_sq,(_sq[_sq.length-1]-_sq[0])>0?'var(--warn)':'var(--good)');
    const sig=SB.signal;
    const sg=document.getElementById('sb-sig');
    if(sig){
      sg.textContent='판정: '+sig.text+' — 주가 '+(M.rate==null?'–':(M.rate>0?'▲':(M.rate<0?'▼':''))+Math.abs(M.rate).toFixed(2)+'%')
        +' × 대차 '+(last.chg==null?'–':shares(last.chg));
      sg.className='sig sig-'+sig.tone;
    }else{sg.textContent='판정 대기 — 주가 등락·잔고 증감 확보 후 표시'; sg.className='sig sig-flat';}
    document.getElementById('sb-hist').innerHTML='<tr><th>날짜</th><th>잔고(주)</th><th>전일 대비</th><th>금액</th>'
      +(mixed?'<th>출처</th>':'')+'</tr>'
      +SB.rows.slice().reverse().map(r=>'<tr><td>'+esc(r.date.slice(5))+'</td><td>'+num(r.qty)
      +'</td><td class="'+(r.chg==null?'flat':cls(r.chg))+'">'+(r.chg==null?'–':shares(r.chg))
      +'</td><td>'+jo(r.value)+'</td>'
      +(mixed?'<td>'+esc(srcShort[r.src]||r.src)+'</td>':'')+'</tr>').join('');
    document.getElementById('sb-note').textContent='대차잔고 = 공매도 등을 위해 빌려간 뒤 아직 갚지 않은 주식 수(T+1 공시). 늘어나면 공매도 대기 물량 증가, 줄어들면 상환(숏 청산) 신호.'+(last.src==='seibro'?' ※ 예탁결제원 폴백 수치 — 협회 통계와 집계 범위가 달라요.':'');
  }else{
    document.getElementById('sb-fresh').textContent='· 데이터 없음';
    for(const id of ['sb-qty','sb-chg','sb-val']){
      const el=document.getElementById(id); el.textContent='–'; el.className='val';
    }
    document.getElementById('sb-sig').textContent=''; document.getElementById('sb-sig').className='sig';
    document.getElementById('sb-spark').innerHTML='';
    document.getElementById('sb-hist').innerHTML='';
    document.getElementById('sb-note').textContent='대차잔고: 데이터 없음 — 소스(금융투자협회·예탁결제원) 응답 실패 또는 미공시. 자동 재시도 중.';
  }
  // ── ADR 환산가·괴리율(P1-4): 환산·괴리율은 서버 스냅샷 계산값 ──
  const A=S.adr;
  if(A){
    document.getElementById('adr-usd-lbl').textContent=esc(A.sym)+' ($)';
    document.getElementById('adr-usd').textContent='$'+A.usd.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});
    const cv=document.getElementById('adr-conv');
    cv.textContent=won(A.converted);
    cv.className='val '+(A.premium_pct==null?'':cls(A.premium_pct));
    document.getElementById('adr-ord').textContent=won(A.ord_price);
    const asg=document.getElementById('adr-sig');
    if(A.premium_pct!=null){
      asg.textContent='괴리율 '+(A.premium_pct>0?'+':'')+A.premium_pct.toFixed(2)+'% — '
        +(A.premium_pct>0?'미국이 원주보다 높게 평가(프리미엄)':(A.premium_pct<0?'미국이 원주보다 낮게 평가(디스카운트)':'등가'));
      asg.className='sig '+cls(A.premium_pct);
    }else{asg.textContent='괴리율 대기 — 원주 체결 확보 후 표시'; asg.className='sig sig-flat';}
    document.getElementById('adr-fresh').textContent='· '
      +(A.us_open?'미국 장중':'미국 장마감 — 전일 종가 기준')
      +' · 환율 '+A.fx.toLocaleString('ko-KR')+'원 · 조회 '+esc(A.fetched||'')+' (KST) · 출처 '
      +(A.src==='kis'?'KIS':(A.src==='naver'?'네이버(폴백)':'데모'));
    document.getElementById('adr-note').textContent='환산가 = '+esc(A.sym)+' × '
      +A.ratio+' (DR '+A.ratio+'주 = 원주 1주) × USD/KRW. 원주보다 비싸면(+, 적색) 미국 프리미엄.';
  }else{
    document.getElementById('adr-fresh').textContent='· 데이터 없음 — DR 시세/환율 조회 실패 또는 미지원 종목. 자동 재시도 중';
    for(const id of ['adr-usd','adr-conv','adr-ord']){
      const el=document.getElementById(id); el.textContent='–'; el.className='val';
    }
    document.getElementById('adr-sig').textContent=''; document.getElementById('adr-sig').className='sig';
  }
  // ── 공매도 일별 체결(P1-6): 대차(빌린 물량) vs 체결(쏜 물량) 비교 ──
  const SS=S.shortsale||{rows:[]};
  if(SS.rows.length){
    const sl=SS.rows[SS.rows.length-1];
    document.getElementById('ss-fresh').textContent='확정 · 기준일: '+sl.date+' · T+1 공시 · 출처 KIS';
    document.getElementById('ss-qty').textContent=num(sl.qty)+'주';
    document.getElementById('ss-ratio').textContent=(sl.ratio||0).toFixed(2)+'%';
    const borrow=SB.rows.length?SB.rows[SB.rows.length-1].qty:null;
    document.getElementById('ss-vs').textContent=borrow?(sl.qty/borrow*100).toFixed(1)+'%':'–';
    const _ssq=SS.rows.map(r=>r.qty);
    document.getElementById('ss-spark').innerHTML=
      spark(_ssq,(_ssq[_ssq.length-1]-_ssq[0])>0?'var(--warn)':'var(--good)');
    document.getElementById('ss-hist').innerHTML='<tr><th>날짜</th><th>공매도(주)</th><th>비중</th><th>종가</th></tr>'
      +SS.rows.slice().reverse().map(r=>'<tr><td>'+esc(r.date.slice(5))+'</td><td>'+num(r.qty)
      +'</td><td>'+(r.ratio||0).toFixed(2)+'%</td><td>'+won(r.close)+'</td></tr>').join('');
  }else{
    document.getElementById('ss-fresh').textContent='· 데이터 없음 — 조회 실패 또는 미공시. 자동 재시도 중';
    for(const id of ['ss-qty','ss-ratio','ss-vs']){
      const el=document.getElementById(id); el.textContent='–'; el.className='val';
    }
    document.getElementById('ss-spark').innerHTML='';
    document.getElementById('ss-hist').innerHTML='';
  }
  // ── 신용융자 잔고(P1-5): 반대매매 연료 게이지 ──
  const CR=S.credit||{rows:[]};
  if(CR.rows.length){
    const cl=CR.rows[CR.rows.length-1];
    document.getElementById('cr-fresh').textContent='확정 · 기준일: '+cl.date+' · 결제 반영 실질 T+2 · 출처 KIS';
    document.getElementById('cr-qty').textContent=num(cl.qty)+'주 ('+(cl.ratio||0).toFixed(2)+'%)';
    const cc=document.getElementById('cr-chg');
    cc.textContent=cl.chg==null?'–':shares(cl.chg);
    cc.className='val '+(cl.chg==null?'flat':cls(cl.chg));
    document.getElementById('cr-val').textContent=jo(cl.value);
    const _crq=CR.rows.map(r=>r.qty);
    document.getElementById('cr-spark').innerHTML=
      spark(_crq,(_crq[_crq.length-1]-_crq[0])>0?'var(--warn)':'var(--good)');
    const csig=CR.signal, csg=document.getElementById('cr-sig');
    if(csig){csg.textContent='판정: '+csig.text; csg.className='sig sig-'+csig.tone;}
    else{csg.textContent='판정 대기 — 이틀 이상 데이터 확보 후 표시'; csg.className='sig sig-flat';}
    document.getElementById('cr-hist').innerHTML='<tr><th>날짜</th><th>잔고(주)</th><th>전일 대비</th><th>금액≈</th></tr>'
      +CR.rows.slice().reverse().map(r=>'<tr><td>'+esc(r.date.slice(5))+'</td><td>'+num(r.qty)
      +'</td><td class="'+(r.chg==null?'flat':cls(r.chg))+'">'+(r.chg==null?'–':shares(r.chg))
      +'</td><td>'+jo(r.value)+'</td></tr>').join('');
  }else{
    document.getElementById('cr-fresh').textContent='· 데이터 없음 — 조회 실패 또는 미공시. 자동 재시도 중';
    for(const id of ['cr-qty','cr-chg','cr-val']){
      const el=document.getElementById(id); el.textContent='–'; el.className='val';
    }
    document.getElementById('cr-spark').innerHTML='';
    document.getElementById('cr-sig').textContent=''; document.getElementById('cr-sig').className='sig';
    document.getElementById('cr-hist').innerHTML='';
  }
  // ── 거래소별 거래량 (KRX vs NXT) ──
  const XV=S.exvol;
  if(XV&&XV.krx&&XV.nxt){
    document.getElementById('xv-fresh').textContent='· 기준 '+esc(XV.asof||'')+' (KST) · 출처 KIS';
    document.getElementById('xv-krx').textContent=num(XV.krx.vol)+'주';
    document.getElementById('xv-nxt').textContent=num(XV.nxt.vol)+'주';
    document.getElementById('xv-share').textContent=XV.nxt_share_pct==null?'–':XV.nxt_share_pct.toFixed(1)+'%';
    document.getElementById('xv-propbar').innerHTML=propbar('KRX 정규',XV.krx.vol,'NXT',XV.nxt.vol);
    const XS=XV.sessions||{};
    const fv=v=>v==null?'– (진행 중/미집계)':num(v)+'주';
    document.getElementById('xv-ses').innerHTML='<tr><th>NXT 세션</th><th>거래량</th></tr>'
      +'<tr><td>장전 (08:00~08:50)</td><td>'+fv(XS.pre)+'</td></tr>'
      +'<tr><td>본장 (09:00~15:20)</td><td>'+fv(XS.main)+'</td></tr>'
      +'<tr><td>장후 (15:30~20:00)</td><td>'+fv(XS.after)+'</td></tr>';
    const W=XV.warn, xg=document.getElementById('xv-sig');
    if(W){
      xg.textContent='판정: '+W.text+' — 시간외 '+(W.move_pct>0?'+':'')+W.move_pct.toFixed(2)
        +'% (NXT '+won(XV.nxt.price)+' vs 정규 종가 '+won(XV.krx.price)
        +') · 장후 거래량 = 당일의 '+W.after_share_pct.toFixed(2)+'%';
      xg.className='sig sig-'+W.tone;
    }else{xg.textContent=''; xg.className='sig';}
  }else{
    document.getElementById('xv-fresh').textContent='· 데이터 없음 — 조회 실패, 자동 재시도 중';
    for(const id of ['xv-krx','xv-nxt','xv-share']){
      const el=document.getElementById(id); el.textContent='–'; el.className='val';
    }
    document.getElementById('xv-propbar').innerHTML='';
    document.getElementById('xv-ses').innerHTML='';
    document.getElementById('xv-sig').textContent='';
  }
  // ── 거래원(회원사) 창구 분석 ──
  const MB=S.member;
  if(MB&&((MB.sell&&MB.sell.length)||(MB.buy&&MB.buy.length))){
    document.getElementById('mb-fresh').textContent='· 기준 '+esc(MB.asof||'')+' (KST) · '
      +(MB.basis==='J'?'정규장(KRX) 기준':'KRX+NXT 통합')+' · 추정';
    const nm=x=>x?('<span'+(x.foreign?' class="fgn"':'')+'>'+esc(x.name)+'</span> <span class="meta">'
      +(x.rlim||0).toFixed(1)+'%</span>'):'';
    let rows='<tr><th>매도 창구</th><th>수량</th><th>매수 창구</th><th>수량</th></tr>';
    for(let i=0;i<5;i++){
      const sr=(MB.sell||[])[i], br=(MB.buy||[])[i];
      if(!sr&&!br)continue;
      rows+='<tr><td>'+nm(sr)+'</td><td>'+(sr?num(sr.qty):'')+'</td><td>'+nm(br)
        +'</td><td>'+(br?num(br.qty):'')+'</td></tr>';
    }
    document.getElementById('mb-tbl').innerHTML=rows;
    const G=MB.glob, mg=document.getElementById('mb-sig');
    if(G&&(G.seln||G.shnu)){
      mg.textContent='외국계 창구(정규장 기준): 매도 '+num(G.seln)+'주 · 매수 '+num(G.shnu)
        +'주 · 순매수 '+shares(G.ntby)
        +(G.ntby<0?' → 외국계 순매도 우위(추정)':(G.ntby>0?' → 외국계 순매수 우위(추정)':' → 균형'));
      mg.className='sig '+(G.ntby<0?'sig-warn':(G.ntby>0?'sig-good':'sig-flat'));
    }else{mg.textContent='외국계 합계 미제공(장전이거나 집계 전)'; mg.className='sig sig-flat';}
  }else{
    document.getElementById('mb-fresh').textContent='· 데이터 없음 — 조회 실패, 자동 재시도 중';
    document.getElementById('mb-tbl').innerHTML='';
    document.getElementById('mb-sig').textContent='';
  }
  document.getElementById('tape').innerHTML='<tr><th>시각</th><th>체결가</th><th>체결량</th><th>구분</th></tr>'
    +S.tape.map(t=>'<tr><td>'+esc(t.t)+'</td><td>'+won(t.price)+'</td><td>'+num(t.vol)
    +'</td><td class="'+(t.side==='buy'?'up':(t.side==='sell'?'down':'flat'))+'">'
    +(t.side==='buy'?'매수':(t.side==='sell'?'매도':'-'))+'</td></tr>').join('');
  // ── 매매 타이밍(이평 20/60/120 × 수급) — 참고용 추정. 헤드라인은 sticky 히어로에 표시 ──
  const TM=S.timing, tmh=document.getElementById('tm-headline');
  if(TM&&TM.stance){
    tmh.textContent=TM.headline+(TM.confidence!=null?' · 확신도 '+TM.confidence+'/3':'');
    tmh.className='sig sig-'+(TM.tone||'flat');
    document.getElementById('tm-comment').textContent=TM.comment||'';
    document.getElementById('tm-reasons').innerHTML=(TM.reasons||[]).map(r=>'<tr><td>· '+esc(r)+'</td></tr>').join('')
      +(TM.entry_hint?'<tr><td>🎯 진입: '+esc(TM.entry_hint)+'</td></tr>':'');
    document.getElementById('tm-fresh').textContent='· 참고용(추정) · '+esc(TM.asof||'')+' 기준';
  }else{
    tmh.textContent=(TM&&TM.headline)||'판정 보류 — 데이터 대기';
    tmh.className='sig sig-flat';
    document.getElementById('tm-comment').textContent=(TM&&TM.comment)||'일봉(120)·수급 확보 후 표시';
    document.getElementById('tm-reasons').innerHTML='';
    document.getElementById('tm-fresh').textContent='· 참고용(추정)';
  }
  // ── 한눈 요약 스트립: 핵심 지표를 히어로 아래 한 줄로 압축(중복이라도 전부 노출) ──
  (function(){
    let g='';
    if(E.rows.length){const lr=E.rows[E.rows.length-1];
      g+=glchip('외인 순매수',shares(lr.frgn),cls(lr.frgn));
      g+=glchip('기관 순매수',shares(lr.orgn),cls(lr.orgn));}
    if(P.net_value!=null)g+=glchip('프로그램',eok(P.net_value),cls(P.net_value));
    if(SS.rows.length)g+=glchip('공매도 비중',(SS.rows[SS.rows.length-1].ratio||0).toFixed(2)+'%','flat');
    if(A&&A.premium_pct!=null)g+=glchip('ADR 괴리',(A.premium_pct>0?'+':'')+A.premium_pct.toFixed(2)+'%',cls(A.premium_pct));
    document.getElementById('glance').innerHTML=g;
  })();
}

// ── 화면 초기화(감시선·섹션) — node 렌더 스모크(window/location/history 없음)에서
//    죽지 않게 가드. render()는 별도로 호출되므로 이 블록이 실패해도 피드는 산다. ──
try{ renderWatchLines(); rearm(); renderWlDraft(); renderMyLines(); }catch(e){}

// ── SSE 연결 관리(P0): 네이티브 EventSource 자동 재접속은 readyState=CONNECTING
//    에서만 동작 → iOS PWA 백그라운드 복귀·서버 재시작(비2xx 응답)·모바일 네트워크
//    전환 시 CLOSED로 죽어 영구 미복구(실사고 "연결 끊어지고 복구 안됨"). 오류 없이
//    조용히 멈춘 half-open도 네이티브는 못 잡는다. 세 경로로 직접 되살린다:
//    (1) onerror가 CLOSED면 상한 백오프로 수동 재접속 — 상한 15s ≪ 서버 LINGER 300s
//        이라 재접속이 웜 엔진을 재사용(KIS 1키1세션 EOF churn 회피).
//    (2) 서버의 1초 스냅샷을 하트비트로 삼아, 공백이 STALL_MS를 넘으면 워치독이 강제 재접속.
//    (3) 화면 복귀(visibilitychange)/온라인 복귀 시 즉시 재접속.
//    모든 재접속은 단일 connect() 경로 + 단일 타이머로 — 병렬 EventSource 금지(중복 연결 방지).
let es=null, esBackoff=1000, reconnTimer=null, lastMsg=0;
const STALL_MS=15000;      // 하트비트(스냅샷 1초) 공백 한계 — 초과 시 정지로 판정
const MAX_BACKOFF=15000;   // 서버 linger(300s)보다 훨씬 작게 — 재접속 시 웜 엔진 재사용 보장
function setConn(txt){const c=document.getElementById('conn');
  if(c){c.textContent=txt; c.className='badge b-off';}}
function scheduleReconnect(){
  if(reconnTimer)return;   // 재접속 타이머는 항상 하나만(중복 연결 원천 차단)
  const wait=esBackoff+Math.floor(Math.random()*1000); // 지터
  setConn('연결 끊김 · '+Math.round(wait/1000)+'초 후 재접속');
  reconnTimer=setTimeout(()=>{reconnTimer=null;connect();},wait);
  esBackoff=Math.min(esBackoff*2,MAX_BACKOFF);
}
function authGuardThen(action){
  // 재접속 전 세션 확인 — 만료(401)면 무한 재접속(방금 고친 버그처럼) 대신 로그인으로.
  // 인증 비활성(라우트 없음 404)·정상(200)·기타는 그대로 재접속 경로로.
  fetch('/api/auth/check',{cache:'no-store'}).then(r=>{
    if(r.status===401)location.href='/login'; else action();
  }).catch(()=>action());
}
function connect(){
  if(reconnTimer){clearTimeout(reconnTimer);reconnTimer=null;}
  if(es){try{es.close();}catch(e){}}   // 기존 연결 정리 — 병렬 스트림 방지
  setConn('연결 중…');
  lastMsg=Date.now();
  es=new EventSource('/api/live/'+CODE+'/stream');
  es.onopen=()=>{esBackoff=1000;};     // 접속 성공 → 백오프 리셋
  es.onmessage=e=>{lastMsg=Date.now();
    try{render(JSON.parse(e.data));}catch(err){console.error(err);}};
  es.onerror=()=>{
    // CONNECTING이면 네이티브가 자체 재시도 중 → 맡긴다. CLOSED면 죽은 것 → 세션
    // 확인 후 수동 재접속(만료면 로그인으로).
    if(es.readyState===EventSource.CLOSED)authGuardThen(scheduleReconnect);
    else setConn('재접속 중…');
  };
}
setInterval(()=>{   // 워치독: 오류 이벤트 없이 멈춘 half-open을 하트비트 공백으로 감지
  if(es&&es.readyState!==EventSource.CLOSED&&Date.now()-lastMsg>STALL_MS){
    setConn('응답 없음 · 재접속');
    authGuardThen(()=>{esBackoff=1000;connect();});
  }
},5000);
function resume(){   // 화면/네트워크 복귀 — 죽었거나 멈췄으면 즉시 되살린다(iOS PWA 잠금 복귀)
  if(!es||es.readyState===EventSource.CLOSED||Date.now()-lastMsg>STALL_MS){
    esBackoff=1000; connect();
  }
}
try{
  if(typeof document.addEventListener==='function')
    document.addEventListener('visibilitychange',()=>{if(!document.hidden)resume();});
  if(typeof window!=='undefined'&&window.addEventListener)
    window.addEventListener('online',resume);
}catch(e){}
connect();
</script>__TABBAR__ __NAV_LOADER__</body></html>"""


_MKT_LABEL = {"UN": "KRX+NXT 통합", "J": "KRX", "NX": "NXT"}


def render_live_page(code: str, name: str, mode: str) -> str:
    import json

    from backend.config import settings
    from backend.flow import watch as watch_mod
    lib = _LIB_PATH.read_text(encoding="utf-8")
    # 파일 저장값(사용자 편집) 우선, 없으면 config 기본값 — 이미 정규화된 [{price:int,label}]
    watch = watch_mod.get_lines(code)
    # </script> 이스케이프: 라벨에 '</'가 들어오면 스크립트 블록이 조기 종료되어
    # 페이지 JS 전체가 죽는다(스크립트 컨텍스트 브레이크아웃, 리뷰 확정)
    watch_js = json.dumps(watch, ensure_ascii=False).replace("</", "<\\/")
    return (_TEMPLATE
            .replace("__BASE_CSS__", _BASE_CSS)
            .replace("__CHART_THEME_JS__", _CHART_THEME_JS)
            .replace("__WATCH__", watch_js)
            .replace("__MKT__", _MKT_LABEL.get(settings.market_div, "KRX+NXT 통합"))
            .replace("__TABBAR__", _TABBAR)
            .replace("__NAV_LOADER__", _NAV_LOADER)
            .replace("__CODE__", escape(code))
            .replace("__NAME__", escape(name))
            .replace("__MODE__", escape(mode.upper()))
            .replace("__MODE_CLS__", "live" if mode == "live" else "demo")
            .replace("__PWA_HEAD__", _PWA_HEAD)
            .replace("__DISCLAIMER__", escape(_DISCLAIMER))
            .replace("__LIB__", lib))
