from __future__ import annotations

"""자기완결(self-contained) 인터랙티브 대시보드 HTML 생성.

한 파일 안에 모든 것을 담는다: 차트 라이브러리(Lightweight Charts) inline,
데이터(신호·뉴스·공시·캔들·검색 유니버스) JSON inline, 렌더 JS inline.
→ 외부 네트워크 0. 같은 파일을 FastAPI가 서빙하고 Claude 아티팩트로도 그대로 본다.

데이터는 스냅샷(생성 시점). '라이브'는 인터랙티브(차트 줌·검색)이며, 최신화는 재생성.
검색은 베이크된 유니버스 '조회'용 — 신규 종목의 분석/차트는 서버에서만 가능(자기완결 한계).
"""

import json
from html import escape
from pathlib import Path

from backend.report.render import _ACTION_KO, _bt_view, _issues_view

_LIB_PATH = Path(__file__).parent.parent / "api" / "static" / "lightweight-charts.js"

# 공유 디자인 시스템(theme.py)에서 재노출 — live_page/scanner_page가 이 이름들을 import.
from backend.report.theme import (  # noqa: E402
    BASE_CSS as _BASE_CSS,
    CHART_THEME_JS as _CHART_THEME_JS,
    DISCLAIMER as _DISCLAIMER,
    NAV_LOADER as _NAV_LOADER,
    PWA_HEAD as _PWA_HEAD,
    TABBAR as _TABBAR,
)

_TEMPLATE = """<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Stock Master 대시보드 __DATE__</title>
__PWA_HEAD__
<style>
__BASE_CSS__
/* ── 대시보드 고유 ── */
h1{display:flex;align-items:baseline;gap:8px;flex-wrap:wrap}
h1 small{font-size:13px;color:var(--text-3);font-weight:600}
.sub{color:var(--text-2);font-size:12.5px;margin:2px 0 14px;line-height:1.6}
.refresh{margin-bottom:10px}
.search{background:var(--surface);border:1px solid var(--border);border-radius:var(--r-lg);
  padding:14px;margin:12px 0;box-shadow:var(--shadow)}
.search input{width:100%;font-size:16px;padding:12px 14px;border:1px solid var(--border);
  border-radius:var(--r);box-sizing:border-box;background:var(--surface-2);color:var(--text)}
.search input::placeholder{color:var(--text-3)}
.srow{padding:11px 4px;border-bottom:1px solid var(--border-2);font-size:14px;
  display:flex;justify-content:space-between;gap:8px;align-items:center}
.srow:last-child{border-bottom:0}
.spx{font-size:12px;color:var(--text-2);white-space:nowrap;font-variant-numeric:tabular-nums}
.card{position:relative;overflow:hidden}
.card.buy{border-left:4px solid var(--primary)}
.card.sell{border-left:4px solid var(--up)}
.card.hold{border-left:4px solid var(--flat)}
.name{font-size:17px;font-weight:800;color:var(--text);text-decoration:none;letter-spacing:-.01em}
a.name:active{opacity:.6}
.conf{font-size:13px;color:var(--text-2);margin-top:6px}
.chg{font-weight:700;font-variant-numeric:tabular-nums} .chg.up{color:var(--up)} .chg.down{color:var(--down)}
.chart{height:180px;margin:10px 0}
ul{margin:8px 0 0 0;padding-left:18px} li{font-size:14px;margin:3px 0;color:var(--text)}
.bt{font-size:12px;color:var(--primary-ink);margin-top:8px;background:var(--info-bg);
  padding:8px 10px;border-radius:var(--r-sm);font-weight:500}
.issues{margin-top:10px;border-top:1px dashed var(--border);padding-top:10px}
.issues-label{font-size:12px;color:var(--text-3)} .issues h4{font-size:13px;margin:10px 0 2px;color:var(--text-2)}
.issues ul{margin:2px 0 0 0} .issues li{font-size:13px;margin:3px 0} .issues a{color:var(--primary)}
.issues .meta{font-size:11px}
.semigrid{display:grid;grid-template-columns:repeat(3,1fr);gap:7px;margin-top:10px}
.scard{background:var(--surface-2);border:1px solid var(--border-2);border-radius:var(--r);
  padding:10px 6px;text-align:center;min-width:0}
.scard .nm{font-size:11px;color:var(--text-3);white-space:nowrap;overflow:hidden;
  text-overflow:ellipsis;margin-bottom:3px}
.scard .px{font-size:14px;font-weight:800;color:var(--text);font-variant-numeric:tabular-nums}
.scard .rt{font-size:12px;font-weight:700}
.rt.up{color:var(--up)}.rt.down{color:var(--down)}.rt.flat{color:var(--flat)}
#semi>b{font-size:14px}
button.wadd{border:1px solid var(--border);background:var(--surface-2);
  color:var(--text-2);border-radius:var(--r-pill);font-size:12px;padding:2px 10px;
  min-height:28px;cursor:pointer;vertical-align:middle}
/* ── 관심종목 관리 리스트(순서 ▲▼·삭제 ×·보유) — 버튼 폴백은 드래그와 독립적으로 항상 동작 ── */
.manage{background:var(--surface);border:1px solid var(--border);border-radius:var(--r-lg);
  box-shadow:var(--shadow);margin:12px 0;overflow:hidden}
.manage:empty{display:none}
.mtitle{font-size:12.5px;color:var(--text-2);font-weight:700;padding:11px 14px 7px}
.mtitle .meta{font-weight:500}
.mrow{display:flex;align-items:center;gap:8px;padding:9px 12px;border-top:1px solid var(--border-2);
  flex-wrap:wrap;touch-action:pan-y;transition:background .12s}
.mrow.mdrag{opacity:.65;background:var(--surface-2)}
.mhandle{color:var(--text-3);font-size:17px;cursor:grab;touch-action:none;padding:0 2px;
  user-select:none;-webkit-user-select:none}
.mname{flex:1;min-width:0;font-size:14px;font-weight:600;color:var(--text);
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.mtag{font-size:10px;font-weight:700;color:var(--text-3);border:1px solid var(--border);
  border-radius:var(--r-sm);padding:0 4px;vertical-align:middle}
.mpx{font-size:12px;color:var(--text-2);white-space:nowrap;font-variant-numeric:tabular-nums}
.mctl{display:flex;gap:4px}
.mctl button{border:1px solid var(--border);background:var(--surface-2);color:var(--text-2);
  border-radius:var(--r-sm);font-size:13px;min-width:30px;min-height:30px;padding:0;cursor:pointer}
.mctl .mdel{color:var(--up)}
.mctl .mhold{min-width:auto;padding:0 8px;font-size:11px}
.mhe{flex-basis:100%;display:flex;gap:6px;align-items:center;padding-top:8px}
.mhe input{flex:1;min-width:0;font-size:15px;padding:8px 10px;border:1px solid var(--border);
  border-radius:var(--r-sm);box-sizing:border-box;background:var(--surface-2);color:var(--text)}
.mhe button{border:0;background:var(--primary);color:#fff;border-radius:var(--r-sm);
  font-size:13px;padding:0 12px;min-height:36px;cursor:pointer}
</style></head><body>
<div id="app"><div id="app-scroll">
<h1>📊 Stock Master <small>__DATE__</small></h1>
<div class="sub">관심종목 분석 · 뉴스/공시 · 차트 — 모든 정보는 참고용(매매 권유 아님)
 · <a href="/scanner">🔍 수급 스캐너</a></div>
__REFRESH__
<div class="card" id="semi" style="display:none">
  <b>🔬 반도체 동향 (메모리 중심)</b> <span class="meta" id="semi-fresh"></span>
  <div class="conf" id="semi-flow"></div>
  <div class="semigrid" id="semi-us"></div>
  <div class="semigrid" id="semi-kr" style="margin-top:6px"></div>
  <div class="meta" style="margin-top:6px">미국: KIS 해외시세(계정에 따라 15분 지연) ·
  국내: KIS 실시간 · 카드 '–'는 조회 실패(자동 재시도) · 60초 자동 갱신</div>
</div>
<div class="manage" id="manage"></div>
<div class="search">
  <input id="q" placeholder="🔎 종목 검색 (이름/코드, 예: 하이닉스) — 조회용">
  <div id="results"></div>
</div>
<div id="cards"></div>
<div class="disc">__DISCLAIMER__</div>
<script>__LIB__</script>
<script>
__CHART_THEME_JS__
const D = __DATA__;
const won = n => n==null ? '–' : Math.round(n).toLocaleString('ko-KR')+'원';
const esc = s => (s==null?'':String(s)).replace(/[&<>"]/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[m]));
const stars = n => '★'.repeat(n)+'☆'.repeat(5-n);
function chg(c){
  if(c==null) return '';
  const cls = c>0?'up':(c<0?'down':'');
  const arrow = c>0?'▲':(c<0?'▼':'–');
  return '<span class="chg '+cls+'">'+arrow+' '+Math.abs(c).toFixed(2)+'%</span>';
}
function issuesHtml(s){
  const hasD=s.disclosures&&s.disclosures.length, hasN=s.news&&s.news.length;
  if(!hasD&&!hasN) return '';
  let h='<div class="issues"><div class="issues-label">📌 관련 이슈 (참고 정보 · 자동 수집 · 매매 권유 아님)</div>';
  if(hasD){ h+='<h4>공시 <span class="meta">(출처: DART·금융감독원)</span></h4><ul>';
    s.disclosures.forEach(d=>h+='<li><a href="'+esc(d.link)+'" target="_blank" rel="noopener">'+esc(d.report_name)+'</a> <span class="meta">'+esc(d.date)+'</span></li>');
    h+='</ul>'; }
  if(hasN){ h+='<h4>뉴스</h4><ul>';
    s.news.forEach(n=>h+='<li><a href="'+esc(n.link)+'" target="_blank" rel="noopener">'+esc(n.title)+'</a> <span class="meta">'+esc(n.source)+(n.published?' · '+esc(n.published):'')+'</span></li>');
    h+='</ul>'; }
  return h+'</div>';
}
function cardHtml(s){
  let h='<div class="card '+esc(s.action)+'">';
  h+='<span class="badge b-'+esc(s.action)+'">'+esc(s.action_ko)+'</span> ';
  h+='<a class="name" href="/live/'+esc(s.code)+'">'+esc(s.name)+' 📡</a> <span class="code">'+esc(s.code)+'</span>';
  if(s.close!=null) h+=' · <span class="cpx" data-code="'+esc(s.code)+'"><b>'+won(s.close)+'</b> '+chg(s.change)+'</span>';
  h+='<div class="conf">신뢰도 '+stars(s.confidence)+(s.advice?' <span class="badge b-buy">검증됨</span>':'')+'</div>';
  h+='<ul>'+s.reasons.map(r=>'<li>'+esc(r)+'</li>').join('')+'</ul>';
  if(s.backtest) h+='<div class="bt">📈 백테스트 — 승률 '+esc(s.backtest.win_rate)+'% · '+esc(s.backtest.trades)+'거래 · 손익비 '+esc(s.backtest.payoff)+' · MDD '+esc(s.backtest.mdd)+'%</div>';
  if(s.candles&&s.candles.length) h+='<div class="chart" id="chart-'+esc(s.code)+'"></div>';
  h+=issuesHtml(s);
  return h+'</div>';
}
document.getElementById('cards').innerHTML = D.stocks.map(cardHtml).join('');
D.stocks.forEach(s=>{
  if(!s.candles||!s.candles.length) return;
  const el=document.getElementById('chart-'+s.code); if(!el) return;
  const _t=chartTheme();
  const chart=LightweightCharts.createChart(el,{autoSize:true,height:180,
    layout:_t.layout,grid:_t.grid,
    rightPriceScale:{borderColor:_t.rightPriceScale.borderColor},
    timeScale:{borderColor:_t.timeScale.borderColor}});
  registerChart(chart);
  const series=chart.addCandlestickSeries({upColor:'#c62828',downColor:'#1565c0',
    borderVisible:false,wickUpColor:'#c62828',wickDownColor:'#1565c0'});
  series.setData(s.candles); chart.timeScale().fitContent();
});
const q=document.getElementById('q'), res=document.getElementById('results');
const US_TICKER=/^[A-Z]{1,5}(\.[A-Z])?$/;   // 미국 티커(대문자 1~5자 +.접미) 감지
function usSuggestHtml(sym){
  // KRX universe엔 없는 대문자 입력 = 미국 티커 후보 — 담기 시 서버가 price_us로 존재확인(없으면 400)
  return '<div class="srow"><span>'+esc(sym)+' <span class="code">US</span>'
    +' <button class="wadd" data-sym="'+esc(sym)+'" onclick="addUS(this.dataset.sym)">＋담기(US)</button>'
    +'</span><span class="spx meta">미국 티커</span></div>';
}
function searchRender(items,usHint){
  usHint=usHint||'';
  if(!items.length&&!usHint){res.innerHTML='<div class="meta" style="padding:8px">검색 결과 없음</div>';return;}
  res.innerHTML=usHint+items.slice(0,30).map(u=>'<div class="srow"><span><a href="/live/'+esc(u.code)+'">'+esc(u.name)+' 📡</a> <span class="code">'+esc(u.code)+'</span>'
    +(!inWatch(u.code)?' <button class="wadd" data-code="'+esc(u.code)+'" onclick="addStock(this.dataset.code)">＋담기</button>':'')
    +'</span><span class="spx">'+(u.close!=null?won(u.close)+' ':'')+chg(u.change)+'</span></div>').join('');
}
q.oninput=()=>{
  const raw=q.value.trim().toUpperCase();
  const t=q.value.trim().toLowerCase();
  if(!t){res.innerHTML='';return;}
  const hits=D.universe.filter(u=>u.name.toLowerCase().includes(t)||u.code.indexOf(t)>=0);
  searchRender(hits, US_TICKER.test(raw)?usSuggestHtml(raw):'');
};
// ── 반도체 동향(메모리 중심): /api/semi 60초 폴링 — 서버 서빙일 때만 뜨고,
//    아티팩트(정적 파일)에서는 fetch 실패로 자동 숨김(자기완결 유지) ──
function semiStale(){
  // 실패 시 이전 값을 최신인 척 두지 않는다(리뷰 확정) — 라벨로 명시
  const el=document.getElementById('semi');
  if(el&&el.style.display!=='none')
    document.getElementById('semi-fresh').textContent='· ⚠ 갱신 실패 — 마지막 값 표시 중(자동 재시도)';
}
async function loadSemi(){
  try{
    const r=await fetch('/api/semi'); if(!r.ok){semiStale();return;}
    const d=await r.json();
    document.getElementById('semi').style.display='';
    const rt=q=>q.rate==null?'<div class="rt flat">'+(q.stale?'전일 종가':'–')+'</div>'
      :'<div class="rt '+(q.rate>0?'up':(q.rate<0?'down':'flat'))+'">'
      +(q.rate>0?'▲':(q.rate<0?'▼':''))+Math.abs(q.rate).toFixed(2)+'%</div>';
    document.getElementById('semi-us').innerHTML=d.us.map(u=>'<div class="scard"><div class="nm">'
      +esc(u.sym)+' · '+esc(u.name||'')+'</div><div class="px">'
      +(u.ok?(u.sym==='SOX'?u.last.toFixed(1):'$'+u.last.toFixed(2)):'–')+'</div>'
      +(u.ok?rt(u):'<div class="rt flat">–</div>')+'</div>').join('');
    document.getElementById('semi-kr').innerHTML=d.kr.map(k=>'<div class="scard"><div class="nm">'
      +esc(k.name)+'</div><div class="px">'+(k.ok?won(k.price):'–')+'</div>'
      +(k.ok?rt(k):'<div class="rt flat">–</div>')+'</div>').join('');
    const g=s=>{const x=d.us.find(u=>u.sym===s);return x&&x.ok?x:null;};
    const hx=d.kr.find(k=>k.code==='000660');
    const f=x=>x&&x.rate!=null?((x.rate>0?'+':'')+x.rate.toFixed(2)+'%'):'–';
    // 미국 장중엔 '간밤→오늘' 인과가 성립하지 않는다(리뷰 확정) — 프레이밍 분기
    document.getElementById('semi-flow').textContent=d.us_open
      ?('미국 진행 중: SOX '+f(g('SOX'))+' · MU '+f(g('MU'))+' — 내일 국내 반응 주목 (오늘 하이닉스 마감 '+f(hx&&hx.ok?hx:null)+')')
      :('간밤 SOX '+f(g('SOX'))+' · MU '+f(g('MU'))+' → 오늘 하이닉스 '+f(hx&&hx.ok?hx:null));
    document.getElementById('semi-fresh').textContent='· 기준 '+esc(d.asof)+' (KST)'
      +(d.us_open?' · 미국 장중(지연 가능)':' · 미국 장마감 — 전일 종가 기준');
  }catch(e){semiStale();}
}
loadSemi(); setInterval(loadSemi,60000);
// 관심종목 카드 현재가 실시간 갱신 — /api/prices 12초 폴링(장중만 서버가 값 반환).
async function loadPrices(){
  try{
    const r=await fetch('/api/prices'); if(!r.ok)return;
    const d=await r.json(); if(!d||!d.open||!d.prices)return;
    for(const code in d.prices){
      const p=d.prices[code]; if(!p||p.close==null)continue;
      document.querySelectorAll('.cpx[data-code="'+code+'"]').forEach(function(el){
        el.innerHTML='<b>'+won(p.close)+'</b> '+chg(p.change);
      });
    }
  }catch(e){}
}
loadPrices(); setInterval(loadPrices, 12000);
// ── 관심종목 편집(v2 2026-07-17): items 계약({items:[{code,market,shares,avg}]}) 전체 교체 POST.
//    순서·삭제·보유는 아래 관리 리스트(별도 <script>)가 담당. 여기엔 공유 유틸 + 검색 담기만. ──
const WATCH = D.stocks.map(s=>s.code);   // 검색 담기 버튼 표시용(KR 카드 코드)
let ITEMS = [];                          // 관리 리스트 authoritative items(KR+US) — /api/watchlist에서 로드
function inWatch(code){ return ITEMS.some(i=>i.code===code) || WATCH.indexOf(code)>=0; }
function cleanItem(i){ return {code:i.code, market:i.market, shares:i.shares, avg:i.avg}; }
function cleanItems(items){ return items.map(cleanItem); }
async function _freshItems(){
  // 담기 직전 서버에서 현재 items를 다시 읽는다 — 비동기 로드 완료 전 담기해도 기존 보유가 날아가지 않게(경합 방지).
  const r = await fetch('/api/watchlist');
  if(!r.ok) throw new Error('load');
  return (await r.json()).items || [];
}
async function saveItems(items){
  try{
    const r=await fetch('/api/watchlist',{method:'POST',
      headers:{'Content-Type':'application/json'},body:JSON.stringify({items})});
    const d=await r.json();
    if(!r.ok){alert(d.error||'저장 실패');return;}
    location.reload();
  }catch(e){alert('저장 실패 — 네트워크를 확인하세요');}
}
async function addStock(code){
  try{
    const cur=await _freshItems();
    if(cur.some(i=>i.code===code))return;
    saveItems([{code:code,market:'KR'}].concat(cleanItems(cur)));   // 새 KR 종목 맨 앞 — 위젯 상위 노출
  }catch(e){alert('담기 실패 — 네트워크를 확인하세요');}
}
async function addUS(sym){
  try{
    const cur=await _freshItems();
    if(cur.some(i=>i.code===sym)){alert('이미 담긴 종목이에요');return;}
    saveItems(cleanItems(cur).concat([{code:sym,market:'US'}]));    // 없는 티커면 서버 400 메시지
  }catch(e){alert('담기 실패 — 네트워크를 확인하세요');}
}
</script>
<script>
// ── 관심종목 관리 리스트(Task 14, 별도 <script>) — 행별 핸들·▲▼·×·[보유] 버튼 폴백.
//    함수 선언은 hoist되므로 이 블록 하단(드래그 Task 15)이 실패해도 버튼 핸들러는 계속 동작한다.
//    ITEMS·saveItems·cleanItems·esc·won·D는 메인 블록의 전역을 재사용(정적 컨텍스트에선 조용히 비활성). ──
function pxOf(code){ const s=D.stocks.find(x=>x.code===code); return s?s.close:null; }
function manageRow(it){
  const isUS=it.market==='US', px=isUS?null:pxOf(it.code);
  let h='<div class="mrow" data-code="'+esc(it.code)+'" data-market="'+esc(it.market)+'">';
  h+='<span class="mhandle" title="드래그로 순서변경">⠿</span>';
  h+='<span class="mname">'+esc(it.name||it.code)+' <span class="code">'+esc(it.code)+'</span>'
    +(isUS?' <span class="mtag">US</span>':'')+'</span>';
  h+='<span class="mpx'+(isUS?'':' cpx')+'" data-code="'+esc(it.code)+'">'
    +(px!=null?won(px):(isUS?'$—':'–'))+'</span>';
  h+='<span class="mctl">'
    +'<button class="mmv" data-code="'+esc(it.code)+'" onclick="moveItem(this.dataset.code,-1)" title="위로">▲</button>'
    +'<button class="mmv" data-code="'+esc(it.code)+'" onclick="moveItem(this.dataset.code,1)" title="아래로">▼</button>'
    +'<button class="mhold" data-code="'+esc(it.code)+'" onclick="editHold(this.dataset.code)" title="보유 편집">보유</button>'
    +'<button class="mdel" data-code="'+esc(it.code)+'" onclick="delItem(this.dataset.code)" title="관심종목에서 삭제">×</button>'
    +'</span>';
  const sv=it.shares!=null?esc(it.shares):'', av=it.avg!=null?esc(it.avg):'';
  h+='<div class="mhe" id="he-'+esc(it.code)+'" style="display:none">'
    +'<input id="hs-'+esc(it.code)+'" type="number" inputmode="numeric" min="0" placeholder="수량" value="'+sv+'">'
    +'<input id="ha-'+esc(it.code)+'" type="number" inputmode="decimal" min="0" step="any" placeholder="평균매입가'+(isUS?'($)':'(원)')+'" value="'+av+'">'
    +'<button data-code="'+esc(it.code)+'" onclick="saveHold(this.dataset.code)">저장</button>'
    +'</div>';
  return h+'</div>';
}
function renderManage(){
  const box=document.getElementById('manage'); if(!box)return;
  if(!ITEMS.length){box.innerHTML='';return;}
  box.innerHTML='<div class="mtitle">관심종목 관리 <span class="meta">· 순서 ▲▼ · 삭제 × · 보유 입력</span></div>'
    +ITEMS.map(manageRow).join('');
}
function moveItem(code,dir){
  const i=ITEMS.findIndex(x=>x.code===code); if(i<0)return;
  const j=i+dir; if(j<0||j>=ITEMS.length)return;
  const items=cleanItems(ITEMS), t=items[i]; items[i]=items[j]; items[j]=t;
  saveItems(items);
}
function delItem(code){
  if(ITEMS.length<=1){alert('관심종목은 최소 1개 필요해요');return;}
  if(confirm('관심종목에서 삭제할까요?')) saveItems(cleanItems(ITEMS).filter(x=>x.code!==code));
}
function editHold(code){
  const box=document.getElementById('he-'+code); if(!box)return;
  box.style.display=box.style.display==='none'?'flex':'none';
}
function saveHold(code){
  const sEl=document.getElementById('hs-'+code), aEl=document.getElementById('ha-'+code);
  if(!sEl||!aEl)return;
  const sv=sEl.value.trim(), av=aEl.value.trim();
  const items=cleanItems(ITEMS), t=items.find(x=>x.code===code); if(!t)return;
  t.shares=sv===''?null:Number(sv);
  t.avg=av===''?null:Number(av);   // KR 원정수/US 소수 정규화는 서버 _clean_item가 담당
  saveItems(items);
}
async function loadItems(){
  try{
    const r=await fetch('/api/watchlist'); if(!r.ok)return;
    ITEMS=(await r.json()).items||[];
    renderManage();
  }catch(e){}   // 정적/아티팩트 컨텍스트에선 조용히 비활성(관리=서버 전용)
}
loadItems();
// ── 드래그 순서변경 + 스와이프 삭제(Task 15, 향상) — 순수 Pointer Events(외부 라이브러리 0).
//    초기화 전체를 try/catch로 감싸 이 코드가 런타임 실패해도 ▲▼·×·[보유] 버튼 폴백은 계속 동작.
//    (파스 오류는 test_dashboard_inline_js_parses의 node --check가 차단 — 이 블록이 renderManage와
//    같은 <script>여야 파스 게이트가 드래그 JS까지 덮는다.) 스크롤 충돌 방지: 핸들에서만 드래그
//    시작, 스와이프는 가로 이동이 세로보다 크고 좌향일 때만 확정(각도 임계). #manage 위임 바인딩
//    이라 renderManage가 innerHTML을 갈아끼워도 리스너가 살아남는다. ──
try{
  (function(){
    var box=document.getElementById('manage');
    if(!box || typeof window.PointerEvent==='undefined') return;   // 미지원 → 버튼 폴백만
    var SWIPE_MIN=64, START_SLOP=8;   // 삭제 확정 가로거리 · 판정 시작 여유(px)
    var mode=null, row=null, code=null, sx=0, sy=0, pid=null;
    function reset(){
      if(row){ row.style.transform=''; row.style.background=''; row.classList.remove('mdrag'); }
      mode=null; row=null; code=null; pid=null;
    }
    function rowAtY(y){
      var rows=box.querySelectorAll('.mrow');
      for(var i=0;i<rows.length;i++){
        var b=rows[i].getBoundingClientRect();
        if(y>=b.top && y<=b.bottom) return rows[i];
      }
      return null;
    }
    box.addEventListener('pointerdown', function(e){
      if(!e.target.closest) return;
      // 입력/버튼/편집폼 위에선 제스처 시작 안 함 — 네이티브 탭·타이핑을 뺏지 않는다(입력 깨짐 방지).
      if(e.target.closest('.mhe, button, input, textarea, select, a')) return;
      var r=e.target.closest('.mrow');
      if(!r) return;
      row=r; code=r.getAttribute('data-code'); sx=e.clientX; sy=e.clientY; pid=e.pointerId;
      if(e.target.classList && e.target.classList.contains('mhandle')){   // 핸들에서만 드래그
        mode='drag'; row.classList.add('mdrag');
        try{ box.setPointerCapture(pid); }catch(_){}
        e.preventDefault();
      }else{
        var he=r.querySelector('.mhe');   // 보유 편집 폼이 열린 행은 스와이프 금지(빨강이 폼 위로 번짐 방지)
        if(he && he.style.display!=='none'){ row=null; return; }
        mode='pending';                    // 스와이프 후보 — 이동 방향으로 확정
      }
    });
    box.addEventListener('pointermove', function(e){
      if(!mode||!row) return;
      var dx=e.clientX-sx, dy=e.clientY-sy;
      if(mode==='pending'){
        if(Math.abs(dx)<START_SLOP && Math.abs(dy)<START_SLOP) return;
        if(dx<0 && Math.abs(dx)>Math.abs(dy)){        // 좌 + 가로>세로(각도) → 스와이프
          mode='swipe';
          try{ box.setPointerCapture(pid); }catch(_){}
        }else{ reset(); return; }                     // 세로 우위 → 스크롤에 양보
      }
      if(mode==='swipe'){
        var off=Math.min(0,dx);
        row.style.transform='translateX('+off+'px)';
        row.style.background=(-off>=SWIPE_MIN)?'var(--up)':'';
        e.preventDefault();
      }else if(mode==='drag'){
        var over=rowAtY(e.clientY);
        if(over && over!==row){
          var rows=Array.prototype.slice.call(box.querySelectorAll('.mrow'));
          if(rows.indexOf(row)<rows.indexOf(over)) over.after(row);   // 아래로 → over 뒤
          else over.before(row);                                      // 위로 → over 앞
        }
        e.preventDefault();
      }
    });
    box.addEventListener('pointerup', function(e){
      if(!mode||!row){ reset(); return; }
      var m=mode, dx=e.clientX-sx, dcode=code;
      if(m==='swipe'){
        var del=(-dx>=SWIPE_MIN);
        reset();
        if(del) delItem(dcode);            // 확인창→저장(최소 1개 가드·격리 email 서버 해석 재사용)
      }else if(m==='drag'){
        var codes=Array.prototype.map.call(box.querySelectorAll('.mrow'),
          function(r){ return r.getAttribute('data-code'); });
        reset();
        var map={}; ITEMS.forEach(function(i){ map[i.code]=i; });
        var ordered=codes.map(function(c){ return map[c]; }).filter(Boolean);
        var before=ITEMS.map(function(i){ return i.code; }).join(',');
        if(ordered.length===ITEMS.length && codes.join(',')!==before)
          saveItems(cleanItems(ordered));  // 순서가 실제로 바뀐 경우만 저장
        else renderManage();               // 무변경/불일치 → 시각 원복
      }else reset();
    });
    box.addEventListener('pointercancel', reset);
    box.addEventListener('lostpointercapture', reset);   // 캡처 유실 시 stuck(빨강·이동) 복구
  })();
}catch(e){}   // 드래그/스와이프 향상 비활성 — ▲▼·×·[보유] 버튼 폴백은 계속 동작(progressive enhancement)
</script></div>__TABBAR__ __NAV_LOADER__</div></body></html>"""


def to_candles(df, days: int = 120) -> list:
    """가격 DataFrame → Lightweight Charts 캔들({time,open,high,low,close}).

    날짜 오름차순·중복 제거(라이브러리가 strictly ascending unique를 요구)."""
    d = df[~df.index.duplicated(keep="last")].sort_index().tail(days)
    out = []
    has_vol = "Volume" in d.columns
    for idx, r in d.iterrows():
        row = {"time": idx.strftime("%Y-%m-%d"),
               "open": round(float(r["Open"]), 2), "high": round(float(r["High"]), 2),
               "low": round(float(r["Low"]), 2), "close": round(float(r["Close"]), 2)}
        if has_vol:
            row["vol"] = int(r["Volume"])
        out.append(row)
    return out


def assemble_stock(signal, issues, candles, price, names=None) -> dict:
    """신호 + 이슈 + 캔들 + 현재가를 대시보드 종목 dict로 합친다.
    names(universe code→name)가 있으면 표시 이름을 그것으로(신규 종목 대응)."""
    from backend.news.names import resolve_name
    iv = _issues_view(issues)
    return {"code": signal.code, "name": resolve_name(signal.code, names),
            "action": signal.action, "action_ko": _ACTION_KO[signal.action],
            "confidence": signal.confidence, "advice": signal.advice,
            "reasons": list(signal.reasons), "backtest": _bt_view(signal.backtest),
            "close": (price or {}).get("close"), "change": (price or {}).get("change"),
            "news": iv["news"] if iv else [],
            "disclosures": iv["disclosures"] if iv else [],
            "candles": candles or []}


def render_dashboard(stocks, universe, date: str, pwa: bool = False) -> str:
    """assembled stocks + universe → 자기완결 HTML 문자열."""
    lib = _LIB_PATH.read_text(encoding="utf-8")
    data = {"date": date, "stocks": stocks, "universe": universe}
    # </script> 조기 종료 방지 + 잘못된 태그 해석 방지
    data_json = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    refresh = '<button class="refresh" onclick="location.reload()">🔄 새로고침</button>' if pwa else ""
    return (_TEMPLATE
            .replace("__BASE_CSS__", _BASE_CSS)
            .replace("__CHART_THEME_JS__", _CHART_THEME_JS)
            .replace("__DATE__", escape(date))
            .replace("__TABBAR__", _TABBAR if pwa else "")
            .replace("__NAV_LOADER__", _NAV_LOADER)
            .replace("__PWA_HEAD__", _PWA_HEAD if pwa else "")
            .replace("__REFRESH__", refresh)
            .replace("__DISCLAIMER__", escape(_DISCLAIMER))
            .replace("__DATA__", data_json)
            .replace("__LIB__", lib))
