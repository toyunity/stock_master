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
    '<meta name="theme-color" content="#f4f6fb" media="(prefers-color-scheme: light)">'
    '<meta name="theme-color" content="#0d1117" media="(prefers-color-scheme: dark)">'
    '<link rel="manifest" href="/manifest.json">'
    '<link rel="apple-touch-icon" href="/icons/icon-180.png">'
    '<meta name="apple-mobile-web-app-capable" content="yes">'
    '<meta name="mobile-web-app-capable" content="yes">'
    '<meta name="apple-mobile-web-app-status-bar-style" content="default">'
    '<meta name="apple-mobile-web-app-title" content="Stock Master">'
)

# ── 디자인 토큰 + 베이스 엘리먼트 + 공통 컴포넌트 ──
BASE_CSS = """
:root{
  --bg:#eef1f7; --surface:#ffffff; --surface-2:#f3f5fa; --surface-3:#eaeef5;
  --text:#131722; --text-2:#556072; --text-3:#8a94a6;
  --border:#e3e8f0; --border-2:#eef1f6; --grid:#f0f2f7;
  --primary:#1565c0; --primary-ink:#0d4a91;
  --up:#e0322c; --down:#1565c0; --flat:#8a94a6;
  --good:#1f9d57; --warn:#e08205; --info:#1565c0;
  --up-bg:#fdecec; --down-bg:#e9f1fb; --good-bg:#e7f6ee; --warn-bg:#fdf1e0; --info-bg:#e9f1fb;
  --shadow:0 1px 2px rgba(17,24,39,.04), 0 6px 20px rgba(17,24,39,.06);
  --shadow-sm:0 1px 2px rgba(17,24,39,.05);
  --r:12px; --r-lg:16px; --r-sm:9px; --r-pill:999px;
  --disc-bg:#fdf6e3; --disc-bd:#f2e2b8; --disc-tx:#7a6320;
}
@media (prefers-color-scheme: dark){
  :root{
    --bg:#0d1117; --surface:#161b22; --surface-2:#1b222c; --surface-3:#232c38;
    --text:#e7edf5; --text-2:#9aa6b6; --text-3:#6b7789;
    --border:#2a323d; --border-2:#20272f; --grid:#20262e;
    --primary:#4c9aff; --primary-ink:#8bbcff;
    --up:#ff5b52; --down:#4c9aff; --flat:#6b7789;
    --good:#3fb959; --warn:#e8992e; --info:#4c9aff;
    --up-bg:#2a1a1a; --down-bg:#141f2e; --good-bg:#14251b; --warn-bg:#2a2113; --info-bg:#141f2e;
    --shadow:0 1px 2px rgba(0,0,0,.4), 0 8px 24px rgba(0,0,0,.5);
    --shadow-sm:0 1px 2px rgba(0,0,0,.4);
    --disc-bg:#241f14; --disc-bd:#3a3320; --disc-tx:#d8c187;
  }
}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%;height:100%}
body{font-family:-apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo","Malgun Gothic",
  "Segoe UI",sans-serif;
  background:var(--bg);color:var(--text);line-height:1.5;
  margin:0;height:100%;overflow:hidden;}
/* ── 앱 셸: 화면을 채우는 flex 프레임 + 내부 스크롤. body는 스크롤하지 않아
      사파리 브라우저 하단 툴바가 접혔다 펴지지 않음 → 하단 탭바가 흔들리지 않는다. ── */
#app{position:fixed;top:0;left:0;right:0;
  height:100vh;height:-webkit-fill-available;height:100dvh;  /* dvh 미지원 엔진 폴백(탭바가 화면 밖으로 나가는 것 방지) */
  display:flex;flex-direction:column;background:var(--bg)}
#app-scroll{flex:1;min-height:0;overflow-y:auto;-webkit-overflow-scrolling:touch;
  overscroll-behavior:none;width:100%;max-width:760px;margin:0 auto;overflow-x:clip;
  padding:16px;
  padding-top:max(16px, env(safe-area-inset-top));
  padding-left:max(16px, env(safe-area-inset-left));
  padding-right:max(16px, env(safe-area-inset-right));
  padding-bottom:24px;}
a{color:var(--primary);text-decoration:none}
a:active{opacity:.6}
h1{font-size:20px;font-weight:800;margin:0;letter-spacing:-.01em}
h2{font-size:15px;font-weight:700;margin:0;letter-spacing:-.01em}
.code{font-size:12px;color:var(--text-3);font-weight:500}
.meta{font-size:12px;color:var(--text-3);line-height:1.55}

/* 상단 뒤로가기 */
.back{display:inline-flex;align-items:center;gap:4px;min-height:36px;
  font-size:14px;font-weight:600;color:var(--text-2);margin-bottom:6px}

/* 카드/패널 — 승격 */
.panel,.card{background:var(--surface);border:1px solid var(--border);border-radius:var(--r-lg);
  padding:16px;margin:14px 0;box-shadow:var(--shadow)}
.panel>h2{display:flex;align-items:baseline;gap:6px;flex-wrap:wrap;margin:0 0 12px}

/* 신선도 캡션 — 제목 줄에서 분리(제목 아래 전폭 캡션) */
.fresh{display:block;font-size:11.5px;font-weight:500;color:var(--text-3);
  margin:3px 0 12px;line-height:1.5}
.panel>h2 .fresh{flex-basis:100%;margin:4px 0 0}

/* 배지(상태) */
.badge{display:inline-flex;align-items:center;font-size:11px;font-weight:700;
  padding:3px 9px;border-radius:var(--r-pill);color:#fff;vertical-align:middle;
  letter-spacing:.01em;white-space:nowrap;line-height:1.4}
.b-live,.b-ok{background:var(--good)} .b-demo{background:var(--warn)}
.b-off{background:var(--flat)} .b-warn{background:var(--warn)} .b-info{background:var(--info)}
.b-buy{background:var(--primary)} .b-sell{background:var(--up)} .b-hold{background:var(--flat)}

/* 등락 색 — 한국식 상승=적/하락=청 */
.up{color:var(--up)} .down{color:var(--down)} .flat{color:var(--flat)}

/* 가격 헤드라인 */
.price{font-size:34px;font-weight:800;margin:10px 0 2px;letter-spacing:-.02em;
  font-variant-numeric:tabular-nums}
.price.up{color:var(--up)} .price.down{color:var(--down)} .price.flat{color:var(--text)}

/* 안내/경고 텍스트 */
.note{font-size:12.5px;color:var(--warn);margin-top:4px;min-height:0;font-weight:500}
.note:empty{display:none}

/* 스탯 타일(3열) */
.grid3{display:flex;gap:8px;text-align:center}
.grid3>div{flex:1;min-width:0;background:var(--surface-2);border:1px solid var(--border-2);
  border-radius:var(--r);padding:11px 6px}
.grid3 .lbl{font-size:11px;color:var(--text-3);margin-bottom:4px;font-weight:500}
.grid3 .val{font-size:16px;font-weight:800;color:var(--text);
  font-variant-numeric:tabular-nums;letter-spacing:-.01em;word-break:keep-all}
.grid3 .val.up{color:var(--up)} .grid3 .val.down{color:var(--down)} .grid3 .val.flat{color:var(--flat)}

/* 시그널 콜아웃(판정) */
.sig{display:block;font-size:13px;font-weight:600;line-height:1.5;margin-top:10px;
  padding:9px 12px;border-radius:var(--r);background:var(--surface-2);color:var(--text-2);
  border-left:3px solid var(--flat)}
.sig:empty{display:none;padding:0;margin:0;border:0}
.sig-good{background:var(--good-bg);color:var(--good);border-left-color:var(--good)}
.sig-warn{background:var(--warn-bg);color:var(--warn);border-left-color:var(--warn)}
.sig-info{background:var(--info-bg);color:var(--info);border-left-color:var(--info)}
.sig-flat{background:var(--surface-2);color:var(--text-2);border-left-color:var(--flat)}
.sig.up{background:var(--up-bg);color:var(--up);border-left-color:var(--up)}
.sig.down{background:var(--down-bg);color:var(--down);border-left-color:var(--down)}

/* 세그먼트/칩 버튼(타임프레임·세션 탭) — 44px 타겟 */
.tfrow{display:flex;gap:6px;margin-bottom:12px;flex-wrap:wrap}
.tf{flex:0 0 auto;min-height:44px;display:inline-flex;align-items:center;justify-content:center;
  font-size:13px;font-weight:600;padding:0 15px;border:1px solid var(--border);
  background:var(--surface);color:var(--text-2);border-radius:var(--r);cursor:pointer;
  -webkit-tap-highlight-color:transparent;transition:background .12s,color .12s,border-color .12s}
.tf:active{background:var(--surface-2)}
.tf.on{background:var(--primary);color:#fff;border-color:var(--primary);
  box-shadow:0 2px 8px rgba(21,101,192,.28)}

/* 테이블 */
table{width:100%;border-collapse:collapse;font-size:13px}
th{font-size:11px;color:var(--text-3);font-weight:600;text-align:right;padding:6px;
  border-bottom:1px solid var(--border);white-space:nowrap}
td{text-align:right;padding:8px 6px;border-bottom:1px solid var(--border-2);
  font-variant-numeric:tabular-nums;color:var(--text);white-space:nowrap}
tr:last-child td{border-bottom:0}
th:first-child,td:first-child{text-align:left}
/* 넓은 표는 페이지가 아니라 표 내부에서 가로 스크롤 */
.tbl-wrap{overflow-x:auto;-webkit-overflow-scrolling:touch;margin:0 -2px;padding:0 2px}
.tbl-wrap::-webkit-scrollbar{height:0}

/* 접이식 패널 */
details.panel summary{cursor:pointer;list-style:none;-webkit-tap-highlight-color:transparent;
  min-height:36px;display:flex;align-items:center}
details.panel summary::-webkit-details-marker{display:none}
details.panel summary h2::before{content:'▸';color:var(--primary);margin-right:6px;
  font-size:12px;transition:transform .15s}
details.panel[open] summary h2::before{content:'▾'}
details.panel[open] summary{margin-bottom:10px}
details.panel summary h2{margin:0}
details.inline summary{cursor:pointer;color:var(--primary);font-size:12px;
  font-weight:600;padding:8px 0;min-height:40px;display:flex;align-items:center}
details.inline summary::-webkit-details-marker{display:none}

/* 투자 유의 디스클레이머 */
.disc{font-size:12px;line-height:1.6;color:var(--disc-tx);background:var(--disc-bg);
  border:1px solid var(--disc-bd);padding:12px 14px;border-radius:var(--r);
  margin-top:20px;margin-bottom:8px}
.disc b{color:var(--disc-tx)}

/* refresh button */
.refresh{min-height:40px;font-size:13px;font-weight:600;padding:0 16px;
  border:0;background:var(--primary);color:#fff;border-radius:var(--r);cursor:pointer;
  -webkit-tap-highlight-color:transparent;box-shadow:0 2px 8px rgba(21,101,192,.25)}
.refresh:active{opacity:.85}

img,canvas{max-width:100%}
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
NAV_LOADER = """<style>#navload{position:fixed;top:0;left:0;height:3px;width:0;
background:linear-gradient(90deg,var(--primary),#7bb4ff);z-index:9999;pointer-events:none;
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
#tabbar{flex:0 0 auto;z-index:9998;display:flex;
  background:var(--surface);border-top:1px solid var(--border);
  padding-bottom:env(safe-area-inset-bottom);box-shadow:0 -2px 14px rgba(17,24,39,.06)}
#tabbar a{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;
  gap:2px;min-height:54px;font-size:11px;font-weight:600;color:var(--text-3);
  text-decoration:none;-webkit-tap-highlight-color:transparent}
#tabbar a .ic{font-size:21px;line-height:1}
#tabbar a.on{color:var(--primary)}
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
