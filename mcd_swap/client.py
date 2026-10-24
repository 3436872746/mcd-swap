#!/usr/bin/env python3
"""Minimal MCP client (Streamable HTTP, stdlib only) for mcp.mcd.cn."""
import json
import os
import sys
import urllib.request
import urllib.error

URL = os.environ.get("MCD_MCP_URL", "https://mcp.mcd.cn")
TOKEN = os.environ.get("MCD_MCP_TOKEN", "")
PROTO = "2025-06-18"


class MCP:
    def __init__(self):
        self.session = None
        self._id = 0

    def _post(self, payload, expect_reply=True):
        data = json.dumps(payload).encode()
        req = urllib.request.Request(URL, data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("Accept", "application/json, text/event-stream")
        req.add_header("Authorization", "Bearer " + (TOKEN or _file_token()))
        req.add_header("MCP-Protocol-Version", PROTO)
        if self.session:
            req.add_header("Mcp-Session-Id", self.session)
        with urllib.request.urlopen(req, timeout=60) as r:
            sid = r.headers.get("Mcp-Session-Id") or r.headers.get("mcp-session-id")
            if sid:
                self.session = sid
            ctype = r.headers.get("Content-Type", "")
            raw = r.read().decode("utf-8", "replace")
        if not expect_reply:
            return None
        if "text/event-stream" in ctype:
            for line in raw.splitlines():
                if line.startswith("data:"):
                    body = line[5:].strip()
                    if body:
                        return json.loads(body)
            raise RuntimeError("SSE stream had no data line:\n" + raw[:500])
        return json.loads(raw) if raw.strip() else None

    def _rpc(self, method, params=None, notify=False):
        msg = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        if not notify:
            self._id += 1
            msg["id"] = self._id
        out = self._post(msg, expect_reply=not notify)
        if out and "error" in out:
            raise RuntimeError(json.dumps(out["error"], ensure_ascii=False))
        return out

    def handshake(self):
        out = self._rpc("initialize", {
            "protocolVersion": PROTO,
            "capabilities": {},
            "clientInfo": {"name": "mcd-hack-cli", "version": "0.1"},
        })
        self._rpc("notifications/initialized", notify=True)
        return out


def main():
    m = MCP()
    info = m.handshake()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"
    if cmd == "init":
        print(json.dumps(info, ensure_ascii=False, indent=2))
    elif cmd == "list":
        tools = m._rpc("tools/list", {})["result"]["tools"]
        print(json.dumps(tools, ensure_ascii=False, indent=2))
    elif cmd == "call":
        args = json.loads(sys.argv[3]) if len(sys.argv) > 3 else {}
        out = m._rpc("tools/call", {"name": sys.argv[2], "arguments": args})
        print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()


def _file_token():
    p = os.path.expanduser("~/.mcd_token")
    if not os.path.exists(p):
        raise SystemExit("set MCD_MCP_TOKEN or create ~/.mcd_token")
    return open(p).read().strip()
