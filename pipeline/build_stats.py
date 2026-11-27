"""Build web/data/{cities,states,nation,lenses,resources,sources}.json from the raw inputs.

Runs after build_world.py and reads pipeline/out/{world.json,cells.npz}.

    python pipeline/build_stats.py
"""
import csv
import json
import math
import os
import sys
from collections import defaultdict

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
import geo  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "cache")
OUT = os.path.join(HERE, "out")
WEB = os.path.join(os.path.dirname(HERE), "web", "data")
os.makedirs(WEB, exist_ok=True)

SQRT3 = math.sqrt(3)

# --- indicator ids ---------------------------------------------------------------------------------------------

WB = {
    "pop": "SP.POP.TOTL",
    "gdp": "NY.GDP.MKTP.CD",
    "gdp_pc": "NY.GDP.PCAP.CD",
    "manuf": "NV.IND.MANF.CD",
    "rnd": "GB.XPD.RSDV.GD.ZS",
    "cereal": "AG.PRD.CREL.MT",
    "agr": "SL.AGR.EMPL.ZS",
    "ind": "SL.IND.EMPL.ZS",
    "srv": "SL.SRV.EMPL.ZS",
    "urban": "SP.URB.TOTL.IN.ZS",
    "life": "SP.DYN.LE00.IN",
    "tourists": "ST.INT.ARVL",
    "elec": "EG.ELC.ACCS.ZS",
    "net": "IT.NET.USER.ZS",
    "mil": "MS.MIL.XPND.CD",
    "arable": "AG.LND.ARBL.HA",
    "researchers": "SP.POP.SCIE.RD.P6",
    "lfpr": "SL.TLF.CACT.ZS",
    "gdpgrowth": "NY.GDP.MKTP.KD.ZG",
}

YIELD_DEFS = [
    {"key": "food", "icon": "y-food", "emoji": "🌾", "label": "Food", "color": "#7fbf3f",
     "unit": "t/yr", "industries": ["agriculture"],
     "description": "Cereal production in tonnes per year (World Bank / FAO). One Food unit is a tonne of grain."},
    {"key": "production", "icon": "y-production", "emoji": "⚙️", "label": "Production", "color": "#d9823b",
     "unit": "usd", "industries": ["industry"],
     "description": "Manufacturing value added in current US$ (World Bank). What the country's factories turn out."},
    {"key": "gold", "icon": "y-gold", "emoji": "💰", "label": "Gold", "color": "#f2c94c",
     "unit": "usd", "industries": [],
     "description": "Gross domestic product in current US$ (World Bank), the size of the whole economy."},
    {"key": "science", "icon": "y-science", "emoji": "🔬", "label": "Science", "color": "#6fb7d9",
     "unit": "usd", "industries": [],
     "description": "Research and development spending (World Bank, R&D as a share of GDP)."},
    {"key": "culture", "icon": "y-culture", "emoji": "🎭", "label": "Culture", "color": "#c77dba",
     "unit": "visitors/yr", "industries": ["services"],
     "description": "International tourist arrivals per year (World Bank / UNWTO)."},
]

INDUSTRY_LABELS = {
    "agriculture": "Agriculture, forestry & fishing",
    "industry": "Industry, mining & manufacturing",
    "services": "Services & tourism",
}

SOURCES = [
    {"id": "world_bank", "title": "World Bank Open Data", "publisher": "World Bank",
     "homepage": "https://data.worldbank.org", "license": "CC BY 4.0",
     "description": "Population, GDP, manufacturing value added, cereal production, employment by sector, urban share, "
                    "life expectancy, tourist arrivals, electricity and internet access, R&D spending, R&D researchers, "
                    "labour-force participation, arable land and military spending, country by country."},
    {"id": "natural_earth", "title": "Natural Earth 1:50m", "publisher": "Natural Earth",
     "homepage": "https://www.naturalearthdata.com", "license": "Public domain",
     "description": "Country outlines, lakes, rivers, urban areas, populated places, ports and airports."},
    {"id": "koppen", "title": "Köppen-Geiger climate classification", "publisher": "Beck et al. 2018",
     "homepage": "https://www.gloh2o.org/koppen/", "license": "CC BY 4.0",
     "description": "Observed 1976–2000 climate zones at 0.5°, used to place rainforest, savanna, desert, scrub, "
                    "temperate and boreal forest, tundra and ice on the map."},
    {"id": "terrarium", "title": "Terrain Tiles (Mapzen / AWS Open Data)", "publisher": "Mapzen, now AWS Open Data",
     "homepage": "https://registry.opendata.aws/terrain-tiles/", "license": "CC BY 4.0 and public-domain sources",
     "description": "Global elevation and bathymetry (SRTM, GMTED, ETOPO1, GEBCO and others), ~10 km per pixel at zoom 4."},
    {"id": "gppd", "title": "Global Power Plant Database", "publisher": "World Resources Institute",
     "homepage": "https://datasets.wri.org/dataset/globalpowerplantdatabase", "license": "CC BY 4.0",
     "description": "Every power plant above 30 MW with coordinates, fuel and capacity."},
]


# --- helpers ---------------------------------------------------------------------------------------------------

def read_json(name):
    with open(name, "r", encoding="utf-8") as f:
        return json.load(f)


def write_json(name, obj):
    path = os.path.join(WEB, name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    print(f"  {name}: {os.path.getsize(path)/1e6:.2f} MB")


def wb_series(ind):
    """{iso3: {year: value}} from a World Bank API dump."""
    path = os.path.join(CACHE, "wb", f"{ind}.json")
    try:
        d = read_json(path)
    except FileNotFoundError:
        return {}
    rows = d[1] if isinstance(d, list) and len(d) > 1 else []
    out = defaultdict(dict)
    for r in rows:
        iso = r.get("countryiso3code")
        v = r.get("value")
        if not iso or v is None:
            continue
        try:
            y = int(r["date"])
        except (KeyError, ValueError):
            continue
        out[iso][y] = float(v)
    return out


def latest(s):
    if not s:
        return None, None
    y = max(s)
    return s[y], y


def num(v, nd=0):
    if v is None or not np.isfinite(v):
        return None
    return round(float(v), nd)


# --- grid math (must match world.js hex.js / build_world.py) ---------------------------------------------------

class Grid:
    def __init__(self, cols, rows, radius):
        self.cols, self.rows, self.R = cols, rows, radius
        self.W = SQRT3 * radius
        self.H = 1.5 * radius
        self.width = self.W * cols
        self.height = self.H * rows

    def xy(self, i):
        r, c = divmod(int(i), self.cols)
        return self.W * (c + 0.5 * (r & 1)), self.H * r

    def cell_at(self, x, y):
        R = self.R
        q = ((SQRT3 / 3) * x - y / 3) / R
        r = ((2 / 3) * y) / R
        rx, rz = round(q), round(r)
        ry = round(-q - r)
        dx, dy, dz = abs(rx - q), abs(ry - (-q - r)), abs(rz - r)
        if dx > dy and dx > dz:
            rx = -ry - rz
        elif dy <= dz:
            rz = -rx - ry
        row = rz
        col = rx + ((row - (row & 1)) >> 1)
        if 0 <= col < self.cols and 0 <= row < self.rows:
            return int(row * self.cols + col)
        return -1

    def lonlat(self, x, y):
        return -180.0 + x / self.width * 360.0, 85.0 - y / 111.32

    def km(self, lon, lat):
        return (lon + 180.0) / 360.0 * self.width, (85.0 - lat) * 111.32


def main():
    main_path = os.path.join(OUT, "world.json")
    world = read_json(main_path)
    cells = np.load(os.path.join(OUT, "cells.npz"), allow_pickle=True)
    owner = cells["owner"]
    water = cells["water"]
    elev = cells["elev"]
    cover = cells["cover"]
    relief = cells["relief"]
    land = cells["land"]
    code = cells["code"].astype(str)
    cols, rows, radius = int(cells["cols"][0]), int(cells["rows"][0]), float(cells["radius"][0])
    grid = Grid(cols, rows, radius)
    n = len(owner)
    cell_area = 3 * SQRT3 / 2 * radius * radius  # km²

    states = world["states"]
    ne_countries = read_json(os.path.join(CACHE, "countries.geojson"))["features"]

    # Country name / sovereign for matching and fallbacks
    for s in states:
        p = ne_countries[s["ne_index"]]["properties"]
        s["_ne"] = p

    print(f"grid: {cols}x{rows} = {n} cells, {int(land.sum())} land, cell area {cell_area:,.0f} km²")

    # --- world bank ----------------------------------------------------------------------------------------------
    if False:
        pass
    series = {k: wb_series(v) for k, v in WB.items()}

    print("country statistics")
    stats = []
    for k, s in enumerate(states):
        ne = s["_ne"]
        iso = s["abbr"]
        sov = ne.get("SOV_A3") or iso
        alt = {"KOS": "XKX"}.get(iso, iso)

        def get(key, iso_list=(alt, sov)):
            for i in iso_list:
                v, y = latest(series[key].get(i))
                if v is not None:
                    return v, y
            return None, None

        pop, pop_y = get("pop")
        if pop is None:
            pop = float(ne.get("POP_EST") or 0)
        gdp, gdp_y = get("gdp")
        if gdp is None and ne.get("GDP_MD_EST"):
            gdp, gdp_y = float(ne["GDP_MD_EST"]) * 1e6, 2023
        gdp_pc, _ = get("gdp_pc")
        if gdp_pc is None and pop:
            gdp_pc = (gdp or 0) / pop
        lfpr, _ = get("lfpr")
        lfpr = lfpr if lfpr is not None else 60.0
        employed = pop * lfpr / 100.0
        shares = {}
        for key in ("agr", "ind", "srv"):
            v, _ = get(key)
            shares[key] = v
        if all(v is None for v in shares.values()):
            shares = {"agr": 5.0, "ind": 25.0, "srv": 70.0}
        tot = sum(v for v in shares.values() if v is not None) or 1.0
        shares = {kk: (v or 0.0) / tot * 100.0 for kk, v in shares.items()}
        jobs = {
            "agriculture": employed * shares["agr"] / 100.0,
            "industry": employed * shares["ind"] / 100.0,
            "services": employed * shares["srv"] / 100.0,
        }
        cereal, _ = get("cereal")
        manuf, _ = get("manuf")
        rnd, _ = get("rnd")
        tourists, _ = get("tourists")
        urban, _ = get("urban")
        life, _ = get("life")
        elec, _ = get("elec")
        net, _ = get("net")
        mil, _ = get("mil")
        arable, _ = get("arable")
        researchers, _ = get("researchers")

        yields = {
            "food": cereal if cereal is not None else 0.0,
            "production": manuf if manuf is not None else 0.0,
            "gold": gdp if gdp is not None else 0.0,
            "science": (rnd / 100.0 * gdp) if (rnd is not None and gdp) else 0.0,
            "culture": tourists if tourists is not None else 0.0,
        }

        # population growth: latest vs 5 years earlier
        growth = None
        growth_years = None
        s_pop = series["pop"].get(alt) or series["pop"].get(sov) or {}
        if len(s_pop) >= 2:
            ys = sorted(s_pop)[-6:]
            if len(ys) >= 2 and s_pop[ys[0]] > 0:
                growth = s_pop[ys[-1]] / s_pop[ys[0]] - 1.0
                growth_years = [ys[0], ys[-1]]

        stats.append({
            "fips": s["fips"], "abbr": s["abbr"], "name": s["name"], "full": s.get("full"),
            "continent": s.get("continent"), "subregion": s.get("subregion"), "iso2": s.get("iso2"),
            "population": pop, "employed": employed, "jobs": jobs, "yields": yields,
            "gdp": gdp, "gdp_year": gdp_y, "gdp_pc": gdp_pc,
            "urban": urban, "life": life, "elec": elec, "net": net, "mil": mil,
            "arable": arable, "researchers": researchers, "tourists": tourists,
            "growth": growth, "growth_years": growth_years,
            "estimated": bool(ne.get("TYPE") in ("Dependency", "Sovereignty")),
        })

    # ranks per yield
    for key in ("food", "production", "gold", "science", "culture"):
        order = sorted(range(len(stats)), key=lambda i: -(stats[i]["yields"].get(key) or 0))
        for r, i in enumerate(order, 1):
            stats[i].setdefault("ranks", {})[key] = r

    # nation
    nation_tot = {
        "population": sum(s["population"] or 0 for s in stats),
        "employed": sum(s["employed"] or 0 for s in stats),
        "jobs": {kk: sum(s["jobs"].get(kk, 0) for s in stats) for kk in ("agriculture", "industry", "services")},
        "yields": {d["key"]: sum(s["yields"][d["key"]] for s in stats) for d in YIELD_DEFS},
        "gdp": sum(s["gdp"] or 0 for s in stats),
        "gdp_year": 2024,
    }
    wp = sum(s["population"] or 0 for s in stats) or 1
    for key in ("urban", "life", "net", "elec", "researchers"):
        tot = sum((s.get(key) or 0) * (s["population"] or 0) for s in stats)
        nation_tot[key] = tot / wp

    # --- cities ---------------------------------------------------------------------------------------------------
    print("cities")
    places = read_json(os.path.join(CACHE, "places.geojson"))["features"]
    by_abbr = {s["abbr"]: i for i, s in enumerate(stats)}

    def snap_cell(cell, abbr):
        """Nearest hex of `abbr` when the city's coordinate lands in water or across a border."""
        if cell < 0:
            return cell
        o = owner[cell]
        if o >= 0 and states[o]["abbr"] == abbr:
            return cell
        r0, c0 = divmod(cell, cols)
        x0, y0 = grid.xy(cell)
        best, bestd = cell, 1e30
        for dr in range(-3, 4):
            for dc in range(-3, 4):
                rr, cc = r0 + dr, c0 + dc
                if not (0 <= rr < rows and 0 <= cc < cols):
                    continue
                j = rr * cols + cc
                oj = owner[j]
                if oj < 0 or states[oj]["abbr"] != abbr:
                    continue
                xj, yj = grid.xy(j)
                d = (xj - x0) ** 2 + (yj - y0) ** 2
                if d < bestd:
                    best, bestd = j, d
        return best

    cities = []
    for f in places:
        p = f["properties"]
        pop = float(p.get("POP_MAX") or 0)
        cap = str(p.get("FEATURECLA") or "").startswith("Admin-0 capital")
        if pop < 300_000 and not cap:
            continue
        iso = p.get("ADM0_A3") or ""
        ci = by_abbr.get(iso)
        if ci is None:
            continue
        lon, lat = p.get("LONGITUDE"), p.get("LATITUDE")
        if lon is None or lat is None:
            continue
        x, y = grid.km(lon, lat)
        st = stats[ci]
        cell = snap_cell(grid.cell_at(x, y), st["abbr"])
        if cell < 0:
            continue
        cpop = st["population"] or 0
        share = min(1.0, pop / cpop) if cpop > 0 else 0.0
        cities.append({
            "id": str(p.get("NE_ID") or p.get("NAME") or len(cities)),
            "name": p.get("NAME"),
            "full": f"{p.get('NAME')}, {p.get('ADM0NAME')}",
            "states": [st["abbr"]],
            "country": st["name"],
            "metro": pop >= 1_000_000,
            "capital": bool(cap),
            "x": round(x, 1), "y": round(y, 1), "cell": cell,
            "population": pop,
            "yields": {kk: (st["yields"].get(kk) or 0) * share for kk in nation_tot["yields"]},
            "jobs": {kk: (st["jobs"].get(kk) or 0) * share for kk in nation_tot["jobs"]},
            "employed": (st["employed"] or 0) * share,
            "gdp": (st["gdp"] or 0) * share,
            "urban": st.get("urban"), "life": st.get("life"), "net": st.get("net"),
            "elec": st.get("elec"), "researchers": st.get("researchers"),
            "growth": None,
        })
    # drop duplicate NE ids, keep the biggest
    byid = {}
    for c in cities:
        if c["id"] not in byid or c["population"] > byid[c["id"]]["population"]:
            byid[c["id"]] = c
    cities = sorted(byid.values(), key=lambda c: -c["population"])
    print(f"  {len(cities)} cities")

    # --- population model (for the density lens) ------------------------------------------------------------------
    print("population model")
    city_by_cell = {}
    for c in cities:
        if c["cell"] >= 0:
            city_by_cell[c["cell"]] = city_by_cell.get(c["cell"], 0) + c["population"]

    cell_climate = np.array([code[i][:1] or "C" for i in range(n)])
    suit = np.zeros(n)
    cf = {"A": 1.5, "B": 0.15, "C": 1.4, "D": 0.8, "E": 0.04}
    for i in range(n):
        if owner[i] < 0:
            continue
        c = code[i][:1]
        f = cf.get(c, 1.0)
        f *= math.exp(-max(0.0, float(elev[i]) - 1200.0) / 1200.0)
        f /= 1.0 + 0.35 * float(relief[i])
        if cover[i] == 9:
            f += 0.5
        if cover[i] == 7:
            f += 0.3
        suit[i] = f

    pop_cell = np.zeros(n)
    for k, st in enumerate(stats):
        idxs = np.where(owner == k)[0]
        if len(idxs) == 0:
            continue
        cpop = st["population"] or 0
        if cpop <= 0:
            continue
        # city kernels: gaussian around each city, normalised inside the country
        cidxs = [c for c in cities if by_abbr.get(c["states"][0]) == k]
        city_total = sum(c["population"] for c in cidxs)
        scale = min(1.0, cpop / city_total) if city_total > 0 else 0.0
        city_part = np.zeros(n)
        for c in cidxs:
            w = c["population"] * scale
            if w <= 0:
                continue
            col0 = int(max(0, (c["x"] - 170) / grid.W))
            col1 = int(min(cols - 1, (c["x"] + 170) / grid.W))
            row0 = int(max(0, (c["y"] - 170) / grid.H))
            row1 = int(min(rows - 1, (c["y"] + 170) / grid.H))
            if col1 < col0 or row1 < row0:
                continue
            cells_local = []
            wlocal = []
            for r in range(row0, row1 + 1):
                for cc in range(col0, col1 + 1):
                    i = r * cols + cc
                    if owner[i] != k:
                        continue
                    x, y = grid.xy(i)
                    d2 = (x - c["x"]) ** 2 + (y - c["y"]) ** 2
                    if d2 > 170 ** 2:
                        continue
                    ww = math.exp(-0.5 * d2 / (45.0 ** 2))
                    cells_local.append(i)
                    wlocal.append(ww)
            s = sum(wlocal)
            if s > 0:
                for i, ww in zip(cells_local, wlocal):
                    city_part[i] += w * ww / s
        residual = max(0.0, cpop - city_part[idxs].sum())
        sw = suit[idxs].sum()
        if sw > 0:
            pop_cell[idxs] += city_part[idxs] + residual * suit[idxs] / sw
        else:
            pop_cell[idxs] += city_part[idxs] + residual / len(idxs)
    density = np.where(land, pop_cell / cell_area, 0.0)

    # --- coast distance (BFS from sea) ----------------------------------------------------------------------------
    print("coast distance")
    dist = np.full((rows, cols), 1e9)
    from collections import deque
    q = deque()
    w2 = water.reshape(rows, cols)
    owner2 = owner.reshape(rows, cols)
    for r in range(rows):
        for c in range(cols):
            if w2[r, c] > 0:
                dist[r, c] = 0.0
                q.append((r, c))
    while q:
        r, c = q.popleft()
        d = dist[r, c] + 1
        for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1)):
            rr, cc = r + dr, c + dc
            if 0 <= rr < rows and 0 <= cc < cols and dist[rr, cc] > d:
                dist[rr, cc] = d
                q.append((rr, cc))
    coast_km = dist.reshape(-1) * grid.W

    # --- lenses ---------------------------------------------------------------------------------------------------
    print("lenses")

    def pct_domain(vals, lo=2, hi=98):
        v = np.array(vals, dtype=float)
        v = v[np.isfinite(v) & (v > 0)]  # log scales and "no data" cells would drag the low end to 0
        if not len(v):
            return [0, 1]
        d0, d1 = np.percentile(v, lo), np.percentile(v, hi)
        if d1 <= d0:
            d1 = d0 + 1
        return [float(max(d0, 1e-9)), float(d1)]

    def land_vals(arr):
        return [float(arr[i]) for i in range(n) if owner[i] >= 0 and np.isfinite(arr[i])]

    def country_lens(getter):
        """Per-hex array from a country field, null where the country has no value."""
        arr = np.full(n, np.nan)
        for i in range(n):
            o = owner[i]
            if o >= 0:
                v = getter(stats[o])
                if v is not None and np.isfinite(v):
                    arr[i] = v
        return arr

    climate_group = np.zeros(n)
    for i in range(n):
        c = code[i][:1]
        climate_group[i] = {"A": 0, "B": 1, "C": 2, "D": 3, "E": 4}.get(c, 2)

    lenses = []

    def add(id, group, name, icon, emoji, unit, fmt, scale, ramp, higher, source, desc, values, domain=None,
            categories=None):
        vals = [round(float(v), 3) if v is not None and np.isfinite(v) else None for v in values]
        dom = list(domain) if domain else pct_domain(land_vals(np.asarray(values, dtype=float)))
        floor = {"density": 0.5, "population": 1, "gdp_pc": 100, "gdp": 1e6, "life": 30, "coast": 0.5}.get(id)
        if floor is not None and dom[0] < floor:
            dom[0] = floor
        o = {"id": id, "group": group, "name": name, "icon": icon, "emoji": emoji, "unit": unit,
             "format": fmt, "scale": scale, "ramp": ramp, "higher_is": higher, "source": source,
             "description": desc, "domain": dom, "values": vals}
        if categories:
            o["categories"] = categories
        lenses.append(o)

    add("density", "people", "Population", "l-people", "👥", "people / km²", "int", "log",
        ["#1b1035", "#4b2377", "#9a3b8a", "#e0645e", "#f9b24a", "#fff3a8"], "neutral", "world_bank",
        "Modelled residents per km² of land: each country's World Bank population is placed on its hexes, "
        "concentrated around Natural Earth cities and on climatically suitable land.",
        density)
    add("population", "people", "People in the hex", "l-people", "👥", "people", "int", "log",
        ["#1b1035", "#4b2377", "#9a3b8a", "#e0645e", "#f9b24a", "#fff3a8"], "neutral", "world_bank",
        "The same population model, as a count per hex rather than a density.", pop_cell)
    add("gdp_pc", "prosperity", "GDP per person", "l-income", "💵", "US$", "usd", "log",
        ["#08213b", "#155e75", "#2f9e8f", "#b8c65a", "#f6d365"], "higher", "world_bank",
        "Gross domestic product per resident (World Bank), current US$. All hexes of a country share its value.",
        country_lens(lambda st: (st["gdp"] / st["population"]) if st.get("gdp") and st.get("population") else None))
    add("gdp", "prosperity", "Economy size", "y-gold", "💰", "US$", "usd", "log",
        ["#1a1035", "#4a2b6b", "#8c3f8f", "#d9647a", "#f9b24a"], "higher", "world_bank",
        "Gross domestic product (World Bank), current US$, the same on every hex of a country.",
        country_lens(lambda st: st.get("gdp")))
    add("urban", "people", "Urban share", "l-developed", "🏙️", "%", "pct", "linear",
        ["#20303f", "#3f6478", "#6fa3a8", "#c8d98a", "#f3e2a0"], "higher", "world_bank",
        "Share of the country's people who live in cities (World Bank).",
        country_lens(lambda st: (st["urban"] / 100) if st.get("urban") is not None else None))
    add("life", "life", "Life expectancy", "l-age", "⏳", "years", "years", "linear",
        ["#2a1b2f", "#5c2f4a", "#a44a56", "#e08a5e", "#f7d98a"], "higher", "world_bank",
        "Life expectancy at birth (World Bank), in years.",
        country_lens(lambda st: st.get("life")))
    add("elec", "life", "Electricity access", "l-broadband", "⚡", "%", "pct", "linear",
        ["#1b1b24", "#3c3c52", "#6e6a86", "#b8a86a", "#ffe28a"], "higher", "world_bank",
        "Share of people with access to electricity (World Bank).",
        country_lens(lambda st: (st["elec"] / 100) if st.get("elec") is not None else None))
    add("net", "knowledge", "Internet users", "l-broadband", "🌐", "%", "pct", "linear",
        ["#101a2b", "#1f415f", "#2f7f96", "#7fc7b0", "#e6f7c8"], "higher", "world_bank",
        "Share of people using the internet (World Bank).",
        country_lens(lambda st: (st["net"] / 100) if st.get("net") is not None else None))
    add("elev", "land", "Elevation", "terrain", "⛰️", "m", "int", "linear",
        ["#173d2b", "#4f7a35", "#a39c58", "#b09366", "#8c8078", "#e8eef2"], "neutral", "terrarium",
        "Mean elevation of the hex in metres, from the terrain tiles (SRTM/GEBCO).",
        elev)
    add("climate", "land", "Climate zone", "l-forest", "🌦️", "", "category", "linear",
        ["#2f7f4f", "#c2a35a", "#7fbf3f", "#5a8fbf", "#cfd8e0"], "neutral", "koppen",
        "Köppen-Geiger climate group: tropical, arid, temperate, continental or polar.",
        climate_group, domain=[0, 4],
        categories=[{"name": "Tropical"}, {"name": "Arid"}, {"name": "Temperate"}, {"name": "Continental"}, {"name": "Polar"}])
    add("coast", "land", "Distance to the sea", "l-commute", "🌊", "km", "int", "log",
        ["#0d2a47", "#1b4266", "#2d6d97", "#7fa6b8", "#e8dfc8"], "lower", "natural_earth",
        "Straight-line distance from the hex to the nearest sea hex.",
        coast_km)
    add("cropland", "land", "Cropland", "l-farmland", "🌾", "", "category", "linear",
        ["#2b2b25", "#c2b65c"], "higher", "world_bank",
        "Hexes the arable-land model picks out as cropland; the country totals are World Bank arable hectares.",
        np.array([1.0 if cover[i] == 7 else 0.0 for i in range(n)]), domain=[0, 1],
        categories=[{"name": "No"}, {"name": "Cropland"}])
    add("forest", "land", "Forest", "l-forest", "🌲", "", "category", "linear",
        ["#2b2b25", "#2f5a3a"], "higher", "koppen",
        "Hexes whose Köppen climate carries forest: tropical rainforest, temperate and boreal forest.",
        np.array([1.0 if cover[i] in (1, 2, 3) else 0.0 for i in range(n)]), domain=[0, 1],
        categories=[{"name": "No"}, {"name": "Forest"}])
    add("relief", "land", "Terrain roughness", "terrain", "🏔️", "", "category", "linear",
        ["#4f7a35", "#9fb35a", "#b09366", "#e8eef2"], "neutral", "terrarium",
        "Flat, hills, mountains or peaks, from the elevation spread inside the hex.",
        relief, domain=[0, 3],
        categories=[{"name": "Flat"}, {"name": "Hills"}, {"name": "Mountains"}, {"name": "Peaks"}])
    add("city", "people", "City population", "l-people", "🏙️", "people", "int", "log",
        ["#1b1035", "#4b2377", "#9a3b8a", "#e0645e", "#f9b24a", "#fff3a8"], "higher", "natural_earth",
        "Population of the cities whose centre falls in this hex (Natural Earth populated places).",
        np.array([city_by_cell.get(i, 0) for i in range(n)]))

    lens_file = {
        "vintage": "World Bank 2024; Natural Earth; Köppen-Geiger 1976–2000",
        "groups": [
            {"id": "people", "name": "People"}, {"id": "prosperity", "name": "Prosperity"},
            {"id": "knowledge", "name": "Knowledge"}, {"id": "life", "name": "Daily life"},
            {"id": "land", "name": "Land"},
        ],
        "lenses": lenses,
    }

    # --- states.json ----------------------------------------------------------------------------------------------
    for s in stats:
        s.pop("_ne", None)
        s.pop("gdp_pc", None)
    # keep world.states free of the helper too
    for s in states:
        s.pop("_ne", None)

    # --- resources: power plants ----------------------------------------------------------------------------------
    print("resources")
    FUEL = {
        "Hydro": ("hydro", "r-hydro", "energy", "#3fa7d6", "MW"),
        "Nuclear": ("nuclear", "r-nuclear", "energy", "#e8d44d", "MW"),
        "Coal": ("coal_plant", "r-coal_plant", "energy", "#5a5a5a", "MW"),
        "Gas": ("gas_plant", "r-gas_plant", "energy", "#8a4a10", "MW"),
        "Oil": ("oil_plant", "r-oil", "energy", "#3b3b3b", "MW"),
        "Wind": ("wind", "r-wind", "energy", "#8fc7d8", "MW"),
        "Solar": ("solar", "r-solar", "energy", "#f2c94c", "MW"),
        "Geothermal": ("geothermal", "r-geothermal", "energy", "#c96f3f", "MW"),
        "Biomass": ("biomass", "r-coal_plant", "energy", "#7a9a3c", "MW"),
        "Waste": ("biomass", "r-coal_plant", "energy", "#7a9a3c", "MW"),
        "Wave and Tidal": ("hydro", "r-hydro", "energy", "#3fa7d6", "MW"),
    }
    types = {}
    items = []
    seen = set()
    with open(os.path.join(CACHE, "power_plants.csv"), newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                cap = float(row["capacity_mw"] or 0)
                lat = float(row["latitude"])
                lon = float(row["longitude"])
            except (ValueError, TypeError):
                continue
            if cap < 100:
                continue
            fuel = row["primary_fuel"]
            if fuel not in FUEL:
                continue
            tid, icon, cat, color, unit = FUEL[fuel]
            x, y = grid.km(lon, lat)
            cell = grid.cell_at(x, y)
            if cell < 0 or owner[cell] < 0:
                continue
            key = (row["name"], round(x), round(y))
            if key in seen:
                continue
            seen.add(key)
            if tid not in types:
                types[tid] = {"id": tid, "name": fuel, "category": cat, "emoji": "⚡", "icon": icon,
                              "color": color, "unit": unit,
                              "description": f"{fuel} power plants, net capacity in MW (WRI Global Power Plant Database).",
                              "source": "gppd"}
            items.append({
                "type": tid, "name": row["name"], "x": round(x, 1), "y": round(y, 1), "cell": cell,
                "value": round(cap, 1),
                "detail": f"{cap:,.0f} MW · {row.get('country_long') or row['country']}"
                          + (f" · since {row['commissioning_year'][:4]}" if row.get("commissioning_year") else ""),
                "state": stats[owner[cell]]["abbr"],
            })
    print(f"  {len(items)} plants in {len(types)} types")

    # --- write ----------------------------------------------------------------------------------------------------
    print("writing")
    write_json("world.json", world)
    write_json("cities.json", cities)
    write_json("states.json", stats)
    write_json("nation.json", {
        "vintage": "World Bank 2024; Natural Earth; WRI power plants",
        "year": 2024,
        "gdp_vintage": "World Bank GDP, current US$",
        "nation": nation_tot,
        "yields": YIELD_DEFS,
        "industries": INDUSTRY_LABELS,
    })
    write_json("lenses.json", lens_file)
    write_json("resources.json", {"types": list(types.values()), "items": items})
    write_json("sources.json", SOURCES)
    print("done")


if __name__ == "__main__":
    main()
