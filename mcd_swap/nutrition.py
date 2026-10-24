#!/usr/bin/env python3
"""Map McDonald's menu/BOM names onto the official nutrition table."""
import json
import os
import re
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.environ.get("MCD_DATA") or os.path.normpath(os.path.join(HERE, "..", "data"))
NUT_KEYS = ("kcal", "protein", "fat", "carb", "sodium", "calcium")

# Hand-checked aliases: menu/BOM name -> nutrition table name
ALIASES = {
    "5块麦乐鸡": "麦乐鸡5块",
    "麦乐鸡-5块": "麦乐鸡5块",
    "麦乐鸡-4块": "麦乐鸡4块",
    "麦乐鸡块5块": "麦乐鸡5块",
    "鱼排堡": "儿童鱼排堡",
    "麦咖啡热奶铁中杯": "热奶铁中杯",
    "麦咖啡冰奶铁中杯": "冰奶铁中杯",
    "麦咖啡热美式中杯": "热美式中杯",
    "麦咖啡冰美式中杯": "冰美式中杯",
    "麦咖啡热燕麦奶铁中杯": "热燕麦奶铁中杯",
    "那么大鸡排椒盐风味": "那么大鸡排",
    "醇香豆浆大杯": "优品豆浆大杯",
    "醇香豆浆小杯": "优品豆浆小杯",
    "纯牛奶": "纯牛奶（盒装）",
    "苹果片一袋(60g)": "苹果片",
    "原味双层深海鳕鱼堡": "双层深海鳕鱼堡",
    "风味双层深海鳕鱼堡": "双层深海鳕鱼堡",
}

# Non-food or negligible items: counted as zero calories rather than "unknown"
ZERO = ("甜酸酱", "牧场酱", "黄油风味酱", "玩具", "纸巾", "餐具", "吸管")


def norm(s):
    s = (s or "").replace("™", "").replace("®", "")
    s = unicodedata.normalize("NFKC", s).lower()
    s = s.replace("麦当劳", "").replace("tm", "")
    return re.sub(r"[\s（）()【】\[\]·/\-—_“”\"'’,，.。+]+", "", s)


def _rows():
    # the nutrition table is store-independent, so a live menu dir can reuse the packaged copy
    path = os.path.join(DATA, "nutrition.json")
    if not os.path.exists(path):
        path = os.path.join(HERE, "..", "data", "nutrition.json")
    raw = json.load(open(path, encoding="utf-8"))
    item = raw["result"]["content"][0]["text"] if "result" in raw else json.dumps(raw, ensure_ascii=False)
    m = re.search(r"##\s*Original Response\s*", item)
    body = item[m.end():] if m else item
    start = body.find("{")
    obj, _ = json.JSONDecoder().raw_decode(body[start:])
    out = []
    for line in obj["data"].splitlines():
        p = [x.strip() for x in line.split(",")]
        if len(p) != 9 or p[0].startswith("productName") or not p[0]:
            continue
        try:
            vals = [float(x) for x in p[2:]]
        except ValueError:
            continue
        row = dict(zip(("kj",) + NUT_KEYS, vals))
        row["name"] = p[0]
        out.append(row)
    return out


_ROWS = _rows()
BY_NAME = {norm(r["name"]): r for r in _ROWS}
for _a, _t in ALIASES.items():
    if norm(_t) in BY_NAME:
        BY_NAME[norm(_a)] = BY_NAME[norm(_t)]


def lookup(name):
    """Nutrition dict for a menu/BOM item name, or None."""
    r = BY_NAME.get(norm(name))
    if r:
        return {k: r[k] for k in NUT_KEYS}
    if len(name or "") <= 12 and any(z in (name or "") for z in ZERO):
        return {k: 0.0 for k in NUT_KEYS}
    return None


def add(a, b):
    if a is None or b is None:
        return None
    return {k: a[k] + b[k] for k in NUT_KEYS}


def scale(a, n):
    return None if a is None else {k: a[k] * n for k in NUT_KEYS}


if __name__ == "__main__":
    import glob
    names = set()
    for f in glob.glob(os.path.join(DATA, "details", "*.json")):
        d = json.load(open(f, encoding="utf-8"))["data"]
        for r in d.get("rounds") or []:
            for c in r["choices"]:
                names.add(c["name"])
    hit = [n for n in names if lookup(n)]
    miss = sorted(n for n in names if not lookup(n))
    print(f"choice names {len(names)}  matched {len(hit)} ({len(hit)/len(names):.0%})")
    print("unmatched:", miss)
