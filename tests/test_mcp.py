import backend.mcp.server as srv


def _capture(monkeypatch):
    sent = []
    monkeypatch.setattr(srv, "_send", lambda o: sent.append(o))
    return sent


def test_initialize_echoes_protocol_and_server_info(monkeypatch):
    sent = _capture(monkeypatch)
    srv.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": "2025-01-01"}})
    r = sent[0]["result"]
    assert r["serverInfo"]["name"] == "stock-master"
    assert r["protocolVersion"] == "2025-01-01"   # 클라이언트 버전 에코
    assert "tools" in r["capabilities"]


def test_notification_gets_no_response(monkeypatch):
    sent = _capture(monkeypatch)
    srv.handle({"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert sent == []   # id 없는 알림은 무응답


def test_tools_list_exposes_all_tools_with_schema(monkeypatch):
    sent = _capture(monkeypatch)
    srv.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    listed = sent[0]["result"]["tools"]
    names = {t["name"] for t in listed}
    assert {"watchlist_summary", "stock_detail", "search_stocks", "chart_data"} <= names
    for t in listed:
        assert t["inputSchema"]["type"] == "object"
        assert "func" not in t   # 내부 구현(func)은 노출 금지


def test_tools_call_dispatches_arguments(monkeypatch):
    monkeypatch.setattr(srv.tools, "search_stocks", lambda q, limit=20: f"FAKE:{q}:{limit}")
    sent = _capture(monkeypatch)
    srv.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                "params": {"name": "search_stocks", "arguments": {"query": "삼성", "limit": 5}}})
    assert sent[0]["result"]["content"][0]["text"] == "FAKE:삼성:5"


def test_tools_call_unknown_tool_errors(monkeypatch):
    sent = _capture(monkeypatch)
    srv.handle({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                "params": {"name": "nope", "arguments": {}}})
    assert "error" in sent[0]


def test_tools_call_exception_returns_iserror(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("x")
    monkeypatch.setattr(srv.tools, "watchlist_summary", boom)
    sent = _capture(monkeypatch)
    srv.handle({"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                "params": {"name": "watchlist_summary", "arguments": {}}})
    assert sent[0]["result"]["isError"] is True


def test_unknown_method_returns_method_not_found(monkeypatch):
    sent = _capture(monkeypatch)
    srv.handle({"jsonrpc": "2.0", "id": 6, "method": "foo/bar"})
    assert sent[0]["error"]["code"] == -32601
