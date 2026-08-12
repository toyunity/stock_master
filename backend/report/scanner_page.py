from __future__ import annotations

"""수급 스캐너 화면(/scanner) — 오늘 수급 특이 종목 자동 발굴.

/api/scanner JSON을 fetch해 렌더(60초 자동 갱신 + 수동 새로고침).
가집계 데이터 특성(잠정·하루 4~5회 갱신)을 라벨로 명시. 각 행 → /live/{code}."""

from html import escape

from backend.report.dashboard import (_AGO_JS, _BASE_CSS, _DISCLAIMER,
                                      _ICON_SPRITE, _NAV_LOADER, _PWA_HEAD,
                                      _TABBAR)

_TEMPLATE = """<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>수급 스캐너 — Stock Master</title>
__PWA_HEAD__
<style>
__BASE_CSS__
/* ── 스캐너 고유 ── */
.hdr{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:4px}
.hdr h1{display:flex;align-items:center;gap:8px;flex-wrap:wrap;font-size:18px}
.topmeta{font-size:12px;color:var(--text-2);margin:8px 0 12px;line-height:1.6}
td a{font-weight:700;color:var(--text)}
.chip{display:inline-block;font-size:10px;font-weight:600;background:var(--info-bg);
  color:var(--primary-ink);border-radius:var(--r-pill);padding:2px 8px;margin-left:4px;vertical-align:middle}
#err{color:var(--up);font-size:13px;margin:8px 0;font-weight:500}
#body details summary{font-size:12px;color:var(--primary);cursor:pointer;
  padding:8px 0;min-height:40px;display:flex;align-items:center;list-style:none}
#body details summary::-webkit-details-marker{display:none}
/* 순위 크기 데이터 막대 — 셀 뒤 비례 막대(우측 정렬 셀이라 오른쪽에서 자람) */
.barcell{position:relative}
.barcell .bar{position:absolute;right:6px;top:5px;bottom:5px;border-radius:3px;opacity:.20;
  pointer-events:none;max-width:calc(100% - 12px)}
.barcell .bar.up{background:var(--up)} .barcell .bar.down{background:var(--down)} .barcell .bar.flat{background:var(--flat)}
.barcell .barv{position:relative}
</style></head><body>
__ICONS__
<div id="app"><div id="app-scroll">
<div><a class="back" href="/">← 대시보드</a></div>
<div class="hdr">
  <h1>🔍 수급 스캐너 <span class="badge b-warn">잠정</span></h1>
  <button class="refresh" onclick="load()">🔄 새로고침</button>
</div>
<div class="topmeta">외국인/기관 가집계는 증권사 수기 잠정치(하루 4~5회 갱신 · 1,000주 단위 반올림).
확정치는 다음 영업일 제공. <span id="asof"></span> <span class="ago" id="asof-ago"></span></div>
<div id="err"></div>
<div id="body">불러오는 중…</div>
<div id="topview"></div>
<div class="disc">__DISCLAIMER__ 스캐너의 종목 나열은 데이터 정렬 결과일 뿐 매수 추천이 아닙니다.</div>
<script>
__AGO_JS__
// D.asof는 서버 벽시계 'HH:MM:SS'(KST, 날짜 없음) — 오늘 날짜와 합쳐야 ago()가 받는
// epoch millis가 된다. 브라우저가 KST라는 전제(국내 전용 개인 앱)로 자정을 넘겼으면
// (변환 시각이 지금보다 미래면) 하루를 물린다(2026-08-13).
function agoFromHms(hms){
  if(!hms) return '';
  const p=hms.split(':').map(Number), n=new Date();
  let t=new Date(n.getFullYear(),n.getMonth(),n.getDate(),p[0],p[1],p[2]||0).getTime();
  if(t>Date.now()) t-=86400000;
  return ago(t);
}
const num=n=>n==null?'–':Math.round(n).toLocaleString('ko-KR');
const eok=n=>n==null?'–':(n>0?'+':'')+(n/1e8).toLocaleString('ko-KR',{maximumFractionDigits:0})+'억';
const cls=n=>n>0?'up':(n<0?'down':'flat');
const esc=s=>(s==null?'':String(s)).replace(/[&<>"]/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[m]));
const rateTd=r=>'<td class="'+esc(r.sign)+'">'+(r.rate>0?'+':'')+r.rate.toFixed(2)+'%</td>';
const nameTd=r=>'<td><a href="/live/'+esc(r.code)+'">'+esc(r.name)+' 📡</a></td>';

function tbl(rows,cols,limit){
  if(!rows||!rows.length) return '<div class="meta">데이터 없음 (장전/장후이거나 조회 실패)</div>';
  const head='<tr>'+cols.map(c=>'<th>'+c[0]+'</th>').join('')+'</tr>';
  const tr=r=>'<tr>'+cols.map(c=>c[1](r)).join('')+'</tr>';
  let h='<div class="tbl-wrap"><table>'+head+rows.slice(0,limit).map(tr).join('')+'</table></div>';
  if(rows.length>limit)
    h+='<details><summary>+'+(rows.length-limit)+'개 더 보기</summary>'
      +'<div class="tbl-wrap"><table>'+rows.slice(limit).map(tr).join('')+'</table></div></details>';
  return h;
}

function render(D){
  document.getElementById('asof').textContent='조회 '+D.asof+' 기준';
  document.getElementById('asof-ago').textContent=agoFromHms(D.asof);
  const S=D.sections;
  // 순위 크기를 눈으로 — 셀 뒤 비례 막대(상단=최대). 방향색(적/청)·거래대금은 무채색.
  const maxAbs=(rows,key)=>Math.max(1,...rows.map(r=>Math.abs(r[key]!=null?r[key]:0)));
  const barTd=(v,max)=>{ if(v==null)return '<td>–</td>';
    const pct=max?Math.min(100,Math.abs(v)/max*100):0, c=cls(v);
    return '<td class="barcell"><span class="bar '+c+'" style="width:'+pct.toFixed(0)+'%"></span>'
      +'<span class="barv '+c+'">'+eok(v)+'</span></td>'; };
  const valTd=(v,max)=>{ if(v==null)return '<td>–</td>';
    const pct=max?Math.min(100,Math.abs(v)/max*100):0;
    return '<td class="barcell"><span class="bar flat" style="width:'+pct.toFixed(0)+'%"></span>'
      +'<span class="barv">'+eok(v).replace('+','')+'</span></td>'; };
  // 수급(외인·기관 막대)을 이름 바로 뒤로 — 화면 안에 보이게(현재가/등락은 뒤로 스크롤).
  const fitColsFor=rows=>{ const mF=maxAbs(rows,'frgn_value'), mO=maxAbs(rows,'orgn_value');
    return [['종목',nameTd],
      ['외인 순매수',r=>barTd(r.frgn_value,mF)],['기관 순매수',r=>barTd(r.orgn_value,mO)],
      ['현재가',r=>'<td>'+num(r.price)+'</td>'],['등락',rateTd]]; };
  const sec=(icon,title,cap,body)=>'<details class="sec" open><summary><svg class="hic secic">'
    +'<use href="#'+icon+'"/></svg> '+title+'<span class="seccap">'+cap+'</span>'
    +'<span class="chev">▾</span></summary><div class="sec-body">'+body+'</div></details>';
  const sub=(icon,title,cap,tblhtml)=>'<div class="panel"><h2><svg class="hic"><use href="#'+icon
    +'"/></svg> '+title+'</h2><div class="fresh">'+cap+'</div>'+tblhtml+'</div>';
  let h='';
  // 리드: 오늘의 특이 종목(수급∩모멘텀 교차) — 스캐너 요약
  if(D.picks&&D.picks.length){
    h+=sec('i-star','오늘의 특이 종목','수급∩모멘텀 교차',
      '<div class="fresh">수급(외인·기관 순매수 상위) ∩ 모멘텀(거래대금·급등 상위) 교차</div>'
      +tbl(D.picks,[['종목',r=>'<td><a href="/live/'+esc(r.code)+'">'+esc(r.name)+' 📡</a>'
        +(r.reasons||[]).map(x=>'<span class="chip">'+esc(x)+'</span>').join('')+'</td>'],
        ['외인',r=>barTd(r.frgn_value,maxAbs(D.picks,'frgn_value'))],
        ['기관',r=>barTd(r.orgn_value,maxAbs(D.picks,'orgn_value'))],
        ['현재가',r=>'<td>'+num(r.price)+'</td>'],['등락',rateTd]],15));
  }
  // 그룹1: 투자자 순매수·순매도 상위(외국인·기관 4종)
  h+=sec('i-flows','투자자 순매수·순매도 상위','외국인·기관 · 가집계(잠정)',
    sub('i-globe','외국인 순매수 상위','가집계(잠정) · 금액 기준',tbl(S.frgn_buy,fitColsFor(S.frgn_buy),10))
    +sub('i-bank','기관 순매수 상위','가집계(잠정) · 금액 기준',tbl(S.orgn_buy,fitColsFor(S.orgn_buy),10))
    +sub('i-globe','외국인 순매도 상위','가집계(잠정) · 금액 기준',tbl(S.frgn_sell,fitColsFor(S.frgn_sell),10))
    +sub('i-bank','기관 순매도 상위','가집계(잠정) · 금액 기준',tbl(S.orgn_sell,fitColsFor(S.orgn_sell),10)));
  // 그룹2: 모멘텀 상위(거래대금·급등)
  h+=sec('i-rise','모멘텀 상위','거래대금·급등 · 실시간',
    sub('i-cash','거래대금 상위','실시간 · ETF/ETN/스팩 제외',
      tbl(S.value_top,[['종목',nameTd],
        ['거래대금',r=>valTd(r.value,maxAbs(S.value_top,'value'))],
        ['현재가',r=>'<td>'+num(r.price)+'</td>'],['등락',rateTd],
        ['거래량 전일比',r=>'<td>'+(r.vol_change!=null?r.vol_change.toFixed(0)+'%':'–')+'</td>']],10))
    +sub('i-rise','급등 상위','실시간 · 거래량 10만주 이상 · ETF/ETN/스팩 제외',
      tbl(S.gainers,[['종목',r=>'<td><a href="/live/'+esc(r.code)+'">'+esc(r.name)+' 📡</a>'
        +(r.limit_up?'<span class="chip">상한가</span>':'')+'</td>'],
        ['현재가',r=>'<td>'+num(r.price)+'</td>'],['등락',rateTd],
        ['거래량',r=>'<td>'+num(r.vol)+'</td>']],10)));
  document.getElementById('body').innerHTML=h;
}

async function load(){
  document.getElementById('err').textContent='';
  try{
    const r=await fetch('/api/scanner');
    if(!r.ok){
      const e=await r.json().catch(()=>({}));
      document.getElementById('err').textContent=e.error||('조회 실패 ('+r.status+')');
      return;
    }
    render(await r.json());
  }catch(e){document.getElementById('err').textContent='네트워크 오류 — 새로고침 해보세요';}
}
load();
setInterval(load, 60000);
// ── 인기 조회 상위(발굴) — /api/topview. #body와 분리된 컨테이너라 render()가 안 지운다. ──
async function loadTopView(){
  try{
    const r=await fetch('/api/topview'); if(!r.ok)return;
    const d=await r.json(); const items=(d&&d.items)||[];
    const box=document.getElementById('topview');
    if(!items.length){ box.innerHTML=''; return; }
    box.innerHTML='<details class="sec" open><summary><svg class="hic secic"><use href="#i-eye"/></svg>'
      +' 인기 조회 상위 <span class="seccap">발굴용</span><span class="chev">▾</span></summary>'
      +'<div class="sec-body"><div class="fresh">HTS 기준 많이 본 종목 · 발굴용</div>'
      +tbl(items,[['종목',nameTd]],10)+'</div></details>';
  }catch(e){}
}
loadTopView();
setInterval(loadTopView, 60000);
</script></div>__TABBAR__ __NAV_LOADER__</div></body></html>"""


def render_scanner_page() -> str:
    return (_TEMPLATE
            .replace("__BASE_CSS__", _BASE_CSS)
            .replace("__ICONS__", _ICON_SPRITE)
            .replace("__AGO_JS__", _AGO_JS)
            .replace("__TABBAR__", _TABBAR)
            .replace("__NAV_LOADER__", _NAV_LOADER)
            .replace("__PWA_HEAD__", _PWA_HEAD)
            .replace("__DISCLAIMER__", escape(_DISCLAIMER)))
