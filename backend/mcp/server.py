from __future__ import annotations

"""의존성 없는 경량 MCP stdio 서버 (Python 3.9 호환 — 공식 mcp SDK는 3.10+라 미사용).

MCP stdio transport = newline-delimited JSON-RPC 2.0. 지원 메서드: initialize,
tools/list, tools/call, ping. 프로토콜은 stdout 전용, 로그는 stderr로만 보낸다.

Claude Desktop 연결: claude_desktop_config.json 에
  "stock-master": {"command": "<repo>/.venv/bin/python", "args": ["-m", "backend.mcp.server"], "cwd": "<repo>"}
"""

import json
import sys

from backend.mcp import tools

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "stock-master", "version": "0.1.0"}

TOOLS = [
    {"name": "watchlist_summary",
     "description": "관심종목 전체의 오늘 분석 요약(신호·현재가·근거·뉴스/공시). 인자 없음.",
     "inputSchema": {"type": "object", "properties": {}},
     "func": lambda a: tools.watchlist_summary()},
    {"name": "stock_detail",
     "description": "특정 종목(6자리 코드)의 상세 분석(신호·근거·백테스트·뉴스/공시).",
     "inputSchema": {"type": "object",
                     "properties": {"code": {"type": "string", "description": "6자리 종목코드 (예: 005930)"}},
                     "required": ["code"]},
     "func": lambda a: tools.stock_detail(a["code"])},
    {"name": "search_stocks",
     "description": "전체 KRX 종목을 이름/코드로 검색(현재가·등락률 포함).",
     "inputSchema": {"type": "object",
                     "properties": {"query": {"type": "string", "description": "이름 또는 코드 일부"},
                                    "limit": {"type": "integer", "description": "최대 결과 수(기본 20)"}},
                     "required": ["query"]},
     "func": lambda a: tools.search_stocks(a["query"], int(a.get("limit", 20)))},
    {"name": "chart_data",
     "description": "특정 종목 최근 120일 캔들(JSON: time/open/high/low/close) — 차트 시각화용.",
     "inputSchema": {"type": "object",
                     "properties": {"code": {"type": "string", "description": "6자리 종목코드"}},
                     "required": ["code"]},
     "func": lambda a: tools.chart_data(a["code"])},
]
_BY_NAME = {t["name"]: t for t in TOOLS}


def _log(msg):
    print(msg, file=sys.stderr, flush=True)


def _send(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _result(id_, result):
    _send({"jsonrpc": "2.0", "id": id_, "result": result})


def _error(id_, code, message):
    _send({"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}})


def handle(msg):
    method = msg.get("method")
    id_ = msg.get("id")
    if id_ is None:
        return  # 알림(notification) — 응답하지 않는다
    if method == "initialize":
        client_ver = (msg.get("params") or {}).get("protocolVersion") or PROTOCOL_VERSION
        _result(id_, {"protocolVersion": client_ver,
                      "capabilities": {"tools": {}},
                      "serverInfo": SERVER_INFO})
    elif method == "ping":
        _result(id_, {})
    elif method == "tools/list":
        listed = [{k: t[k] for k in ("name", "description", "inputSchema")} for t in TOOLS]
        _result(id_, {"tools": listed})
    elif method == "tools/call":
        params = msg.get("params") or {}
        tool = _BY_NAME.get(params.get("name"))
        if tool is None:
            _error(id_, -32602, f"unknown tool: {params.get('name')}")
            return
        try:
            text = tool["func"](params.get("arguments") or {})
            _result(id_, {"content": [{"type": "text", "text": str(text)}]})
        except Exception as e:
            _result(id_, {"content": [{"type": "text", "text": f"오류: {type(e).__name__}: {e}"}],
                          "isError": True})
    else:
        _error(id_, -32601, f"method not found: {method}")


def main():
    _log("stock-master MCP server (stdio) 시작")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        try:
            handle(msg)
        except Exception as e:  # 한 메시지 오류가 서버를 죽이지 않게
            _log(f"handle 오류: {e}")


if __name__ == "__main__":
    main()
