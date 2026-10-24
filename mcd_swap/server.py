#!/usr/bin/env python3
"""McSolver — an MCP server that plans McDonald's meals as a constrained
optimisation problem, using the official mcd.mcd.cn tools for menu, nutrition,
combo structure and price verification.

Transport: stdio (JSON-RPC 2.0, one message per line).
"""
import json
import os
import sys


from . import api as mcd
from . import planner
from . import nutrition as resolver

PROTO = "2025-06-18"
SERVER = {"name": "mcsolver", "version": "0.1.0"}

TOOLS = [
    {
        "name": "plan_meal",
        "description": (
            "在麦当劳真实菜单上做约束优化配餐。枚举所有套餐 × 所有换购组合，"
            "满足热量/蛋白质/预算约束，返回经官方 calculate-price 复核价格的方案。"
            "适合“600 大卡以内的高蛋白午餐”“35 元怎么吃到最多蛋白质”这类问题。"),
        "inputSchema": {
            "type": "object",
            "properties": {
                "kcal_max": {"type": "number", "description": "热量上限 kcal"},
                "protein_min": {"type": "number", "description": "蛋白质下限 g"},
                "budget_max": {"type": "number", "description": "预算上限 元"},
                "objective": {"type": "string",
                              "enum": list(planner.OBJECTIVES),
                              "description": "protein_per_yuan=性价比, lean=最高蛋白, "
                                             "kcal_fit=最接近目标热量, cheapest=最便宜"},
                "kcal_target": {"type": "number", "description": "objective=kcal_fit 时的目标热量"},
                "top_n": {"type": "integer", "default": 3},
                "store_code": {"type": "string", "description": "门店编码，省略则用默认门店"},
            },
        },
    },
    {
        "name": "find_store",
        "description": "按城市/关键词查麦当劳门店，返回 storeCode（plan_meal 需要）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "city": {"type": "string"},
                "keyword": {"type": "string"},
            },
            "required": ["city"],
        },
    },
    {
        "name": "item_nutrition",
        "description": "查询单个餐品的官方营养成分（热量、蛋白质、脂肪、碳水、钠、钙）。",
        "inputSchema": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    },
]


def do_plan(a):
    args = planner.argparse.Namespace(
        kcal=a.get("kcal_max"), protein=a.get("protein_min"),
        budget=a.get("budget_max"), objective=a.get("objective", "protein_per_yuan"),
        top=1, check=False, kcal_target=a.get("kcal_target"))
    if a.get("store_code"):
        planner.STORE = a["store_code"]
    if args.objective == "kcal_fit":
        args.kcal = args.kcal_target or args.kcal
        rows = planner.search(args)[: a.get("top_n", 3)]
        out = []
        for r in rows:
            r["score"] = abs(r["nut"]["kcal"] - (args.kcal_target or 0))
        rows.sort(key=lambda r: r["score"])
    else:
        rows = planner.search(args)[: a.get("top_n", 3)]
    plans = []
    for r in rows:
        real = planner.verify(r)
        plans.append({
            "combo": r["combo"].name,
            "price": r["price"],
            "price_verified": real,
            "price_ok": abs(real - r["price"]) < 0.01,
            "kcal": round(r["nut"]["kcal"]),
            "protein_g": round(r["nut"]["protein"], 1),
            "fat_g": round(r["nut"]["fat"], 1),
            "carb_g": round(r["nut"]["carb"], 1),
            "sodium_mg": round(r["nut"]["sodium"]),
            "swaps": r["diff"],
        })
    return {"plans": plans, "candidates_examined": len(rows)}


def do_stores(a):
    d = mcd.call("query-nearby-stores",
                 {"beType": 1, "searchType": 2, "city": a["city"],
                  "keyword": a.get("keyword", "")})
    return [{"store_code": s["storeCode"], "name": s["storeName"],
             "address": s.get("address"), "distance_m": s.get("distance"),
             "open": f"{s.get('businessStartTime')}-{s.get('businessEndTime')}"}
            for s in (d.get("data") or [])]


def do_nutrition(a):
    n = resolver.lookup(a["name"])
    return n or {"error": f"营养表中没有“{a['name']}”"}


HANDLERS = {"plan_meal": do_plan, "find_store": do_stores, "item_nutrition": do_nutrition}


def send(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def handle(msg):
    mid, method = msg.get("id"), msg.get("method")
    if method == "initialize":
        return send({"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": PROTO, "capabilities": {"tools": {}},
            "serverInfo": SERVER}})
    if method == "tools/list":
        return send({"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}})
    if method == "ping":
        return send({"jsonrpc": "2.0", "id": mid, "result": {}})
    if method.startswith("notifications/"):
        return None
    if method == "tools/call":
        name = msg["params"]["name"]
        args = msg["params"].get("arguments") or {}
        try:
            out = HANDLERS[name](args)
            text = json.dumps(out, ensure_ascii=False, indent=1)
            return send({"jsonrpc": "2.0", "id": mid, "result": {
                "content": [{"type": "text", "text": text}], "isError": False}})
        except Exception as e:  # noqa: BLE001
            return send({"jsonrpc": "2.0", "id": mid, "result": {
                "content": [{"type": "text", "text": f"{type(e).__name__}: {e}"}],
                "isError": True}})
    if mid is not None:
        send({"jsonrpc": "2.0", "id": mid,
              "error": {"code": -32601, "message": f"unknown method {method}"}})


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            handle(json.loads(line))
        except Exception as e:  # noqa: BLE001
            print("mcsolver: bad message:", e, file=sys.stderr)


if __name__ == "__main__":
    main()
