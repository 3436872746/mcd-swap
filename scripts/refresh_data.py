#!/usr/bin/env python3
"""Re-pull menu / combo structure / nutrition from the official MCP server."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from mcd_swap import api, nutrition, planner   # noqa: E402


def main():
    store = os.environ.get("MCD_STORE", planner.STORE)
    data = os.environ.get("MCD_DATA") or os.path.join(os.path.dirname(__file__), "..", "data")
    details = os.path.join(data, "details")
    os.makedirs(details, exist_ok=True)

    raw = api.call("query-meals", {"storeCode": store, "orderType": 1, "beType": 1})
    meals = raw["data"]["meals"]
    cat = {m["code"]: c["name"] for c in raw["data"]["categories"] for m in c["meals"]}
    items = [{"code": k, "name": v.get("name"), "price": float(v.get("currentPrice") or 0),
              "originalPrice": float(v.get("originalPrice") or 0), "category": cat.get(k, ""),
              "discountType": v.get("discountType")} for k, v in meals.items()]
    json.dump(items, open(os.path.join(data, "menu.json"), "w"), ensure_ascii=False, indent=1)
    print("menu:", len(items), "items")

    for it in items:
        d = api.call("query-meal-detail", {"storeCode": store, "orderType": 1, "beType": 1, "code": it["code"]})
        json.dump(d, open(os.path.join(details, it["code"] + ".json"), "w"), ensure_ascii=False)
    print("details:", len(items))

    nut = api.call("list-nutrition-foods", {})
    json.dump(nut, open(os.path.join(data, "nutrition.json"), "w"), ensure_ascii=False)
    print("nutrition: ok")


if __name__ == "__main__":
    main()
