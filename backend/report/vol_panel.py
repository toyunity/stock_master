from __future__ import annotations

"""대시보드 변동성지수(VKOSPI) 섹션 — CSS·마크업·JS 세 조각.

dashboard.py에서 분리한 이유는 크기다(dashboard.py가 이미 710줄이고 차트가 붙으면
100줄쯤 는다). options_panel.py와 같은 기준. 문자열만 내보내고 파이썬 로직은 없다."""

CSS = """
#volsec .vknow{display:flex;align-items:baseline;gap:8px;margin:10px 0 2px}
#volsec .vkv{font-family:var(--font-num);font-variant-numeric:tabular-nums;
  font-size:28px;font-weight:700;color:var(--text);letter-spacing:-.02em}
#volsec .vkd{font-family:var(--font-num);font-variant-numeric:tabular-nums;
  font-size:13px;font-weight:700}
#volsec .vkd.up{color:var(--up)} #volsec .vkd.down{color:var(--down)}
#volsec .vkd.flat{color:var(--flat)}
/* 높이를 CSS로 고정한다 — JS가 백킹스토어(cv.height)를 dpr배로 키워도 박스는
   그대로여야 한다. height 속성만 믿으면 리사이즈마다 섹션이 늘어난다. */
#vk-chart{width:100%;height:180px;display:block;margin-top:6px}
#volsec .vkfoot{margin-top:8px}
"""

HTML = """
<details class="sec" id="volsec">
  <summary><svg class="hic secic"><use href="#i-activity"/></svg> 변동성 · VKOSPI
    <span class="seccap" id="vk-cap">펼치면 조회</span><span class="chev">▾</span></summary>
  <div class="sec-body">
    <div class="vknow" id="vk-now"></div>
    <canvas id="vk-chart" height="180" data-h="180"></canvas>
    <div class="meta vkfoot" id="vk-foot"></div>
  </div>
</details>
"""

JS = r"""
// ── 변동성지수(VKOSPI) — **펼칠 때만 조회한다**(이 앱 최초의 지연 로딩). ──
// 안 펼치면 KIS 호출 0건. 대시보드를 열 때마다 나가는 호출을 늘리지 않는 게 요점이다.
function vkNum(n, d){ return n==null ? '–' : Number(n).toLocaleString('ko-KR',
  {minimumFractionDigits:d||0, maximumFractionDigits:d||0}); }

function vkDraw(cv, d){ window.__vkLast = d; }   // Task 4에서 구현

let vkLoaded = false;
async function loadVkospi(){
  let d = null;
  try{
    const r = await fetch('/api/vkospi');
    if(r && r.ok) d = await r.json();
  }catch(e){}
  const sec = document.getElementById('volsec');
  if(!sec) return;
  // 보여줄 게 없으면 섹션을 통째로 숨긴다(기업 체력·옵션 패널과 같은 관행).
  if(!d || !(d.days||[]).length){ sec.style.display='none'; return; }
  vkLoaded = true;

  const cap = document.getElementById('vk-cap');
  if(cap) cap.textContent = '최근 ' + d.days.length + '거래일';

  const n = d.now || {};
  const el = document.getElementById('vk-now');
  if(el){
    const cls = n.rate>0?'up':(n.rate<0?'down':'flat');
    const ar = n.rate>0?'▲':(n.rate<0?'▼':'·');
    el.innerHTML = '<span class="vkv">'+vkNum(n.price,2)+'</span>'
      + '<span class="vkd '+cls+'">'+ar+' '+vkNum(Math.abs(n.change||0),2)
      + ' ('+(n.rate==null?'–':vkNum(Math.abs(n.rate),2)+'%')+')</span>';
  }

  vkDraw(document.getElementById('vk-chart'), d);

  const foot = document.getElementById('vk-foot');
  // 기준선(20/30 등)을 말하지 않는다 — 이 시장은 오늘 78이고 100일 범위가 48~97이다.
  // 교과서 기준을 갖다 붙이면 틀린 말이 된다. 지표의 성질만 알려준다.
  if(foot) foot.textContent = '최근 ' + d.days.length + '거래일 · 지수와 반대로 움직입니다';
}

// 펼칠 때 딱 한 번만 조회한다. 접었다 폈다 해도 다시 안 부른다(서버 TTL 60초와 별개로
// 프론트에서도 막는다 — 토글은 사용자가 얼마든지 연타할 수 있다).
(function(){
  const sec = document.getElementById('volsec');
  if(!sec) return;
  sec.addEventListener('toggle', function(){
    if(sec.open && !vkLoaded) loadVkospi();
  });
})();
window.addEventListener('resize', function(){
  if(window.__vkLast) vkDraw(document.getElementById('vk-chart'), window.__vkLast);
});
"""
