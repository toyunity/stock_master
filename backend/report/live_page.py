from __future__ import annotations

"""실시간 수급 화면(/live/{code}) — 자기완결 HTML (영웅문 '종목별 수급' 축소판).

dashboard.py와 같은 패턴: 차트 라이브러리 inline + 렌더 JS inline.
데이터는 SSE(/api/live/{code}/stream)로 1초마다 전체 스냅샷을 받아 그린다.
모든 수치에 신선도 라벨(실시간/잠정/전일 확정)을 붙인다 — 초보자 오해 방지.
"""

from html import escape

from backend.report.dashboard import _DISCLAIMER, _LIB_PATH, _PWA_HEAD

_TEMPLATE = """<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__NAME__ 실시간 수급 — Stock Master</title>
__PWA_HEAD__
<style>
body{font-family:-apple-system,"Apple SD Gothic Neo","Malgun Gothic",sans-serif;
  max-width:760px;margin:0 auto;padding:16px;color:#1a1a2e;background:#f7f8fb}
a{color:#1565c0;text-decoration:none}
h1{font-size:18px;margin:0} .code{font-size:12px;color:#999;font-weight:400}
.badge{font-size:11px;padding:2px 8px;border-radius:10px;color:#fff;vertical-align:middle}
.b-live{background:#2e7d32} .b-demo{background:#ef6c00} .b-off{background:#9e9e9e}
.price{font-size:32px;font-weight:700;margin:6px 0 0}
.up{color:#c62828} .down{color:#1565c0} .flat{color:#555}
.meta{font-size:12px;color:#888}
.panel{border:1px solid #e0e3eb;border-radius:12px;padding:12px;margin:12px 0;background:#fff}
.panel h2{font-size:14px;margin:0 0 2px} .fresh{font-size:11px;color:#888;margin-bottom:8px}
.grid3{display:flex;gap:8px;text-align:center}
.grid3>div{flex:1;background:#f7f8fb;border-radius:8px;padding:8px 4px}
.grid3 .lbl{font-size:12px;color:#666} .grid3 .val{font-size:16px;font-weight:700}
table{width:100%;border-collapse:collapse;font-size:13px}
th{font-size:11px;color:#888;font-weight:500;text-align:right;padding:4px 6px;border-bottom:1px solid #eee}
td{text-align:right;padding:4px 6px;border-bottom:1px solid #f5f5f5;font-variant-numeric:tabular-nums}
th:first-child,td:first-child{text-align:left}
#chart{height:180px}
.disc{font-size:12px;color:#666;background:#fff3cd;border:1px solid #ffe69c;padding:10px;border-radius:8px;margin-top:16px}
.note{font-size:12px;color:#ef6c00;margin-top:4px;min-height:14px}
.tfrow{display:flex;gap:6px;margin-bottom:8px}
.tf{font-size:12px;padding:4px 12px;border:1px solid #ccd4e0;background:#fff;border-radius:8px;cursor:pointer}
.tf.on{background:#1565c0;color:#fff;border-color:#1565c0}
#pchart{height:220px}
details.panel summary{cursor:pointer;list-style:none;-webkit-tap-highlight-color:transparent}
details.panel summary::-webkit-details-marker{display:none}
details.panel summary h2::before{content:'▸ ';color:#1565c0}
details.panel[open] summary h2::before{content:'▾ ';color:#1565c0}
details.panel summary h2{margin:0}
details.panel[open] summary{margin-bottom:6px}
</style></head><body>
<div><a href="/">← 대시보드</a></div>
<h1>__NAME__ <span class="code">__CODE__</span>
  <span id="mode" class="badge b-__MODE_CLS__">__MODE__</span>
  <span id="conn" class="badge b-off">연결 중…</span></h1>
<div class="price" id="price">–</div>
<div class="meta" id="pmeta">체결 대기 중 <span class="fresh">· 실시간</span></div>
<div class="note" id="note"></div>

<div class="panel">
  <h2>📈 가격 차트 <span class="fresh" id="pc-fresh">· 불러오는 중</span></h2>
  <div class="tfrow">
    <button class="tf" data-tf="1m">1분</button>
    <button class="tf on" data-tf="5m">5분</button>
    <button class="tf" data-tf="15m">15분</button>
    <button class="tf" data-tf="1d">일봉</button>
  </div>
  <div id="pchart"></div>
</div>

<div class="panel">
  <h2>💰 투자자별 순매수 (장중 추정)</h2>
  <div class="fresh" id="est-fresh">잠정 · 갱신 대기 · 장중 추정치는 익일 확정과 다를 수 있음</div>
  <div class="grid3">
    <div><div class="lbl" id="est-prsn-lbl">개인+기타*</div><div class="val" id="est-prsn">–</div></div>
    <div><div class="lbl">외국인</div><div class="val" id="est-frgn">–</div></div>
    <div><div class="lbl">기관</div><div class="val" id="est-orgn">–</div></div>
  </div>
  <table id="est-hist" style="margin-top:8px"></table>
  <div class="meta" id="est-note">*개인+기타법인 = −(외국인+기관) 역산 — 장중 개인 집계는 어디에도 없어
  "전체 매매 합계는 0" 원리로 추정한 값</div>
  <table id="est-detail" style="margin-top:8px"></table>
  <div class="meta" id="est-detail-note"></div>
</div>

<div class="panel">
  <h2>🤖 프로그램매매 <span class="fresh">· 실시간</span></h2>
  <div class="grid3" style="margin-bottom:8px">
    <div><div class="lbl">순매수 수량</div><div class="val" id="pgm-qty">–</div></div>
    <div><div class="lbl">순매수 금액</div><div class="val" id="pgm-val">–</div></div>
  </div>
  <div id="chart"></div>
  <div class="meta">당일 누적 순매수 금액 추이(억원)</div>
</div>

<details class="panel">
  <summary><h2>📅 일별 확정 수급 <span class="fresh">· 전일까지 확정치</span></h2></summary>
  <table id="daily"><tr><th>날짜</th><th>개인</th><th>외국인</th><th>기관</th><th>종가</th></tr></table>
</details>

<details class="panel">
  <summary><h2>🏛️ 기관 세부 수급 (연기금·투신·금융투자 …)</h2></summary>
  <div class="fresh" id="dt-fresh">확정 · 기준일 대기 · 기관계를 주체별로 분해한 확정치</div>
  <table id="detail"></table>
</details>

<details class="panel">
  <summary><h2>⚡ 실시간 체결 <span class="fresh">· 최근 30건</span></h2></summary>
  <table id="tape"><tr><th>시각</th><th>체결가</th><th>체결량</th><th>구분</th></tr></table>
</details>

<div class="disc">__DISCLAIMER__ 실시간 수급의 외국인/기관 수치는 장중 <b>추정치(잠정)</b>이며
확정치는 다음 영업일에 제공됩니다. 데이터 출처: 한국투자증권 오픈API·KRX.</div>

<script>__LIB__</script>
<script>
const CODE='__CODE__';
const num=n=>n==null?'–':Math.round(n).toLocaleString('ko-KR');
const won=n=>n==null?'–':num(n)+'원';
const shares=n=>n==null?'–':(n>0?'+':'')+num(n)+'주';
const eok=n=>n==null?'–':(n>0?'+':'')+(n/1e8).toLocaleString('ko-KR',{maximumFractionDigits:1})+'억';
const cls=n=>n>0?'up':(n<0?'down':'flat');
const esc=s=>(s==null?'':String(s)).replace(/[&<>"]/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[m]));
const sgn={up:'▲',down:'▼',flat:''};

const chart=LightweightCharts.createChart(document.getElementById('chart'),{autoSize:true,height:180,
  layout:{background:{color:'#fff'},textColor:'#999',fontSize:10},
  grid:{vertLines:{color:'#f4f4f4'},horzLines:{color:'#f4f4f4'}},
  rightPriceScale:{borderColor:'#eee'},
  timeScale:{borderColor:'#eee',timeVisible:true,secondsVisible:false}});
const series=chart.addBaselineSeries({baseValue:{type:'price',price:0},
  topLineColor:'#c62828',topFillColor:'rgba(198,40,40,.15)',
  bottomLineColor:'#1565c0',bottomFillColor:'rgba(21,101,192,.15)',lineWidth:2});
function toTs(t){const[h,m,s]=t.split(':').map(Number);const d=new Date();
  d.setHours(h,m,s||0,0);return Math.floor(d.getTime()/1000);}

// ── 가격 차트 (봉 주기 선택) ──
const pchart=LightweightCharts.createChart(document.getElementById('pchart'),{autoSize:true,height:220,
  layout:{background:{color:'#fff'},textColor:'#999',fontSize:10},
  grid:{vertLines:{color:'#f4f4f4'},horzLines:{color:'#f4f4f4'}},
  rightPriceScale:{borderColor:'#eee'},
  timeScale:{borderColor:'#eee',timeVisible:true,secondsVisible:false}});
const pseries=pchart.addCandlestickSeries({upColor:'#c62828',downColor:'#1565c0',
  borderVisible:false,wickUpColor:'#c62828',wickDownColor:'#1565c0'});
let TF='5m';
const TF_KO={'1m':'당일 1분봉','5m':'당일 5분봉','15m':'당일 15분봉','1d':'일봉 120일'};
async function loadCandles(){
  try{
    const r=await fetch('/api/candles/'+CODE+'?tf='+TF);
    if(!r.ok){document.getElementById('pc-fresh').textContent='· 차트 조회 실패';return;}
    const d=await r.json();
    if(!d.candles.length){document.getElementById('pc-fresh').textContent='· 데이터 없음(장전이거나 조회 실패)';return;}
    pseries.setData(d.candles.map(c=>({time:TF==='1d'?c.t:toTs(c.t),
      open:c.open,high:c.high,low:c.low,close:c.close})));
    pchart.applyOptions({timeScale:{timeVisible:TF!=='1d'}});
    pchart.timeScale().fitContent();
    document.getElementById('pc-fresh').textContent='· '+TF_KO[TF]+(TF==='1d'?'':' · 60초 자동 갱신');
  }catch(e){console.error(e);}
}
document.querySelectorAll('.tf').forEach(b=>b.onclick=()=>{
  document.querySelectorAll('.tf').forEach(x=>x.classList.remove('on'));
  b.classList.add('on'); TF=b.dataset.tf; loadCandles();
});
loadCandles();
setInterval(()=>{if(TF!=='1d')loadCandles();},60000);
function nextSlot(){
  // 잠정치 발표 슬롯(±10분): 외국인 09:30~, 기관 10:00~ — 다음 예상 시점 안내
  const slots=['09:30','10:00','11:20','13:20','14:30'];
  const n=new Date(), cur=String(n.getHours()).padStart(2,'0')+':'+String(n.getMinutes()).padStart(2,'0');
  for(const s of slots) if(s>cur) return '~'+s+' (±10분)';
  return '다음 영업일 09:30';
}

function render(S){
  const mode=document.getElementById('mode');
  mode.textContent=S.mode.toUpperCase();
  mode.className='badge '+(S.mode==='live'?'b-live':'b-demo');
  const conn=document.getElementById('conn');
  conn.textContent=S.status.connected?'수신 중':'끊김';
  conn.className='badge '+(S.status.connected?'b-live':'b-off');
  document.getElementById('note').textContent=S.status.note||'';
  const M=S.market;
  if(M.price!=null){
    const p=document.getElementById('price');
    p.textContent=won(M.price)+' '+sgn[M.sign]+' '+(M.rate!=null?Math.abs(M.rate).toFixed(2)+'%':'');
    p.className='price '+M.sign;
    document.getElementById('pmeta').innerHTML='거래량 '+num(M.vol)+'주 · 거래대금 '+eok(M.value).replace('+','')
      +' · 체결강도 '+(M.strength==null?'–':M.strength.toFixed(1))+' · '+esc(M.time||'')+' <span class="fresh">· 실시간</span>';
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
    document.getElementById('est-prsn-lbl').textContent = canSplit?'개인(추정)':'개인+기타*';
    document.getElementById('est-note').textContent = canSplit
      ? '개인 = −(외국인+기관+기타법인) 역산 · 기타법인 '+shares(ED.etc_qty)+' (장중 가집계, 1,000주 단위) · 아래 이력 표의 개인+기타는 슬롯별 역산값'
      : '*개인+기타법인 = −(외국인+기관) 역산 — 장중 개인 집계는 어디에도 없어 "전체 매매 합계는 0" 원리로 추정한 값';
    for(const[v,id]of[[pv,'est-prsn'],[last.frgn,'est-frgn'],[last.orgn,'est-orgn']]){
      const el=document.getElementById(id);
      el.textContent=shares(v); el.className='val '+cls(v);
    }
    document.getElementById('est-hist').innerHTML='<tr><th>기준</th><th>개인+기타*</th><th>외국인</th><th>기관</th></tr>'
      +E.rows.slice().reverse().map(r=>'<tr><td>'+esc(r.asof)+'</td><td class="'+cls(prsn(r))+'">'+shares(prsn(r))
      +'</td><td class="'+cls(r.frgn)+'">'+shares(r.frgn)
      +'</td><td class="'+cls(r.orgn)+'">'+shares(r.orgn)+'</td></tr>').join('');
  }
  const P=S.program;
  const q=document.getElementById('pgm-qty');
  q.textContent=shares(P.net_qty); q.className='val '+cls(P.net_qty);
  const v=document.getElementById('pgm-val');
  v.textContent=eok(P.net_value); v.className='val '+cls(P.net_value);
  if(P.points.length){
    const seen={},pts=[];
    for(const pt of P.points){const ts=toTs(pt.t);
      if(!seen[ts]){seen[ts]=1;pts.push({time:ts,value:pt.net_value/1e8});}}
    series.setData(pts); chart.timeScale().fitContent();
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
  document.getElementById('daily').innerHTML='<tr><th>날짜</th><th>개인</th><th>외국인</th><th>기관</th><th>종가</th></tr>'
    +S.daily.map(d=>'<tr><td>'+esc(d.date.slice(5))+'</td><td class="'+cls(d.prsn)+'">'+shares(d.prsn)
    +'</td><td class="'+cls(d.frgn)+'">'+shares(d.frgn)+'</td><td class="'+cls(d.orgn)+'">'+shares(d.orgn)
    +'</td><td>'+won(d.close)+'</td></tr>').join('');
  document.getElementById('tape').innerHTML='<tr><th>시각</th><th>체결가</th><th>체결량</th><th>구분</th></tr>'
    +S.tape.map(t=>'<tr><td>'+esc(t.t)+'</td><td>'+won(t.price)+'</td><td>'+num(t.vol)
    +'</td><td class="'+(t.side==='buy'?'up':(t.side==='sell'?'down':'flat'))+'">'
    +(t.side==='buy'?'매수':(t.side==='sell'?'매도':'-'))+'</td></tr>').join('');
}

const es=new EventSource('/api/live/'+CODE+'/stream');
es.onmessage=e=>{try{render(JSON.parse(e.data));}catch(err){console.error(err);}};
es.onerror=()=>{const c=document.getElementById('conn');c.textContent='재연결 중…';c.className='badge b-off';};
</script></body></html>"""


def render_live_page(code: str, name: str, mode: str) -> str:
    lib = _LIB_PATH.read_text(encoding="utf-8")
    return (_TEMPLATE
            .replace("__CODE__", escape(code))
            .replace("__NAME__", escape(name))
            .replace("__MODE__", escape(mode.upper()))
            .replace("__MODE_CLS__", "live" if mode == "live" else "demo")
            .replace("__PWA_HEAD__", _PWA_HEAD)
            .replace("__DISCLAIMER__", escape(_DISCLAIMER))
            .replace("__LIB__", lib))
