"""Build web/data/world.json: the global hex grid (terrain, water, ownership, rivers).

Inputs (pipeline/cache): countries, lakes, urban areas, koppen, terrarium4, rivers.
Output: pipeline/out/world.json + pipeline/out/cells.npz (arrays the stats build reuses).

    python pipeline/build_world.py
"""
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
import geo  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "cache")
OUT = os.path.join(HERE, "out")
os.makedirs(OUT, exist_ok=True)

# --- grid ------------------------------------------------------------------------------------------------------
# Plate Carree in km. The world is 360 deg wide; hexes are ~121 km across (R = 70 km), which is a
# Civ-like world scale: ~330 x 180 hexes, ~60k cells.
R = 70.0
SQRT3 = math.sqrt(3)
COLS = math.ceil(40075.0 / (SQRT3 * R))          # 331
ROWS = 180
WIDTH = SQRT3 * R * COLS                          # km
HEIGHT = 1.5 * R * ROWS                           # km
LON_TOP, LON_SCALE = -180.0 + 0.0, 360.0 / WIDTH  # lon = LON_TOP + x * LON_SCALE
LAT_TOP = 85.0                                    # lat = LAT_TOP - y / 111.32


def lon_at(x):
    return LON_TOP + x * LON_SCALE


def lat_at(y):
    return LAT_TOP - y / 111.32


def cell_xy(i):
    r, c = divmod(i, COLS)
    return SQRT3 * R * (c + 0.5 * (r & 1)), 1.5 * R * r


# The terrarium mosaic is a Web-Mercator z4 image: 16x16 tiles of 256 px.
MOSAIC = 16 * 256
MERC_LAT_MAX = 85.05112878


def lonlat_to_px(lon, lat):
    x = (lon + 180.0) / 360.0 * MOSAIC
    lat = np.clip(lat, -MERC_LAT_MAX, MERC_LAT_MAX)
    r = np.radians(lat)
    y = (1.0 - np.log(np.tan(np.pi / 4 + r / 2)) / math.pi) / 2.0 * MOSAIC
    return x, y


def load_dem():
    from PIL import Image
    mos = np.zeros((MOSAIC, MOSAIC), dtype=np.float32)
    for x in range(16):
        for y in range(16):
            p = os.path.join(CACHE, "terrarium4", f"{x}_{y}.png")
            im = np.asarray(Image.open(p).convert("RGB"), dtype=np.float32)
            elev = im[:, :, 0] * 256.0 + im[:, :, 1] + im[:, :, 2] / 256.0 - 32768.0
            mos[y * 256:(y + 1) * 256, x * 256:(x + 1) * 256] = elev
    return mos


def sample_dem(mos, lon, lat):
    x, y = lonlat_to_px(lon, lat)
    x = np.clip(np.nan_to_num(x, nan=0.0, posinf=MOSAIC - 2.0, neginf=0.0), 0.0, MOSAIC - 2.0)
    y = np.clip(np.nan_to_num(y, nan=0.0, posinf=MOSAIC - 2.0, neginf=0.0), 0.0, MOSAIC - 2.0)
    x0 = np.floor(x).astype(np.int64)
    y0 = np.floor(y).astype(np.int64)
    x0 = np.clip(x0, 0, MOSAIC - 2)
    y0 = np.clip(y0, 0, MOSAIC - 2)
    x1 = np.minimum(x0 + 1, MOSAIC - 1)
    y1 = np.minimum(y0 + 1, MOSAIC - 1)
    fx = x - x0
    fy = y - y0
    a = mos[y0, x0] * (1 - fx) + mos[y0, x1] * fx
    b = mos[y1, x0] * (1 - fx) + mos[y1, x1] * fx
    return a * (1 - fy) + b * fy


# Rings of sample points inside a hex: centre, r=0.45R, r=0.85R (the 0.85 ring stays inside edges at 0.866R).
RING_FRACS = [0.0, 0.45, 0.45, 0.45, 0.45, 0.45, 0.45, 0.85, 0.85, 0.85, 0.85, 0.85, 0.85]
RING_ANGLES = [0] + [60 * k for k in range(6)] + [60 * k + 30 for k in range(6)]


def sample_points(idx):
    """(13, n) sample-point km coordinates for cells idx."""
    cx = np.array([cell_xy(i)[0] for i in idx], dtype=float)
    cy = np.array([cell_xy(i)[1] for i in idx], dtype=float)
    xs, ys = [], []
    for frac, ang in zip(RING_FRACS, RING_ANGLES):
        xs.append(cx + math.cos(math.radians(ang)) * R * frac)
        ys.append(cy + math.sin(math.radians(ang)) * R * frac)
    return np.array(xs), np.array(ys)


# --- cover (from the Koppen climate polygons) -----------------------------------------------------------------

KOPPEN_COVER = {
    "Af": 2, "Am": 2, "Aw": 5, "As": 5,                 # tropical: rainforest evergreen / savanna grass
    "BWh": 4, "BWk": 4, "BSh": 5, "BSk": 5,             # arid: desert scrub / steppe grass
    "Csa": 4, "Csb": 4, "Csc": 4,                       # Mediterranean scrub
    "Cfa": 3, "Cwa": 3, "Cwb": 3, "Cwc": 3,             # humid subtropical / highland: mixed forest
    "Cfb": 1, "Cfc": 1,                                 # oceanic: deciduous
    "Dfa": 1, "Dfb": 1, "Dsa": 1, "Dsb": 1, "Dwa": 1, "Dwb": 1,
    "Dfc": 2, "Dfd": 2, "Dsc": 2, "Dsd": 2, "Dwc": 2, "Dwd": 2,  # boreal conifer
    "ET": 10, "EF": 11,
}

TABLES = {
    "water": [
        {"id": 0, "name": "Land"},
        {"id": 1, "name": "Ocean", "color": "#1b4266",
         "rule": "Sea more than 200 m deep and away from land (ETOPO/terrarium bathymetry)."},
        {"id": 2, "name": "Coast", "color": "#2d6d97",
         "rule": "Sea shallower than 200 m, or touching land."},
        {"id": 3, "name": "Lake", "color": "#3a80b0",
         "rule": "Hex centre inside a Natural Earth lake."},
    ],
    "relief": [
        {"id": 0, "name": "Flat", "rule": "Elevation standard deviation inside the hex under 60 m."},
        {"id": 1, "name": "Hills", "rule": "Elevation standard deviation 60-200 m."},
        {"id": 2, "name": "Mountains", "rule": "Elevation standard deviation 200-450 m."},
        {"id": 3, "name": "Peaks", "rule": "Elevation standard deviation over 450 m, or mean elevation over 2,500 m."},
    ],
    "cover": [
        {"id": 0, "key": "none", "name": "None"},
        {"id": 1, "key": "forest_deciduous", "name": "Temperate forest", "color": "#4f7a35"},
        {"id": 2, "key": "forest_evergreen", "name": "Rainforest & boreal", "color": "#2f5a3a"},
        {"id": 3, "key": "forest_mixed", "name": "Mixed forest", "color": "#436d36"},
        {"id": 4, "key": "scrub", "name": "Scrub & desert", "color": "#b8a26a"},
        {"id": 5, "key": "grassland", "name": "Grassland & savanna", "color": "#9fb35a"},
        {"id": 6, "key": "pasture", "name": "Pasture", "color": "#a8b862"},
        {"id": 7, "key": "cropland", "name": "Cropland", "color": "#c2b65c"},
        {"id": 8, "key": "wetland", "name": "Wetland", "color": "#4f7f68"},
        {"id": 9, "key": "urban", "name": "Built-up", "color": "#8c8780"},
        {"id": 10, "key": "barren", "name": "Barren & tundra", "color": "#b9ab94"},
        {"id": 11, "key": "ice", "name": "Ice & snow", "color": "#e8eef2"},
    ],
    "notes": {
        "land": "A hex is land when at least 7 of its 13 sample points fall inside a Natural Earth 1:50m country polygon.",
        "cover": "Cover comes from the 1976-2000 Koppen-Geiger climate polygons (Beck et al.), mapped to the six biome "
                 "groups the map draws, then cropland and pasture are carved out of each country's World Bank arable "
                 "and permanent-pasture hectares on the most suitable hexes, and Natural Earth urban areas override "
                 "forest or grass where a city stands.",
        "elev": "Mean elevation from the Mapzen/Terrain Tiles terrarium set (z4, ~10 km pixels), bilinear-sampled at "
                "13 points per hex; ocean cells carry the bathymetry value.",
        "rivers": "Natural Earth 1:50m rivers and lake centrelines, simplified to 1 point per 25 km.",
    },
}


def build():
    print("loading Natural Earth + climate")
    countries = geo.load(os.path.join(CACHE, "countries.geojson"))
    lakes = geo.load(os.path.join(CACHE, "lakes.geojson"))
    urban = geo.load(os.path.join(CACHE, "urban.geojson"))
    koppen = geo.load(os.path.join(CACHE, "koppen.geojson"))

    cfeats = countries["features"]
    kfeats = [f for f in koppen["features"] if f.get("properties", {}).get("CODE")]
    kcodes = [f["properties"]["CODE"] for f in kfeats]

    print("rasterising countries / lakes / urban areas / climates at 0.05 deg")
    country_r = geo.rasterize(cfeats)                       # value = feature index + 1
    lake_m = geo.rasterize_mask(lakes["features"])
    urban_m = geo.rasterize_mask(urban["features"])
    koppen_r = geo.rasterize(kfeats, ids=list(range(1, len(kfeats) + 1)))

    n = COLS * ROWS
    idx = np.arange(n)
    print(f"grid {COLS}x{ROWS} = {n} cells")

    print("sampling country / lake / climate / urban at 13 points per hex")
    xs, ys = sample_points(idx)                       # (13, n)
    lons = lon_at(xs)
    lats = lat_at(ys)

    clab = geo.lookup(country_r, lons, lats)          # (13, n), 0 = sea
    ok_c = clab > 0

    # land fraction and majority country
    land_frac = ok_c.sum(axis=0) / 13.0
    land = land_frac >= 7 / 13.0

    owner = np.full(n, -1, dtype=np.int32)
    for i in np.where(land)[0]:
        votes = clab[:, i][ok_c[:, i]].astype(np.int32) - 1
        if len(votes):
            vals, counts = np.unique(votes, return_counts=True)
            owner[i] = int(vals[np.argmax(counts)])

    # Countries that never own a cell are dropped; remap to a compact index.
    used = [int(c) for c in np.unique(owner[owner >= 0])]
    remap = {c: k for k, c in enumerate(used)}
    owner = np.array([remap.get(int(o), -1) if o >= 0 else -1 for o in owner], dtype=np.int32)

    # lake / urban / climate at the hex centre
    cx = xs[0]
    cy = ys[0]
    ok_lake = geo.lookup(lake_m, lon_at(cx), lat_at(cy)) > 0
    ok_urban = geo.lookup(urban_m, lon_at(cx), lat_at(cy)) > 0
    klab = geo.lookup(koppen_r, lon_at(cx), lat_at(cy)).astype(np.int32)
    codes = np.array([kcodes[k - 1] if k > 0 else "" for k in klab])

    print("elevation")
    dem = load_dem()
    elev_s = sample_dem(dem, lons.ravel(), lats.ravel()).reshape(13, n)
    elev = elev_s.mean(axis=0)
    elev_std = elev_s.std(axis=0)

    # water classification: a hex whose centre falls in a Natural Earth lake is lake water, even when its
    # shores make most sample points land.
    water = np.zeros(n, dtype=np.int8)
    water[~land] = 1
    land[ok_lake] = False
    owner[ok_lake] = -1
    water[ok_lake] = 3
    # coast: ocean cells within 1 hex of land or shallower than -200 m
    e2 = elev.reshape(ROWS, COLS)
    land2 = land.reshape(ROWS, COLS)
    near = np.zeros_like(land2)
    for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1)]:
        near |= np.roll(np.roll(land2, dr, axis=0), dc, axis=1)
    coast = (~land2) & (near | (e2 > -200))
    w2 = water.reshape(ROWS, COLS)
    w2[coast & (w2 == 1)] = 2
    w2[ok_lake.reshape(ROWS, COLS) & ~land2] = 3
    water = w2.reshape(-1)

    # cover
    cover = np.zeros(n, dtype=np.int8)
    for i in np.where(land)[0]:
        code = codes[i]
        cover[i] = KOPPEN_COVER.get(code, 0)
    cover[ok_urban & land] = 9
    cover[(elev > 3800) & land] = np.maximum(cover[(elev > 3800) & land], 10)
    cover[(elev_std > 450) & land & (cover > 0)] = np.minimum(cover[(elev_std > 450) & land & (cover > 0)], 10)

    relief = np.zeros(n, dtype=np.int8)
    relief[(land) & (elev_std >= 60)] = 1
    relief[(land) & (elev_std >= 200)] = 2
    relief[(land) & ((elev_std >= 450) | (elev >= 2500))] = 3


    # state table (countries that own at least one hex)
    states = []
    for k, c in enumerate(used):
        f = cfeats[c]
        p = f["properties"]
        abbr = p.get("ISO_A3") if p.get("ISO_A3") not in (None, "-99", "") else p.get("ADM0_A3", f"X{k}")
        states.append({
            "fips": abbr,
            "abbr": abbr,
            "name": p.get("NAME") or p.get("NAME_LONG") or abbr,
            "full": p.get("NAME_LONG") or p.get("NAME"),
            "continent": p.get("CONTINENT") or "",
            "subregion": p.get("SUBREGION") or "",
            "iso2": p.get("ISO_A2") or "",
            "ne_index": int(c),
        })

    print("rivers")
    rivers = build_rivers()

    world = {
        "version": 2,
        "grid": {"radius": R, "cols": COLS, "rows": ROWS},
        "width": round(WIDTH, 1),
        "height": round(HEIGHT, 1),
        "margin": 200.0,
        "owner": owner.tolist(),
        "elev": [int(round(v)) for v in elev],
        "elev_max": int(round(float(elev.max()))),
        "water": water.tolist(),
        "relief": relief.tolist(),
        "cover": cover.tolist(),
        "tables": TABLES,
        "states": states,
        "rivers": rivers,
    }
    with open(os.path.join(OUT, "world.json"), "w", encoding="utf-8") as f:
        json_dump(world, f)

    np.savez_compressed(
        os.path.join(OUT, "cells.npz"),
        owner=owner, water=water, elev=elev, elev_std=elev_std, cover=cover,
        relief=relief, land=land, code=codes, ok_urban=ok_urban,
        cols=np.array([COLS]), rows=np.array([ROWS]), radius=np.array([R]),
        width=np.array([WIDTH]), height=np.array([HEIGHT]),
    )
    land_cells = int(land.sum())
    print(f"world.json: {land_cells} land cells, {n - land_cells} water; "
          f"{len(states)} countries; {sum(len(r['pts'])//2 for r in rivers)} river vertices")


def build_rivers():
    rv = geo.load(os.path.join(CACHE, "rivers.geojson"))
    out = []
    for f in rv["features"]:
        p = f["properties"]
        rank = p.get("scalerank")
        if rank is None:
            rank = 10
        if rank > 9:
            continue
        name = p.get("name") or p.get("name_en") or ""
        for line in geo.line_parts(f.get("geometry")):
            pts = []
            last = None
            for lon, lat in line:
                x = (lon - LON_TOP) / LON_SCALE
                y = (LAT_TOP - lat) * 111.32
                if x < -50 or x > WIDTH + 50 or y < -50 or y > HEIGHT + 50:
                    last = None
                    continue
                if last is None or math.hypot(x - last[0], y - last[1]) >= 25:
                    pts.extend([round(x, 1), round(y, 1)])
                    last = (x, y)
            if len(pts) >= 6:
                out.append({"name": name, "rank": int(rank), "pts": pts})
    out.sort(key=lambda r: (r["rank"], -len(r["pts"])))
    return out[:220]


def json_dump(obj, f):
    import json
    json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))


if __name__ == "__main__":
    build()
