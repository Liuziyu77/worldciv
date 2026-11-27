"""Download the raw inputs worldciv is built from into pipeline/cache/.

Everything here is public-domain or openly licensed and is fetched once; the build
scripts never touch the network except through this file.

    python pipeline/fetch_data.py
"""
import json
import os
import time
import urllib.request

CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache")
UA = {"User-Agent": "worldciv-build/1.0 (one-off data fetch)"}

NE = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/"

# Natural Earth layers (1:50m where detail is enough for 75 km hexes).
NE_FILES = {
    "countries": "ne_50m_admin_0_countries.geojson",
    "places": "ne_10m_populated_places.geojson",      # 7k cities, filtered at build time
    "lakes": "ne_50m_lakes.geojson",
    "rivers": "ne_50m_rivers_lake_centerlines.geojson",
    "urban": "ne_50m_urban_areas.geojson",
    "ports": "ne_10m_ports.geojson",
    "airports": "ne_10m_airports.geojson",
}

KOPPEN = "https://raw.githubusercontent.com/circleofconfusion/climate-map/master/topojson/1976-2000.geojson"

WB_IND = [
    "SP.POP.TOTL",        # population
    "NY.GDP.MKTP.CD",     # GDP, current US$
    "NY.GDP.PCAP.CD",     # GDP per capita
    "NV.IND.MANF.CD",     # manufacturing value added
    "GB.XPD.RSDV.GD.ZS",  # R&D, % of GDP
    "AG.PRD.CREL.MT",     # cereal production, tonnes
    "SL.AGR.EMPL.ZS",     # employment in agriculture, %
    "SL.IND.EMPL.ZS",     # employment in industry, %
    "SL.SRV.EMPL.ZS",     # employment in services, %
    "SP.URB.TOTL.IN.ZS",  # urban population, %
    "SP.DYN.LE00.IN",     # life expectancy
    "ST.INT.ARVL",        # international tourist arrivals
    "EG.ELC.ACCS.ZS",     # access to electricity, %
    "IT.NET.USER.ZS",     # internet users, %
    "MS.MIL.XPND.CD",     # military expenditure
    "AG.LND.ARBL.HA",     # arable land, ha
    "SP.POP.SCIE.RD.P6",  # researchers per million
    "SL.TLF.CACT.ZS",     # labour force participation, %
    "NY.GDP.MKTP.KD.ZG",  # GDP growth, %
]


def get(url, path, tries=4, binary=False):
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return path
    for k in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=90) as r:
                data = r.read()
            with open(path + ".part", "wb") as f:
                f.write(data)
            os.replace(path + ".part", path)
            print(f"  ok {os.path.basename(path)} ({len(data)/1e6:.2f} MB)")
            return path
        except Exception as e:
            print(f"  retry {k+1}/{tries}: {url} — {e}")
            time.sleep(3 * (k + 1))
    raise SystemExit(f"failed to download {url}")


def main():
    os.makedirs(CACHE, exist_ok=True)

    for name, fn in NE_FILES.items():
        print(f"natural earth: {name}")
        get(NE + fn, os.path.join(CACHE, f"{name}.geojson"))
        time.sleep(0.5)

    print("koppen climates")
    get(KOPPEN, os.path.join(CACHE, "koppen.geojson"))

    print("world bank indicators")
    for ind in WB_IND:
        fn = os.path.join(CACHE, "wb", f"{ind}.json")
        os.makedirs(os.path.dirname(fn), exist_ok=True)
        url = f"https://api.worldbank.org/v2/country/all/indicator/{ind}?format=json&per_page=20000&date=2000:2025"
        get(url, fn)
        time.sleep(0.4)

    print("terrarium elevation tiles, zoom 4 (16x16)")
    tdir = os.path.join(CACHE, "terrarium4")
    os.makedirs(tdir, exist_ok=True)
    n = 16
    for x in range(n):
        for y in range(n):
            url = f"https://s3.amazonaws.com/elevation-tiles-prod/terrarium/4/{x}/{y}.png"
            get(url, os.path.join(tdir, f"{x}_{y}.png"), tries=3)
        print(f"  column {x+1}/{n}")

    print("done")


if __name__ == "__main__":
    main()
