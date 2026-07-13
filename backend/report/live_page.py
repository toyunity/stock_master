from __future__ import annotations

"""실시간 수급 화면(/live/{code}) — 자기완결 HTML (영웅문 '종목별 수급' 축소판).

dashboard.py와 같은 패턴: 차트 라이브러리 inline + 렌더 JS inline.
데이터는 SSE(/api/live/{code}/stream)로 1초마다 전체 스냅샷을 받아 그린다.
모든 수치에 신선도 라벨(실시간/잠정/전일 확정)을 붙인다 — 초보자 오해 방지.
"""

from html import escape

from backend.report.dashboard import (_DISCLAIMER, _LIB_PATH, _NAV_LOADER,
                                      _PWA_HEAD)

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
.sig{font-size:13px;font-weight:600;margin-top:8px;min-height:16px}
.sig-good{color:#2e7d32} .sig-warn{color:#ef6c00} .sig-info{color:#1565c0} .sig-flat{color:#888}
.b-warn{background:#ef6c00} .b-info{background:#1565c0}
.chartwrap{position:relative}
.stall{display:none;position:absolute;inset:0;background:rgba(247,248,251,.85);z-index:5;
  align-items:center;justify-content:center;font-size:13px;font-weight:600;color:#ef6c00;
  text-align:center;padding:0 12px}
.stall.on{display:flex}
</style></head><body>
<div><a href="/">← 대시보드</a></div>
<h1>__NAME__ <span class="code">__CODE__</span>
  <span id="mode" class="badge b-__MODE_CLS__">__MODE__</span>
  <span id="conn" class="badge b-off">연결 중…</span>
  <span id="mstate" class="badge b-off">상태 확인 중</span></h1>
<div class="price" id="price">–</div>
<div class="meta" id="pmeta">체결 대기 중 <span class="fresh">· 실시간</span></div>
<div class="note" id="note"></div>
<div class="note" id="walert"></div>

<div class="panel">
  <h2>📈 가격 차트 <span class="fresh" id="pc-fresh">· 불러오는 중</span></h2>
  <div class="tfrow">
    <button class="tf" data-tf="1m">1분</button>
    <button class="tf on" data-tf="5m">5분</button>
    <button class="tf" data-tf="15m">15분</button>
    <button class="tf" data-tf="1d">일봉</button>
    <button class="tf" id="notifbtn" style="display:none">🔔 감시선 알림 허용</button>
  </div>
  <div class="chartwrap"><div id="pchart"></div><div class="stall" id="pstall"></div></div>
</div>

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
  <h2>🤖 프로그램매매 <span class="fresh" id="pgm-fresh">· 실시간</span></h2>
  <div class="grid3" style="margin-bottom:8px">
    <div><div class="lbl">순매수 수량</div><div class="val" id="pgm-qty">–</div></div>
    <div><div class="lbl">순매수 금액</div><div class="val" id="pgm-val">–</div></div>
  </div>
  <div class="chartwrap"><div id="chart"></div><div class="stall" id="cstall"></div></div>
  <div class="meta">당일 누적 순매수 금액 추이(억원) — Y축은 당일 전체 범위 고정</div>
</div>

<details class="panel">
  <summary><h2>📅 일별 확정 수급 <span class="fresh">· 전일까지 확정치</span></h2></summary>
  <table id="daily"><tr><th>날짜</th><th>개인</th><th>외국인</th><th>기관</th><th>종가</th><th>대차잔고</th></tr></table>
</details>

<div class="panel">
  <h2>🩳 대차잔고 (공매도 선행지표) <span class="fresh" id="sb-fresh">· 데이터 대기</span></h2>
  <div class="grid3">
    <div><div class="lbl">잔고 주수</div><div class="val" id="sb-qty">–</div></div>
    <div><div class="lbl">전일 대비</div><div class="val" id="sb-chg">–</div></div>
    <div><div class="lbl">잔고 금액</div><div class="val" id="sb-val">–</div></div>
  </div>
  <div class="sig" id="sb-sig"></div>
  <details style="margin-top:8px">
    <summary class="meta" style="cursor:pointer">최근 20거래일 추이</summary>
    <table id="sb-hist" style="margin-top:6px"></table>
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
  <details style="margin-top:8px">
    <summary class="meta" style="cursor:pointer">최근 20거래일 추이</summary>
    <table id="ss-hist" style="margin-top:6px"></table>
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
  <div class="sig" id="cr-sig"></div>
  <details style="margin-top:8px">
    <summary class="meta" style="cursor:pointer">최근 20거래일 추이</summary>
    <table id="cr-hist" style="margin-top:6px"></table>
  </details>
  <div class="meta" id="cr-note">신용융자 = 빚내서 산 주식. 급락하면 증거금 부족분이 다음 날 아침
  반대매매(강제청산)로 쏟아진다 — 잔고가 클수록 하락 가속 연료. 금액은 주수×종가 환산(≈).</div>
</div>

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
확정치는 다음 영업일에 제공됩니다. 데이터 출처: 한국투자증권 오픈API(국내·해외 시세, 환율,
신용잔고, 공매도)·금융투자협회(대차잔고)·네이버(폴백). 모든 표시 시각은 KST(Asia/Seoul) 기준.</div>

<script>__LIB__</script>
<script>
const CODE='__CODE__';
const WATCH=__WATCH__; // 감시선 [{price,label}] — 서버 설정(SM_WATCH_LINES) 주입
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
const pchart=LightweightCharts.createChart(document.getElementById('pchart'),{autoSize:true,height:220,
  layout:{background:{color:'#fff'},textColor:'#999',fontSize:10},
  grid:{vertLines:{color:'#f4f4f4'},horzLines:{color:'#f4f4f4'}},
  rightPriceScale:{borderColor:'#eee'},
  timeScale:{borderColor:'#eee',timeVisible:true,secondsVisible:false}});
const pseries=pchart.addCandlestickSeries({upColor:'#c62828',downColor:'#1565c0',
  borderVisible:false,wickUpColor:'#c62828',wickDownColor:'#1565c0'});
// 감시선(P1-8): 라벨 달린 수평선 — 가격이 ±0.5% 진입하면 알림+사운드 1회
WATCH.forEach(w=>{try{pseries.createPriceLine({price:w.price,title:w.label,
  color:'#8e24aa',lineWidth:1,lineStyle:2,axisLabelVisible:true});}catch(e){}});
let TF='5m', tfSeq=0;
const TF_KO={'1m':'당일 1분봉','5m':'당일 5분봉','15m':'당일 15분봉','1d':'일봉 120일'};
async function loadCandles(){
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
    pchart.applyOptions({timeScale:{timeVisible:tf!=='1d'}});
    pchart.timeScale().fitContent();
    const lastT=d.candles[d.candles.length-1].t;
    document.getElementById('pc-fresh').textContent='· '+TF_KO[tf]+' · 기준 '
      +lastT+(tf==='1d'?'':' (KST) · 60초 자동 갱신');
  }catch(e){console.error(e);}
}
document.querySelectorAll('.tf').forEach(b=>b.onclick=()=>{
  document.querySelectorAll('.tf').forEach(x=>x.classList.remove('on'));
  b.classList.add('on'); TF=b.dataset.tf; loadCandles();
});
loadCandles();
setInterval(()=>{if(TF!=='1d')loadCandles();},60000);
function nextSlot(){
  // 잠정치 발표 슬롯(±10분): 외국인 09:30~, 기관 10:00~ — 다음 예상 시점 안내.
  // 기준 시각은 서버 KST(KTIME) — 클라이언트 로컬 시계 금지(P0-3)
  const slots=['09:30','10:00','11:20','13:20','14:30'];
  const cur=(KTIME||'00:00:00').slice(0,5);
  for(const s of slots) if(s>cur) return '~'+s+' (±10분)';
  return '다음 영업일 09:30';
}

// ── 감시선 알림(P1-8): ±0.5% 진입 시 1회, 0.7% 이탈 후 재무장(경계 진동 방지) ──
const armed=WATCH.map(()=>true);
let ac=null, lastWatchPrice=null;
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

function render(S){
  KDATE=S.kst_date; KTIME=S.kst_time; // 모든 표시 시각의 기준(서버 KST)
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
    document.getElementById('est-prsn-lbl').textContent = canSplit?'개인(추정)':'개인+기타*';
    document.getElementById('est-note').textContent = canSplit
      ? '개인 = −(외국인+기관+기타법인) 역산 · 기타법인 '+shares(ED.etc_qty)+' (장중 가집계, 1,000주 단위) · 아래 이력 표의 개인+기타는 슬롯별 역산값'
      : '*개인+기타법인 = −(외국인+기관) 역산 — 장중 개인 집계는 어디에도 없어 "전체 매매 합계는 0" 원리로 추정한 값';
    for(const[v,id]of[[pv,'est-prsn'],[last.frgn,'est-frgn'],[last.orgn,'est-orgn']]){
      const el=document.getElementById(id);
      el.textContent=shares(v); el.className='val '+cls(v);
    }
    document.getElementById('est-hist').innerHTML='<tr><th>기준</th><th>개인+기타*</th><th>외국인</th><th>기관</th></tr>'
      +E.rows.slice().reverse().map(r=>'<tr><td>'+esc(r.asof)+'</td><td class="'+cls(combined(r))+'">'+shares(combined(r))
      +'</td><td class="'+cls(r.frgn)+'">'+shares(r.frgn)
      +'</td><td class="'+cls(r.orgn)+'">'+shares(r.orgn)+'</td></tr>').join('');
  }else{
    // 날짜가 바뀌어 서버가 당일 상태를 비우면(전일 잠정 잔존 방지) 화면도 함께 비운다
    document.getElementById('est-fresh').textContent='잠정 · 오늘 발표 전 — 첫 잠정치 '+nextSlot()+' · 익일 확정';
    document.getElementById('est-prsn-lbl').textContent='개인+기타*';
    document.getElementById('est-note').textContent='*개인+기타법인 = −(외국인+기관) 역산 — 장중 개인 집계는 어디에도 없어 "전체 매매 합계는 0" 원리로 추정한 값';
    for(const id of ['est-prsn','est-frgn','est-orgn']){
      const el=document.getElementById(id); el.textContent='–'; el.className='val';
    }
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
    document.getElementById('ss-hist').innerHTML='<tr><th>날짜</th><th>공매도(주)</th><th>비중</th><th>종가</th></tr>'
      +SS.rows.slice().reverse().map(r=>'<tr><td>'+esc(r.date.slice(5))+'</td><td>'+num(r.qty)
      +'</td><td>'+(r.ratio||0).toFixed(2)+'%</td><td>'+won(r.close)+'</td></tr>').join('');
  }else{
    document.getElementById('ss-fresh').textContent='· 데이터 없음 — 조회 실패 또는 미공시. 자동 재시도 중';
    for(const id of ['ss-qty','ss-ratio','ss-vs']){
      const el=document.getElementById(id); el.textContent='–'; el.className='val';
    }
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
    document.getElementById('cr-sig').textContent=''; document.getElementById('cr-sig').className='sig';
    document.getElementById('cr-hist').innerHTML='';
  }
  document.getElementById('tape').innerHTML='<tr><th>시각</th><th>체결가</th><th>체결량</th><th>구분</th></tr>'
    +S.tape.map(t=>'<tr><td>'+esc(t.t)+'</td><td>'+won(t.price)+'</td><td>'+num(t.vol)
    +'</td><td class="'+(t.side==='buy'?'up':(t.side==='sell'?'down':'flat'))+'">'
    +(t.side==='buy'?'매수':(t.side==='sell'?'매도':'-'))+'</td></tr>').join('');
}

const es=new EventSource('/api/live/'+CODE+'/stream');
es.onmessage=e=>{try{render(JSON.parse(e.data));}catch(err){console.error(err);}};
es.onerror=()=>{const c=document.getElementById('conn');c.textContent='재연결 중…';c.className='badge b-off';};
</script>__NAV_LOADER__</body></html>"""


_MKT_LABEL = {"UN": "KRX+NXT 통합", "J": "KRX", "NX": "NXT"}


def render_live_page(code: str, name: str, mode: str) -> str:
    import json

    from backend.config import settings
    lib = _LIB_PATH.read_text(encoding="utf-8")
    watch = [w for w in (settings.watch_lines.get(code) or [])
             if isinstance(w.get("price"), (int, float)) and w.get("label")]
    # </script> 이스케이프: 라벨에 '</'가 들어오면 스크립트 블록이 조기 종료되어
    # 페이지 JS 전체가 죽는다(스크립트 컨텍스트 브레이크아웃, 리뷰 확정)
    watch_js = json.dumps(watch, ensure_ascii=False).replace("</", "<\\/")
    return (_TEMPLATE
            .replace("__WATCH__", watch_js)
            .replace("__MKT__", _MKT_LABEL.get(settings.market_div, "KRX+NXT 통합"))
            .replace("__NAV_LOADER__", _NAV_LOADER)
            .replace("__CODE__", escape(code))
            .replace("__NAME__", escape(name))
            .replace("__MODE__", escape(mode.upper()))
            .replace("__MODE_CLS__", "live" if mode == "live" else "demo")
            .replace("__PWA_HEAD__", _PWA_HEAD)
            .replace("__DISCLAIMER__", escape(_DISCLAIMER))
            .replace("__LIB__", lib))
