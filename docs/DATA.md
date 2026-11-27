# Data contracts & build notes

## Grid

- Equirectangular, km units. `R = 70 km`, `COLS = 331`, `ROWS = 180` (59,580 hexes).
- `lon = -180 + x * 360 / width`, `lat = 85 - y / 111.32`.
- World is `40,131 x 18,900 km`; the camera treats it like usaciv's map.
- 13 sample points per hex (centre + rings at 0.45R and 0.85R) decide land, owner and water.

## world.json (v2)

```
{version, grid:{radius,cols,rows}, width, height, margin,
 owner:[int per hex],            # country index, -1 water
 elev:[int per hex],             # metres (bathymetry below 0)
 elev_max, water:[0..3], relief:[0..3], cover:[0..11],
 tables:{water,relief,cover,notes}, states:[{fips,abbr,name,full,continent,subregion,iso2,ne_index}],
 rivers:[{name,rank,pts:[x,y,...]}]}
```

- `water`: 0 land, 1 ocean, 2 coast, 3 lake (Natural Earth lake at the hex centre).
- `cover` ids match usaciv's palette: 1 temperate forest, 2 rainforest/boreal, 3 mixed, 4 scrub/desert,
  5 grassland/savanna, 6 pasture, 7 cropland, 8 wetland, 9 built-up, 10 barren/tundra, 11 ice.
- Cover comes from Köppen–Geiger polygons; urban areas override; elevation overrides high mountains.
  Cropland/pasture carving is documented in `tables.notes.cover` (planned refinement: World Bank arable
  hectares per country placed on the most suitable hexes).

## cities.json

Natural Earth populated places, filtered to `POP_MAX >= 300k` or a national capital (1,519 places).
City yields/jobs are the country's World Bank totals shared by the city's population share. `cell` is the
hex index from the grid's `cellAt(x, y)`.

## states.json

One entry per mapped country, in the same order as `world.json.states`:

```
{fips, abbr, name, full, continent, subregion, iso2, population, employed,
 jobs:{agriculture,industry,services}, yields:{food,production,gold,science,culture},
 ranks:{...}, gdp, gdp_year, growth, growth_years, urban, life, elec, net, researchers}
```

Country totals come from the World Bank, falling back to Natural Earth's `POP_EST` / `GDP_MD_EST`.

## nation.json

`{vintage, year, gdp_vintage, nation:{population, employed, jobs, yields, gdp, gdp_year, urban, life, net,
elec, researchers}, yields:[definitions], industries:{labels}}`.

## lenses.json

15 lenses with a `values` array of length `COLS*ROWS`. Country-level values are painted on every hex the
country owns; population is a model (country totals around mapped cities); elevation, climate, coast
distance and terrain are per-hex rasters.

## resources.json

WRI Global Power Plant Database, plants >= 100 MW, grouped by fuel into the map's existing energy icons.
`value` is net capacity in MW.

## Known limitations

- Hexes are 121 km across: countries and islands smaller than a hex may not appear.
- Population, city yields and country borders are modelled at hex resolution, not census-exact.
- Antarctica is drawn but has no statistics.

## Validation

```bash
python3.12 pipeline/check_data.py
```

Checks every array length, owner/rank/water/cover range, state and nation totals, city cells and country
matches, lens domains, resource links and source ids. Prints a data-quality report and exits 1 on failure.
