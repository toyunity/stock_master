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

from backend.report.dashboard import (_AGO_JS, _BASE_CSS, _CHART_THEME_JS, _DISCLAIMER,
                                      _ICON_SPRITE, _LIB_PATH, _NAV_LOADER,
                                      _PWA_HEAD, _TABBAR)

_TEMPLATE = """<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>__NAME__ 실시간 수급 — Stock Master</title>
__PWA_HEAD__
<style>
__BASE_CSS__
/* ── /live 고유 스타일 ── */
.ob{margin-top:8px}
/* 기업 체력(접힘) — 접힌 줄엔 숫자 요약, 펼치면 지표별 쉬운말 + ⓘ 개념 */
.findig{font-family:var(--font-num);font-size:12px;font-weight:700;color:var(--text-2);
  font-variant-numeric:tabular-nums;letter-spacing:0;
  min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.finlead{font-size:12.5px;color:var(--text-2);line-height:1.6;padding:10px 0 2px}
.fin{margin-top:8px;font-size:12.5px;font-weight:600;color:var(--text-2)}
ul.finex{margin:6px 0 0;padding-left:17px;font-size:12px;color:var(--text-2);font-weight:500}
.finex li{margin:3px 0}
.finex li .qi{cursor:pointer;color:var(--primary);font-weight:800;margin-left:6px;user-select:none}
.finex .cexp{margin-top:3px;font-size:11.5px;color:var(--text-2);line-height:1.5;display:none}
.finex .cexp.on{display:block}
.obbar{display:flex;height:8px;border-radius:4px;overflow:hidden;background:var(--surface-2)}
.obbid{background:var(--up)}.obask{background:var(--down)}
.obtxt{font-size:12px;color:var(--text-2);margin-top:3px;font-weight:600}
/* 자세히 보기(전문 패널 접기) */
.advtoggle{width:100%;margin:16px 0 4px;min-height:48px;font-size:14px;font-weight:800;
  border:1px dashed var(--border);background:var(--surface-2);color:var(--text-2);border-radius:var(--r);
  cursor:pointer;-webkit-tap-highlight-color:transparent}
.advtoggle .ar{display:inline-block;transition:transform .2s}
.advtoggle.on .ar{transform:rotate(180deg)}
/* 확정 밴드(대차·공매도·신용) — 하루~이틀 전 데이터임을 초보에게 명시 */
.fixed-band{display:flex;align-items:center;flex-wrap:wrap;gap:8px}
.whyfixed{margin-left:auto}
.whyfixed>summary{list-style:none;cursor:pointer;font-size:11.5px;font-weight:800;color:var(--primary);
  background:var(--info-bg);border-radius:var(--r-sm);padding:3px 9px;min-height:32px;
  display:inline-flex;align-items:center}
.whyfixed>summary::-webkit-details-marker{display:none}
.whyfixed-body{font-size:12.5px;color:var(--text-2);line-height:1.55;margin-top:8px;
  background:var(--surface-2);border-radius:var(--r-sm);padding:9px 12px}
/* 지연 데이터 초보 카드 */
.dp .dp-h{display:flex;align-items:flex-start;justify-content:space-between;gap:10px}
.dp .dp-h h2{font-size:16px}
.dp-key{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;margin:6px 0 4px}
.dp-num{font-family:var(--font-num);font-size:26px;font-weight:700;letter-spacing:-.02em;
  font-variant-numeric:tabular-nums}
.dp-one{font-size:13px;color:var(--text-2);font-weight:600;line-height:1.5;margin:0 0 10px}
.dp-foot{display:flex;align-items:center;justify-content:flex-end}
.det>summary.a-more{list-style:none;cursor:pointer;font-size:12px;font-weight:800;color:var(--primary);
  background:var(--info-bg);border-radius:var(--r-sm);padding:5px 11px;min-height:34px;
  display:inline-flex;align-items:center;-webkit-tap-highlight-color:transparent}
.det>summary::-webkit-details-marker{display:none}
.det>summary:focus-visible{outline:2px solid var(--primary);outline-offset:2px;border-radius:8px}
.det[open]>summary.a-more{background:var(--primary);color:#fff}
.det-body{margin-top:10px;display:grid;gap:10px}
/* L3 전문가 지표 — 계기(무채색 surface, 값은 모노) */
.pro{margin-top:2px;border:1px solid var(--border);border-radius:var(--r-sm);background:var(--surface-2)}
.pro>summary{list-style:none;cursor:pointer;padding:8px 11px;font-size:12px;font-weight:800;
  color:var(--text-2);display:flex;align-items:center;-webkit-tap-highlight-color:transparent}
.pro>summary::-webkit-details-marker{display:none}
.pro>summary:focus-visible{outline:2px solid var(--primary);outline-offset:2px;border-radius:8px}
.pro-body{padding:0 11px 11px;display:grid;gap:9px}
.pro-grid{display:grid;grid-template-columns:1fr 1fr 1fr;gap:7px}
.pro-grid.g4{grid-template-columns:1fr 1fr}
/* 종목 상세 부가 패널(/api/stockinfo, 2026-09-08): 일정 칩 · 시장 속 위치 표 — 레이아웃만, 색은 토큰 */
.evrow{display:flex;flex-wrap:wrap;gap:6px;margin:6px 12px 0}
.evchip{font-size:11px;font-weight:700;padding:3px 9px;border-radius:999px;background:var(--surface-2);border:1px solid var(--border-2);color:var(--text-2);white-space:nowrap}
.evchip.soon{background:var(--warn-bg);color:var(--warn);border-color:transparent}
.evnote{margin:4px 12px 0}
#rp-tbl th{text-align:left;font-weight:600;color:var(--text-3);font-size:11px;padding:5px 6px;white-space:nowrap}
#rp-tbl td{font-family:var(--font-num);font-size:12px;padding:5px 6px}
.pro-cell{background:var(--surface);border:1px solid var(--border-2);border-radius:var(--r-sm);padding:7px 9px;text-align:center}
.pro-cell .pl{font-size:9.5px;color:var(--text-3);font-weight:700;letter-spacing:.02em}
.pro-cell .pv{font-family:var(--font-num);font-size:13px;font-weight:700;margin-top:2px;font-variant-numeric:tabular-nums}
.pro-verdict{font-size:12px;font-weight:800;border-radius:var(--r-sm);padding:7px 10px;line-height:1.45;
  background:var(--warn-bg);color:var(--warn)}
.pro-verdict.flat{background:var(--surface-2);color:var(--text-2)}
.pro-verdict.good{background:var(--good-bg);color:var(--good)}
.pro-verdict.info{background:var(--info-bg);color:var(--primary-ink)}
.pro-basis{font-size:11px;color:var(--text-3);font-weight:700}
.advw{display:none}.advw.on{display:block}
#pmeta{margin-top:8px}
#pmeta .fresh{display:inline;margin:0}
#chart{height:180px}
#pchart{height:230px}
#vchart{height:72px}
#mchart{height:64px}
.volwrap{position:relative;margin-top:1px}
.chartwrap{position:relative}
.ext-lbl{position:absolute;font-size:11px;font-weight:800;white-space:nowrap;pointer-events:none;z-index:3;
  font-variant-numeric:tabular-nums;transform:translateX(-50%);
  text-shadow:0 0 3px var(--bg),0 0 3px var(--bg),0 1px 3px var(--bg)}
.ext-lbl.hi{color:var(--up)}
.ext-lbl.lo{color:var(--down)}
.vol-lb{position:absolute;left:8px;top:1px;font-size:10px;font-weight:700;color:var(--text-3);
  pointer-events:none;z-index:3;text-shadow:0 0 3px var(--bg),0 0 3px var(--bg)}
.stall{display:none;position:absolute;inset:0;
  background:color-mix(in srgb,var(--surface) 88%,transparent);z-index:5;
  align-items:center;justify-content:center;font-size:13px;font-weight:600;color:var(--warn);
  text-align:center;padding:0 16px;border-radius:var(--r)}
.stall.on{display:flex}
/* 차트 로딩 오버레이 — 수신 정지(.stall 기본)와 톤을 가른다. 경고가 아니라 대기다.
   pstall과 별도 요소여야 한다: render()가 SSE 1초마다 pstall.className을 덮어쓴다. */
.cload{color:var(--text-3);z-index:4}
/* 이평선(이동평균) 토글 줄 */
.marow{display:flex;align-items:center;gap:6px;margin:2px 0 10px;flex-wrap:wrap}
.marow .ma-lb{font-size:12px;font-weight:700;color:var(--text-2);margin-right:2px}
.marow .ma-hint{font-size:11px;color:var(--text-3);margin-left:2px}
.ma-btn{min-height:36px;padding:0 14px;border-radius:var(--r-pill);border:1px solid var(--border);
  background:var(--surface);color:var(--text-3);font-size:12.5px;font-weight:800;cursor:pointer;
  -webkit-tap-highlight-color:transparent;font-variant-numeric:tabular-nums}
.ma-btn:active{opacity:.7}
.ma-btn::before{content:'';display:inline-block;width:8px;height:8px;border-radius:2px;
  background:var(--dot,transparent);margin-right:5px;vertical-align:middle}
.ma-btn[data-ma="5"].on{background:#9aa0a6;border-color:#9aa0a6;color:#fff}
.ma-btn[data-ma="10"].on{background:#ec4899;border-color:#ec4899;color:#fff}
.ma-btn[data-ma="20"].on{background:#f59e0b;border-color:#f59e0b;color:#fff}
.ma-btn[data-ma="60"].on{background:#22c55e;border-color:#22c55e;color:#fff}
.ma-btn[data-ma="120"].on{background:#3b82f6;border-color:#3b82f6;color:#fff}
.ma-btn.on::before{background:#fff}
.ma-btn:disabled,.ma-btn.na{opacity:.32;cursor:not-allowed;background:var(--surface);
  border-color:var(--border);color:var(--text-3);box-shadow:none}
/* 공매도 거래량 오버레이 토글(일봉 전용) */
.ss-btn{min-height:36px;padding:0 13px;border-radius:var(--r-pill);border:1px solid var(--border);
  background:var(--surface);color:var(--text-3);font-size:12px;font-weight:800;cursor:pointer;
  -webkit-tap-highlight-color:transparent;margin-left:4px}
.ss-btn.on{background:var(--violet);border-color:var(--violet);color:#fff}
.ss-btn:disabled,.ss-btn.na{opacity:.32;cursor:not-allowed}
.fit-btn{min-height:36px;padding:0 12px;border-radius:var(--r-pill);border:1px solid var(--border);
  background:var(--surface);color:var(--text-2);font-size:12px;font-weight:700;cursor:pointer;
  -webkit-tap-highlight-color:transparent;margin-left:4px}
.fit-btn:active{opacity:.6}
/* 크로스헤어 OHLC 정보줄(터치 시 표시) + 다음 봉 카운트다운 */
.ohlc{font-size:12.5px;font-weight:700;min-height:18px;margin:0 2px 4px;line-height:1.4}
.ohlc:not(.on){visibility:hidden}
.ohlc .meta{font-weight:500;font-variant-numeric:tabular-nums}
.pc-count{font-size:11px;font-weight:700;color:var(--text-3);margin:6px 2px 0;
  font-variant-numeric:tabular-nums;min-height:14px}
.pc-count:empty{display:none}
.szrow{display:flex;align-items:center;gap:8px;font-size:11px;margin:3px 0}
.szlbl{width:92px;flex:0 0 auto;color:var(--text-2);text-align:right;white-space:nowrap}
.szbar{height:14px;border-radius:4px;min-width:2px;flex:0 0 auto}
.szbuy{background:var(--up)} .szsell{background:var(--down)}
.szval{color:var(--text-3);white-space:nowrap;font-variant-numeric:tabular-nums}
.fgn{color:var(--violet);font-weight:700}
#mb-tbl th:nth-child(3),#mb-tbl td:nth-child(3){text-align:left}
/* 한글 텍스트 셀(창구명·구분)은 모노 상속 해제 — 숫자 정렬 근거가 없고 한글은 sans가 낫다 */
#mb-tbl td:nth-child(3),#tape td:nth-child(4){font-family:inherit}
/* 섹션 구분 헤더 — 시그니처: 라벨 + 틱마크 축(axis) 룰(가격 눈금자 모티프) */
.sechd{display:flex;align-items:center;gap:12px;font-size:12px;font-weight:800;color:var(--text-2);
  letter-spacing:.01em;margin:28px 2px 4px;padding-top:6px}
.sechd::after{content:"";flex:1;height:7px;align-self:flex-end;
  border-bottom:1px solid var(--border);
  background-image:repeating-linear-gradient(90deg,var(--border) 0 1px,transparent 1px 8px)}
.sechd.fixed-band::after{display:none}
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
.dv-val{width:82px;flex:0 0 auto;text-align:right;font-family:var(--font-num);font-size:12.5px;
  font-weight:700;font-variant-numeric:tabular-nums}
/* 2분할 비중 바 — KRX vs NXT(방향 없는 범주) → 무채색 스틸 + 보라 */
.pb{margin:12px 0 2px}
.pb-track{display:flex;height:18px;border-radius:5px;overflow:hidden;background:var(--surface-2)}
.pb-a{background:var(--flat)} .pb-b{background:var(--violet)}
.pb-lg{display:flex;justify-content:space-between;margin-top:6px;font-size:11.5px;
  color:var(--text-2);font-weight:600}
.pb-dot{display:inline-block;width:8px;height:8px;border-radius:2px;margin-right:5px;vertical-align:middle}
.pb-da{background:var(--flat)} .pb-db{background:var(--violet)}
/* 한눈 요약 스트립 */
.glance{display:flex;gap:8px;overflow-x:auto;margin:12px 0 2px;padding-bottom:2px;
  -webkit-overflow-scrolling:touch}
.glance::-webkit-scrollbar{height:0}
.glance:empty{display:none}
.gl{flex:0 0 auto;min-width:86px;background:var(--surface);border:1px solid var(--border);
  border-radius:var(--r);padding:9px 13px;box-shadow:var(--shadow-sm)}
.gl-lb{font-size:10.5px;color:var(--text-3);font-weight:700;white-space:nowrap;letter-spacing:.01em}
.gl-vl{font-family:var(--font-num);font-size:15px;font-weight:700;font-variant-numeric:tabular-nums;
  margin-top:3px;white-space:nowrap;letter-spacing:-.01em}
.gl-vl.up{color:var(--up)} .gl-vl.down{color:var(--down)} .gl-vl.flat{color:var(--text)}
/* 감시선 편집기 + 내 라인 칩 */
.mylines{display:flex;flex-wrap:wrap;gap:6px;margin-top:12px}
.myline{display:inline-flex;align-items:center;gap:6px;font-size:12px;font-weight:600;
  padding:5px 11px;border-radius:var(--r-pill);background:var(--surface-2);
  border:1px solid var(--border-2);color:var(--text-2);font-variant-numeric:tabular-nums}
.myline .dot{width:8px;height:8px;border-radius:50%;background:var(--violet);flex:0 0 auto}
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
/* ══ 토스식 요약우선 IA — 히어로 판정 + 주제별 드릴다운 섹션 ══ */
#today-line{margin-top:9px;font-size:14.5px;font-weight:700;color:var(--text);line-height:1.5;
  padding-left:13px;border-left:3px solid var(--primary)}
#today-line:empty{display:none}
.sec-body>.glance,.sec-body>.ob{margin:12px 0 0}
.fixed-note{font-size:12.5px;color:var(--text-2);line-height:1.55;padding:10px 0 2px}
.fixed-note .whyfixed{margin-top:6px}
</style></head><body>
__ICONS__
<div id="app"><div id="app-scroll">
<div class="hero hgrid">
  <div class="htop"><a class="back" href="/" style="margin:0">← 목록</a>
    <span class="hname">__NAME__</span> <span class="code">__CODE__</span></div>
  <!-- .hmain — 560px↑에서 히어로가 2열이 될 때 왼쪽 열로 통째로 들어가는 묶음.
       래퍼가 없으면 CSS가 자식 개수를 세야 하고, 히어로에 줄이 하나 늘 때마다 깨진다. -->
  <div class="hmain">
    <!-- 2026-08-25: 보이는 '현재가' 줄 제거. 48px 숫자 밑에 늘 같은 글자라 아무것도
         말하지 않았고, 마감 후 종가일 때도 '현재가'라고 우기는 고정 텍스트였다
         (render()가 건드린 적 없다). 기준 시각·실시간 여부는 아래 #pmeta와
         시장 상태 배지가 이미 말한다. 음성용 맥락만 .vh로 남긴다 — #price
         **안**에 넣으면 render()의 textContent= 한 방에 지워지므로 앞 형제로 둔다.
         미국 상세(us_page)는 보이는 라벨을 그대로 둔다 — 거긴 '종가'로 시작해
         정규장이면 '현재가'로 바뀌므로 그 한 줄이 어제 값과 지금 값을 가른다. -->
    <span class="vh">현재가</span><div class="price" id="price">–</div>
    <span class="pill flat" id="chg"></span>
    <div class="note" id="walert"></div>
    <div id="today-line"></div>
  </div>
  <!-- 근거 레일 — 히어로 숫자를 만든 재료. 2026-08-13: 시가·고가·저가는 넣지 않는다.
       SSE 스냅샷(_market)에 price/sign/change/rate/vol/value/strength/time 8필드뿐이라
       그 값이 아예 없다. 호가는 /api/asking 별도 5초 폴링이라 갱신 주기가 달라 #ob 패널에 둔다.
       대시만 남는 행은 화면만 길어지고 아무것도 말하지 않는다. -->
  <div class="rail" id="hrail">
    <div><span class="k">전일 종가</span><span class="v" id="hr-prev">–</span></div>
    <div><span class="k">거래대금</span><span class="v" id="hr-amt">–</span></div>
    <div><span class="k">체결강도</span><span class="v" id="hr-str">–</span></div>
  </div>
  <div class="hstate">
    <span id="mode" class="badge b-__MODE_CLS__">__MODE__</span>
    <span id="conn" class="badge b-off">연결 중…</span>
    <span id="mstate" class="badge b-off">상태 확인 중</span>
    <span id="wpill"></span>
    <span class="ago" id="hago"></span>
  </div>
</div>

<div class="meta" id="pmeta">체결 대기 중 <span class="fresh">· 실시간</span></div>
<div class="note" id="note"></div>
<!-- 시간외 알약은 .hstate(줄바꿈 없음)에 넣으면 390px에서 넘친다(2026-09-08 실측 419px) — 자체 줄 -->
<div class="evrow" id="otrow" style="display:none"><span id="otpill" class="badge b-off"></span></div>
<div class="evrow" id="ev-chips" style="display:none"></div>
<div class="meta evnote" id="ev-note"></div>

<details class="sec" id="finsec" style="display:none">
  <summary><svg class="hic secic"><use href="#i-bars"/></svg> 기업 체력
    <span class="findig" id="fin-digest"></span><span class="chev">▾</span></summary>
  <div class="sec-body">
    <div class="finlead">이 회사가 <b>얼마에 거래되는지(밸류)</b>와 <b>얼마나 잘 버는지·빚은 얼마나 되는지</b>를
      지표마다 쉬운 말로 풀었습니다. ⓘ를 누르면 그 지표의 뜻이 펼쳐집니다.
      분기 실적 기준이라 <b>실시간이 아닙니다</b> — 오늘 등락이 아니라 회사 체력을 볼 때 씁니다.</div>
    <div class="fin" id="fin"></div>
  </div>
</details>

<details class="sec" id="opsec" style="display:none">
  <summary><svg class="hic secic"><use href="#i-bars"/></svg> 증권사 목표가
    <span class="findig" id="op-digest"></span><span class="chev">▾</span></summary>
  <div class="sec-body" id="op-body"></div>
</details>

<div class="panel">
  <h2><svg class="hic"><use href="#i-chart"/></svg> 가격 차트 <span class="fresh" id="pc-fresh">· 불러오는 중</span></h2>
  <div class="tfrow">
    <button class="tf" data-tf="1m">1분</button>
    <button class="tf on" data-tf="5m">5분</button>
    <button class="tf" data-tf="15m">15분</button>
    <button class="tf" data-tf="60m">60분</button>
    <button class="tf" data-tf="1d">일봉</button>
    <button class="tf" data-tf="1w">주봉</button>
    <button class="tf" data-tf="1mo">월봉</button>
    <button class="tf" id="notifbtn" style="display:none">🔔 감시선 알림 허용</button>
  </div>
  <div class="marow">
    <span class="ma-lb">이평선</span>
    <button class="ma-btn on" data-ma="5">5</button>
    <button class="ma-btn on" data-ma="10">10</button>
    <button class="ma-btn on" data-ma="20">20</button>
    <button class="ma-btn on" data-ma="60">60</button>
    <button class="ma-btn on" data-ma="120">120</button>
    <span class="ma-hint">봉 이동평균 · 켜고 끄기</span>
    <button class="ss-btn" data-ss="1" type="button" disabled>🩳 공매도</button>
    <button class="fit-btn" type="button" title="전체 기간 보기">⤢ 전체</button>
  </div>
  <div class="ohlc" id="ohlc"></div>
  <div class="chartwrap"><div id="pchart"></div>
    <div class="ext-lbl hi" id="hi-lbl"></div><div class="ext-lbl lo" id="lo-lbl"></div>
    <div class="stall" id="pstall"></div>
    <div class="stall cload on" id="pcload">차트 불러오는 중…</div></div>
  <div class="volwrap"><div id="vchart"></div><div class="vol-lb" id="vol-lb"></div></div>
  <div class="volwrap"><div id="mchart"></div><div class="vol-lb" id="mac-lb"></div></div>
  <div class="sig" id="wk-macd"></div>
  <div class="pc-count" id="pc-count"></div>
  <div class="mylines" id="mylines"></div>
  <!-- 매물대는 시간축을 공유하지 않는 별도 패널 — 캔들·거래량·MACD(세 pane)·카운트다운·내 라인 뒤.
       2026-09-08(98ca790)에 거래량과 MACD 사이에 끼워 넣었다가 "MACD가 없어졌다"는 제보(2026-10-21). -->
  <div class="dp-h" style="margin-top:10px"><h2><svg class="hic"><use href="#i-bars"/></svg> 매물대</h2><span class="pill fixed" id="pb-pill">🕐 데이터 대기</span></div>
  <p class="dp-one">가격대별로 거래가 얼마나 몰렸나. 두꺼운 가격 = 그 값에 산 사람이 많다 → 위면 저항, 아래면 지지 후보.</p>
  <div id="pb-bars"></div>
  <div class="meta" id="pb-note"></div>
</div>

<details class="sec" id="wl-panel">
  <summary><svg class="hic secic"><use href="#i-target"/></svg> 감시선·알림 <span class="seccap">가격 도달 알림</span><span class="chev">▾</span></summary>
  <div class="sec-body">
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
  </div>
</details>

<details class="sec" id="sec-flow" open>
  <summary><svg class="hic secic"><use href="#i-flows"/></svg> 수급 <span class="seccap">누가 사고파나</span><span class="chev">▾</span></summary>
  <div class="sec-body">
    <div class="glance" id="glance"></div>
    <div class="ob" id="ob" style="display:none"></div>
    <div class="panel">
      <h2><svg class="hic"><use href="#i-flows"/></svg> 투자자별 순매수 (장중 추정)</h2>
      <div class="fresh" id="est-fresh">잠정 · 갱신 대기 · 장중 추정치는 익일 확정과 다를 수 있음</div>
      <div id="est-bars" style="margin:8px 0 4px"></div>
      <div class="tbl-wrap"><table id="est-hist" style="margin-top:8px"></table></div>
      <div class="meta" id="est-note">*개인+기타법인 = −(외국인+기관) 역산 — 장중 개인 집계는 어디에도 없어
      "전체 매매 합계는 0" 원리로 추정한 값</div>
      <div class="tbl-wrap"><table id="est-detail" style="margin-top:8px"></table></div>
      <div class="meta" id="est-detail-note"></div>
    </div>
    <div class="panel">
      <h2><svg class="hic"><use href="#i-cpu"/></svg> 프로그램매매 <span class="fresh" id="pgm-fresh">· 실시간</span></h2>
      <div class="grid3" style="margin-bottom:8px">
        <div><div class="lbl">순매수 수량</div><div class="val" id="pgm-qty">–</div></div>
        <div><div class="lbl">순매수 금액</div><div class="val" id="pgm-val">–</div></div>
      </div>
      <div class="chartwrap"><div id="chart"></div><div class="stall" id="cstall"></div></div>
      <div class="meta">당일 누적 순매수 금액 추이(억원) — Y축은 당일 전체 범위 고정</div>
      <div class="dp-foot"><span class="sparkwrap"><span class="sk-cap">프로그램 30일(확정)</span><span class="sk-svg" id="pgd-spark"></span></span></div>
      <div class="meta" id="pgd-note"></div>
    </div>
    <div class="panel">
      <h2><svg class="hic"><use href="#i-building"/></svg> 거래원(회원사) 창구 분석 <span class="fresh" id="mb-fresh">· 데이터 대기</span></h2>
      <div class="tbl-wrap"><table id="mb-tbl"></table></div>
      <div class="sig" id="mb-sig"></div>
      <div class="meta" id="mb-note">상위 5 창구(KRX+NXT 통합) · <span class="fgn">보라색</span> = 외국계 창구.
      외국계 합계는 정규장(KRX) 기준(NXT 외국계 집계 미제공). 창구≠주체 — 외국인이 국내
      창구를 쓸 수 있어 <b>추정치(정확한 주체 식별 불가)</b>. 확정 수급은 T+1 09:30 이후.</div>
    </div>
    <div class="panel">
      <h2><svg class="hic"><use href="#i-split"/></svg> 거래소별 거래량 (KRX vs NXT) <span class="fresh" id="xv-fresh">· 데이터 대기</span></h2>
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
      <h2><svg class="hic"><use href="#i-bars"/></svg> 체결 규모 분포 — 주체 추정 <span class="fresh" id="sz-fresh">· 실시간 집계 대기</span></h2>
      <div class="tfrow" id="sz-tabs">
        <button class="tf" data-ses="pre">장전</button>
        <button class="tf" data-ses="regular">정규장</button>
        <button class="tf" data-ses="after">장후(NXT)</button>
      </div>
      <div id="sz-bars"></div>
      <div class="sig" id="sz-sig"></div>
      <div class="dp-h" style="margin-top:10px"><h2>체결금액 구간별 매수/매도 <span class="fresh">· KIS 집계(확정)</span></h2></div>
      <div id="ta-bars"></div>
      <div class="dp-foot"><span class="sparkwrap"><span class="sk-cap">일별 체결강도 20일</span><span class="sk-svg" id="tv-spark"></span></span></div>
      <div class="meta" id="tv-note"></div>
      <div class="meta">체결량 구간별 건수·거래대금 비중 — <b>추정치(정확한 주체 식별 불가)</b>.
      100주 초과 대금 비중↑ = 기관성, 1-10주 건수 비중↑ = 개인 중심. 시장이 얇은
      시간외 구간일수록 판별력이 높다. 투자자별 순매수 <b>확정치는 T+1 09:30 이후</b> 제공.</div>
    </div>
    <div class="panel">
      <h2><svg class="hic"><use href="#i-calendar"/></svg> 일별 확정 수급 <span class="fresh" id="daily-fresh">· 전일까지 확정치</span></h2>
      <div class="tbl-wrap"><table id="daily"><tr><th>날짜</th><th>개인</th><th>외국인</th><th>기관</th><th>종가</th><th>대차잔고</th></tr></table></div>
    </div>
    <div class="panel">
      <h2><svg class="hic"><use href="#i-bank"/></svg> 기관 세부 수급 (연기금·투신·금융투자 …)</h2>
      <div class="fresh" id="dt-fresh">확정 · 기준일 대기 · 기관계를 주체별로 분해한 확정치</div>
      <div class="tbl-wrap"><table id="detail"></table></div>
    </div>
  </div>
</details>

<details class="sec" id="sec-risk" open>
  <summary><svg class="hic secic"><use href="#i-short"/></svg> 위험 지표 <span class="seccap">공매도·빚 · 며칠 전 확정</span><span class="chev">▾</span></summary>
  <div class="sec-body">
    <div class="fixed-note"><span class="tag-fixed">🕐 확정</span> 하루~이틀 전 · 실시간 아님 · 떨어질 때 연료
      <details class="whyfixed"><summary>왜 늦어요? ▾</summary>
        <div class="whyfixed-body">장 마감 뒤 집계·정산돼서 다음 영업일(공매도·대차)~이틀 뒤(신용융자)에
        확정돼요. 그래서 오늘이 아니라 며칠 전 날짜로 보이는 게 정상이에요. 지금 이 순간의 매수·매도
        압력은 위 <span class="tag-live">🟢 실시간</span> 수급·호가·체결에서 보세요.</div>
      </details>
    </div>
    <div class="panel dp" id="rp-panel">
      <div class="dp-h"><h2><svg class="hic"><use href="#i-short"/></svg> 시장 속 위치</h2><span class="pill fixed" id="rp-pill">🕐 데이터 대기</span></div>
      <p class="dp-one">이 종목이 시장 전체 순위에서 어디쯤인가. 공매도·빚투 상위권이면 흔들릴 때 더 크게 흔들린다.</p>
      <div class="tbl-wrap"><table id="rp-tbl"></table></div>
      <div class="meta">공매도 상위 30·신용잔고 상위 100(전일 확정) 안이면 순위, 밖이면 '밖'. 52주 위치 95%↑ = 신고가 근접(돌파냐 저항이냐 갈림길).</div>
    </div>
    <div class="panel dp">
      <div class="dp-h"><h2><svg class="hic"><use href="#i-borrow"/></svg> 대차잔고</h2><span class="pill fixed" id="sb-pill">🕐 데이터 대기</span></div>
      <div class="dp-key"><span class="dp-num" id="sb-qty">–</span><span class="sig" id="sb-sig"></span></div>
      <p class="dp-one">빌려간 주식(공매도 준비 물량). 늘면 매도 부담 ↑, 줄면 상환 신호.</p>
      <div class="dp-foot"><span class="sparkwrap"><span class="sk-cap">대차 20일</span><span class="sk-svg" id="sb-spark"></span></span></div>
      <details class="det" open><summary class="a-more">ⓘ 자세히 ▾</summary>
        <div class="det-body">
          <div class="grid3">
            <div><div class="lbl">전일 대비</div><div class="val" id="sb-chg">–</div></div>
            <div><div class="lbl">잔고 금액</div><div class="val" id="sb-val">–</div></div>
            <div><div class="lbl">출처</div><div class="val meta" id="sb-fresh">·</div></div>
          </div>
          <details class="inline" style="margin-top:8px" open><summary>최근 20거래일 추이</summary>
            <div class="tbl-wrap"><table id="sb-hist" style="margin-top:6px"></table></div></details>
          <div class="meta" id="sb-note">대차잔고 = 공매도 등을 위해 빌려간 뒤 아직 갚지 않은 주식 수(T+1 공시).</div>
          <details class="pro" open><summary>🔬 전문가 지표 ▾</summary>
            <div class="pro-body">
              <div class="pro-grid">
                <div class="pro-cell"><div class="pl">체결−상환(순증)</div><div class="pv" id="sb-pro-flow">–</div></div>
                <div class="pro-cell"><div class="pl">잔고 증감률</div><div class="pv" id="sb-pro-rate">–</div></div>
                <div class="pro-cell"><div class="pl">소스</div><div class="pv" id="sb-pro-src">–</div></div>
              </div>
            </div></details>
        </div>
      </details>
    </div>
    <div class="panel dp">
      <div class="dp-h"><h2><svg class="hic"><use href="#i-short"/></svg> 공매도 일별 체결</h2><span class="pill fixed" id="ss-pill">🕐 데이터 대기</span></div>
      <div class="dp-key"><span class="dp-num" id="ss-qty">–</span><span class="sig" id="ss-ratio-big"></span></div>
      <p class="dp-one">실제로 공매도로 쏜 물량. 비중 높으면 그날 매도 압력이 셌다는 뜻.</p>
      <div class="dp-foot"><span class="sparkwrap"><span class="sk-cap">공매도 20일</span><span class="sk-svg" id="ss-spark"></span></span></div>
      <details class="det" open><summary class="a-more">ⓘ 자세히 ▾</summary>
        <div class="det-body">
          <div class="grid3">
            <div><div class="lbl">거래량 비중</div><div class="val" id="ss-ratio">–</div></div>
            <div><div class="lbl">대차잔고 대비</div><div class="val" id="ss-vs">–</div></div>
            <div><div class="lbl">출처</div><div class="val meta" id="ss-fresh">·</div></div>
          </div>
          <details class="inline" style="margin-top:8px" open><summary>최근 20거래일 추이</summary>
            <div class="tbl-wrap"><table id="ss-hist" style="margin-top:6px"></table></div></details>
          <div class="meta">위 대차잔고가 '빌린 물량'이라면 이것은 '실제로 쏜 물량'(T+1 확정). 비중 = 그날 전체 거래량 중 공매도 비율.</div>
          <details class="pro" open><summary>🔬 전문가 지표 ▾</summary>
            <div class="pro-body">
              <div class="pro-grid g4">
                <div class="pro-cell"><div class="pl">거래대금</div><div class="pv" id="ss-pro-value">–</div></div>
                <div class="pro-cell"><div class="pl">공매도 평균가</div><div class="pv" id="ss-pro-avgprc">–</div></div>
                <div class="pro-cell"><div class="pl">비중</div><div class="pv" id="ss-pro-ratio">–</div></div>
                <div class="pro-cell"><div class="pl">20일 평균</div><div class="pv" id="ss-pro-avg">–</div></div>
              </div>
              <div class="pro-verdict" id="ss-pro-verdict"></div>
            </div></details>
        </div>
      </details>
    </div>
    <div class="panel dp">
      <div class="dp-h"><h2><svg class="hic"><use href="#i-card"/></svg> 신용융자 잔고</h2><span class="pill fixed" id="cr-pill">🕐 데이터 대기</span></div>
      <div class="dp-key"><span class="dp-num" id="cr-qty">–</span><span class="sig" id="cr-sig"></span></div>
      <p class="dp-one">빚내서 산 주식. 급락하면 다음 날 아침 반대매매(강제청산) 연료 — 클수록 하락 가속.</p>
      <div class="dp-foot"><span class="sparkwrap"><span class="sk-cap">신용 20일</span><span class="sk-svg" id="cr-spark"></span></span></div>
      <details class="det" open><summary class="a-more">ⓘ 자세히 ▾</summary>
        <div class="det-body">
          <div class="grid3">
            <div><div class="lbl">전일 대비</div><div class="val" id="cr-chg">–</div></div>
            <div><div class="lbl">잔고 금액≈</div><div class="val" id="cr-val">–</div></div>
            <div><div class="lbl">출처</div><div class="val meta" id="cr-fresh">·</div></div>
          </div>
          <details class="inline" style="margin-top:8px" open><summary>최근 20거래일 추이</summary>
            <div class="tbl-wrap"><table id="cr-hist" style="margin-top:6px"></table></div></details>
          <div class="meta" id="cr-note">신용융자 = 빚내서 산 주식. 급락하면 다음 날 아침 반대매매(강제청산)로 쏟아진다. 금액은 주수×종가 환산(≈).</div>
          <details class="pro" open><summary>🔬 전문가 지표 ▾</summary>
            <div class="pro-body">
              <div class="pro-grid">
                <div class="pro-cell"><div class="pl">잔고비율</div><div class="pv" id="cr-pro-ratio">–</div></div>
                <div class="pro-cell"><div class="pl">신규/상환</div><div class="pv" id="cr-pro-flow">–</div></div>
                <div class="pro-cell"><div class="pl">증감률</div><div class="pv" id="cr-pro-rate">–</div></div>
              </div>
              <div class="pro-verdict" id="cr-pro-verdict"></div>
              <div class="pro-basis" id="cr-pro-basis"></div>
            </div></details>
        </div>
      </details>
    </div>
  </div>
</details>

__ADR_PANEL__
<details class="sec" id="sec-tape">
  <summary><svg class="hic secic"><use href="#i-activity"/></svg> 실시간 체결 <span class="seccap">최근 30건 · 계속 갱신</span><span class="chev">▾</span></summary>
  <div class="sec-body">
    <div class="panel">
      <h2><svg class="hic"><use href="#i-activity"/></svg> 실시간 체결 <span class="fresh">· 최근 30건</span></h2>
      <div class="tbl-wrap"><table id="tape"><tr><th>시각</th><th>체결가</th><th>체결량</th><th>구분</th></tr></table></div>
    </div>
  </div>
</details>

<div class="disc">__DISCLAIMER__ 실시간 수급의 외국인/기관 수치는 장중 <b>추정치(잠정)</b>이며
확정치는 다음 영업일에 제공됩니다. 데이터 출처: 한국투자증권 오픈API(국내·해외 시세, 환율,
신용잔고, 공매도)·금융투자협회(대차잔고)·네이버(폴백). 모든 표시 시각은 KST(Asia/Seoul) 기준.</div>

<script>__LIB__</script>
<script>
__AGO_JS__
const CODE='__CODE__';
let WATCH=__WATCH__; // 감시선 [{price,label}] — 서버 저장(/api/watch)에서 주입, 편집 시 가변
const num=n=>n==null?'–':Math.round(n).toLocaleString('ko-KR');
const won=n=>n==null?'–':num(n)+'원';
function toggleAdv(){var a=document.getElementById('advanced'),b=document.getElementById('advtoggle');
  if(!a)return; var on=a.classList.toggle('on'); if(b)b.classList.toggle('on',on);}
// ── 호가(매도벽·매수받침) — /api/asking REST 스냅샷 5초 폴링(실시간 WS 세션 회피). ──
async function pollOB(){
  try{
    const r=await fetch('/api/asking/'+CODE); if(!r.ok)return;
    const a=await r.json(); const el=document.getElementById('ob');
    if(!a||a.bid_ratio==null||(!a.total_ask&&!a.total_bid)){ el.style.display='none'; return; }
    const br=a.bid_ratio, ar=Math.max(0,100-br);
    el.innerHTML='<div class="obbar"><span class="obbid" style="width:'+br+'%"></span>'
      +'<span class="obask" style="width:'+ar+'%"></span></div>'
      // 서버가 갱신 실패로 직전 스냅샷을 줬으면(stale) 지연이라고 말한다 — 사다리가
      // 마지막 성공값에 굳어 있는 걸 '지금 호가'로 읽으면 매매 판단이 틀어진다(감사 D-M9).
      +'<div class="obtxt">📖 매수세 '+br.toFixed(0)+'%  ·  매수 '+num(a.total_bid)+'  ·  매도 '+num(a.total_ask)+(a.stale?'  ·  지연':'')+'</div>';
    el.style.display='block';
  }catch(e){}
}
pollOB(); setInterval(pollOB, 5000);
const shares=n=>n==null?'–':(n>0?'+':'')+num(n)+'주';
const eok=n=>n==null?'–':(n>0?'+':'')+(n/1e8).toLocaleString('ko-KR',{maximumFractionDigits:1})+'억';
const cls=n=>n>0?'up':(n<0?'down':'flat');
const esc=s=>(s==null?'':String(s)).replace(/[&<>"]/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[m]));
const sgn={up:'▲',down:'▼',flat:''};

// ── 종목 상세 부가 데이터 — /api/stockinfo/{code} 5분 폴링(설계 2026-09-08). ──
// 일정·목표가·매물대·시간외·프로그램 일별·체결강도 일별·KIS 체결금액 비중·시장 속 위치.
// SSE 스냅샷과 별개 통로라 render()와 독립이다 — 블록마다 try/catch로 격리해
// 한 패널의 이상값이 다른 패널을 죽이지 않는다. 날짜 기준은 서버 KST(KDATE).
let INFO=null, W52=null;
async function loadInfo(){
  try{ const r=await fetch('/api/stockinfo/'+CODE); if(!r.ok)return; INFO=await r.json(); renderInfo(INFO); }catch(e){}
}
function ddayS(iso){ const base=KDATE||new Date().toISOString().slice(0,10);
  return Math.round((new Date(iso+'T00:00:00Z')-new Date(base+'T00:00:00Z'))/86400000); }
function pctS(x,d){ return x==null?'–':(x>0?'+':'')+x.toFixed(d==null?1:d)+'%'; }
function mdS(iso){ return String(iso||'').slice(5).replace('-','/'); }
function renderInfo(d){
  d=d||{};
  const ot=d.overtime;
  // 1) 📅 다가오는 일정 — 어제 기준일까지만 남긴다('놓쳤다'도 정보다)
  try{
    const el=document.getElementById('ev-chips'), nt=document.getElementById('ev-note');
    const rows=((d.events||{}).rows||[]).filter(r=>ddayS(r.date)>=-1).slice(0,5);
    if(!rows.length){ el.style.display='none'; el.innerHTML=''; nt.textContent=''; }
    else{
      el.innerHTML=rows.map(r=>{ const n=ddayS(r.date);
        return '<span class="evchip'+(n<=7?' soon':'')+'">📅 '+(n===0?'오늘':(n<0?'D+'+(-n):'D-'+n))+' · '+esc(r.label)+' '+mdS(r.date)+'</span>'; }).join('');
      el.style.display='';
      nt.textContent=rows.slice(0,3).map(r=>mdS(r.date)+' '+r.label+' — '+r.detail).join('  ·  ')
        +(rows.some(r=>r.kind==='dividend')?'  ·  배당은 기준일 2영업일 전까지 사야 받습니다':'');
    }
  }catch(e){}
  // 2) 🎯 증권사 목표가 — 증권사별 최신 1건 집계(서버)
  try{
    const sec=document.getElementById('opsec'), op=d.opinion;
    if(!op||!op.n){ sec.style.display='none'; }
    else{
      const g=op.upside_pct;   // 목표가/현재가−1 — "현재가 대비 −46%"는 목표가가 위인지 아래인지 안 읽혀서 뒤집음(2026-09-10)
      document.getElementById('op-digest').textContent='평균 '+won(op.avg_target)+(g==null?'':' · '+pctS(g));   // 접힌 줄은 좁다 — 짧게
      let h='<div class="grid3"><div><div class="lbl">평균 목표가</div><div class="val">'+won(op.avg_target)+'</div></div>'
        +'<div><div class="lbl">목표가까지</div><div class="val '+(g>0?'up':(g<0?'down':'flat'))+'">'+pctS(g)+'</div></div>'
        +'<div><div class="lbl">의견 '+op.n+'개사</div><div class="val">매수'+op.buy+'·중립'+op.hold+'·매도'+op.sell+'</div></div></div>';
      h+='<div class="meta">최고 '+won(op.max_target)+' · 최저 '+won(op.min_target)+' · '+esc(op.latest||'')+' 기준 · 증권사별 최신 1건씩</div>';
      if((op.changes||[]).length) h+='<div class="meta"><b>최근 의견 변경</b> '+op.changes.map(c=>esc(c.broker)+' '+esc(c.prev)+'→'+esc(c.opinion)+'('+won(c.target)+', '+mdS(c.date)+')').join(' · ')+'</div>';
      h+='<div class="meta">목표가는 예언이 아니라 증권사의 희망입니다. 숫자보다 <b>방향이 바뀌었나</b>(상향↔하향)가 신호예요. 현재가가 평균 목표가보다 한참 아래면 "싸다"가 아니라 "증권사들이 아직 안 내렸다"일 수도 있습니다.</div>';
      document.getElementById('op-body').innerHTML=h; sec.style.display='';
    }
  }catch(e){}
  // 3) 매물대 — 현재가 위의 두꺼운 가격대 = 저항 후보(하락색), 아래 = 지지 후보(상승색)
  try{
    const pb=d.pbar, bars=document.getElementById('pb-bars'), pill=document.getElementById('pb-pill'), note=document.getElementById('pb-note');
    if(!pb||!(pb.levels||[]).length){ pill.textContent='🕐 데이터 대기'; bars.innerHTML=''; note.textContent=''; }
    else{
      const mx=Math.max.apply(null,pb.levels.map(l=>l.pct))||1, cur=pb.price||0;
      bars.innerHTML=pb.levels.map(l=>{ const above=l.price>cur, at=cur&&Math.abs(l.price-cur)/cur<0.004;
        return '<div class="szrow"><span class="szlbl">'+won(l.price)+(at?' ◀':'')+'</span><div class="szbar '+(above?'szsell':'szbuy')+'" style="width:'+Math.max(2,l.pct/mx*100)+'px"></div><span class="szval">'+l.pct.toFixed(1)+'%</span></div>'; }).join('');
      const t=pb.top, dv=cur?(t.price/cur-1)*100:null;
      note.textContent='가장 두꺼운 가격 '+won(t.price)+'(거래량의 '+t.pct.toFixed(1)+'%)'
        +(dv==null?'':' · 현재가 대비 '+pctS(dv)+' → '+(dv>0.3?'위에 매물벽(저항 후보)':(dv<-0.3?'아래에 받침(지지 후보)':'현재가 근처 — 여기서 손바뀜이 가장 많았음')))
        +' · 가중평균가 '+won(Math.round(pb.wavg||0));
      pill.textContent='🟢 '+(d.demo?'데모':(d.asof||''))+' · 5분 갱신';
    }
  }catch(e){}
  // 4) 시간외 단일가 알약 — 체결이 있을 때만(대형주는 애프터마켓이 NXT라 0)
  try{
    const pl=document.getElementById('otpill'), row=document.getElementById('otrow');
    if(ot&&ot.vol>0){ pl.textContent='시간외 단일가 '+pctS(ot.rate,2)+' · '+num(ot.vol)+'주 · '+won(ot.price);
      pl.className='badge '+(ot.rate>0?'b-live':(ot.rate<0?'b-warn':'b-off'));
      pl.title='시간외 단일가(16:00~18:00, 10분마다 체결) · 예상 '+won(ot.expected); row.style.display=''; }
    else{ pl.textContent=''; row.style.display='none'; }
  }catch(e){}
  // 5) 프로그램매매 30일(확정) — 위 당일 누적 차트의 짝
  try{
    const pg=d.pgm_daily||[], sp=document.getElementById('pgd-spark'), nt=document.getElementById('pgd-note');
    if(pg.length>=2){
      const last=pg[pg.length-1], s0=Math.sign(last.net_qty); let k=0;
      for(let i=pg.length-1;i>=0&&s0!==0&&Math.sign(pg[i].net_qty)===s0;i--)k++;
      sp.innerHTML=spark(pg.map(r=>r.net_qty), s0>=0?'var(--up)':'var(--down)');
      nt.textContent=(k?k+'일 연속 '+(s0>0?'순매수':'순매도'):'마지막 날 보합')+' · '+pg.length+'일 중 순매수 '+pg.filter(r=>r.net_qty>0).length+'일 · '+mdS(last.date)+' '+num(last.net_qty)+'주 확정';
    }else{ sp.innerHTML=''; nt.textContent=''; }
  }catch(e){}
  // 6) 일별 체결강도 20일 + KIS 체결금액 구간별 매수/매도(확정) — 위 추정 분포의 확정판
  try{
    const tv=(d.tradevol||[]).filter(r=>r.strength!=null).slice(-20), sp=document.getElementById('tv-spark'), nt=document.getElementById('tv-note');
    if(tv.length>=2){ const last=tv[tv.length-1], w=tv.slice(-5).filter(r=>r.strength>100).length;
      sp.innerHTML=spark(tv.map(r=>r.strength), last.strength>=100?'var(--up)':'var(--down)');
      nt.textContent='최근 5일 중 사자 우위(체결강도 100↑) '+w+'일 · '+mdS(last.date)+' '+last.strength.toFixed(0)+' (매수 '+num(last.buy)+'주 / 매도 '+num(last.sell)+'주)'; }
    else{ sp.innerHTML=''; nt.textContent=''; }
    const ta=d.tradeamt||[], tb=document.getElementById('ta-bars');
    const mx=Math.max.apply(null,ta.map(r=>Math.abs(r.net_rate)).concat([0.01]));
    tb.innerHTML=ta.map(r=>'<div class="szrow"><span class="szlbl">'+esc(r.band)+'</span><div class="szbar '+(r.net_rate>=0?'szbuy':'szsell')+'" style="width:'+Math.max(2,Math.abs(r.net_rate)/mx*100)+'px"></div><span class="szval">'+pctS(r.net_rate,2)+' · '+num(r.buy_cnt+r.sell_cnt)+'건</span></div>').join('');
  }catch(e){}
  // 7) 시장 속 위치 — 마스터 지시(2026-09-08): 스캐너 탭 대신 "이 종목이 시장 순위 어디에 있나"
  try{
    const rp=d.rankpos||{}, s=rp.short, c=rp.credit, t=document.getElementById('rp-tbl'), pl=document.getElementById('rp-pill');
    const rows=[
      ['공매도 비중', !s?'–':(s.rank?'시장 '+s.rank+'위 / 상위 '+s.n+' · '+s.ratio.toFixed(2)+'%':'상위 '+s.n+'위 밖'), s&&s.rank?(s.rank<=10?'down':'flat'):'up'],
      ['신용잔고 비율', !c?'–':(c.rank?'시장 '+c.rank+'위 / 상위 '+c.n+' · '+c.rate.toFixed(2)+'%':'상위 '+c.n+'위 밖'), c&&c.rank?(c.rank<=10?'down':'flat'):'up'],
      ['52주 위치', W52==null?'–':(Math.round(W52)+'%'+(W52>=95?' · 신고가 근접(돌파냐 저항이냐)':(W52<=5?' · 신저가 근접':''))), W52==null?'flat':(W52>=95?'up':(W52<=5?'down':'flat'))],
      ['시간외 단일가', ot&&ot.vol>0?pctS(ot.rate,2)+' · '+num(ot.vol)+'주':'거래 없음 — 대형주 애프터마켓은 NXT(거래소별 거래량 패널)', ot&&ot.vol>0?(ot.rate>0?'up':(ot.rate<0?'down':'flat')):'flat']];
    t.innerHTML=rows.map(r=>'<tr><th>'+r[0]+'</th><td class="'+r[2]+'">'+r[1]+'</td></tr>').join('');
    pl.textContent=rp.asof?'🕐 '+mdS(rp.asof)+' 기준 · T+1':'🕐 데이터 대기';
  }catch(e){}
}
loadInfo(); setInterval(loadInfo, 300000);

// ── 기업 체력(밸류 + 재무) — /api/financials/{code} 1회 로드. ──
// 분기 실적·일 단위로만 바뀌어 폴링하지 않는다. 차트 위 접힘 섹션:
// 접힌 줄엔 숫자 3개 요약(PER·ROE·부채), 펼치면 지표별 쉬운말 + ⓘ 개념 설명.
// 값이 하나도 없으면(키 없음·조회 실패·재무 미제공) 섹션을 통째로 숨긴다 —
// '기업 체력'이라 써놓고 열면 비어 있는 화면을 만들지 않는다.
async function loadFin(){
  const sec=document.getElementById('finsec');
  try{
    const r=await fetch('/api/financials/'+CODE); if(!r.ok){sec.style.display='none';return;}
    const d=await r.json()||{}; const v=d.valuation||{}; const f=(d.financials||[])[0]||{};
    W52=(v.w52_pos!=null)?v.w52_pos:null; if(INFO)renderInfo(INFO);   // 시장 속 위치 표의 52주 행
    const bits=[],dig=[];
    if(v.per!=null){bits.push('PER <span class="n">'+v.per.toFixed(1)+'</span>');dig.push('PER '+v.per.toFixed(1));}
    if(v.pbr!=null)bits.push('PBR <span class="n">'+v.pbr.toFixed(1)+'</span>');
    if(v.w52_pos!=null)bits.push('52주 <span class="n">'+Math.round(v.w52_pos)+'%</span>');
    if(f.roe!=null){bits.push('ROE <span class="n">'+f.roe.toFixed(0)+'%</span>');dig.push('ROE '+f.roe.toFixed(0)+'%');}
    if(f.debt!=null){bits.push('부채 <span class="n">'+f.debt.toFixed(0)+'%</span>');dig.push('부채 '+f.debt.toFixed(0)+'%');}
    if(!bits.length){ sec.style.display='none'; return; }
    const ex=d.explains||{}, co=d.concepts||{};
    let h=bits.join('  ·  ')+(f.period?'  ('+esc(f.period)+' 기준)':'');
    const rows=['per','w52','roe','debt','pbr'].filter(k=>ex[k]).map(function(k){
      const c=co[k]; let li='<li>'+esc(ex[k]);
      if(c) li+='<span class="qi" data-k="'+k+'">ⓘ</span>'
        +'<div class="cexp" id="cexp-'+k+'"><b>'+esc(c.title)+'</b> — '+esc(c.body)+'</div>';
      return li+'</li>';
    });
    if(rows.length) h+='<ul class="finex">'+rows.join('')+'</ul>';
    document.getElementById('fin').innerHTML=h;
    document.getElementById('fin-digest').textContent=dig.join(' · ');
    sec.style.display='';
    sec.querySelectorAll('.qi').forEach(function(q){ q.onclick=function(){
      const e=document.getElementById('cexp-'+q.dataset.k); if(e)e.classList.toggle('on'); }; });
  }catch(e){ if(sec)sec.style.display='none'; }
}
loadFin();

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
  topLineColor:'#e5342f',topFillColor:'rgba(229,52,47,.15)',
  bottomLineColor:'#1f66e0',bottomFillColor:'rgba(31,102,224,.15)',lineWidth:2,
  autoscaleInfoProvider:()=>pgmRange?{priceRange:pgmRange}:null});
registerSemSeries(series,'baseline');   // 라이트/다크 전환 시 선 색 재적용
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
const pseries=pchart.addCandlestickSeries({upColor:'#e5342f',downColor:'#1f66e0',
  borderVisible:false,wickUpColor:'#e5342f',wickDownColor:'#1f66e0',
  priceFormat:{type:'price',precision:0,minMove:1}});   // KRW는 정수 — 축 '.00' 제거(폭도 축소)
registerSemSeries(pseries,'candle');   // 라이트/다크 전환 시 캔들 색 재적용(theme.py)
// 이동평균선(20/60/120봉) — 켜고 끄기. addLineSeries 없는 node 하니스에선 가드로 생략.
const MA_COLORS={5:'#9aa0a6',10:'#ec4899',20:'#f59e0b',60:'#22c55e',120:'#3b82f6'};
let maOn={5:true,10:true,20:true,60:true,120:true};
let maSeries={};
if(pchart.addLineSeries){[5,10,20,60,120].forEach(function(n){
  maSeries[n]=pchart.addLineSeries({color:MA_COLORS[n],lineWidth:1.5,
    priceLineVisible:false,lastValueVisible:false,crosshairMarkerVisible:false,visible:maOn[n]});
});}
// 범례 칩 색점(토스식 ■색 번호) — MA_COLORS를 버튼에 주입
document.querySelectorAll('.ma-btn[data-ma]').forEach(function(b){
  b.style.setProperty('--dot', MA_COLORS[+b.getAttribute('data-ma')]||'transparent');});
// 캔들이 메인 pane 전체를 쓰도록(거래량은 아래 별도 차트로 분리) — 캔들이 작아 보이던 문제 해결.
try{pchart.priceScale('right').applyOptions({scaleMargins:{top:0.08,bottom:0.08},minimumWidth:76});}catch(e){}
// ── 거래량 별도 차트(vchart) — 캔들 차트 바로 아래. 시간축은 pchart와 논리범위 동기화(전부 하니스 가드) ──
let vchart=null, volSeries=null;
try{
  vchart=LightweightCharts.createChart(document.getElementById('vchart'),{autoSize:true,height:72,
    layout:_pt2.layout,grid:_pt2.grid,
    rightPriceScale:{borderColor:_pt2.rightPriceScale.borderColor},
    leftPriceScale:{visible:false}, timeScale:{visible:false},
    handleScroll:false, handleScale:false,
    crosshair:{horzLine:{visible:false}}});
  registerChart(vchart);
  try{vchart.priceScale('right').applyOptions({minimumWidth:76,scaleMargins:{top:0.14,bottom:0}});}catch(e){}
}catch(e){}
if(vchart&&vchart.addHistogramSeries){
  volSeries=vchart.addHistogramSeries({priceFormat:{type:'volume'},
    lastValueVisible:false,priceLineVisible:false});
}
// ── MACD 히스토그램(mchart) — 거래량 차트 아래. 막대 = MACD선(12,26) − 시그널선(9) ──
let mchart=null, oscSeries=null, lastOsc=null;
try{
  mchart=LightweightCharts.createChart(document.getElementById('mchart'),{autoSize:true,height:64,
    layout:_pt2.layout,grid:_pt2.grid,
    rightPriceScale:{borderColor:_pt2.rightPriceScale.borderColor},
    leftPriceScale:{visible:false}, timeScale:{visible:false},
    handleScroll:false, handleScale:false,
    crosshair:{horzLine:{visible:false}}});
  registerChart(mchart);
  try{mchart.priceScale('right').applyOptions({minimumWidth:76,scaleMargins:{top:0.12,bottom:0.12}});}catch(e){}
}catch(e){}
if(mchart&&mchart.addHistogramSeries){
  oscSeries=mchart.addHistogramSeries({base:0,priceFormat:{type:'price',precision:0,minMove:1},
    lastValueVisible:false,priceLineVisible:false});
}
// 공매도 거래량(일봉 전용) — 거래량 차트에 함께.
let ssSeries=null, ssOn=false, SS_ROWS=[], lastVol=0;
if(vchart&&vchart.addHistogramSeries){
  ssSeries=vchart.addHistogramSeries({priceFormat:{type:'volume'},
    lastValueVisible:false,priceLineVisible:false,color:'rgba(168,85,247,.7)'});
}
function renderSS(){
  var showSS = ssOn && TF==='1d' && SS_ROWS.length;
  if(ssSeries){
    ssSeries.setData(showSS?SS_ROWS.map(function(r){return {time:r.date, value:r.qty||0};}):[]);
  }
  // 공매도 볼 땐 거래량을 숨긴다 — 같은 스케일에 눌리지 않게, 공매도가 자체 스케일로 크게 보이도록.
  if(volSeries){try{volSeries.applyOptions({visible:!showSS});}catch(e){}}
  var _vlb=document.getElementById('vol-lb');
  if(_vlb){
    if(showSS){var _sq=SS_ROWS[SS_ROWS.length-1].qty||0; _vlb.textContent='공매도 '+num(_sq)+'주';}
    else _vlb.textContent='거래량 '+num(lastVol)+'주';
  }
}
// 시간축 동기화: 캔들을 pan/zoom하면 서브패널(거래량·MACD)이 같이 이동.
// 반드시 '메인 → 서브 전부'를 한 번에 미는 팬아웃이어야 한다. 재진입 가드(_vsync)가
// 전역 하나뿐이라 pairwise로 엮으면(구: _bindSync(a,b) 2회) 메인→A 전파 중에 A→B가
// 가드에 삼켜져 두 번째 서브패널만 조용히 안 따라온다. make verify는 pan/zoom을
// 하지 않으므로 이 고장은 하네스를 통과한다 — 손으로만 드러난다(2026-08-24).
let _vsync=false;
function _subs(){ return [vchart,mchart].filter(Boolean); }
function _push(targets,r){ if(_vsync||!r||!targets.length)return; _vsync=true;
  targets.forEach(function(t){ try{t.timeScale().setVisibleLogicalRange(r);}catch(e){} });
  _vsync=false; }
function _sub1(c,targets){ var ts=c&&c.timeScale&&c.timeScale();
  if(!ts||!ts.subscribeVisibleLogicalRangeChange)return;
  ts.subscribeVisibleLogicalRangeChange(function(r){ _push(targets,r); }); }
_sub1(pchart,_subs());                                  // 메인 → 서브 전부(한 번의 가드 안에서)
// 서브 → 메인 역방향은 걸지 않는다. 서브는 handleScroll/handleScale이 false라
// 사용자 조작으로 범위를 만들 일이 없고, setData 직후 자기 오토스케일로 뒤늦게
// 뱉는 범위가 loadCandles의 fitContent()를 덮어써 일봉 전환이 전체(0~119) 대신
// 41~119·79~119로 실행마다 다르게 갇혔다(2026-08-24 CDP 실측, 차트 2개일 땐
// 잠복해 있다가 3개가 되며 드러남). 범위의 단일 출처는 메인 차트 하나다.
function syncVol(){ var ts=pchart.timeScale();
  if(!ts.getVisibleLogicalRange)return;
  try{var r=ts.getVisibleLogicalRange(); if(r)_push(_subs(),r);}catch(e){} }
// 현재가 이동 라인(매 틱 위치·색 갱신). 하니스 createPriceLine은 undefined 반환 → 가드.
let nowLine=null;
try{nowLine=pseries.createPriceLine({price:0,color:'#8a94a6',lineWidth:1,lineStyle:1,
  axisLabelVisible:false,title:''});}catch(e){}
let lastCandle=null, lastCandleTf=null;
function bucketMin(m,n){return m>=540?m-((m-540)%n):m-(m%n);} // 백엔드 aggregate와 동일(09:00 정렬)
function updateLiveCandle(M){
  if(M.price==null||!pseries.update)return;   // 하니스(update 없음)·미체결 가드
  var price=M.price;
  var _col=(M.sign==='up'?'#e5342f':(M.sign==='down'?'#1f66e0':'#8a94a6'));
  if(nowLine){try{nowLine.applyOptions({price:price,color:_col});}catch(e){}}
  try{pseries.applyOptions({priceLineColor:_col,priceLineWidth:2});}catch(e){}   // 현재가 축 태그 방향색
  var ce=document.getElementById('pc-count');
  if(isDay(TF)||!lastCandle||lastCandleTf!==TF){if(ce)ce.textContent='';return;} // 일·주·월봉·미로드 제외
  var n={'1m':1,'5m':5,'15m':15,'60m':60}[TF]; if(!n){if(ce)ce.textContent='';return;}
  var p=(KTIME||'00:00:00').split(':'), mm=(+p[0])*60+(+p[1]);
  var bmin=bucketMin(mm,n), bh=Math.floor(bmin/60), bm=bmin%60;
  var bt=(bh<10?'0':'')+bh+':'+(bm<10?'0':'')+bm+':00', ts=toTs(bt,KDATE);
  if(ts<lastCandle.time)return;                 // 과거로 되돌아가지 않음
  if(ts>lastCandle.time){lastCandle={time:ts,open:price,high:price,low:price,close:price};} // 새 봉
  else{lastCandle.close=price; if(price>lastCandle.high)lastCandle.high=price; // 형성 중 봉 갱신
       if(price<lastCandle.low)lastCandle.low=price;}
  try{pseries.update(lastCandle);}catch(e){}
  if(ce){var sec=(+p[0])*3600+(+p[1])*60+(+(p[2]||0)), rem=n*60-(sec-bmin*60);
    if(rem<0)rem=0; ce.textContent='⏱ 다음 봉 '+Math.floor(rem/60)+':'+((rem%60)<10?'0':'')+(rem%60);}
}
function ohlcHtml(dd){var chg=dd.close-dd.open, c=chg>0?'up':(chg<0?'down':'flat');
  return '<b class="'+c+'">'+won(dd.close)+'</b> <span class="meta">시 '+num(dd.open)
    +' · 고 '+num(dd.high)+' · 저 '+num(dd.low)+'</span>';}
if(pchart.subscribeCrosshairMove){pchart.subscribeCrosshairMove(function(param){
  var el=document.getElementById('ohlc'); if(!el)return;
  var dd=(param&&param.seriesData)?param.seriesData.get(pseries):null;
  if(dd&&dd.open!=null){el.innerHTML=ohlcHtml(dd); el.classList.add('on');}
  else{el.classList.remove('on');}
});}
// 최고/최저 오버레이 라벨 배치 — 좌표 변환(가드). 극값이 화면 밖이면 가장자리 고정,
// 라벨을 플롯 안(상단/볼륨밴드 위)으로 클램프해 잘리지 않게.
let EXT=null;
function placeExt(){
  var hi=document.getElementById('hi-lbl'), lo=document.getElementById('lo-lbl');
  if(!EXT||!pseries.priceToCoordinate){if(hi)hi.style.display='none';if(lo)lo.style.display='none';return;}
  var pc=document.getElementById('pchart')||{}, cw=pc.clientWidth||0, ph=pc.clientHeight||0;
  var band=ph*0.08, ts=pchart.timeScale();
  [[hi,EXT.hiTime,EXT.hi,EXT.hiText,true],[lo,EXT.loTime,EXT.lo,EXT.loText,false]].forEach(function(a){
    var el=a[0]; if(!el)return;
    var y=pseries.priceToCoordinate(a[2]);
    if(y==null){el.style.display='none';return;}
    var x=ts.timeToCoordinate(a[1]);
    if(x==null){var r=ts.getVisibleRange?ts.getVisibleRange():null; x=(r&&a[1]<r.from)?8:cw-8;}
    var top=a[4]?(y-16):(y+6);                         // 최고=봉 위, 최저=봉 아래
    top=Math.max(2,Math.min(ph-band-14,top));          // 플롯 안(볼륨밴드 위)로 클램프
    var ax=Math.max(4,Math.min(cw-4,x));               // 가장자리에선 좌/우 정렬(중앙 정렬 밀림 방지)
    el.style.transform=ax<56?'translateX(0)':(ax>cw-56?'translateX(-100%)':'translateX(-50%)');
    el.textContent=a[3]; el.style.display='';
    el.style.left=ax+'px'; el.style.top=top+'px';
  });
}
(function(){var _ts=pchart.timeScale();
  if(_ts.subscribeVisibleTimeRangeChange)_ts.subscribeVisibleTimeRangeChange(placeExt);})();
let TF='5m', tfSeq=0;
const TF_KO={'1m':'당일 1분봉','5m':'당일 5분봉','15m':'당일 15분봉','60m':'당일 60분봉',
  '1d':'일봉 120일','1w':'주봉 120주','1mo':'월봉 120개월'};
// 일 단위 봉(시간 라벨이 날짜 문자열) — 분봉과 시간축 처리·갱신 주기가 갈린다
const isDay=tf=>tf==='1d'||tf==='1w'||tf==='1mo';
// 차트 로딩 오버레이 — /api/candles는 웜 3.8초·콜드 8.2초가 걸린다(2026-08-11 실측).
// 그동안 차트 영역은 라이브러리 워터마크만 있는 빈 상자라 '고장'으로 읽힌다(제보 2회).
// 헤더 pc-fresh의 작은 글씨는 신호가 못 된다. fit=true(최초·주기 전환)에만 덮는다 —
// 60초 자동 갱신마다 덮으면 1분에 한 번씩 화면이 깜빡인다.
function setChartLoading(on){
  const el=document.getElementById('pcload');
  if(el)el.className='stall cload'+(on?' on':'');
}
async function loadCandles(fit){
  // fit=true일 때만 전체 보기로 맞춘다(최초 로드·타임프레임 전환). 60초 자동 갱신은
  // fit=false로 사용자의 확대/이동 뷰를 보존(실사고: 갱신마다 초기화).
  const seq=++tfSeq, tf=TF; // 연타로 주기를 바꿔도 마지막 요청만 반영(경합 방지)
  if(fit)setChartLoading(true);
  try{
    const r=await fetch('/api/candles/'+CODE+'?tf='+tf);
    if(seq!==tfSeq)return;
    if(!r.ok){document.getElementById('pc-fresh').textContent='· 차트 조회 실패';return;}
    const d=await r.json();
    if(seq!==tfSeq)return;
    if(!d.candles.length){document.getElementById('pc-fresh').textContent='· 데이터 없음(장전이거나 조회 실패)';return;}
    var _mapped=d.candles.map(c=>({time:isDay(tf)?c.t:toTs(c.t,d.date),
      open:c.open,high:c.high,low:c.low,close:c.close}));
    pseries.setData(_mapped);
    // 최고/최저 자동 주석: 전체 로드 기간 고정 · 현재가(마지막 종가) 대비 % · 오버레이 라벨(placeExt).
    var _hi=-Infinity,_lo=Infinity,_hiI=0,_loI=0;
    for(var _i=0;_i<_mapped.length;_i++){
      if(_mapped[_i].high>_hi){_hi=_mapped[_i].high;_hiI=_i;}
      if(_mapped[_i].low<_lo){_lo=_mapped[_i].low;_loI=_i;}
    }
    var _cur=_mapped.length?_mapped[_mapped.length-1].close:0;
    var _pct=function(v){var p=_cur?((v-_cur)/_cur*100):0;return (p>=0?'+':'')+p.toFixed(1)+'%';};
    var _dt=function(idx){var t=(d.candles[idx]||{}).t||'';return t.length>=10?t.slice(5).replace('-','.'):t;};
    EXT=_mapped.length?{hi:_hi,lo:_lo,hiTime:_mapped[_hiI].time,loTime:_mapped[_loI].time,
      hiText:won(_hi)+' ('+_dt(_hiI)+') '+_pct(_hi),
      loText:won(_lo)+' ('+_dt(_loI)+') '+_pct(_lo)}:null;
    placeExt();
    // 실시간 봉 갱신 기준: 마지막 로드 봉(틱마다 이 봉의 고저종을 pseries.update로 갱신)
    lastCandle=_mapped.length?Object.assign({},_mapped[_mapped.length-1]):null; lastCandleTf=tf;
    // 거래량 히스토그램(상승=적/하락=청 반투명). FDR 일·주·월봉은 vol이 실리고 분봉은 당일 집계.
    if(volSeries){volSeries.setData(d.candles.map(function(c){return {
      time:isDay(tf)?c.t:toTs(c.t,d.date), value:c.vol||0,
      color:(c.close>=c.open?'rgba(229,52,47,.5)':'rgba(31,102,224,.5)')};}));}
    lastVol=d.candles.length?(d.candles[d.candles.length-1].vol||0):0;   // 최근 봉 거래량(라벨은 renderSS)
    // 이평선: 데이터 세팅 + 봉주기별 사용 가능 여부로 버튼 활성화.
    // 짧은 봉(5분 79개 등)엔 120봉 표본이 없어 선이 안 그려짐 → 버튼 비활성+안내(무반응 오해 방지).
    var _na=[];
    [5,10,20,60,120].forEach(function(n){
      var key='ma'+n, has=d.candles.some(function(c){return c[key]!=null;});
      if(pchart.addLineSeries&&maSeries[n]){
        maSeries[n].setData(has?d.candles.filter(function(c){return c[key]!=null;})
          .map(function(c){return {time:isDay(tf)?c.t:toTs(c.t,d.date), value:c[key]};}):[]);
      }
      if(!has)_na.push(n);
    });
    document.querySelectorAll('.ma-btn').forEach(function(btn){
      var has=_na.indexOf(+btn.getAttribute('data-ma'))<0;
      btn.disabled=!has; btn.classList.toggle('na',!has);
    });
    document.querySelectorAll('.ma-hint').forEach(function(h){
      h.textContent=_na.length?('이평 · '+_na.join('/')+'봉은 표본 부족'
          +(isDay(tf)?'':'(일봉에서 전부 표시)'))
        :'봉 이동평균 · 켜고 끄기';
    });
    // MACD 히스토그램(12,26,9) — 앞 33봉은 워밍업이라 osc가 null(백엔드 _attach_macd).
    // 34봉이 안 되는 주기(15분 26봉·60분 7봉)는 전 구간 null → 막대 없이 안내만 남긴다.
    var _osc=d.candles.filter(function(c){return c.osc!=null;});
    if(oscSeries){oscSeries.setData(_osc.map(function(c){return {
      time:isDay(tf)?c.t:toTs(c.t,d.date), value:c.osc,
      color:(c.osc>=0?'rgba(229,52,47,.5)':'rgba(31,102,224,.5)')};}));}   // 바로 위 거래량 막대와 같은 투명도
    lastOsc=_osc.length?_osc[_osc.length-1].osc:null;
    var _mlb=document.getElementById('mac-lb');
    if(_mlb)_mlb.textContent=(lastOsc==null)
      ? 'MACD · 이 봉주기는 표본 부족(34봉 이상 필요)'
      : 'MACD '+num(lastOsc)+' · '+(lastOsc>=0
          ? '0 위 — 단기 흐름이 장기보다 세다' : '0 아래 — 단기 흐름이 장기보다 약하다');
    // 공매도 오버레이: 일봉에서만(일별 T+1 데이터) — 버튼 활성화 + 재정렬
    var _ssOk=(tf==='1d');
    document.querySelectorAll('.ss-btn').forEach(function(b){b.disabled=!_ssOk;
      b.classList.toggle('na',!_ssOk); if(!_ssOk)b.classList.remove('on');});
    if(!_ssOk)ssOn=false;
    renderSS();
    pchart.applyOptions({timeScale:{timeVisible:!isDay(tf)}});
    if(fit)pchart.timeScale().fitContent();
    syncVol();   // 거래량 차트 시간축을 캔들과 정렬
    const lastT=d.candles[d.candles.length-1].t;
    document.getElementById('pc-fresh').textContent='· '+TF_KO[tf]+' · 기준 '
      +lastT+(isDay(tf)?'':' (KST) · 60초 자동 갱신');
  }catch(e){console.error(e);}
  // seq 가드: 뒤늦게 끝난 옛 요청이 진행 중인 새 요청의 오버레이를 걷어내면 안 된다.
  finally{ if(seq===tfSeq)setChartLoading(false); }
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
// 공매도 거래량 오버레이 토글(일봉 전용 — 비활성 시 무시)
document.querySelectorAll('.ss-btn').forEach(function(b){b.onclick=function(){
  if(b.disabled)return; ssOn=!ssOn; b.classList.toggle('on',ssOn); renderSS();
  // 켤 때 전체 봉(120일)이 보이게 맞춤 — 확대 상태에서 공매도만 채워 보이던 문제 방지
  if(ssOn){try{pchart.timeScale().fitContent();}catch(e){}} syncVol();};});
// 전체 보기 — 확대/이동으로 갇혔을 때 전체 기간 캔들로 복귀
document.querySelectorAll('.fit-btn').forEach(function(b){b.onclick=function(){
  try{pchart.timeScale().fitContent();}catch(e){} syncVol();};});
// 주봉 MACD 배지 — 일·분봉을 보는 중에도 상위 시간축을 한 줄로 같이 본다.
// (마스터 질문 2026-08-25: "일봉 기준엔 MACD가 반등인데 주봉은 아직 하향추세, 어떻게 보나")
// 판정 문구는 백엔드가 만든다(candles.weekly_macd_signal) — 여기선 그대로 띄운다.
// 차트를 더 그리지 않는 이유: 주봉은 시간축이 달라 _subs() 팬아웃에 넣을 수 없고
// (넣으면 메인 차트가 끌려간다), 마스터가 물은 건 그림이 아니라 해석이다.
// 주 단위로 움직이는 값이라 10분 스로틀 — 서버도 주·월봉 원료를 1시간 캐시한다.
let wkAt=0;
async function loadWeeklyMacd(){
  if(Date.now()-wkAt<600000)return;
  const el=document.getElementById('wk-macd'); if(!el)return;
  try{
    const r=await fetch('/api/candles/'+CODE+'?tf=1w'); if(!r.ok)return;
    const s=(await r.json()).signal; wkAt=Date.now();
    el.textContent=s?s.text:'';        // 표본 부족(null)이면 빈 문자열 → .sig:empty가 감춘다
    el.className='sig'+(s?' sig-'+s.tone:'');
  }catch(e){}
}
loadCandles(true);
loadWeeklyMacd();
setInterval(()=>{loadWeeklyMacd();if(!isDay(TF))loadCandles(false);},60000);
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

// #hago 페인트용 마지막 체결시각(epoch ms). render()에만 두면 SSE가 멈춰 render()가
// 안 불릴 때 "방금"에 영구 고착한다 — 그래서 워치독(1450행 근처 setInterval)도
// 이 변수로 다시 그린다(2026-08-13).
let _hagoTs=null;
function paintHago(){
  try{var _h=document.getElementById('hago'); if(_h&&_hagoTs!=null)_h.textContent=ago(_hagoTs);}catch(e){}
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
  // 매수 유의사항(토스 Open API) — 정리매매·단기과열·투자경고/위험·VI·신주인수권.
  // 바로 왼쪽 mstate의 'VI/CB 의심'은 체결 공백으로 **추정**한 것이고, 이 배지는
  // 거래소가 실제로 건 지정이다(추정 옆에 확정을 나란히 둔다).
  // 색(tone)은 서버가 정한다 — 프런트는 칠하기만 한다(이 리포의 관행).
  // 빈 배열이면 반드시 지운다: VI는 2~10분이면 풀리는데 마지막 값을 붙들면
  // 이미 끝난 경고가 종일 남는다. className도 같이 비워 빈 알약이 안 그려지게.
  const wl=S.warnings||[], wp=document.getElementById('wpill');
  // esc()를 안 쓴다 — textContent는 대입 자체가 이스케이프다. 여기에 esc를 걸면
  // 라벨에 '&'가 들어가는 날 화면에 '&amp;'가 글자 그대로 찍힌다.
  wp.textContent=wl.length?('⚠ '+wl.map(w=>w.label||'').join(' · ')):'';
  wp.className=wl.length?('badge b-'+(wl.some(w=>w.tone==='warn')?'warn':'info')):'';
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
    p.textContent=won(M.price);
    p.className='price '+M.sign;
    var cg=document.getElementById('chg');
    cg.textContent=(M.change!=null?sgn[M.sign]+won(Math.abs(M.change)):'')
      +(M.rate!=null?'  '+(M.rate>0?'+':(M.rate<0?'-':''))+Math.abs(M.rate).toFixed(2)+'%':'');
    cg.className='pill '+M.sign;
    // 2026-08-13: 거래대금·체결강도는 여기서 뺐다 — 히어로 근거 레일(#hrail)이 이미
    // 말해서, 히어로와 200px 아래에 같은 숫자가 두 번 보이던 중복이었다(리뷰 지적).
    document.getElementById('pmeta').innerHTML='거래량 <span class="n">'+num(M.vol)+'</span>주 · 기준 <span class="n">'+esc(M.time||'')+'</span> (KST) <span class="fresh">· 실시간 · __MKT__</span>';
    // 히어로 근거 레일(#hrail) — 거래대금·체결강도는 여기서만 말한다(위 pmeta 참고).
    // 전일 종가는 스냅샷에 별도 필드가 없어 현재가-부호있는전일대비로 역산한다.
    // sign(up/down)으로 부호를 만들고 change는 abs()로 씌워, 와이어가 change를
    // 이미 부호 있는 값으로 주든(데모) 크기만 주든(실 KIS, 부호는 별도 필드) 둘 다 맞는다.
    var _pc=M.change!=null?M.price-(M.sign==='up'?1:(M.sign==='down'?-1:0))*Math.abs(M.change):null;
    document.getElementById('hr-prev').textContent=won(_pc);
    document.getElementById('hr-amt').textContent=eok(M.value).replace('+','');
    document.getElementById('hr-str').textContent=M.strength==null?'–':M.strength.toFixed(1);
    // 히어로 하단 상대시간(#hago) — M.time은 체결시각 "HH:MM:SS"(KST), 날짜 없음.
    // toTs()는 이 벽시계를 UTC인 척 만들어(차트 라벨용) 9h(32400000ms) 앞선 값을 주므로,
    // ago()가 Date.now()(진짜 epoch)와 비교할 수 있게 9h를 빼서 진짜 epoch로 되돌린다(2026-08-12).
    if(M.time)_hagoTs=toTs(M.time)*1000-32400000;
    paintHago();
    checkWatch(M.price); // 감시선 ±0.5% 진입 알림(P1-8)
    updateLiveCandle(M); // 실시간 봉 갱신 + 현재가 라인 + 다음 봉 카운트다운
  }
  const ED=S.estimate_detail;
  const E=S.estimate;
  // 오늘 수급 요약의 출처 — 당일 확정 행이 있으면 확정(서버 판정). 잠정 API는
  // 슬롯이 14:30이 마지막이라 마감 후에도 멈춰 아래 확정치와 어긋난다.
  const TF=S.today_flow||null;
  const TFC=!!(TF&&TF.src==='confirmed');
  if(E.rows.length){
    const last=E.rows[E.rows.length-1];
    document.getElementById('est-fresh').textContent='잠정 · '+last.asof+' 기준 · '
      +(TFC?'마감 후 확정치로 대체됨 — 아래 일별 확정 수급 참고'
          :'다음 갱신 '+nextSlot()+' · 익일 확정');
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
  // 당일 확정 행이 붙는 날이 있으므로 '전일까지' 라벨을 고정하지 않는다
  document.getElementById('daily-fresh').textContent=
    (S.daily.length&&S.daily[S.daily.length-1].date===S.kst_date)
      ? '· 오늘 확정까지 반영' : '· 전일까지 확정치';
  document.getElementById('daily').innerHTML='<tr><th>날짜</th><th>개인</th><th>외국인</th><th>기관</th><th>종가</th><th>대차잔고</th></tr>'
    +S.daily.map(d=>{const m=sbm[d.date];
    return '<tr><td>'+esc(d.date.slice(5))+'</td><td class="'+cls(d.prsn)+'">'+shares(d.prsn)
    +'</td><td class="'+cls(d.frgn)+'">'+shares(d.frgn)+'</td><td class="'+cls(d.orgn)+'">'+shares(d.orgn)
    +'</td><td>'+won(d.close)+'</td><td class="'+(m&&m.chg!=null?cls(m.chg):'flat')+'">'
    +(m?num(m.qty):'–')+'</td></tr>';}).join('');
  // ── 대차잔고 패널: 최신 잔고·증감(증가=적색/감소=청색)·판정 시그널·20일 추이 ──
  const jo=n=>n==null?'–':(Math.abs(n)>=1e12?(n/1e12).toLocaleString('ko-KR',{maximumFractionDigits:1})+'조':eok(n).replace('+',''));
  const srcKo={kofia:'금융투자협회',seibro:'예탁결제원(SEIBro)',demo:'데모(시뮬레이션)'};
  const _dow='일월화수목금토';
  const fmtD=iso=>{const p=(iso||'').split('-');if(p.length!==3)return iso||'';
    const dt=new Date(+p[0],+p[1]-1,+p[2]);return (+p[1])+'/'+(+p[2])+'('+_dow[dt.getDay()]+')';};
  if(SB.rows.length){
    const last=SB.rows[SB.rows.length-1];
    // 협회·예탁원은 집계 범위가 달라 절대치가 다르다 — 혼합 시 행별 출처 표기
    const srcShort={kofia:'협회',seibro:'예탁원',demo:'데모'};
    const mixed=new Set(SB.rows.map(r=>r.src)).size>1;
    document.getElementById('sb-pill').textContent='🕐 '+fmtD(last.date)+' 기준 · T+1';
    document.getElementById('sb-fresh').textContent='출처 '+(srcKo[last.src]||last.src)
      +(mixed?' · ⚠ 기간 내 출처 혼합':'');
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
    const _net=(last.contract!=null&&last.repay!=null)?last.contract-last.repay:null;
    document.getElementById('sb-pro-flow').textContent=_net==null?'–':(_net>0?'순증 +':'순증 ')+shares(_net);
    const _prevq=SB.rows.length>1?SB.rows[SB.rows.length-2].qty:null;
    document.getElementById('sb-pro-rate').textContent=(_prevq?((last.qty-_prevq)/_prevq*100).toFixed(1)+'%':'–');
    document.getElementById('sb-pro-src').textContent=(srcKo[last.src]||last.src);
  }else{
    document.getElementById('sb-pill').textContent='🕐 데이터 대기';
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
  // DR이 없는 종목엔 패널 자체가 없다(서버가 settings.adr_map으로 가른다) —
  // 그때 getElementById는 null이라 아래 접근이 전부 TypeError가 되고, 그러면
  // 이 뒤의 공매도·체결 렌더까지 통째로 죽는다. 앵커 하나로 먼저 막는다.
  const A=S.adr;
  if(!document.getElementById('adr-fresh')){ /* ADR 없는 종목 — 건너뛴다 */ }
  else if(A){
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
      +({regular:'미국 장중',after:'미국 애프터장(시간외)',pre:'미국 프리마켓(시간외)'}[A.session]
        ||(A.us_open?'미국 장중':'미국 장마감 — 전일 종가 기준'))
      +' · 환율 '+A.fx.toLocaleString('ko-KR')+'원 · 조회 '+esc(A.fetched||'')+' (KST) · 출처 '
      +(A.src==='naver-ext'?'네이버(시간외)':(A.src==='kis'?'KIS':(A.src==='naver'?'네이버(폴백)':'데모')));
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
  SS_ROWS=SS.rows; renderSS();   // 공매도 거래량 차트 오버레이(일봉·토글 시)
  if(SS.rows.length){
    const sl=SS.rows[SS.rows.length-1];
    // 마감 후 당일 확정이 들어오면 'T+1'(전일 기준)은 사실과 어긋난다
    document.getElementById('ss-pill').textContent='🕐 '+fmtD(sl.date)+' 기준 · '
      +(sl.date===S.kst_date?'당일 확정':'T+1');
    document.getElementById('ss-fresh').textContent='출처 KIS';
    document.getElementById('ss-ratio-big').textContent='비중 '+(sl.ratio||0).toFixed(1)+'%';
    document.getElementById('ss-ratio-big').className='sig sig-'+((sl.ratio||0)>=5?'warn':'flat');
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
    document.getElementById('ss-pro-value').textContent=eok(sl.value).replace('+','');
    // 공매도 평균가 = 거래대금/체결량. KIS 응답의 avrg_prc는 공식 라벨이 '평균가격'뿐이라
    // (2026-09-08 확인) 공매도 평균가라는 보장이 없어 직접 나눈다. 실응답 픽스처의 avrg_prc
    // 2,218,400원과는 26원 차(2,218,426) — KIS 쪽 백원 단위 반올림으로 추정, 검증 안 됨.
    const _ap=(sl.qty>0&&sl.value>0)?sl.value/sl.qty:null;
    document.getElementById('ss-pro-avgprc').textContent=won(_ap);
    document.getElementById('ss-pro-ratio').textContent=(sl.ratio||0).toFixed(2)+'%';
    const _avg=SS.rows.reduce((a,r)=>a+(r.ratio||0),0)/SS.rows.length;
    document.getElementById('ss-pro-avg').textContent=_avg.toFixed(2)+'%';
    const _hot=(sl.ratio||0)>_avg;
    const pv=document.getElementById('ss-pro-verdict');
    // 종가 vs 공매도 평균가: 종가가 위면 공매도 쪽이 손실 중(되사기 압력), 아래면 이익 중.
    const _gap=(_ap&&sl.close)?(sl.close/_ap-1)*100:null;
    pv.textContent=(_hot?('비중이 20일 평균('+_avg.toFixed(1)+'%)을 웃돎 — 공매도 과열 구간')
      :('비중이 20일 평균('+_avg.toFixed(1)+'%) 이하 — 평시'))
      +(_gap==null?'':Math.abs(_gap)<0.05?' · 종가 ≈ 공매도 평균가 — 공매도 쪽 손익 균형'
        :' · 종가가 공매도 평균가보다 '+Math.abs(_gap).toFixed(1)+'% '
        +(_gap>0?'위 — 공매도 쪽 손실 중(되사기 압력)':'아래 — 공매도 쪽 이익 중'));
    pv.className='pro-verdict'+(_hot?'':' flat');
  }else{
    document.getElementById('ss-pill').textContent='🕐 데이터 대기';
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
    document.getElementById('cr-pill').textContent='🕐 '+fmtD(cl.date)+' 기준 · T+2';
    document.getElementById('cr-fresh').textContent='출처 KIS · 결제 반영';
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
    document.getElementById('cr-pro-ratio').textContent=(cl.ratio||0).toFixed(2)+'%';
    document.getElementById('cr-pro-flow').textContent=(cl.new!=null?num(cl.new):'–')+' / '+(cl.rdmp!=null?num(cl.rdmp):'–');
    const _cpq=CR.rows.length>1?CR.rows[CR.rows.length-2].qty:null;
    document.getElementById('cr-pro-rate').textContent=(_cpq?((cl.qty-_cpq)/_cpq*100).toFixed(1)+'%':'–');
    const _cpv=document.getElementById('cr-pro-verdict');
    _cpv.textContent=csig?csig.text:'판정 대기';
    _cpv.className='pro-verdict '+(csig?csig.tone:'flat');   // 상환=good(청)/경계=warn(적)/중립=flat
    document.getElementById('cr-pro-basis').textContent='deal_date 기준 · 결제 반영 T+2';
  }else{
    document.getElementById('cr-pill').textContent='🕐 데이터 대기';
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
  // ── 한눈 요약 스트립: 핵심 지표를 히어로 아래 한 줄로 압축(중복이라도 전부 노출) ──
  (function(){
    let g='';
    if(TF){const sfx=TFC?'(확정)':'(잠정)';
      g+=glchip('외인 순매수'+sfx,shares(TF.frgn),cls(TF.frgn));
      g+=glchip('기관 순매수'+sfx,shares(TF.orgn),cls(TF.orgn));}
    if(P.net_value!=null)g+=glchip('프로그램',eok(P.net_value),cls(P.net_value));
    if(SS.rows.length)g+=glchip('공매도 비중',(SS.rows[SS.rows.length-1].ratio||0).toFixed(2)+'%','flat');
    if(A&&A.premium_pct!=null)g+=glchip('ADR 괴리',(A.premium_pct>0?'+':'')+A.premium_pct.toFixed(2)+'%',cls(A.premium_pct));
    document.getElementById('glance').innerHTML=g;
  })();
  // ── 한 줄 요약(초보): 오늘 수급을 평문 한 문장으로 — 히어로 아래(요약우선 IA) ──
  (function(){
    var el=document.getElementById('today-line'); if(!el)return;
    var p=[];
    // 마감 후 확정치엔 진행형('사는 중')을 쓰지 않는다 — 이미 끝난 매매다
    if(TF){var bu=TFC?' 순매수':' 사는 중', se=TFC?' 순매도':' 파는 중';
      if(TF.frgn>0)p.push('외국인'+bu); else if(TF.frgn<0)p.push('외국인'+se);
      if(TF.orgn>0)p.push('기관'+bu); else if(TF.orgn<0)p.push('기관'+se);}
    if(P.net_value>0)p.push('프로그램 매수'); else if(P.net_value<0)p.push('프로그램 매도');
    el.textContent=p.length?('오늘 · '+p.join('  ·  ')):'';
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
  paintHago(); // render()에만 두면 SSE가 멈췄을 때 "방금"에 고착한다(2026-08-13)
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
// 드릴다운 섹션이 열릴 때 그 안의 차트(프로그램)를 재-핏 — LWC는 접힌(width:0) 컨테이너에서
// 생성되면 크기가 0이라, 펼칠 때 fitContent로 강제 리사이즈(하니스엔 addEventListener 가드).
// 2026-08-12: 여기에 접힘 상태 저장·복원을 얹었다 — 같은 핸들러가 저장도 재핏도 책임진다.
// 2026-08-13 실측: chart·pchart는 616·640행 top-level const로 먼저 생성되고 이 복원
// 블록은 1470행(connect() 뒤)에서 돈다 — 같은 <script>의 동기 실행이라 #chart는 항상
// 섹션이 열린 뒤 생성되고 그 다음에 닫힌다. '접힌 채로 생성 → 폭 0'은 #chart엔 재현되지
// 않는다. fitContent는 그대로 둔다(접힘→펼침 왕복에서 LWC가 0폭으로 굳던 원래 이유).
try{document.querySelectorAll('details.sec').forEach(function(d){
  if(!d.id)return;                       // id 없는 섹션은 기억하지 않는다(순서 밀림 방지)
  var key='livesec:'+d.id;
  try{var v=localStorage.getItem(key); if(v==='0')d.open=false; else if(v==='1')d.open=true;}catch(e){}
  d.addEventListener('toggle',function(){
    try{localStorage.setItem(key, d.open?'1':'0');}catch(e){}
    if(!d.open)return;
    try{chart.timeScale().fitContent();}catch(e){}
    try{pchart.timeScale().fitContent();syncVol();}catch(e){} });
});}catch(e){}
</script></div>__TABBAR__ __NAV_LOADER__</div></body></html>"""


_MKT_LABEL = {"UN": "KRX+NXT 통합", "J": "KRX", "NX": "NXT"}


_ADR_PANEL = """<details class="sec" id="sec-xvol" open>
  <summary><svg class="hic secic"><use href="#i-globe"/></svg> 해외 DR <span class="chev">▾</span></summary>
  <div class="sec-body">
    <div class="panel">
      <h2><svg class="hic"><use href="#i-globe"/></svg> ADR 환산가·괴리율 <span class="fresh" id="adr-fresh">· 데이터 대기</span></h2>
      <div class="grid3">
        <div><div class="lbl" id="adr-usd-lbl">DR 가격($)</div><div class="val" id="adr-usd">–</div></div>
        <div><div class="lbl">환산가(원)</div><div class="val" id="adr-conv">–</div></div>
        <div><div class="lbl">원주 현재가</div><div class="val" id="adr-ord">–</div></div>
      </div>
      <div class="sig" id="adr-sig"></div>
      <div class="meta" id="adr-note">환산가 = DR가격 × 전환비율 × USD/KRW — 미국 시장이 매긴
      원주 값을 원화로 환산. 원주보다 비싸면(+, 적색) 미국 프리미엄.</div>
    </div>
  </div>
</details>
"""


def _adr_panel(code: str) -> str:
    """DR이 있는 종목에만 ADR 섹션을 그린다(2026-08-21부터 <details> 껍데기째).

    없는 종목(삼성전자·ETF 등)에도 그리면 '데이터 없음 — 조회 실패 또는 미지원 종목.
    자동 재시도 중'이 영원히 남는다. 재시도할 게 없는데 대기 중처럼 보이는 건 거짓말이고,
    자리만 차지한다. 어느 종목에 DR이 있는지는 서버가 이미 안다(settings.adr_map).
    'DR은 있는데 조회 실패'는 여전히 패널 안에서 안내한다 — 그건 재시도가 의미 있다.

    2026-08-21: 거래소별 거래량·체결 규모 분포가 수급 섹션으로 옮겨가 이 섹션엔 ADR
    하나만 남았다. 그래서 패널만 비우면 제목뿐인 빈 껍데기가 남는다 — 섹션째 가른다."""
    from backend.config import settings
    return _ADR_PANEL if code in getattr(settings, "adr_map", {}) else ""


def render_live_page(code: str, name: str, mode: str, email=None) -> str:
    import json

    from backend.config import settings
    from backend.flow import userstore
    lib = _LIB_PATH.read_text(encoding="utf-8")
    # 계정별 감시선(사용자 편집) 우선, 없으면 마스터만 config 폴백 — 이미 정규화된 [{price:int,label}].
    # email=None(직접 렌더/테스트)은 default_account로 해석(마스터 config 시드).
    watch = userstore.get_lines(email or userstore.default_account(), code)
    # </script> 이스케이프: 라벨에 '</'가 들어오면 스크립트 블록이 조기 종료되어
    # 페이지 JS 전체가 죽는다(스크립트 컨텍스트 브레이크아웃, 리뷰 확정)
    watch_js = json.dumps(watch, ensure_ascii=False).replace("</", "<\\/")
    return (_TEMPLATE
            .replace("__BASE_CSS__", _BASE_CSS)
            .replace("__ICONS__", _ICON_SPRITE)
            .replace("__CHART_THEME_JS__", _CHART_THEME_JS)
            .replace("__AGO_JS__", _AGO_JS)
            .replace("__MKT__", _MKT_LABEL.get(settings.market_div, "KRX+NXT 통합"))
            .replace("__TABBAR__", _TABBAR)
            .replace("__NAV_LOADER__", _NAV_LOADER)
            .replace("__ADR_PANEL__", _adr_panel(code))
            .replace("__CODE__", escape(code))
            .replace("__NAME__", escape(name))
            .replace("__MODE__", escape(mode.upper()))
            .replace("__MODE_CLS__", "live" if mode == "live" else "demo")
            .replace("__PWA_HEAD__", _PWA_HEAD)
            .replace("__DISCLAIMER__", escape(_DISCLAIMER))
            .replace("__LIB__", lib)
            # 사용자 데이터는 **항상 맨 마지막**이다. 체인은 앞 단계가 넣은 문자열을
            # 뒤 단계가 다시 스캔하므로, 감시선 라벨이 "__LIB__"면 400KB 차트
            # 라이브러리가 JSON 안으로 주입돼 페이지 JS가 통째로 죽는다(재현 확인).
            # 뒤에 스캔할 단계가 없으면 주입 자체가 성립하지 않는다.
            .replace("__WATCH__", watch_js))
