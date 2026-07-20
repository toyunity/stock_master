from __future__ import annotations

"""공유 디자인 시스템 — 4개 PWA 화면(대시보드·라이브·스캐너·인증)의 단일 스타일 출처.

- 토큰(CSS 커스텀 프로퍼티)으로 라이트/다크 자동 대응(prefers-color-scheme).
- 공통 컴포넌트(카드·배지·시그널 콜아웃·스탯 타일·세그먼트·테이블 스크롤)를 여기서 정의.
- 한국식 상승=적/하락=청 관례, 신선도 라벨, 자기완결(외부 폰트/CDN 0) 유지.
- 엔진(JS 로직)은 각 페이지 그대로 — 여기서는 '껍데기'만 제공한다.

Python 3.9 호환(마스터 실서버는 시스템 3.9) — 단순 문자열 상수만.
"""

# ── PWA head: 라이트/다크 theme-color + 세이프에어리어 전제(viewport-fit은 각 페이지) ──
PWA_HEAD = (
    '<meta name="theme-color" content="#eceef3" media="(prefers-color-scheme: light)">'
    '<meta name="theme-color" content="#0a0c12" media="(prefers-color-scheme: dark)">'
    '<link rel="manifest" href="/manifest.json">'
    '<link rel="apple-touch-icon" href="/icons/icon-180.png">'
    '<meta name="apple-mobile-web-app-capable" content="yes">'
    '<meta name="mobile-web-app-capable" content="yes">'
    '<meta name="apple-mobile-web-app-status-bar-style" content="default">'
    '<meta name="apple-mobile-web-app-title" content="Stock Master">'
)

# ── 디자인 토큰 + 베이스 엘리먼트 + 공통 컴포넌트 ──
BASE_CSS = """
/* ═══════════════════════════════════════════════════════════════════
   Stock Master — "관제(Instrument)" 디자인 시스템
   두 레지스터로 설계: (1) 계기(instrument) — 데이터는 모노 숫자·시맨틱 색·무채색 크롬,
   (2) 튜터(tutor) — 안내/코칭은 sans·둥근 iris 강조·여백. 색은 곧 정보 —
   빨강=상승/매수, 파랑=하락/매도, 초록=양호, 앰버=주의, 보라=공매도/대차/감시선.
   iris(--primary)는 길찾기·코칭 표면에만(장식 금지).
   ═══════════════════════════════════════════════════════════════════ */
:root{
  /* 표면 — 차가운 계기판 무채색 */
  --bg:#eceef3; --surface:#ffffff; --surface-2:#f3f5f9; --surface-3:#e7eaf1;
  --text:#12151d; --text-2:#586074; --text-3:#8b93a4;
  --border:#e0e4ec; --border-2:#ebeef4; --grid:#eef0f6;
  /* 브랜드 iris — 길찾기·코칭 전용 */
  --primary:#6a4ff0; --primary-ink:#5238d8;
  /* 시장 시맨틱 — 의미를 나르는 유일한 chroma. 상승=적/하락=청(한국식) */
  --up:#e5342f; --down:#1f66e0; --flat:#8b93a4;
  --good:#12a56a; --warn:#dc8400; --info:#6a4ff0;
  --violet:#a855f7;   /* 데이터: 공매도·대차·감시선·외국계 창구 */
  --up-bg:#fdeceb; --down-bg:#e9f0fd; --good-bg:#e3f6ee; --warn-bg:#fdf1de; --info-bg:#efebfe;
  --shadow:0 1px 2px rgba(18,21,29,.05), 0 6px 18px rgba(18,21,29,.06);
  --shadow-sm:0 1px 2px rgba(18,21,29,.05);
  --accent-glow:0 1px 8px rgba(106,79,240,.28);
  --font-mono:ui-monospace,SFMono-Regular,"SF Mono",Menlo,"Roboto Mono",monospace;
  --font-num:ui-monospace,SFMono-Regular,"SF Mono",Menlo,"Roboto Mono",monospace;
  --r:12px; --r-lg:16px; --r-sm:9px; --r-pill:999px;
  --disc-bg:#fbf5e6; --disc-bd:#efe1bb; --disc-tx:#7a6320;
}
@media (prefers-color-scheme: dark){
  :root{
    /* 다크 = 터미널: 깊은 잉크-네이비(순흑 회피) */
    --bg:#0a0c12; --surface:#141824; --surface-2:#1a1f2e; --surface-3:#232a3c;
    --text:#e9ecf3; --text-2:#8b93a5; --text-3:#5f6879;
    --border:#252c3c; --border-2:#1c2231; --grid:#1c2231;
    --primary:#9a86ff; --primary-ink:#b3a4ff;
    --up:#ff5b52; --down:#4f8bff; --flat:#5f6879;
    --good:#2fcf8a; --warn:#f2a83a; --info:#9a86ff;
    --violet:#c084fc;
    --up-bg:#2a1512; --down-bg:#101d33; --good-bg:#0d2a1f; --warn-bg:#2a2113; --info-bg:#1a1636;
    --shadow:0 1px 2px rgba(0,0,0,.4), 0 8px 22px rgba(0,0,0,.5);
    --shadow-sm:0 1px 2px rgba(0,0,0,.45);
    --accent-glow:0 1px 10px rgba(154,134,255,.30);
    --disc-bg:#221d13; --disc-bd:#3a3320; --disc-tx:#d8c187;
  }
}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{font-family:-apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo","Malgun Gothic",
  "Segoe UI",sans-serif;
  max-width:760px;margin:0 auto;background:var(--bg);color:var(--text);
  line-height:1.5;overflow-x:clip;-webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility;
  padding:16px;
  padding-top:max(16px, env(safe-area-inset-top));
  padding-left:max(16px, env(safe-area-inset-left));
  padding-right:max(16px, env(safe-area-inset-right));
  padding-bottom:max(24px, env(safe-area-inset-bottom));}
a{color:var(--primary);text-decoration:none;font-weight:600}
a:active{opacity:.6}
h1{font-size:21px;font-weight:800;margin:0;letter-spacing:-.03em;color:var(--text)}
h2{font-size:15px;font-weight:800;margin:0;letter-spacing:-.02em}
/* 코드/티커/타임스탬프 — 계기 모노 유틸 */
.code{font-size:11.5px;color:var(--text-3);font-weight:600;font-family:var(--font-mono);
  letter-spacing:.01em;font-variant-numeric:tabular-nums}
.meta{font-size:12px;color:var(--text-3);line-height:1.55}

/* 상단 뒤로가기 — iris 길찾기 */
.back{display:inline-flex;align-items:center;gap:4px;min-height:36px;
  font-size:14px;font-weight:700;color:var(--primary);margin-bottom:6px}

/* 카드/패널 — 계기 베이(플랫·크리스프 1px·타이트 반경) */
.panel,.card{background:var(--surface);border:1px solid var(--border);border-radius:var(--r-lg);
  padding:15px;margin:13px 0;box-shadow:var(--shadow)}
.panel>h2{display:flex;align-items:baseline;gap:6px;flex-wrap:wrap;margin:0 0 12px}

/* 신선도 캡션 — 제목 줄에서 분리(제목 아래 전폭 캡션). 모노 유틸 톤 */
.fresh{display:block;font-size:11px;font-weight:500;color:var(--text-3);
  margin:3px 0 12px;line-height:1.5;font-variant-numeric:tabular-nums}
.panel>h2 .fresh{flex-basis:100%;margin:4px 0 0}

/* 배지(상태) — 모노 대문자 유틸 태그 */
.badge{display:inline-flex;align-items:center;font-size:10.5px;font-weight:700;
  padding:3px 9px;border-radius:var(--r-sm);color:#fff;vertical-align:middle;
  letter-spacing:.02em;white-space:nowrap;line-height:1.4;
  font-family:var(--font-mono);text-transform:uppercase}
.b-live,.b-ok{background:var(--good)} .b-demo{background:var(--warn)}
.b-off{background:var(--flat)} .b-warn{background:var(--warn)} .b-info{background:var(--info)}
.b-buy{background:var(--primary)} .b-sell{background:var(--up)} .b-hold{background:var(--flat)}

/* 등락 색 — 한국식 상승=적/하락=청 */
.up{color:var(--up)} .down{color:var(--down)} .flat{color:var(--flat)}

/* 가격 헤드라인 — 계기 모노 리드아웃(시그니처) */
.price{font-family:var(--font-num);font-size:37px;font-weight:700;margin:10px 0 2px;
  letter-spacing:-.02em;font-variant-numeric:tabular-nums;font-feature-settings:"tnum" 1}
.price.up{color:var(--up)} .price.down{color:var(--down)} .price.flat{color:var(--text)}

/* 안내/경고 텍스트 */
.note{font-size:12.5px;color:var(--warn);margin-top:4px;min-height:0;font-weight:500}
.note:empty{display:none}

/* 스탯 타일(3열) — 계기: 값은 모노, 라벨은 대문자 유틸 */
.grid3{display:flex;gap:7px;text-align:center}
.grid3>div{flex:1;min-width:0;background:var(--surface-2);border:1px solid var(--border-2);
  border-radius:var(--r-sm);padding:10px 6px}
.grid3 .lbl{font-size:10px;color:var(--text-3);margin-bottom:4px;font-weight:600;
  letter-spacing:.02em}
.grid3 .val{font-family:var(--font-num);font-size:16px;font-weight:700;color:var(--text);
  font-variant-numeric:tabular-nums;letter-spacing:-.01em;word-break:keep-all}
.grid3 .val.up{color:var(--up)} .grid3 .val.down{color:var(--down)} .grid3 .val.flat{color:var(--flat)}

/* 시그널 콜아웃(판정) */
.sig{display:block;font-size:13px;font-weight:600;line-height:1.5;margin-top:10px;
  padding:9px 12px;border-radius:var(--r-sm);background:var(--surface-2);color:var(--text-2);
  border-left:3px solid var(--flat)}
.sig:empty{display:none;padding:0;margin:0;border:0}
.sig-good{background:var(--good-bg);color:var(--good);border-left-color:var(--good)}
.sig-warn{background:var(--warn-bg);color:var(--warn);border-left-color:var(--warn)}
.sig-info{background:var(--info-bg);color:var(--info);border-left-color:var(--info)}
.sig-flat{background:var(--surface-2);color:var(--text-2);border-left-color:var(--flat)}
.sig.up{background:var(--up-bg);color:var(--up);border-left-color:var(--up)}
.sig.down{background:var(--down-bg);color:var(--down);border-left-color:var(--down)}

/* 세그먼트/칩 버튼(타임프레임·세션 탭) — 44px 타겟. 활성=iris 길찾기 */
.tfrow{display:flex;gap:6px;margin-bottom:12px;flex-wrap:wrap}
.tf{flex:0 0 auto;min-height:44px;display:inline-flex;align-items:center;justify-content:center;
  font-size:13px;font-weight:700;padding:0 15px;border:1px solid var(--border);
  background:var(--surface);color:var(--text-2);border-radius:var(--r-sm);cursor:pointer;
  -webkit-tap-highlight-color:transparent;transition:background .12s,color .12s,border-color .12s}
.tf:active{background:var(--surface-2)}
.tf.on{background:var(--primary);color:#fff;border-color:var(--primary);
  box-shadow:var(--accent-glow)}

/* 테이블 — 계기: 헤더는 대문자 유틸, 숫자셀은 모노 */
table{width:100%;border-collapse:collapse;font-size:13px}
th{font-size:10px;color:var(--text-3);font-weight:700;text-align:right;padding:7px 6px;
  border-bottom:1px solid var(--border);white-space:nowrap;letter-spacing:.03em}
td{text-align:right;padding:8px 6px;border-bottom:1px solid var(--border-2);
  font-family:var(--font-num);font-variant-numeric:tabular-nums;color:var(--text);white-space:nowrap}
tr:last-child td{border-bottom:0}
th:first-child{text-align:left}
/* 첫 열(대개 종목명/날짜)은 한글이 섞이므로 sans 유지 */
td:first-child{text-align:left;font-family:inherit}
/* 넓은 표는 페이지가 아니라 표 내부에서 가로 스크롤 */
.tbl-wrap{overflow-x:auto;-webkit-overflow-scrolling:touch;margin:0 -2px;padding:0 2px}
.tbl-wrap::-webkit-scrollbar{height:0}

/* 접이식 패널 */
details.panel summary{cursor:pointer;list-style:none;-webkit-tap-highlight-color:transparent;
  min-height:36px;display:flex;align-items:center}
details.panel summary::-webkit-details-marker{display:none}
details.panel summary h2::before{content:'+';color:var(--primary);margin-right:7px;
  font-size:15px;font-weight:700;transition:transform .15s;font-family:var(--font-mono)}
details.panel[open] summary h2::before{content:'−'}
details.panel[open] summary{margin-bottom:10px}
details.panel summary h2{margin:0}
details.inline summary{cursor:pointer;color:var(--primary);font-size:12px;
  font-weight:700;padding:8px 0;min-height:40px;display:flex;align-items:center}
details.inline summary::-webkit-details-marker{display:none}

/* 투자 유의 디스클레이머 — 튜터 레지스터(따뜻·둥근) */
.disc{font-size:12px;line-height:1.6;color:var(--disc-tx);background:var(--disc-bg);
  border:1px solid var(--disc-bd);padding:13px 15px;border-radius:var(--r);
  margin-top:20px;margin-bottom:8px}
.disc b{color:var(--disc-tx)}

/* refresh button — iris 길찾기 */
.refresh{min-height:40px;font-size:13px;font-weight:700;padding:0 18px;
  border:0;background:var(--primary);color:#fff;border-radius:var(--r-sm);cursor:pointer;
  -webkit-tap-highlight-color:transparent;box-shadow:var(--accent-glow)}
.refresh:active{opacity:.85}

/* 포커스 링(키보드 접근성) — iris */
a:focus-visible,button:focus-visible,summary:focus-visible,input:focus-visible,
.tf:focus-visible{outline:2px solid var(--primary);outline-offset:2px;border-radius:8px}

/* 시그니처: 시장상태 펄스 닷 (장중=초록·야간/미국=iris·장종료=회색) */
.pulse{display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--flat);
  position:relative;flex:none}
.pulse.live{background:var(--good)} .pulse.night{background:var(--primary)} .pulse.closed{background:var(--flat)}
.pulse.live::after,.pulse.night::after{content:"";position:absolute;inset:0;border-radius:50%;
  background:inherit;animation:pulsering 1.8s ease-out infinite}
@keyframes pulsering{0%{transform:scale(1);opacity:.55}100%{transform:scale(2.6);opacity:0}}

/* 실시간/확정 상태 태그(초보용 구분) — 모노 유틸 */
.tag-live,.tag-fixed{display:inline-flex;align-items:center;gap:4px;font-size:11px;font-weight:800;
  border-radius:var(--r-pill);padding:2px 8px;vertical-align:middle;letter-spacing:0}
.tag-live{background:var(--good-bg);color:var(--good)}
.tag-fixed{background:var(--warn-bg);color:var(--warn)}
img,canvas{max-width:100%}
@media (prefers-reduced-motion:reduce){
  *{animation-duration:.001ms!important;animation-iteration-count:1!important;transition-duration:.001ms!important}
}
"""

# ── 차트 테마: CSS 토큰을 읽어 LightweightCharts 외관에 반영(스킴 전환 시 재적용) ──
# node 실행 하니스(window·getComputedStyle 없음)에서도 죽지 않게 전부 가드 —
# render() 스모크(test_live_page_js.py)가 이 스크립트를 그대로 eval 하기 때문.
CHART_THEME_JS = """
var __CHARTS=[];
function _cv(n){try{return getComputedStyle(document.documentElement).getPropertyValue(n).trim();}catch(e){return '';}}
function chartTheme(){return {
  layout:{background:{color:_cv('--surface')||'#fff'},textColor:_cv('--text-3')||'#999',fontSize:10},
  grid:{vertLines:{color:_cv('--grid')||'#f0f2f7'},horzLines:{color:_cv('--grid')||'#f0f2f7'}},
  rightPriceScale:{borderColor:_cv('--border')||'#e3e8f0'},
  timeScale:{borderColor:_cv('--border')||'#e3e8f0'}};}
function registerChart(c){try{__CHARTS.push(c);}catch(e){}}
function applyChartTheme(){try{__CHARTS.forEach(function(c){c.applyOptions(chartTheme());});}catch(e){}}
try{if(typeof window!=='undefined'&&window.matchMedia)
  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change',applyChartTheme);}catch(e){}
"""

# 페이지 전환 로딩 바 — 내부 링크 클릭/이탈 시 상단 진행 바(전 페이지 공용).
# bfcache 복귀(pageshow)에서 제거해 뒤로가기 잔상을 막는다.
NAV_LOADER = """<style>#navload{position:fixed;top:0;left:0;height:2px;width:0;
background:linear-gradient(90deg,var(--primary),#b3a4ff);z-index:9999;pointer-events:none;
transition:width .5s ease;border-radius:0 2px 2px 0}
#navload.on{width:85%}
#navload.done{width:100%;opacity:0;transition:width .15s,opacity .3s .15s}</style>
<script>(function(){
var bar=null,tmo=null;
function el(){if(!bar){bar=document.createElement('div');bar.id='navload';document.body.appendChild(bar);}return bar;}
function hide(){if(bar){bar.classList.remove('on');bar.classList.add('done');
  setTimeout(function(){if(bar){bar.remove();bar=null;}},500);}
  if(tmo){clearTimeout(tmo);tmo=null;}}
function show(){var b=el();b.classList.remove('done');void b.offsetWidth;b.classList.add('on');
  if(tmo)clearTimeout(tmo);
  tmo=setTimeout(hide,12000);} // 취소된 내비게이션에서 85% 고착 방지
document.addEventListener('click',function(e){
  // 새 탭/보조버튼/취소된 클릭은 현재 페이지가 안 떠나므로 바를 켜지 않는다
  if(e.defaultPrevented||e.button!==0||e.metaKey||e.ctrlKey||e.shiftKey||e.altKey)return;
  var t=e.target; while(t&&t.tagName!=='A')t=t.parentElement;
  if(!t||!t.getAttribute)return;
  var href=t.getAttribute('href')||'';
  if(!href||href[0]==='#'||t.target==='_blank'||t.hasAttribute('download'))return;
  if(/^(javascript:|mailto:|tel:)/i.test(href))return;
  if(t.origin&&t.origin!==location.origin)return;
  show();
},true);
// beforeunload 리스너는 bfcache를 무력화(Firefox 전면, Safari 일부)하므로 쓰지 않는다
window.addEventListener('pageshow',hide);
})();</script>"""

# ── 하단 고정 탭바(앱 골격) — 전 페이지 공용. 활성 탭은 pathname으로, '종목' 탭은
#    마지막 조회 종목(localStorage)로. 자기완결 <style>+<nav>+<script> 한 덩어리. ──
TABBAR = """<style>
body{padding-bottom:calc(60px + env(safe-area-inset-bottom))}
#tabbar{position:fixed;left:0;right:0;bottom:0;z-index:9998;display:flex;
  background:color-mix(in srgb, var(--surface) 90%, transparent);
  -webkit-backdrop-filter:saturate(160%) blur(12px);backdrop-filter:saturate(160%) blur(12px);
  border-top:1px solid var(--border);
  padding-bottom:env(safe-area-inset-bottom);box-shadow:0 -1px 0 var(--border-2)}
#tabbar a{position:relative;flex:1;display:flex;flex-direction:column;align-items:center;
  justify-content:center;gap:3px;min-height:54px;font-size:11px;font-weight:700;color:var(--text-3);
  text-decoration:none;-webkit-tap-highlight-color:transparent;transition:color .15s;letter-spacing:-.01em}
#tabbar a .ic{font-size:20px;line-height:1;transition:transform .15s}
#tabbar a.on{color:var(--primary)}
#tabbar a.on .ic{transform:translateY(-1px) scale(1.05)}
#tabbar a.on::before{content:"";position:absolute;top:0;left:50%;transform:translateX(-50%);
  width:22px;height:2px;border-radius:0 0 2px 2px;background:var(--primary);box-shadow:var(--accent-glow)}
#tabbar a:active{opacity:.6}
</style>
<nav id="tabbar">
  <a href="/" data-tab="home"><span class="ic">🏠</span>홈</a>
  <a href="/live/" id="tab-live" data-tab="live"><span class="ic">📈</span>종목</a>
  <a href="/scanner" data-tab="scan"><span class="ic">🔎</span>스캐너</a>
</nav>
<script>(function(){try{
  var p=location.pathname, m=p.match(/^\\/live\\/(\\d{6})/);
  if(m){try{localStorage.setItem('sm:lastCode',m[1]);}catch(e){}}
  var last='005930'; try{last=localStorage.getItem('sm:lastCode')||last;}catch(e){}
  var tl=document.getElementById('tab-live'); if(tl)tl.setAttribute('href','/live/'+last);
  var on=p==='/'?'home':(p.indexOf('/live/')===0?'live':(p.indexOf('/scanner')===0?'scan':''));
  var a=document.querySelectorAll('#tabbar a');
  for(var i=0;i<a.length;i++) if(a[i].getAttribute('data-tab')===on) a[i].classList.add('on');
}catch(e){}})();</script>"""

DISCLAIMER = (
    "⚠️ 투자 유의 안내 — 본 애플리케이션이 제공하는 모든 정보·분석·신호는 참고용이며, "
    "특정 종목의 매수·매도를 권유하지 않습니다. 모든 투자 판단과 그 결과에 대한 책임은 "
    "이용자 본인에게 있습니다. 과거 성과(백테스트)는 미래 수익을 보장하지 않습니다. "
    "데이터는 FDR·DART·KRX·언론사 등에서 수집되며 오류·지연이 있을 수 있습니다."
)
