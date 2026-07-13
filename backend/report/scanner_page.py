from __future__ import annotations

"""수급 스캐너 화면(/scanner) — 오늘 수급 특이 종목 자동 발굴.

/api/scanner JSON을 fetch해 렌더(60초 자동 갱신 + 수동 새로고침).
가집계 데이터 특성(잠정·하루 4~5회 갱신)을 라벨로 명시. 각 행 → /live/{code}."""

from html import escape

from backend.report.dashboard import _DISCLAIMER, _NAV_LOADER, _PWA_HEAD

_TEMPLATE = """<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>수급 스캐너 — Stock Master</title>
__PWA_HEAD__
<style>
body{font-family:-apple-system,"Apple SD Gothic Neo","Malgun Gothic",sans-serif;
  max-width:760px;margin:0 auto;padding:16px;color:#1a1a2e;background:#f7f8fb}
a{color:#1565c0;text-decoration:none}
h1{font-size:18px;margin:0}
.badge{font-size:11px;padding:2px 8px;border-radius:10px;color:#fff;vertical-align:middle}
.b-warn{background:#ef6c00} .b-ok{background:#2e7d32}
.up{color:#c62828} .down{color:#1565c0} .flat{color:#555}
.meta{font-size:12px;color:#888;margin:4px 0 10px}
.panel{border:1px solid #e0e3eb;border-radius:12px;padding:12px;margin:12px 0;background:#fff}
.panel h2{font-size:14px;margin:0 0 2px} .fresh{font-size:11px;color:#888;margin-bottom:8px}
table{width:100%;border-collapse:collapse;font-size:13px}
th{font-size:11px;color:#888;font-weight:500;text-align:right;padding:4px 6px;border-bottom:1px solid #eee}
td{text-align:right;padding:5px 6px;border-bottom:1px solid #f5f5f5;font-variant-numeric:tabular-nums}
th:first-child,td:first-child{text-align:left}
td a{font-weight:600;color:inherit}
.chip{display:inline-block;font-size:10px;background:#eef4fc;color:#1565c0;
  border-radius:8px;padding:1px 6px;margin-left:3px}
.refresh{font-size:13px;padding:6px 12px;border:1px solid #1565c0;background:#1565c0;
  color:#fff;border-radius:8px;cursor:pointer}
.disc{font-size:12px;color:#666;background:#fff3cd;border:1px solid #ffe69c;padding:10px;border-radius:8px;margin-top:16px}
#err{color:#c62828;font-size:13px;margin:8px 0}
details summary{font-size:12px;color:#1565c0;cursor:pointer;padding:6px 0}
</style></head><body>
<div><a href="/">← 대시보드</a></div>
<h1>🔍 수급 스캐너 <span class="badge b-warn">잠정</span>
  <button class="refresh" style="float:right" onclick="load()">🔄 새로고침</button></h1>
<div class="meta">외국인/기관 가집계는 증권사 수기 잠정치(하루 4~5회 갱신 · 1,000주 단위 반올림).
확정치는 다음 영업일 제공. <span id="asof"></span></div>
<div id="err"></div>
<div id="body">불러오는 중…</div>
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
  let h='<table>'+head+rows.slice(0,limit).map(tr).join('')+'</table>';
  if(rows.length>limit)
    h+='<details><summary>+'+(rows.length-limit)+'개 더 보기</summary><table>'
      +rows.slice(limit).map(tr).join('')+'</table></details>';
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
</script>__NAV_LOADER__</body></html>"""


def render_scanner_page() -> str:
    return (_TEMPLATE
            .replace("__NAV_LOADER__", _NAV_LOADER)
            .replace("__PWA_HEAD__", _PWA_HEAD)
            .replace("__DISCLAIMER__", escape(_DISCLAIMER)))
