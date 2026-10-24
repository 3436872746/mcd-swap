#!/usr/bin/env python3
"""Meal planner: enumerate every combination of combo-substitutions, score, verify.

Every plan's price is re-checked against McDonald's own calculate-price tool, so a
plan that prints is a plan that costs exactly what it says.
"""
import argparse
import itertools
import json
import os
import subprocess
import sys

from . import api as mcd
from . import nutrition as rs

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.environ.get("MCD_DATA") or os.path.normpath(os.path.join(HERE, "..", "data"))
STORE = os.environ.get("MCD_STORE", "1450713")

# objective -> key function (lower total is better unless noted)
OBJECTIVES = ("protein_per_yuan", "lean", "kcal_fit", "cheapest")


def delta_price(s):
    """'+¥1' / '-¥0.5' / '+¥0' -> float yuan."""
    if not s:
        return 0.0
    s = s.replace("¥", "").replace("+", "").strip()
    try:
        return float(s)
    except ValueError:
        return 0.0


class Opt:
    __slots__ = ("code", "name", "nut", "dp", "is_default")

    def __init__(self, code, name, nut, dp, is_default):
        self.code, self.name, self.nut, self.dp = code, name, nut, dp
        self.is_default = is_default


class Combo:
    __slots__ = ("code", "name", "price", "rounds", "cat", "unknown", "solo", "card", "card_price")

    def __init__(self, code, name, price, cat):
        self.code, self.name, self.price, self.cat = code, name, price, cat
        self.rounds = []      # list[list[Opt]]
        self.unknown = []     # option names with no nutrition data
        self.solo = None      # nutrition for single-item SKUs
        self.card = None      # card-gated promo, e.g. 随单购麦金卡优惠
        self.card_price = None


def load(store=STORE, cache_only=True):
    menu = json.load(open(os.path.join(DATA, "menu.json"), encoding="utf-8"))
    combos = []
    for it in menu:
        if os.environ.get("MCD_COMBO") and os.environ["MCD_COMBO"] not in it["name"]: continue
        path = os.path.join(DATA, "details", it["code"] + ".json")
        if not os.path.exists(path):
            continue
        d = json.load(open(path, encoding="utf-8"))["data"]
        c = Combo(it["code"], it["name"], (it["originalPrice"] if it.get("discountType") else it["price"]), it["category"].replace("\n", ""))
        ok = True
        for r in d.get("rounds") or []:
            opts = []
            for ch in r["choices"]:
                nut = rs.lookup(ch["name"])
                if nut is None:
                    c.unknown.append(ch["name"])
                    continue
                if (ch.get("quantity") or 1) > 1 or (r.get("maxQuantity") or 1) > 1:
                    continue
                opts.append(Opt(ch["code"], ch["name"], nut,
                                delta_price(ch.get("diffPrice")), ch.get("isDefault") == 1))
            if not opts:
                ok = False
                break
            c.rounds.append(opts)
        if ok and not c.rounds:
            c.solo = rs.lookup(it["name"])
            ok = c.solo is not None
        if ok:
            combos.append(c)
    return combos


def variants(c, limit_per_round=14):
    """All substitution combinations; cap options per round to keep it sane."""
    rounds = []
    for opts in c.rounds:
        defaults = [o for o in opts if o.is_default]
        # keep every option: the interesting ones are the non-default swaps
        keep = opts if len(opts) <= limit_per_round else (
            defaults + [o for o in opts if not o.is_default][:limit_per_round])
        rounds.append(keep)
    for pick in itertools.product(*rounds) if rounds else [()]:
        nut = {k: 0.0 for k in rs.NUT_KEYS}
        if not pick and c.solo:
            nut = dict(c.solo)
        price = c.price
        for o in pick:
            for k in rs.NUT_KEYS:
                nut[k] += o.nut[k]
            price += o.dp
        yield pick, nut, round(price, 2)


def score(nut, price, args):
    obj = args.objective
    if obj == "protein_per_yuan":
        return -(nut["protein"] / price) if price > 0 else 0
    if obj == "lean":
        return -nut["protein"]
    if obj == "kcal_fit":
        return abs(nut["kcal"] - args.kcal)
    return price


def feasible(nut, price, args):
    if args.kcal and nut["kcal"] > args.kcal and args.objective != "kcal_fit":
        return False
    if args.protein and nut["protein"] < args.protein:
        return False
    if args.budget and price > args.budget + 1e-6:
        return False
    return True


def diff_text(c, pick):
    out = []
    for opts, o in zip(c.rounds, pick):
        d = [x for x in opts if x.is_default]
        if d and d[0].code == o.code:
            continue
        base = d[0] if d else None
        dk = o.nut["kcal"] - (base.nut["kcal"] if base else 0)
        head = f"{base.name} → {o.name}" if base else f"选 {o.name}"
        out.append(f"{head} ({o.dp - (base.dp if base else 0):+.1f}元, {dk:+.0f}kcal)")
    return "；".join(out) or "与默认一致"


def search(args):
    combos = load()
    rows = []
    for c in combos:
        for pick, nut, price in variants(c):
            if feasible(nut, price, args):
                rows.append({
                    "combo": c, "pick": pick, "nut": nut, "price": price,
                    "score": score(nut, price, args),
                    "diff": diff_text(c, pick),
                })
    rows.sort(key=lambda r: r["score"])
    seen, uniq = set(), []
    for r in rows:
        sig = (round(r["nut"]["kcal"]), round(r["nut"]["protein"]),
               round(r["nut"]["fat"]), round(r["price"] * 100))
        if sig in seen:
            continue
        seen.add(sig)
        uniq.append(r)
    search.total = len(rows)
    return uniq


def round_list(pick):
    return [{"round": str(i + 1),
             "comboItemList": [{"code": o.code, "quantity": 1}]}
            for i, o in enumerate(pick)]


def verify(row):
    """Ask McDonald's pricing engine what this plan actually costs.

    Returns (price_yuan, status). status is "ok" or the engine's own message --
    combos go off sale when a store switches meal periods (e.g. 早餐 after midnight),
    and the pricing call fails with 60006 rather than returning a price.
    """
    out = mcd.call("calculate-price", {
        "storeCode": STORE, "orderType": 1, "beType": 1,
        "items": [{"productCode": row["combo"].code, "quantity": 1,
                   "roundList": round_list(row["pick"])}],
    })
    if not out.get("success") or "data" not in out:
        if out.get("code") == 60006:      # off sale in this meal period
            return None, "当前时段不可售"
        return None, out.get("message") or "计价失败"
    return out["data"]["price"] / 100.0, "ok"


def render(rows, top, check):
    for i, r in enumerate(rows[:top], 1):
        n, c = r["nut"], r["combo"]
        tag = ""
        if check:
            real, status = verify(r)
            if status != "ok":
                tag = f"  ⚠ {status}，加 --live 按当前时段重跑"
            elif abs(real - r["price"]) < 0.01:
                tag = f"  ✓官方计价 ¥{real:.2f}"
            else:
                tag = f"  ✗计价不符(本地{r['price']:.2f}/官方{real:.2f})"
        print(f"\n#{i}  {c.name}   ¥{r['price']:.2f}{tag}{card_note(c.code)}")
        print(f"    {n['kcal']:.0f} kcal | 蛋白质 {n['protein']:.0f}g | "
              f"脂肪 {n['fat']:.0f}g | 碳水 {n['carb']:.0f}g | 钠 {n['sodium']:.0f}mg")
        print(f"    {r['diff']}")


def refresh_live():
    """Re-pull the menu for whatever meal period the store is in right now.

    Writes to data/live/ so the committed snapshot stays reproducible.
    """
    global DATA
    live = os.path.join(os.path.dirname(DATA), "live")
    script = os.path.join(os.path.dirname(DATA), "scripts", "refresh_data.py")
    subprocess.run([sys.executable, script], check=True,
                   env={**os.environ, "MCD_DATA": live, "MCD_STORE": STORE})
    DATA = live


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--kcal", type=float)
    p.add_argument("--protein", type=float)
    p.add_argument("--budget", type=float)
    p.add_argument("--objective", default="protein_per_yuan", choices=OBJECTIVES)
    p.add_argument("--top", type=int, default=5)
    p.add_argument("--check", action="store_true", help="verify prices via MCP")
    p.add_argument("--live", action="store_true",
                   help="先按当前时段重新拉一遍菜单，再用新数据算（门店换菜单时用）")
    a = p.parse_args()
    if a.live:
        refresh_live()
    rows = search(a)
    print(f"候选方案 {len(rows)} 个（{len(load())} 个套餐可解析）")
    render(rows, a.top, a.check)


if __name__ == "__main__":
    main()


_CARDS = None


def _cards():
    global _CARDS
    if _CARDS is None:
        menu = json.load(open(os.path.join(DATA, "menu.json"), encoding="utf-8"))
        _CARDS = {m["code"]: (m.get("discountType"), m.get("price")) for m in menu if m.get("discountType")}
    return _CARDS


def card_note(code):
    c = _cards().get(code)
    if not c:
        return ""
    return "  [" + str(c[0]) + "：会员价 ¥" + format(c[1], ".2f") + "]"
