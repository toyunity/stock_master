from __future__ import annotations

"""위젯 설치 페이지(/widget-setup) — 게이트 뒤. 토큰·스크립트를 아이폰 사파리에서 복사.

파일 전송·토큰 수동 조회 단계를 통째로 없앤다(설계: 초보 최대 실패 지점 제거).
스크립트 본문에 토큰은 절대 넣지 않는다 — Scriptable은 기본으로 스크립트를
iCloud Drive에 평문 동기화하므로, 토큰은 최초 실행 시 1회 입력받아 Keychain에 저장."""

from html import escape

from backend.report.dashboard import _BASE_CSS, _PWA_HEAD

# Scriptable 위젯 스크립트 — 이 문자열이 곧 배포물이다(토큰 없음·공유-안전).
# JS는 Scriptable(JavaScriptCore) 대상: 옵셔널체이닝(?.) 등 신문법 회피.
_SCRIPT = r"""// Stock Master 아이폰 위젯 — 관심종목 시세 (중간 크기 전용)
// 이 파일에 비밀 토큰은 없습니다(최초 1회 입력 → 아이폰 Keychain 저장).
// ⚠ 이 스크립트·토큰을 타인과 공유하지 마세요 — KIS 시세 제3자 제공은 약관 위반.
const BASE = "__BASE_URL__";
const KEY = "sm_widget_token";
const CACHE = "sm_widget_cache.json";
const UP = Color.dynamic(new Color("#d32f2f"), new Color("#ff6b6b"));
const DOWN = Color.dynamic(new Color("#1565c0"), new Color("#6ba3ff"));

function cachePath() {
  // FileManager.local 고정 — iCloud는 위젯 컨텍스트에서 '미다운로드'로 못 읽고,
  // cacheDirectory는 iOS가 임의 삭제한다(설계).
  const fm = FileManager.local();
  return { fm: fm, path: fm.joinPath(fm.documentsDirectory(), CACHE) };
}
function saveCache(d) {
  try { const c = cachePath(); c.fm.writeString(c.path, JSON.stringify(d)); } catch (e) {}
}
function loadCache() {
  try {
    const c = cachePath();
    if (!c.fm.fileExists(c.path)) return null;
    return JSON.parse(c.fm.readString(c.path));
  } catch (e) { return null; }
}

async function getToken(promptIfMissing) {
  if (Keychain.contains(KEY)) return Keychain.get(KEY);
  if (!promptIfMissing) return null;
  const a = new Alert();
  a.title = "위젯 토큰 입력";
  a.message = "사파리로 " + BASE + "/widget-setup 에서 토큰을 복사해 붙여넣으세요 (1회만)";
  a.addSecureTextField("토큰");
  a.addAction("저장");
  a.addCancelAction("취소");
  if (await a.presentAlert() === -1) return null;
  const t = a.textFieldValue(0).trim();
  if (t) Keychain.set(KEY, t);
  return t || null;
}

async function fetchData(token) {
  const req = new Request(BASE + "/api/widget");
  req.timeoutInterval = 10;   // 기본 60초는 위젯 실행 예산 초과 — 맥 잠자기 = 매달리는 실패
  req.headers = { "Authorization": "Bearer " + token };
  const d = await req.loadJSON();
  if (d && d.error === "unauthorized") {
    const e = new Error("토큰이 맞지 않아요");   // 401 구분 — 오프라인과 다른 안내(스펙 에러 표)
    e.isAuth = true;
    throw e;
  }
  if (!d || !d.items) throw new Error("응답 오류 — 토큰을 확인하세요");
  return d;
}

function pad(n) { return (n < 10 ? "0" : "") + n; }
function fmtPrice(v) { return v == null ? "—" : Number(v).toLocaleString("ko-KR"); }
function fmtChg(c) {
  if (c == null) return "—";
  const s = c > 0 ? "+" : (c < 0 ? "−" : "");
  return s + Math.abs(c).toFixed(2) + "%";
}
function chgColor(c) {
  if (c == null || c === 0) return Color.gray();
  return c > 0 ? UP : DOWN;
}
function statusLabel(d) {
  if (d.open) {
    const t = new Date(d.fetched_at);
    return pad(t.getHours()) + ":" + pad(t.getMinutes()) + " 장중";
  }
  const td = new Date(d.trade_date + "T00:00:00+09:00");
  const w = "일월화수목금토".charAt(td.getDay());
  return (td.getMonth() + 1) + "/" + td.getDate() + "(" + w + ") 마감";
}

function buildWidget(d, offline) {
  const w = new ListWidget();
  w.url = BASE + "/";   // 몸통 탭 → 대시보드(미지정 시 편집기가 열려 초보 사고 지점)
  const fam = config.widgetFamily || "medium";   // 앱 내 미리보기(null) = medium 취급
  if (d && d.refresh_after_sec)
    w.refreshAfterDate = new Date(Date.now() + d.refresh_after_sec * 1000);
  const head = w.addStack();
  const title = head.addText("관심종목");
  title.font = Font.boldSystemFont(13);
  head.addSpacer();
  const brand = head.addText("STOCK MASTER");
  brand.font = Font.mediumSystemFont(9);
  brand.textColor = Color.gray();
  w.addSpacer(4);
  if (!d) {
    const t = w.addText("서버에 연결할 수 없어요.\n스크립트를 실행해 토큰을 확인하세요.");
    t.font = Font.systemFont(12);
    return w;
  }
  const max = fam === "large" ? 10 : 5;
  const items = d.items.slice(0, max);
  for (let i = 0; i < items.length; i++) {
    const it = items[i];
    const row = w.addStack();
    row.centerAlignContent();
    const nm = row.addText(it.name);
    nm.font = Font.mediumSystemFont(13);
    nm.lineLimit = 1;
    nm.minimumScaleFactor = 0.7;   // 'LG에너지솔루션' 등 긴 이름 완충
    row.addSpacer();
    const px = row.addText(fmtPrice(it.price));
    px.font = Font.mediumSystemFont(13);
    const ch = row.addText("  " + fmtChg(it.change));
    ch.font = Font.boldSystemFont(12);
    ch.textColor = chgColor(it.change);
    w.addSpacer(2);
  }
  if (d.items.length > max) {
    const more = w.addText("+" + (d.items.length - max) + "종목");
    more.font = Font.systemFont(10);
    more.textColor = Color.gray();
  }
  w.addSpacer();
  const foot = w.addStack();
  foot.centerAlignContent();
  const st = foot.addText((offline ? "오프라인 · " : "") + statusLabel(d));
  st.font = Font.systemFont(10);
  st.textColor = offline ? Color.orange() : Color.gray();
  foot.addSpacer();
  const rf = foot.addStack();   // ↻ 갱신: 자체 url — 몸통 탭(대시보드)과 영역 구분
  rf.url = "scriptable:///run/" + encodeURIComponent(Script.name()) + "?mode=refresh";
  const rt = rf.addText("↻ 갱신");
  rt.font = Font.boldSystemFont(10);
  rt.textColor = Color.gray();
  return w;
}

function buildAuthError() {
  // 401: 캐시 폴백이 아니라 재입력 안내(스펙 §에러 처리 — 토큰 회전 직후 '오프라인' 오진단 방지)
  const w = new ListWidget();
  w.url = BASE + "/widget-setup";
  const t = w.addText("토큰이 맞지 않아요");
  t.font = Font.boldSystemFont(13);
  w.addSpacer(4);
  const s = w.addText("Scriptable에서 이 스크립트를 ▶ 실행해 '토큰 다시 입력'을 선택하세요.");
  s.font = Font.systemFont(11);
  s.textColor = Color.gray();
  return w;
}

async function showLive(token) {
  // ↻ 갱신: 앱에서 즉시 KIS 최신 시세를 전체 화면 표로 + 캐시 갱신.
  // (위젯 숫자의 즉시 갱신은 iOS가 허용하지 않음 — 다음 OS 갱신 때 반영)
  let d = null, err = "";
  try { d = await fetchData(token); saveCache(d); } catch (e) { err = String(e); }
  const t = new UITable();
  t.showSeparators = true;
  const hr = new UITableRow();
  hr.isHeader = true;
  hr.addText(d ? "실시간 시세 · " + statusLabel(d) : "갱신 실패: " + err);
  t.addRow(hr);
  const items = d ? d.items : ((loadCache() || {}).items || []);
  for (let i = 0; i < items.length; i++) {
    const it = items[i];
    const r = new UITableRow();
    r.height = 48;
    r.addText(it.name, it.code);
    r.addText(fmtPrice(it.price) + "   " + fmtChg(it.change)).rightAligned();
    t.addRow(r);
  }
  await t.present(false);
}

const params = args.queryParameters || {};
if (config.runsInWidget) {
  const token = await getToken(false);
  let data = null, offline = false, authError = false;
  if (token) {
    try { data = await fetchData(token); saveCache(data); }
    catch (e) {
      if (e && e.isAuth) { authError = true; }        // 401 → 재입력 안내(캐시 폴백 아님)
      else { data = loadCache(); offline = true; }    // 그 외 실패 = 캐시 + 오프라인 배지
    }
  } else {
    data = loadCache();
    offline = true;
  }
  Script.setWidget(authError ? buildAuthError() : buildWidget(data, offline));
} else if (params.mode === "refresh") {
  const token = await getToken(true);
  if (token) await showLive(token);
} else if (!Keychain.contains(KEY)) {
  // 최초 설치: 토큰 입력 → 다음 단계 안내
  const token = await getToken(true);
  if (token) {
    const a = new Alert();
    a.title = "설정 완료";
    a.message = "홈 화면을 길게 눌러 Scriptable 위젯(중간 크기)을 추가하고,\n위젯 편집에서 Script를 이 스크립트로 지정하세요.";
    a.addAction("확인");
    await a.presentAlert();
  }
} else {
  // 재실행 메뉴 — 토큰 회전(가이드 문제해결) 시 '토큰 다시 입력'이 실제로 동작해야 한다
  const a = new Alert();
  a.title = "Stock Master 위젯";
  a.addAction("실시간 시세 보기");
  a.addAction("토큰 다시 입력");
  a.addCancelAction("닫기");
  const i = await a.presentAlert();
  if (i === 0) await showLive(Keychain.get(KEY));
  else if (i === 1) await reenterToken();
}

async function reenterToken() {
  // 토큰 회전 — 새 값을 먼저 받고 비어있지 않을 때만 덮어쓴다. 취소/빈 입력이면
  // 기존 토큰을 그대로 둔다(먼저 지우면 취소 한 번에 정상 위젯이 깨진다 — 리뷰 2026-07-16).
  const a = new Alert();
  a.title = "토큰 다시 입력";
  a.message = BASE + "/widget-setup 에서 새 토큰을 복사해 붙여넣으세요.";
  a.addSecureTextField("토큰");
  a.addAction("저장");
  a.addCancelAction("취소");
  if (await a.presentAlert() === -1) return;
  const t = a.textFieldValue(0).trim();
  if (t) Keychain.set(KEY, t);
}
Script.complete();
"""

_TEMPLATE = """<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>위젯 설치 — Stock Master</title>
__PWA_HEAD__
<style>
__BASE_CSS__
.step{margin:14px 0;padding:14px;background:var(--surface);border:1px solid var(--border);
  border-radius:var(--r)}
.step h3{margin:0 0 6px;font-size:15px}
.step p{margin:0;font-size:13px;color:var(--text-2);line-height:1.6}
.tok{font-family:ui-monospace,Menlo,monospace;font-size:13px;word-break:break-all;
  background:var(--surface-2);border:1px solid var(--border);border-radius:var(--r-sm);
  padding:10px 12px;margin:8px 0}
pre#script{font-family:ui-monospace,Menlo,monospace;font-size:11px;line-height:1.5;
  background:var(--surface-2);border:1px solid var(--border);border-radius:var(--r-sm);
  padding:12px;max-height:300px;overflow:auto;white-space:pre-wrap;word-break:break-all}
button.copy{min-height:44px;padding:10px 18px;border:0;border-radius:var(--r-sm);
  background:var(--primary);color:#fff;font-size:14px;font-weight:700;cursor:pointer}
.warn{background:var(--warn-bg);border:1px solid var(--border);border-radius:var(--r);
  padding:12px 14px;font-size:13px;margin:14px 0}
</style></head><body>
<div id="app"><div id="app-scroll">
<div><a class="back" href="/">← 대시보드</a></div>
<h1>📱 아이폰 위젯 설치</h1>
<div class="warn">⚠ 이 페이지의 토큰과 스크립트를 <b>타인과 공유하지 마세요</b> —
KIS 시세 제3자 제공은 약관 위반입니다. 자세한 사용법: docs/widget-guide.md</div>
<div class="step"><h3>1. App Store에서 “Scriptable” 설치 (무료)</h3>
<p>애플 개발자 계정·컴퓨터 불필요.</p></div>
<div class="step"><h3>2. 아래 스크립트 전체 복사 → Scriptable 새 스크립트에 붙여넣기</h3>
<p>Scriptable 앱 → 우상단 ＋ → 붙여넣기 → 이름을 <b>StockMaster</b>로 저장.</p>
<p style="margin-top:8px"><button class="copy" onclick="copyScript()">스크립트 전체 복사</button>
<span id="copied1" style="font-size:12px;color:var(--good)"></span></p>
<pre id="script">__SCRIPT__</pre></div>
<div class="step"><h3>3. 스크립트 실행(▶) → 토큰 붙여넣기 (1회)</h3>
<p>아래 토큰을 복사해 두세요. 토큰은 아이폰 Keychain에 저장되고 파일엔 남지 않습니다.</p>
<div class="tok" id="token">__TOKEN__</div>
<p><button class="copy" onclick="copyToken()">토큰 복사</button>
<span id="copied2" style="font-size:12px;color:var(--good)"></span></p></div>
<div class="step"><h3>4. 홈 화면 길게 누르기 → ＋ → Scriptable → <b>중간 크기</b> → 추가</h3>
<p>작게/크게 말고 중간(4×2)을 선택하세요.</p></div>
<div class="step"><h3>5. 위젯 길게 누르기 → 위젯 편집 → Script: <b>StockMaster</b> 지정</h3>
<p>⚠ 이 단계를 빼먹으면 “Tap to configure” 상태로 남습니다 — 가장 흔한 실수.</p></div>
<script>
function _copy(id, mark){
  const t = document.getElementById(id).textContent;
  navigator.clipboard.writeText(t).then(function(){
    document.getElementById(mark).textContent = ' ✓ 복사됨';
  });
}
function copyScript(){ _copy('script', 'copied1'); }
function copyToken(){ _copy('token', 'copied2'); }
</script>
</div></div></body></html>"""


def render_widget_setup(token: str, base_url: str) -> str:
    """설치 페이지 HTML — 토큰은 이 페이지(게이트 뒤)에만, 스크립트엔 절대 없음."""
    script = _SCRIPT.replace("__BASE_URL__", base_url.rstrip("/"))
    return (_TEMPLATE
            .replace("__PWA_HEAD__", _PWA_HEAD)
            .replace("__BASE_CSS__", _BASE_CSS)
            .replace("__SCRIPT__", escape(script))
            .replace("__TOKEN__", escape(token)))
