"""Validate web/data/*.json against the contracts in docs/DATA.md.

    python3.12 pipeline/check_data.py

Prints a data-quality report and exits 1 if any hard check fails. Uses the standard
library only, so it runs anywhere the site's data can be inspected.
"""
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(os.path.dirname(HERE), "web", "data")

failures = []
warnings = []


def fail(msg):
    failures.append(msg)


def warn(msg):
    warnings.append(msg)


def load(name):
    with open(os.path.join(DATA, f"{name}.json"), "r", encoding="utf-8") as f:
        return json.load(f)


def check_range(name, arr, lo, hi, n):
    if len(arr) != n:
        fail(f"{name}: length {len(arr)} != {n}")
        return
    bad = [i for i, v in enumerate(arr) if not (lo <= v <= hi)]
    if bad:
        fail(f"{name}: {len(bad)} values outside [{lo},{hi}], e.g. index {bad[:5]}")
    return


def main():
    world = load("world")
    states = load("states")
    cities = load("cities")
    nation = load("nation")
    lenses = load("lenses")
    resources = load("resources")
    sources = load("sources")

    cols = world["grid"]["cols"]
    rows = world["grid"]["rows"]
    n = cols * rows
    print(f"grid {cols}x{rows} = {n} cells")

    # --- world.json ------------------------------------------------------------------------------------------
    for key in ("owner", "elev", "water", "relief", "cover"):
        if not isinstance(world.get(key), list):
            fail(f"world.{key} missing")
    check_range("world.owner", world["owner"], -1, len(world["states"]) - 1, n)
    check_range("world.water", world["water"], 0, 3, n)
    check_range("world.relief", world["relief"], 0, 3, n)
    check_range("world.cover", world["cover"], 0, 11, n)
    if len(world["elev"]) != n:
        fail(f"world.elev length {len(world['elev'])} != {n}")
    elev_max = max(world["elev"])
    if elev_max != world.get("elev_max"):
        fail(f"world.elev_max {world.get('elev_max')} != observed {elev_max}")
    land = sum(1 for o in world["owner"] if o >= 0)
    water = sum(1 for w in world["water"] if w > 0)
    if land + water != n:
        fail(f"land {land} + water {water} != {n}")

    used = {o for o in world["owner"] if o >= 0}
    missing = [i for i in range(len(world["states"])) if i not in used]
    if missing:
        fail(f"states with no hex: {missing[:10]}")

    for r in world["rivers"]:
        if len(r["pts"]) % 2:
            fail(f"river {r['name']!r}: odd point list")
        xs = r["pts"][0::2]
        ys = r["pts"][1::2]
        if xs and (min(xs) < -50 or max(xs) > world["width"] + 50 or min(ys) < -50 or max(ys) > world["height"] + 50):
            fail(f"river {r['name']!r}: points outside the map")

    # --- states.json -----------------------------------------------------------------------------------------
    if len(states) != len(world["states"]):
        fail(f"states.json has {len(states)} entries, world.states has {len(world['states'])}")
    abbrs = [s["abbr"] for s in states]
    if len(set(abbrs)) != len(abbrs):
        fail("states.json: duplicate abbr")
    for i, (st, geo) in enumerate(zip(states, world["states"])):
        if st.get("abbr") != geo.get("abbr"):
            fail(f"states.json[{i}] abbr {st.get('abbr')} != world.states {geo.get('abbr')}")
        pop = st.get("population")
        if pop is None or pop < 0:
            fail(f"states.json[{i}] {st.get('name')}: bad population {pop}")
        for k, v in (st.get("yields") or {}).items():
            if not isinstance(v, (int, float)) or v < 0 or math.isnan(v):
                fail(f"states.json[{i}] {st.get('name')}: yield {k}={v}")
        ranks = st.get("ranks") or {}
        for k, r in ranks.items():
            if not (1 <= r <= len(states)):
                fail(f"states.json[{i}] {st.get('name')}: rank {k}={r}")

    # --- nation.json -----------------------------------------------------------------------------------------
    nat = nation["nation"]
    pop_sum = sum(s["population"] for s in states)
    if abs(nat["population"] - pop_sum) > max(1, pop_sum * 1e-6):
        fail(f"nation population {nat['population']} != sum(states) {pop_sum}")
    for k, v in nat["yields"].items():
        s = sum(st["yields"].get(k, 0) for st in states)
        if abs(v - s) > max(1.0, abs(s) * 1e-6):
            fail(f"nation yield {k}: {v} != sum(states) {s}")
    for k in nat["jobs"]:
        s = sum(st["jobs"].get(k, 0) for st in states)
        if abs(nat["jobs"][k] - s) > max(1.0, abs(s) * 1e-6):
            fail(f"nation job {k}: {nat['jobs'][k]} != sum(states) {s}")

    # --- cities.json -----------------------------------------------------------------------------------------
    ids = set()
    wrong_owner = []
    too_big = []
    for c in cities:
        if c["id"] in ids:
            fail(f"city duplicate id {c['id']}")
        ids.add(c["id"])
        cell = c.get("cell", -1)
        if not (0 <= cell < n):
            fail(f"city {c['name']}: bad cell {cell}")
            continue
        o = world["owner"][cell]
        if o < 0:
            wrong_owner.append(c["name"])
        elif c["states"] and c["states"][0] != states[o]["abbr"]:
            wrong_owner.append(f"{c['name']} ({c['states'][0]} vs {states[o]['abbr']})")
        x, y = c.get("x"), c.get("y")
        if not (0 <= x <= world["width"] and 0 <= y <= world["height"]):
            fail(f"city {c['name']}: coordinates outside the map")
        if c.get("population", 0) <= 0:
            fail(f"city {c['name']}: population {c.get('population')}")
        ci = next((i for i, st in enumerate(states) if st["abbr"] == (c["states"] or [None])[0]), None)
        if ci is not None and c["population"] > states[ci]["population"] * 1.01:
            too_big.append(f"{c['name']} {c['population']:.0f} > {states[ci]['name']} {states[ci]['population']:.0f}")
    if wrong_owner:
        warn(f"cities whose hex is water or another country: {len(wrong_owner)} (e.g. {wrong_owner[:5]})")
    if too_big:
        fail(f"cities larger than their country: {too_big[:5]}")

    # --- lenses.json -----------------------------------------------------------------------------------------
    for l in lenses["lenses"]:
        vals = l.get("values") or []
        if len(vals) != n:
            fail(f"lens {l['id']}: {len(vals)} values != {n}")
            continue
        if l.get("format") == "category":
            cats = l.get("categories") or []
            hi = int(l["domain"][1])
            if len(cats) <= hi:
                fail(f"lens {l['id']}: {len(cats)} categories for domain 0..{hi}")
        if l["domain"][0] >= l["domain"][1]:
            fail(f"lens {l['id']}: empty domain {l['domain']}")
        if l.get("scale") == "log" and l["domain"][0] <= 0:
            fail(f"lens {l['id']}: log domain starts at {l['domain'][0]}")
        if not any(l.get("source") == s["id"] for s in sources):
            fail(f"lens {l['id']}: unknown source {l.get('source')}")
        land_vals = [v for v, o in zip(vals, world["owner"]) if o >= 0 and v is not None]
        if not land_vals:
            fail(f"lens {l['id']}: no land values")
        else:
            known = sum(1 for v in land_vals if v != 0)
            if known < len(land_vals) * 0.5 and l["id"] not in ("cropland", "forest", "relief", "climate", "city"):
                warn(f"lens {l['id']}: only {known}/{len(land_vals)} land cells have a non-zero value")

    # --- resources.json --------------------------------------------------------------------------------------
    tids = {t["id"] for t in resources["types"]}
    srcids = {s["id"] for s in sources}
    for t in resources["types"]:
        if t.get("source") not in srcids:
            fail(f"resource type {t['id']}: unknown source {t.get('source')}")
    bad_res = [it for it in resources["items"] if it.get("type") not in tids or not (0 <= it.get("cell", -1) < n)
               or world["owner"][it["cell"]] < 0 or not (it.get("value", 0) > 0)]
    if bad_res:
        fail(f"resources: {len(bad_res)} invalid items, e.g. {[b.get('name') for b in bad_res[:5]]}")

    # --- summary ---------------------------------------------------------------------------------------------
    print(f"land cells        {land}")
    print(f"countries         {len(states)}")
    print(f"cities            {len(cities)} (capital {sum(1 for c in cities if c.get('capital'))})")
    print(f"lenses            {len(lenses['lenses'])}")
    print(f"resources         {len(resources['items'])} plants, {len(resources['types'])} types")
    print(f"nation population {nat['population']:,.0f}")
    print(f"nation GDP        ${nat['gdp'] / 1e12:,.1f}T")
    for k, v in nat["yields"].items():
        cov = sum(1 for st in states if (st["yields"].get(k) or 0) > 0)
        print(f"  yield {k:<10} {v:>18,.0f}  ({cov}/{len(states)} countries)")
    print()
    for w in warnings:
        print(f"WARN  {w}")
    for f in failures:
        print(f"FAIL  {f}")
    if failures:
        print(f"\n{len(failures)} failure(s)")
        sys.exit(1)
    print(f"ok — {len(warnings)} warning(s)")


if __name__ == "__main__":
    main()
