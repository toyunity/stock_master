from __future__ import annotations

"""수급 스캐너 화면(/scanner) — 오늘 수급 특이 종목 자동 발굴.

/api/scanner JSON을 fetch해 렌더(60초 자동 갱신 + 수동 새로고침).
가집계 데이터 특성(잠정·하루 4~5회 갱신)을 라벨로 명시. 각 행 → /live/{code}."""

from html import escape

from backend.report.dashboard import (_BASE_CSS, _DISCLAIMER, _NAV_LOADER,
                                      _PWA_HEAD, _TABBAR)

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
</style></head><body>
<div id="app"><div id="app-scroll">
<div><a class="back" href="/">← 대시보드</a></div>
<div class="hdr">
  <h1>🔍 수급 스캐너 <span class="badge b-warn">잠정</span></h1>
  <button class="refresh" onclick="load()">🔄 새로고침</button>
</div>
<div class="topmeta">외국인/기관 가집계는 증권사 수기 잠정치(하루 4~5회 갱신 · 1,000주 단위 반올림).
확정치는 다음 영업일 제공. <span id="asof"></span></div>
<div id="err"></div>
<div id="body">불러오는 중…</div>
<div id="topview"></div>
<div class="disc">__DISCLAIMER__ 스캐너의 종목 나열은 데이터 정렬 결과일 뿐 매수 추천이 아닙니다.</div>
<script>
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
  const S=D.sections;
  const fitCols=[['종목',nameTd],['현재가',r=>'<td>'+num(r.price)+'</td>'],['등락',rateTd],
    ['외인 순매수',r=>'<td class="'+cls(r.frgn_value)+'">'+eok(r.frgn_value)+'</td>'],
    ['기관 순매수',r=>'<td class="'+cls(r.orgn_value)+'">'+eok(r.orgn_value)+'</td>']];
  let h='';
  if(D.picks&&D.picks.length){
    h+='<div class="panel"><h2>⭐ 오늘의 수급 특이 종목</h2>'
      +'<div class="fresh">수급(외인·기관 순매수 상위) ∩ 모멘텀(거래대금·급등 상위) 교차</div>'
      +tbl(D.picks,[['종목',r=>'<td><a href="/live/'+esc(r.code)+'">'+esc(r.name)+' 📡</a>'
        +(r.reasons||[]).map(x=>'<span class="chip">'+esc(x)+'</span>').join('')+'</td>'],
        ['현재가',r=>'<td>'+num(r.price)+'</td>'],['등락',rateTd],
        ['외인',r=>'<td class="'+cls(r.frgn_value)+'">'+eok(r.frgn_value)+'</td>'],
        ['기관',r=>'<td class="'+cls(r.orgn_value)+'">'+eok(r.orgn_value)+'</td>']],15)+'</div>';
  }
  h+='<div class="panel"><h2>🌏 외국인 순매수 상위</h2><div class="fresh">가집계(잠정) · 금액 기준</div>'+tbl(S.frgn_buy,fitCols,10)+'</div>';
  h+='<div class="panel"><h2>🏦 기관 순매수 상위</h2><div class="fresh">가집계(잠정) · 금액 기준</div>'+tbl(S.orgn_buy,fitCols,10)+'</div>';
  h+='<div class="panel"><h2>🌏 외국인 순매도 상위</h2><div class="fresh">가집계(잠정) · 금액 기준</div>'+tbl(S.frgn_sell,fitCols,10)+'</div>';
  h+='<div class="panel"><h2>🏦 기관 순매도 상위</h2><div class="fresh">가집계(잠정) · 금액 기준</div>'+tbl(S.orgn_sell,fitCols,10)+'</div>';
  h+='<div class="panel"><h2>💵 거래대금 상위</h2><div class="fresh">실시간 · ETF/ETN/스팩 제외</div>'
    +tbl(S.value_top,[['종목',nameTd],['현재가',r=>'<td>'+num(r.price)+'</td>'],['등락',rateTd],
      ['거래대금',r=>'<td>'+eok(r.value).replace('+','')+'</td>'],
      ['거래량 전일比',r=>'<td>'+(r.vol_change!=null?r.vol_change.toFixed(0)+'%':'–')+'</td>']],10)+'</div>';
  h+='<div class="panel"><h2>🚀 급등 상위</h2><div class="fresh">실시간 · 거래량 10만주 이상 · ETF/ETN/스팩 제외</div>'
    +tbl(S.gainers,[['종목',r=>'<td><a href="/live/'+esc(r.code)+'">'+esc(r.name)+' 📡</a>'
      +(r.limit_up?'<span class="chip">상한가</span>':'')+'</td>'],
      ['현재가',r=>'<td>'+num(r.price)+'</td>'],['등락',rateTd],
      ['거래량',r=>'<td>'+num(r.vol)+'</td>']],10)+'</div>';
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
    box.innerHTML='<div class="panel"><h2>👀 인기 조회 상위</h2>'
      +'<div class="fresh">HTS 기준 많이 본 종목 · 발굴용</div>'+tbl(items,[['종목',nameTd]],10)+'</div>';
  }catch(e){}
}
loadTopView();
setInterval(loadTopView, 60000);
</script></div>__TABBAR__ __NAV_LOADER__</div></body></html>"""


def render_scanner_page() -> str:
    return (_TEMPLATE
            .replace("__BASE_CSS__", _BASE_CSS)
            .replace("__TABBAR__", _TABBAR)
            .replace("__NAV_LOADER__", _NAV_LOADER)
            .replace("__PWA_HEAD__", _PWA_HEAD)
            .replace("__DISCLAIMER__", escape(_DISCLAIMER)))
