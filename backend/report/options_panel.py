from __future__ import annotations

"""대시보드 코스피200 옵션 섹션 — CSS·마크업·JS 세 조각.

dashboard.py에서 분리한 이유는 순전히 크기다(섹션 하나가 차트 둘을 포함해 250줄이
넘는다). 렌더 시점에 dashboard._TEMPLATE의 자리표시자로 끼워진다.
문자열만 내보내고 파이썬 로직은 없다."""

CSS = """
#optsec .optdig{margin-left:auto;margin-right:8px;font-family:var(--font-num);
  font-variant-numeric:tabular-nums;font-size:11.5px;color:var(--text-3);
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.optnums{display:flex;gap:8px;margin:10px 0 4px}
.optnums .on{flex:1;min-width:0;background:var(--surface-2);border-radius:var(--r-md);
  padding:8px 10px}
.optnums .ok{font-size:11px;color:var(--text-3);white-space:nowrap}
.optnums .ov{font-family:var(--font-num);font-variant-numeric:tabular-nums;
  font-size:17px;font-weight:700;color:var(--text);margin-top:2px}
.optnums .oz{font-size:10.5px;color:var(--text-3);margin-top:1px}
.optch{margin-top:12px}
.optcap{font-size:12.5px;font-weight:600;color:var(--text);margin-bottom:4px}
.optcap .meta{font-weight:400}
.optch canvas{width:100%;display:block}
#opt-foot{margin-top:10px}
"""

HTML = """
<details class="sec" id="optsec" style="display:none">
  <summary><svg class="hic secic"><use href="#i-bars"/></svg> 코스피200 옵션
    <span class="optdig" id="opt-dig"></span><span class="chev">▾</span></summary>
  <div class="sec-body">
    <div class="optnums" id="opt-nums"></div>
    <div class="optch">
      <div class="optcap">오늘의 증감 <span class="meta">— 오늘 새로 걸린 자리</span></div>
      <canvas id="opt-chg" height="190"></canvas>
    </div>
    <div class="optch">
      <div class="optcap">누적 미결제 <span class="meta">— 지금까지 쌓인 포지션</span></div>
      <canvas id="opt-oi" height="190"></canvas>
    </div>
    <div class="meta" id="opt-foot"></div>
  </div>
</details>
"""

JS = r"""
// ── 코스피200 옵션 섹션 — 1시간 수집분을 보여준다(장중 5분마다 재확인). ──
function optNum(n, d){ return n==null ? '–' : Number(n).toLocaleString('ko-KR',
  {minimumFractionDigits:d||0, maximumFractionDigits:d||0}); }
function optSigned(n){ return n==null ? '–' : (n>0?'+':'')+optNum(n); }

function optDraw(cv, d, fi, mark){ window.__optLast = d; }   // Task 7에서 구현

function optCard(k, v, z){
  return '<div class="on"><div class="ok">'+k+'</div><div class="ov">'+v+'</div>'
       + (z?'<div class="oz">'+z+'</div>':'')+'</div>';
}

async function loadOptions(){
  let d = null;
  try{
    const r = await fetch('/api/options');
    if(r && r.ok) d = await r.json();
  }catch(e){}
  const sec = document.getElementById('optsec');
  if(!sec) return;
  // 보여줄 게 없으면 섹션을 통째로 숨긴다 — 빈 칸이 '데이터 없음'처럼 자리를
  // 차지하는 것보다 없는 게 정직하다(기업 체력 패널에서 정한 규칙 그대로).
  if(!d || !d.summary || (!(d.calls||[]).length && !(d.puts||[]).length)){
    sec.style.display='none'; return;
  }
  sec.style.display='';
  const s = d.summary || {};
  // 접힌 줄 — 펼치지 않아도 쓸모가 있어야 한다.
  const bits = [];
  if(d.label) bits.push(d.label);
  if(d.remain_days!=null) bits.push('만기 '+d.remain_days+'일');
  if(s.pcr!=null) bits.push('풋콜 '+optNum(s.pcr,2));
  if(s.atm_iv!=null) bits.push('IV '+optNum(s.atm_iv,0)+'%');
  if(s.call_chg_sum) bits.push('오늘 콜 '+optSigned(s.call_chg_sum));
  const dig = document.getElementById('opt-dig');
  if(dig) dig.textContent = bits.join(' · ');

  // 숫자 3개. 콜 벽은 없다 — 범위 따라 흔들려 숫자로 단정하지 않기로 했다.
  const nums = document.getElementById('opt-nums');
  if(nums){
    nums.innerHTML =
        optCard('풋콜 비율', optNum(s.pcr,2), s.pcr==null?'거래 없음':'풋÷콜 거래량')
      + optCard('ATM 변동성', s.atm_iv==null?'–':optNum(s.atm_iv,0)+'%',
                s.atm_strike==null?'거래된 행사가 없음':'행사가 '+optNum(s.atm_strike,1))
      + optCard('풋 벽', optNum(s.put_wall,1),
                '지수 ±'+optNum(s.wall_pct)+'% 안에서');
  }

  optDraw(document.getElementById('opt-chg'), d, 2, true);   // 오늘의 증감(마커 O)
  optDraw(document.getElementById('opt-oi'),  d, 1, false);  // 누적 미결제(마커 X)

  // 각주 — 기준 시각, 수집 중, 실패 건수를 숨기지 않는다.
  const foot = document.getElementById('opt-foot');
  if(foot){
    const parts = [];
    if(d.ts) parts.push(new Date(d.ts*1000).toLocaleTimeString('ko-KR',
      {hour:'2-digit', minute:'2-digit'})+' 기준');
    if(d.collecting) parts.push('집계 중');
    else if(d.stale) parts.push('갱신 지연');
    if(d.failed) parts.push('조회 실패 '+d.failed+'건 — 합계 지표(풋콜 비율)에 그만큼 빠져 있다');
    parts.push('빨강=콜 · 파랑=풋 · 음영=지수 ±'+optNum((s.wall_pct||20))+'%');
    foot.textContent = parts.join(' · ');
  }
}
loadOptions(); setInterval(loadOptions, 300000);   // 5분마다 재확인(수집은 서버가 1시간)
window.addEventListener('resize', function(){
  const d = window.__optLast;
  if(d){ optDraw(document.getElementById('opt-chg'), d, 2, true);
         optDraw(document.getElementById('opt-oi'), d, 1, false); }
});
"""
