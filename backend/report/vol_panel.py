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

// ── 100거래일 라인 차트. 가로축은 월 눈금, 세로축은 최저·최고만. ──
// 세로 눈금을 촘촘히 달면 390px에서 겹친다(옵션 차트에서 겪었다). 가로 라벨을
// 살리는 대신 세로는 양 끝만 둔다.
function vkDraw(cv, d){
  window.__vkLast = d;
  if(!cv || !cv.getContext) return;
  const days = d.days || [];
  if(days.length < 2) return;
  const dpr = window.devicePixelRatio || 1;
  const w = cv.clientWidth || 340;
  // 의도한 CSS 높이는 data-h에서 읽는다 — height 속성은 아래에서 우리가 덮어쓰므로
  // 거기서 되읽으면 다시 그릴 때마다 dpr배로 부푼다.
  const h = parseInt(cv.getAttribute('data-h'), 10) || 180;
  cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr);
  const g = cv.getContext('2d');
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  g.clearRect(0, 0, w, h);

  const cs = getComputedStyle(document.documentElement);
  const CV = k => (cs.getPropertyValue(k) || '').trim();
  const LN = CV('--border') || '#dcdfe6', TX = CV('--text-3') || '#8b93a4';
  const INK = CV('--text') || '#1a1d24';
  const n = d.now || {};
  const ACC = (n.rate > 0 ? (CV('--up') || '#e5342f') : (CV('--down') || '#1f66e0'));

  const padL = 34, padR = 8, padT = 12, padB = 18;   // padL은 세로축 값 라벨 자리
  const vals = days.map(x => x.v);
  let lo = Math.min.apply(null, vals), hi = Math.max.apply(null, vals);
  if(hi === lo){ hi = lo + 1; }
  const X = i => padL + i / (days.length - 1) * (w - padL - padR);
  const Y = v => padT + (1 - (v - lo) / (hi - lo)) * (h - padT - padB);

  // 월 경계 — **달력이 아니라 데이터에서** 월이 바뀌는 첫 행으로 잡는다.
  // 휴장일 때문에 1일이 데이터에 없다(실측: 5월 경계가 5/4, 8월이 8/3).
  const marks = [];
  let prev = null;
  days.forEach(function(x, i){
    const m = String(x.d).slice(4, 6);
    if(m !== prev){ marks.push({i: i, m: parseInt(m, 10)}); prev = m; }
  });

  // 월 격자선(옅게) — 눈이 구간을 나눠 읽게 하는 용도
  g.strokeStyle = LN; g.lineWidth = 1;
  marks.forEach(function(k){
    if(k.i === 0) return;                    // 왼쪽 끝엔 선을 긋지 않는다
    g.globalAlpha = 0.45;
    g.beginPath(); g.moveTo(X(k.i), padT); g.lineTo(X(k.i), h - padB); g.stroke();
    g.globalAlpha = 1;
  });

  // 라인
  g.strokeStyle = ACC; g.lineWidth = 1.6;
  g.beginPath();
  days.forEach(function(x, i){ i ? g.lineTo(X(i), Y(x.v)) : g.moveTo(X(i), Y(x.v)); });
  g.stroke();

  // 오늘 마커 + 값
  const last = days.length - 1, ly = Y(days[last].v);
  g.fillStyle = ACC;
  g.beginPath(); g.arc(X(last), ly, 3, 0, Math.PI * 2); g.fill();
  g.font = '600 10px system-ui, sans-serif';
  g.textAlign = 'right';
  // 라벨은 마커 위가 기본. 천장에 닿으면 아래로 접는다(옵션 차트와 같은 규칙).
  let ty = ly - 6, tb = 'bottom';
  if(ty < 14){ ty = ly + 6; tb = 'top'; }
  g.textBaseline = tb;
  g.fillStyle = INK;
  g.fillText(vkNum(days[last].v, 2), w - padR, Math.min(h - padB - 6, Math.max(14, ty)));

  // 세로축 — 최저·최고만
  g.fillStyle = TX; g.font = '10px system-ui, sans-serif';
  g.textAlign = 'left'; g.textBaseline = 'middle';
  g.fillText(vkNum(hi, 1), 2, Math.max(13, padT));
  g.fillText(vkNum(lo, 1), 2, h - padB - 4);

  // 가로축 월 라벨. 마지막 월 경계는 늘 오른쪽 끝 근처라(월초는 항상 최근이다)
  // 마커 값 라벨과 같은 높이에 오면 안 된다 — 월 라벨은 축(아래쪽)에, 마커 값은
  // 라인 근처(위쪽)에 둔다. 마커 라벨의 y는 위에서 h-padB-6 이하로 묶어 뒀다.
  g.textAlign = 'center'; g.textBaseline = 'top';
  marks.forEach(function(k){
    const x = Math.min(w - padR - 10, Math.max(padL + 10, X(k.i)));
    g.fillText(k.m + '월', x, h - padB + 3);
  });
}

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
