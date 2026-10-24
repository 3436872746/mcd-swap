#!/usr/bin/env python3
"""Thin wrapper: call a McDonald's MCP tool and return its parsed JSON payload."""
import json
import re
import sys

from .client import MCP


def unwrap(text):
    m = re.search(r"##\s*Original Response\s*", text)
    body = text[m.end():] if m else text
    cands = [i for i in (body.find("{"), body.find("[")) if i >= 0]
    if not cands:
        return {"_raw": text}
    try:
        obj, _end = json.JSONDecoder().raw_decode(body[min(cands):])
        return obj
    except ValueError:
        return {"_raw": text}


import threading

_local = threading.local()


def client():
    c = getattr(_local, "c", None)
    if c is None:
        c = MCP()
        c.handshake()
        _local.c = c
    return c


def call(tool, args=None):
    out = client()._rpc("tools/call", {"name": tool, "arguments": args or {}})
    res = out["result"]
    if res.get("isError"):
        raise RuntimeError(json.dumps(res, ensure_ascii=False)[:800])
    return unwrap(res["content"][0]["text"])


if __name__ == "__main__":
    print(json.dumps(call(sys.argv[1], json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}),
                     ensure_ascii=False, indent=1))
