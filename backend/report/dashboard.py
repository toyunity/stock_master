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
from backend.news.names import display_name

_LIB_PATH = Path(__file__).parent.parent / "api" / "static" / "lightweight-charts.js"

_PWA_HEAD = (
    '<meta name="theme-color" content="#1565c0">'
    '<link rel="manifest" href="/manifest.json">'
    '<link rel="apple-touch-icon" href="/icons/icon-180.png">'
    '<meta name="apple-mobile-web-app-capable" content="yes">'
    '<meta name="mobile-web-app-capable" content="yes">'
    '<meta name="apple-mobile-web-app-status-bar-style" content="default">'
    '<meta name="apple-mobile-web-app-title" content="Stock Master">'
)

# 페이지 전환 로딩 바 — 내부 링크 클릭/이탈 시 상단 진행 바(전 페이지 공용).
# 자기완결 HTML이 커서(차트 라이브러리 inline) 전환 공백이 체감됨 → 즉각 피드백.
# bfcache 복귀(pageshow)에서 제거해 뒤로가기 잔상을 막는다.
_NAV_LOADER = """<style>#navload{position:fixed;top:0;left:0;height:3px;width:0;
background:linear-gradient(90deg,#1565c0,#42a5f5);z-index:9999;pointer-events:none;
transition:width .5s ease;border-radius:0 2px 2px 0}
#navload.on{width:85%}
#navload.done{width:100%;opacity:0;transition:width .15s,opacity .3s .15s}</style>
<script>(function(){
var bar=null;
function el(){if(!bar){bar=document.createElement('div');bar.id='navload';document.body.appendChild(bar);}return bar;}
function show(){var b=el();b.classList.remove('done');void b.offsetWidth;b.classList.add('on');}
document.addEventListener('click',function(e){
  var t=e.target; while(t&&t.tagName!=='A')t=t.parentElement;
  if(!t||!t.getAttribute)return;
  var href=t.getAttribute('href')||'';
  if(!href||href[0]==='#'||t.target==='_blank'||t.hasAttribute('download'))return;
  if(/^(javascript:|mailto:|tel:)/i.test(href))return;
  if(t.origin&&t.origin!==location.origin)return;
  show();
},true);
window.addEventListener('beforeunload',function(){show();});
window.addEventListener('pageshow',function(){
  if(bar){bar.classList.remove('on');bar.classList.add('done');
    setTimeout(function(){if(bar){bar.remove();bar=null;}},500);}
});
})();</script>"""

_DISCLAIMER = (
    "⚠️ 투자 유의 안내 — 본 애플리케이션이 제공하는 모든 정보·분석·신호는 참고용이며, "
    "특정 종목의 매수·매도를 권유하지 않습니다. 모든 투자 판단과 그 결과에 대한 책임은 "
    "이용자 본인에게 있습니다. 과거 성과(백테스트)는 미래 수익을 보장하지 않습니다. "
    "데이터는 FDR·DART·KRX·언론사 등에서 수집되며 오류·지연이 있을 수 있습니다."
)

_TEMPLATE = """<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Stock Master 대시보드 __DATE__</title>
__PWA_HEAD__
<style>
body{font-family:-apple-system,"Apple SD Gothic Neo","Malgun Gothic",sans-serif;
  max-width:760px;margin:0 auto;padding:16px;color:#1a1a2e;background:#f7f8fb}
h1{font-size:20px;margin:0 0 4px} .sub{color:#888;font-size:12px;margin-bottom:10px}
.refresh{font-size:14px;padding:8px 14px;border:1px solid #1565c0;background:#1565c0;
  color:#fff;border-radius:8px;cursor:pointer;margin-bottom:8px}
.search{background:#fff;border:1px solid #e0e3eb;border-radius:12px;padding:12px;margin:10px 0}
.search input{width:100%;font-size:16px;padding:10px;border:1px solid #ccc;border-radius:8px;box-sizing:border-box}
.srow{padding:8px 4px;border-bottom:1px solid #f0f0f0;font-size:14px;display:flex;justify-content:space-between}
.spx{font-size:12px;color:#666}
.card{border:1px solid #e0e3eb;border-radius:12px;padding:14px;margin:12px 0;background:#fff}
.buy{border-left:5px solid #1565c0} .sell{border-left:5px solid #c62828} .hold{border-left:5px solid #9e9e9e}
.badge{font-size:12px;padding:2px 8px;border-radius:10px;color:#fff}
.b-buy{background:#1565c0} .b-sell{background:#c62828} .b-hold{background:#9e9e9e}
.name{font-size:17px;font-weight:700;color:inherit;text-decoration:none}
a.name:active{opacity:.6} .code{font-size:12px;color:#999;font-weight:400}
.conf{font-size:13px;color:#555;margin-top:4px}
.chg{font-weight:600} .chg.up{color:#c62828} .chg.down{color:#1565c0}
.chart{height:180px;margin:8px 0}
ul{margin:6px 0 0 0;padding-left:18px} li{font-size:14px}
.bt{font-size:12px;color:#1565c0;margin-top:6px;background:#eef4fc;padding:6px 8px;border-radius:6px}
.issues{margin-top:8px;border-top:1px dashed #e0e3eb;padding-top:8px}
.issues-label{font-size:12px;color:#888} .issues h4{font-size:13px;margin:8px 0 2px;color:#444}
.issues ul{margin:2px 0 0 0} .issues li{font-size:13px;margin:2px 0} .issues a{color:#1565c0;text-decoration:none}
.meta{font-size:11px;color:#999}
.disc{font-size:12px;color:#666;background:#fff3cd;border:1px solid #ffe69c;padding:10px;border-radius:8px;margin-top:16px}
</style></head><body>
<h1>📊 Stock Master <small style="font-size:13px;color:#888">__DATE__</small></h1>
<div class="sub">관심종목 분석 · 뉴스/공시 · 차트 — 모든 정보는 참고용(매매 권유 아님)
 · <a href="/scanner" style="color:#1565c0;text-decoration:none">🔍 수급 스캐너</a></div>
__REFRESH__
<div class="search">
  <input id="q" placeholder="🔎 종목 검색 (이름/코드, 예: 하이닉스) — 조회용">
  <div id="results"></div>
</div>
<div id="cards"></div>
<div class="disc">__DISCLAIMER__</div>
<script>__LIB__</script>
<script>
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
  if(s.close!=null) h+=' · <b>'+won(s.close)+'</b> '+chg(s.change);
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
  const chart=LightweightCharts.createChart(el,{autoSize:true,height:180,
    layout:{background:{color:'#fff'},textColor:'#999',fontSize:10},
    grid:{vertLines:{color:'#f4f4f4'},horzLines:{color:'#f4f4f4'}},
    rightPriceScale:{borderColor:'#eee'},timeScale:{borderColor:'#eee'}});
  const series=chart.addCandlestickSeries({upColor:'#c62828',downColor:'#1565c0',
    borderVisible:false,wickUpColor:'#c62828',wickDownColor:'#1565c0'});
  series.setData(s.candles); chart.timeScale().fitContent();
});
const q=document.getElementById('q'), res=document.getElementById('results');
function searchRender(items){
  if(!items.length){res.innerHTML='<div class="meta" style="padding:8px">검색 결과 없음</div>';return;}
  res.innerHTML=items.slice(0,30).map(u=>'<div class="srow"><span><a href="/live/'+esc(u.code)+'">'+esc(u.name)+' 📡</a> <span class="code">'+esc(u.code)+'</span></span><span class="spx">'+(u.close!=null?won(u.close)+' ':'')+chg(u.change)+'</span></div>').join('');
}
q.oninput=()=>{
  const t=q.value.trim().toLowerCase();
  if(!t){res.innerHTML='';return;}
  searchRender(D.universe.filter(u=>u.name.toLowerCase().includes(t)||u.code.indexOf(t)>=0));
};
</script>__NAV_LOADER__</body></html>"""


def to_candles(df, days: int = 120) -> list:
    """가격 DataFrame → Lightweight Charts 캔들({time,open,high,low,close}).

    날짜 오름차순·중복 제거(라이브러리가 strictly ascending unique를 요구)."""
    d = df[~df.index.duplicated(keep="last")].sort_index().tail(days)
    out = []
    for idx, r in d.iterrows():
        out.append({"time": idx.strftime("%Y-%m-%d"),
                    "open": round(float(r["Open"]), 2), "high": round(float(r["High"]), 2),
                    "low": round(float(r["Low"]), 2), "close": round(float(r["Close"]), 2)})
    return out


def assemble_stock(signal, issues, candles, price) -> dict:
    """신호 + 이슈 + 캔들 + 현재가를 대시보드 종목 dict로 합친다."""
    iv = _issues_view(issues)
    return {"code": signal.code, "name": display_name(signal.code),
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
            .replace("__DATE__", escape(date))
            .replace("__NAV_LOADER__", _NAV_LOADER)
            .replace("__PWA_HEAD__", _PWA_HEAD if pwa else "")
            .replace("__REFRESH__", refresh)
            .replace("__DISCLAIMER__", escape(_DISCLAIMER))
            .replace("__DATA__", data_json)
            .replace("__LIB__", lib))
