from __future__ import annotations

"""미국 티커 상세 화면(/live/{티커}) — 자기완결 HTML. 설계 2026-08-06.

**live_page.py와 분리한 이유**: 국내 화면의 18패널 중 13개가 국내 전용 TR을 쓴다.
1,500줄짜리 live_page에 `if market=="US"`를 흩뿌리면 US 화면을 얻는 대신 국내 화면의
회귀 위험을 산다. 두 화면은 공유 CSS(dashboard._BASE_CSS)로 묶고 마크업만 가른다.

그리는 것: 히어로(가격·등락) · 일·주·월봉 차트(각 120봉, 이평·감시선 겹침) · 감시선 편집기.
주·월봉은 서버가 FDR 일봉 15년을 집계한 것(candles.aggregate_daily)이라 KIS 무관.
안 그리는 것: 수급·공매도·대차·신용·거래원·재무·호가·실시간체결(전부 국내 전용) ·
분봉 탭(KIS 국내 TR 전용).

**빈 섹션을 지우기만 하지 않는다** — 왜 없는지 한 줄로 적는다. 국내 화면과 나란히
비교당할 자리라 "왜 없지?"가 남으면 안 된다(ADR 패널·US 카드에서 내린 판단과 같다).

가격 표기: 달러 소수 2자리. 상승=빨강/하락=파랑(국내 관례 유지 — 미국식 반전 금지).
"""

import json
from html import escape

from backend.report.dashboard import (_BASE_CSS, _CHART_THEME_JS, _DISCLAIMER,
                                      _ICON_SPRITE, _LIB_PATH, _NAV_LOADER,
                                      _PWA_HEAD, _TABBAR)

_TEMPLATE = """<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>__SYM__ · 미국</title>
__PWA_HEAD__
<style>__BASE_CSS__</style>
<style>
#pchart{height:230px}
.chartwrap{position:relative}
.usbadge{font-size:11px;padding:2px 7px;border-radius:3px;border:1px solid var(--border-2);
  color:var(--text-2);margin-left:6px;vertical-align:middle}
.nomore{font-size:12.5px;color:var(--text-2);line-height:1.6;padding:14px 15px;
  border-top:1px solid var(--border-2);margin-top:4px}
.nomore b{color:var(--text-1)}
.ma-row{display:flex;gap:6px;flex-wrap:wrap;padding:8px 0 2px}
.ma-btn{font-size:12px;padding:4px 9px;border-radius:3px;border:1px solid var(--border-2);
  background:transparent;color:var(--text-2);cursor:pointer}
.ma-btn.on{border-color:var(--iris);color:var(--iris)}
.ma-btn:disabled{opacity:.35;cursor:default}
/* 봉주기 탭 — .ma-btn과 모양은 같지만 클래스를 분리한다: .ma-btn 셀렉터의
   활성화 토글·클릭 핸들러(data-ma 파싱)가 탭에 잘못 걸리면 안 된다 */
.tf-btn{font-size:12px;padding:4px 9px;border-radius:3px;border:1px solid var(--border-2);
  background:transparent;color:var(--text-2);cursor:pointer}
.tf-btn.on{border-color:var(--iris);color:var(--iris)}
</style>
__NAV_LOADER__
</head><body>
__ICONS__
<div id="app"><div id="app-scroll">

<div class="hero">
  <div class="htop"><a class="back" href="/" style="margin:0">← 목록</a>
    <span class="hname">__NAME__</span> <span class="code">__SYM__</span>
    <span class="badge b-live">미국</span>
    <span class="usbadge" id="pbasis">불러오는 중</span></div>
  <div class="price" id="price">–</div>
  <div class="chg flat" id="chg"></div>
  <div class="note" id="walert"></div>
</div>

<div class="meta" id="mylines"></div>

<details class="sec" open>
  <summary><svg class="hic secic"><use href="#i-chart"/></svg> 가격 차트
    <span class="seccap" id="tf-cap">일봉 120</span><span class="chev">▾</span></summary>
  <div class="sec-body">
    <div class="ma-row">
      <button class="tf-btn on" type="button" data-tf="1d">일봉</button>
      <button class="tf-btn" type="button" data-tf="1w">주봉</button>
      <button class="tf-btn" type="button" data-tf="1mo">월봉</button>
    </div>
    <div class="chartwrap"><div id="pchart"></div></div>
    <div class="ma-row" id="ma-row">
      <button class="ma-btn" type="button" data-ma="20">20일</button>
      <button class="ma-btn" type="button" data-ma="60">60일</button>
      <button class="ma-btn" type="button" data-ma="120">120일</button>
      <span class="wl-status" id="ma-hint"></span>
    </div>
  </div>
</details>

<details class="sec" id="wl-panel">
  <summary><svg class="hic secic"><use href="#i-target"/></svg> 감시선·알림
    <span class="seccap">가격 도달 알림</span><span class="chev">▾</span></summary>
  <div class="sec-body">
    <div class="meta" style="margin:2px 0 10px">차트에 표시할 수평선을 추가·편집합니다.
    라벨은 자유(절대선/손절 등) — <b>실제 주문이 아니라 표시·알림용</b>.
    차트를 탭해도 그 가격에 선이 추가됩니다. 저장하면 다른 기기에도 반영됩니다.</div>
    <div class="wl-preset">
      <button class="wl-chip" type="button" onclick="wlAddRow('감시선')">＋ 감시선</button>
      <button class="wl-chip" type="button" onclick="wlAddRow('손절')">＋ 손절</button>
    </div>
    <div id="wl-rows"></div>
    <div class="wl-actions">
      <button class="refresh" type="button" onclick="saveLines()">저장</button>
      <span class="wl-status" id="wl-status"></span>
    </div>
  </div>
</details>

<div class="nomore">이 화면에 없는 것: <b>수급·공매도·대차·신용·거래원·재무·호가·실시간 체결</b>은
<b>국내 종목에만</b> 있는 데이터입니다. 분봉도 국내 전용이라 일·주·월봉만 그립니다.</div>

<div class="disc">__DISCLAIMER__ 미국 시세는 일별 종가(FinanceDataReader) 기준이며,
미국 정규장 중에는 한국투자증권 해외시세로 갱신합니다. 표시 시각은 현지 거래일 기준.</div>

__TABBAR__
</div></div>
<script>__CHART_THEME_JS__</script>
<script>__LIB__</script>
<script>
const SYM='__SYM__';
let WATCH=__WATCH__;   // 감시선 [{price,label}] — /api/watch에서 주입, 편집 시 가변
// 달러 표기 — 국내(원 정수)와 달리 센트가 살아야 한다. 감시선 저장도 소수를 보존한다.
const usd=n=>n==null?'–':'$'+Number(n).toLocaleString('en-US',
  {minimumFractionDigits:2,maximumFractionDigits:2});
const esc=s=>String(s==null?'':s).replace(/[&<>"']/g,
  c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

// ── 차트 ──────────────────────────────────────────────────────
const _pt=chartTheme();
const pchart=LightweightCharts.createChart(document.getElementById('pchart'),
  {autoSize:true,height:230,layout:_pt.layout,grid:_pt.grid,rightPriceScale:_pt.rightPriceScale,
   timeScale:{borderVisible:false},crosshair:{mode:0}});
if(typeof registerChart==='function')registerChart(pchart);
// 상승=빨강·하락=파랑 — 국내 관례를 미국 종목에도 그대로 쓴다(앱 안에서 색이 뒤집히면 안 된다)
const pseries=pchart.addCandlestickSeries({upColor:'#e5342f',downColor:'#1f66e0',
  borderUpColor:'#e5342f',borderDownColor:'#1f66e0',
  wickUpColor:'#e5342f',wickDownColor:'#1f66e0',
  priceFormat:{type:'price',precision:2,minMove:0.01}});
const MA_COLORS={20:'#f0a020',60:'#6a4ff0',120:'#8a8f9a'};
let maSeries={}, maOn={20:false,60:false,120:false};
[20,60,120].forEach(function(n){
  if(pchart.addLineSeries)maSeries[n]=pchart.addLineSeries(
    {color:MA_COLORS[n],lineWidth:1.5,priceLineVisible:false,lastValueVisible:false});
});

let priceLines=[];
function renderWatchLines(){
  priceLines.forEach(function(l){try{pseries.removePriceLine(l);}catch(e){}});
  priceLines=WATCH.map(function(w){
    try{return pseries.createPriceLine({price:w.price,color:'#8a8f9a',lineWidth:1,
      lineStyle:2,axisLabelVisible:true,title:w.label});}catch(e){return null;}
  }).filter(Boolean);
}

let TF='1d', tfSeq=0;
const TF_CAP={'1d':'일봉 120','1w':'주봉 120','1mo':'월봉 120'};
const TF_UNIT={'1d':'일','1w':'주','1mo':'개월'};
async function loadCandles(){
  const seq=++tfSeq, tf=TF;  // 탭 연타 경합 방지 — 마지막 요청만 반영(국내 화면과 동일)
  try{
    const r=await fetch('/api/candles/'+SYM+'?tf='+tf); if(!r.ok)throw 0;
    const d=await r.json(); if(seq!==tfSeq)return;
    const cs=(d&&d.candles)||[];
    if(!cs.length)throw 0;
    pseries.setData(cs.map(c=>({time:c.t,open:c.open,high:c.high,low:c.low,close:c.close})));
    // 이평선 — 표본이 없으면(신규 상장 등) 버튼을 비활성으로 두고 이유를 적는다.
    // SKHY처럼 거래일이 얼마 없는 종목은 20/60/120이 전부 빈다. 꾸며내지 않는다.
    const na=[];
    [20,60,120].forEach(function(n){
      const key='ma'+n, has=cs.some(c=>c[key]!=null);
      if(maSeries[n])maSeries[n].setData(has&&maOn[n]
        ?cs.filter(c=>c[key]!=null).map(c=>({time:c.t,value:c[key]})):[]);
      if(!has)na.push(n);
    });
    document.querySelectorAll('.ma-btn').forEach(function(b){
      const n=b.getAttribute('data-ma'), ok=na.indexOf(+n)<0;
      b.disabled=!ok; if(!ok)b.classList.remove('on');
      b.textContent=n+TF_UNIT[tf];   // 20일 ↔ 20주 ↔ 20개월 — 주봉에서 '20일'은 거짓말이다
    });
    const hint=document.getElementById('ma-hint');
    if(hint)hint.textContent=na.length
      ?(na.join('/')+TF_UNIT[tf]+'선은 '+(tf==='1d'?'거래일':'봉')+'이 모자라 아직 안 그려집니다')
      :'이동평균 켜고 끄기';
    renderWatchLines();
    try{pchart.timeScale().fitContent();}catch(e){}
    // 가격은 차트와 같은 데이터에서 뽑는다 — 따로 조회하면 둘이 어긋난다.
    // 등락 기준은 일봉의 전일 종가 하나로 고정 — 주·월봉 탭에서 직전 봉 대비로
    // 계산하면 히어로의 %가 탭에 따라 달라져 보인다.
    if(tf==='1d'){
      const last=cs[cs.length-1], prev=cs.length>1?cs[cs.length-2]:null;
      setPrice(last.close, prev?prev.close:null, '종가 · '+(last.t||''));
    }
    startPoll();
  }catch(e){
    document.getElementById('pbasis').textContent='가격 이력을 못 불러왔어요';
  }
}

function setPrice(price, base, basis){
  document.getElementById('price').textContent=usd(price);
  const el=document.getElementById('chg');
  if(base){
    const p=(price-base)/base*100;
    el.textContent=(p>=0?'+':'')+p.toFixed(2)+'%';
    el.className='chg '+(p>0?'up':(p<0?'down':'flat'));
  }else{el.textContent='';el.className='chg flat';}
  document.getElementById('pbasis').textContent=basis;
  checkWatch(price);
}

// 미국 정규장 중에만 서버가 실시간 시세를 준다(장외엔 204) — 60초 폴링.
// 웹소켓은 쓰지 않는다: 1키1세션을 국내 수급·야간선물과 나눠 쓰지 않기로 했다(설계 §4).
// startPoll 가드: loadCandles가 성공할 때마다(이평 토글·탭 전환 포함) 호출되므로
// 그대로 pollLive를 부르면 setTimeout 사슬이 겹겹이 쌓인다.
let _polling=false;
function startPoll(){if(_polling)return; _polling=true; pollLive();}
async function pollLive(){
  try{
    const r=await fetch('/api/usprice/'+SYM);
    if(r.status===200){const q=await r.json();
      if(q&&q.price){
        const el=document.getElementById('chg');
        document.getElementById('price').textContent=usd(q.price);
        if(q.change!=null){el.textContent=(q.change>=0?'+':'')+Number(q.change).toFixed(2)+'%';
          el.className='chg '+(q.change>0?'up':(q.change<0?'down':'flat'));}
        document.getElementById('pbasis').textContent='정규장 · 60초 갱신';
        checkWatch(q.price);
      }}
  }catch(e){}
  setTimeout(pollLive,60000);
}

// ── 감시선 알림 ────────────────────────────────────────────────
let armed=WATCH.map(()=>true), lastWatchPrice=null;
function rearm(){armed=WATCH.map(()=>true);}
function checkWatch(price){
  if(price==null)return;
  WATCH.forEach(function(w,i){
    const dist=Math.abs(price-w.price)/w.price;
    const crossed=lastWatchPrice!=null&&(lastWatchPrice-w.price)*(price-w.price)<0;
    if(dist<=0.005||crossed){
      if(armed[i]){armed[i]=false;
        document.getElementById('walert').textContent='🔔 '+w.label+' '+usd(w.price)+' 접근';}
    }else if(dist>0.007){armed[i]=true;}
  });
  lastWatchPrice=price;
}

// ── 감시선 편집기 — 국내 화면과 같은 /api/watch를 쓴다 ──────────
let wlDraft=WATCH.map(w=>({price:w.price,label:w.label}));
function renderMyLines(){
  const el=document.getElementById('mylines'); if(!el)return;
  let h=WATCH.map(w=>'<span class="myline"><span class="dot"></span>'
    +esc(w.label)+' '+usd(w.price)+'</span>').join('');
  h+='<span class="myline add" onclick="openWlEditor()">＋ 라인 추가</span>';
  el.innerHTML=h;
}
function openWlEditor(){const d=document.getElementById('wl-panel'); if(d)d.open=true;}
function wlStatus(t){const s=document.getElementById('wl-status'); if(s)s.textContent=t;}
function renderWlDraft(){
  const el=document.getElementById('wl-rows'); if(!el)return;
  el.innerHTML=wlDraft.map((w,i)=>'<div class="wl-row">'
    +'<input class="wl-label" data-i="'+i+'" data-k="label" type="text" maxlength="20" placeholder="라벨(예: 손절)" value="'+esc(w.label)+'">'
    // step=0.01 — 국내와 달리 센트 단위를 받아야 한다(정수로 받으면 $153.16을 못 넣는다)
    +'<input class="wl-price" data-i="'+i+'" data-k="price" type="number" step="0.01" inputmode="decimal" placeholder="가격($)" value="'+(w.price===''||w.price==null?'':w.price)+'">'
    +'<button class="wl-del" type="button" data-del="'+i+'">✕</button></div>').join('');
  if(!el.querySelectorAll)return;
  // 인라인 oninput은 최상위 let 바인딩을 못 찾을 수 있다 — addEventListener로 확실히 건다
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
    // 국내는 Math.round로 원 단위를 맞추지만 여기선 반올림하지 않는다 — 서버가 센트로 정규화한다
    if(!(p>0)||!l)continue; lines.push({price:p,label:l});}
  wlStatus('저장 중…');
  fetch('/api/watch/'+SYM,{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({lines:lines})})
    .then(r=>r.json().then(d=>({ok:r.ok,d:d})))
    .then(res=>{
      if(res.ok){WATCH=res.d.lines; wlDraft=WATCH.map(w=>({price:w.price,label:w.label}));
        renderWatchLines(); rearm(); renderWlDraft(); renderMyLines();
        wlStatus('저장됨 ✓ ('+WATCH.length+'개 · 기기 간 반영)');}
      else{wlStatus((res.d&&res.d.error)||'저장 실패');}
    }).catch(()=>wlStatus('저장 실패 — 네트워크 확인 후 재시도'));
}
try{if(pchart&&pchart.subscribeClick)pchart.subscribeClick(function(param){
  try{if(param&&param.point){const price=pseries.coordinateToPrice(param.point.y);
    if(price!=null&&price>0){wlDraft.push({price:Math.round(price*100)/100,label:'감시선'});
      renderWlDraft(); openWlEditor(); wlStatus('차트에서 고른 가격 추가됨 — 라벨 확인 후 저장');}}}catch(e){}
});}catch(e){}

document.querySelectorAll('.ma-btn').forEach(function(b){
  b.addEventListener('click',function(){
    const n=+b.getAttribute('data-ma');
    maOn[n]=!maOn[n]; b.classList.toggle('on',maOn[n]); loadCandles();
  });
});
document.querySelectorAll('.tf-btn').forEach(function(b){
  b.addEventListener('click',function(){
    document.querySelectorAll('.tf-btn').forEach(x=>x.classList.remove('on'));
    b.classList.add('on'); TF=b.getAttribute('data-tf');
    const cap=document.getElementById('tf-cap'); if(cap)cap.textContent=TF_CAP[TF];
    loadCandles();
  });
});

renderMyLines(); renderWlDraft(); loadCandles();
</script>
</body></html>
"""


def render_us_page(sym: str, name: str, email=None) -> str:
    """US 티커 상세 화면 HTML. `email`은 계정별 감시선 조회용(None=마스터)."""
    from backend.flow import userstore
    lib = _LIB_PATH.read_text(encoding="utf-8")
    watch = userstore.get_lines(email or userstore.default_account(), sym)
    # </script> 이스케이프 — 라벨에 '</'가 들어오면 스크립트 블록이 조기 종료돼
    # 페이지 JS 전체가 죽는다(live_page에서 같은 이유로 이미 한 처리).
    watch_js = json.dumps(watch, ensure_ascii=False).replace("</", "<\\/")
    return (_TEMPLATE
            .replace("__BASE_CSS__", _BASE_CSS)
            .replace("__ICONS__", _ICON_SPRITE)
            .replace("__CHART_THEME_JS__", _CHART_THEME_JS)
            .replace("__WATCH__", watch_js)
            .replace("__TABBAR__", _TABBAR)
            .replace("__NAV_LOADER__", _NAV_LOADER)
            .replace("__PWA_HEAD__", _PWA_HEAD)
            .replace("__DISCLAIMER__", escape(_DISCLAIMER))
            .replace("__NAME__", escape(name))
            .replace("__SYM__", escape(sym))
            .replace("__LIB__", lib))
