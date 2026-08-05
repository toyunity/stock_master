from __future__ import annotations

"""대시보드 코스피200 옵션 섹션 — CSS·마크업·JS 세 조각.

dashboard.py에서 분리한 이유는 순전히 크기다(섹션 하나가 차트 둘을 포함해 250줄이
넘는다). 렌더 시점에 dashboard._TEMPLATE의 자리표시자로 끼워진다.
문자열만 내보내고 파이썬 로직은 없다."""

CSS = """
/* 제목('K200 옵션')이 두 줄로 깨지면 요약 줄이 통째로 밀린다 — 390px에서 실제로
   깨졌다. 선물 칩의 'K200선물'과 같은 어휘를 써서 짧게 유지한다. */
#optsec>summary{white-space:nowrap}
/* 11px·여백 4px로 조인 이유: 11.5px·8px에서는 390px 화면에서 5px가 모자라
   '콜 +6,1…'로 잘렸다(CDP 실측). 잘리는 건 항상 줄 끝 = 오늘의 증감이다. */
#optsec .optdig{margin-left:auto;margin-right:4px;font-family:var(--font-num);
  font-variant-numeric:tabular-nums;font-size:11px;color:var(--text-3);
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0}
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
/* 높이를 CSS로 고정한다 — JS가 백킹스토어(cv.height)를 dpr배로 키워도 박스는
   그대로여야 한다. height 속성만 믿으면 리사이즈마다 섹션이 늘어난다. */
.optch canvas{width:100%;height:190px;display:block}
#opt-foot{margin-top:10px}
"""

HTML = """
<details class="sec" id="optsec" style="display:none">
  <summary><svg class="hic secic"><use href="#i-bars"/></svg> K200 옵션
    <span class="optdig" id="opt-dig"></span><span class="chev">▾</span></summary>
  <div class="sec-body">
    <div class="optnums" id="opt-nums"></div>
    <div class="optch">
      <div class="optcap">오늘의 증감 <span class="meta">— 오늘 새로 걸린 자리</span></div>
      <canvas id="opt-chg" height="190" data-h="190"></canvas>
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
// 접힌 줄 전용 축약 — 만 단위. 1,012 종목 합계는 쉽게 십만 단위가 되는데
// '+486,213'은 접힌 줄(약 200px)을 넘겨 잘린다(CDP 실측). '+48.6만'은 짧고
// 한국어로 더 빨리 읽힌다. 펼친 쪽 마커는 원래 숫자를 그대로 쓴다.
function optSignedShort(n){
  if(n==null) return '–';
  const s = n>0?'+':(n<0?'-':''), a = Math.abs(n);
  if(a < 10000) return s+optNum(a);
  return s+(a/10000).toFixed(1)+'만';
}

// ── 행사가별 분포 차트 — 중앙선 위=콜(빨강) 아래=풋(파랑), 음수는 반대쪽. ──
// 막대가 780~1,012개라 SVG가 아니라 Canvas다. fi는 payload.cols의 인덱스
// (1=누적 미결제, 2=당일 증감). mark는 최대 증가 지점 마커 — 증감 차트만 true다.
// 누적의 최댓값은 사다리 끝(복권·보험이 쌓인 자리)이라 강조하면 오해를 만든다.
function optDraw(cv, d, fi, mark){
  window.__optLast = d;
  if(!cv || !cv.getContext) return;
  const calls = d.calls || [], puts = d.puts || [];
  if(!calls.length && !puts.length) return;
  const dpr = window.devicePixelRatio || 1;
  const w = cv.clientWidth || 340;
  // 의도한 CSS 높이는 data-h에서 읽는다. height 속성은 아래에서 우리가 덮어쓰므로
  // 거기서 되읽으면 다시 그릴 때마다 dpr배로 부푼다(190 → 570 → 1710).
  const h = parseInt(cv.getAttribute('data-h'), 10) || 190;
  cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr);
  const g = cv.getContext('2d');
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  g.clearRect(0, 0, w, h);

  const cs = getComputedStyle(document.documentElement);
  const CV = k => (cs.getPropertyValue(k) || '').trim();
  const UP = CV('--up') || '#e5342f', DN = CV('--down') || '#1f66e0';
  const LN = CV('--border') || '#dcdfe6', TX = CV('--text-3') || '#8b93a4';

  const all = calls.concat(puts);
  let kmin = Infinity, kmax = -Infinity, vmax = 0;
  const ks = [];
  all.forEach(function(r){
    const k = r[0], v = Math.abs(r[fi] || 0);
    if(k < kmin) kmin = k;
    if(k > kmax) kmax = k;
    if(v > vmax) vmax = v;
    ks.push(k);
  });
  if(!(kmax > kmin) || !vmax) return;

  const padL = 4, padR = 4, padB = 15;
  const cy = (h - padB) / 2, half = cy - 10;
  const X = k => padL + (k - kmin) / (kmax - kmin) * (w - padL - padR);
  // 막대 폭 = 인접 행사가 간격. 행사가 사다리는 등간격이라 최소 간격이 곧 한 칸.
  ks.sort(function(a, b){ return a - b; });
  let step = kmax - kmin;
  for(let i = 1; i < ks.length; i++){
    const gap = ks[i] - ks[i-1];
    if(gap > 0 && gap < step) step = gap;
  }
  const bw = Math.max(1, (X(kmin + step) - X(kmin)) - 0.5);

  // 지수 ±20% 밴드 음영 — 벽을 이 안에서만 읽는다는 걸 눈으로 보여준다.
  const spot = d.spot, pct = ((d.summary || {}).wall_pct || 20) / 100;
  if(spot){
    const x1 = Math.max(padL, X(spot * (1 - pct)));
    const x2 = Math.min(w - padR, X(spot * (1 + pct)));
    if(x2 > x1){
      g.globalAlpha = 0.05; g.fillStyle = TX;
      g.fillRect(x1, 0, x2 - x1, h - padB); g.globalAlpha = 1;
    }
  }

  // 중앙선
  g.strokeStyle = LN; g.lineWidth = 1;
  g.beginPath(); g.moveTo(padL, cy); g.lineTo(w - padR, cy); g.stroke();

  function bars(rows, color, up){
    g.fillStyle = color;
    rows.forEach(function(r){
      const v = r[fi] || 0;
      if(!v) return;
      const len = Math.abs(v) / vmax * half;
      // up이면 위로 뻗는 게 기본. 값이 음수면 부호가 뒤집혀 반대쪽으로 간다.
      const dir = (up ? -1 : 1) * (v < 0 ? -1 : 1);
      g.fillRect(X(r[0]) - bw / 2, cy, bw, dir * len);
    });
  }
  bars(calls, UP, true);
  bars(puts, DN, false);

  // 현재 지수 세로선
  if(spot && spot >= kmin && spot <= kmax){
    g.strokeStyle = TX; g.lineWidth = 1;
    g.beginPath(); g.moveTo(X(spot), 0); g.lineTo(X(spot), h - padB); g.stroke();
  }

  // 최대 증가 지점 마커 — 증감 차트에만.
  if(mark){
    [[calls, UP, true], [puts, DN, false]].forEach(function(t){
      const rows = t[0], color = t[1], up = t[2];
      let best = null;
      rows.forEach(function(r){
        const v = r[fi] || 0;
        if(v > 0 && (!best || v > best[fi])) best = r;
      });
      if(!best) return;
      const len = Math.abs(best[fi]) / vmax * half;
      const y = cy + (up ? -1 : 1) * len;
      g.fillStyle = color;
      g.beginPath(); g.arc(X(best[0]), y, 3, 0, Math.PI * 2); g.fill();
      g.font = '600 10px system-ui, sans-serif';
      const right = X(best[0]) > w * 0.75;
      g.textAlign = right ? 'right' : 'left';
      // 라벨은 막대 바깥쪽에 놓는 게 기본이지만, 값이 클수록 막대가 천장에 닿아
      // 하필 가장 중요한 마커가 잘린다 — 가장자리에 닿으면 안쪽으로 접는다.
      // (10px 폰트 기준 상하 12px 여백을 확보한다.)
      const LBL = 12;
      let ty, tb;
      if(up){
        if(y - LBL < 0){ ty = y + 4; tb = 'top'; }        // 위가 좁다 → 아래로 접기
        else { ty = y - 4; tb = 'bottom'; }
      } else {
        if(y + LBL > h - padB){ ty = y - 4; tb = 'bottom'; }  // 아래가 좁다 → 위로
        else { ty = y + 4; tb = 'top'; }
      }
      g.textBaseline = tb;
      ty = Math.min(h - padB - 2, Math.max(LBL, ty));
      const tx = Math.min(w - padR, Math.max(padL, X(best[0]) + (right ? -5 : 5)));
      g.fillText(optNum(best[0], 0) + ' +' + optNum(best[fi]), tx, ty);
    });
  }

  // 가로축 — 양 끝과 현재 지수만. 780칸에 눈금을 촘촘히 달면 글자가 겹친다.
  g.fillStyle = TX; g.font = '10px system-ui, sans-serif'; g.textBaseline = 'top';
  g.textAlign = 'left';  g.fillText(optNum(kmin, 0), padL, h - padB + 3);
  g.textAlign = 'right'; g.fillText(optNum(kmax, 0), w - padR, h - padB + 3);
  if(spot && spot >= kmin && spot <= kmax){
    g.textAlign = 'center';
    g.fillText('지수 ' + optNum(spot, 0),
               Math.min(w - 34, Math.max(34, X(spot))), h - padB + 3);
  }
}

// 접힌 줄을 폭에 맞춘다 — 들어갈 때까지 **뒤에서부터** 항목을 뺀다.
// 글자 수로 예산을 잡는 방식은 못 믿는다: 한글은 전각이라 '만' 하나가 라틴
// 두 글자 폭이고, 자릿수·월물 이름·기기 폭이 다 변수다(CDP 실측에서 31자가
// 들어가는 날과 안 들어가는 날이 갈렸다). 잘린 값은 무슨 값인지 알 수 없으므로
// 잘리게 두느니 항목 하나를 통째로 뺀다. 앞쪽일수록 중요하다.
function optFit(el, parts){
  if(!el) return;
  for(let n = parts.length; n > 0; n--){
    el.textContent = parts.slice(0, n).join(' · ');
    if(el.scrollWidth <= el.clientWidth) return;
  }
  el.textContent = parts.length ? parts[0] : '';
}

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
  // 390px에 실제로 담기는 건 28자다(CDP 실측). 풋콜·IV는 뺐다 — 둘 다 펼치면
  // 숫자 카드에 있지만 오늘의 증감은 거기에도 없고, 그게 이 설계의 주인공이다.
  // 자릿수가 늘어난 날(합계 십만 단위) 하필 그 값이 잘리면 이 줄이 무의미해진다.
  const bits = [];
  const head = [d.label, d.remain_days!=null ? 'D-'+d.remain_days : ''];
  if(head.filter(Boolean).length) bits.push(head.filter(Boolean).join(' '));
  if(s.call_chg_sum) bits.push('콜 '+optSignedShort(s.call_chg_sum));
  if(s.put_chg_sum) bits.push('풋 '+optSignedShort(s.put_chg_sum));
  optFit(document.getElementById('opt-dig'), bits);

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
