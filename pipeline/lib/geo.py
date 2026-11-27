"""Small geometry helpers: GeoJSON loading, vectorised point-in-polygon, a bucket index.

No shapely/geopandas needed; everything here is numpy + stdlib, so the pipeline runs anywhere
with numpy and Pillow.
"""
import json
import math
from collections import defaultdict

import numpy as np


# --- GeoJSON -------------------------------------------------------------------------------------------------


def load(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def poly_parts(geom):
    """GeoJSON geometry -> list of (outer_ring, [holes]) in lon/lat."""
    if not geom:
        return []
    t = geom.get("type")
    coords = geom.get("coordinates")
    if t == "Polygon":
        return [(coords[0], coords[1:])] if coords else []
    if t == "MultiPolygon":
        return [(poly[0], poly[1:]) for poly in coords if poly]
    return []


def line_parts(geom):
    """GeoJSON LineString / MultiLineString -> list of coordinate lists."""
    if not geom:
        return []
    t = geom.get("type")
    coords = geom.get("coordinates")
    if t == "LineString":
        return [coords] if coords else []
    if t == "MultiLineString":
        return list(coords or [])
    return []


def ring_bbox(ring):
    a = np.asarray(ring, dtype=float)
    return a[:, 0].min(), a[:, 1].min(), a[:, 0].max(), a[:, 1].max()


def points_in_ring(ring, lon, lat):
    """Even-odd ray casting, vectorised over points. `ring` may or may not be closed."""
    a = np.asarray(ring, dtype=float)
    n = len(a)
    inside = np.zeros(lon.shape, dtype=bool)
    j = n - 1
    for i in range(n):
        xi, yi = a[i, 0], a[i, 1]
        xj, yj = a[j, 0], a[j, 1]
        if yi == yj:
            j = i
            continue
        straddles = (yi > lat) != (yj > lat)
        if straddles.any():
            xint = (xj - xi) * (lat - yi) / (yj - yi) + xi
            inside ^= straddles & (lon < xint)
        j = i
    return inside


class PolyIndex:
    """Bucket index over polygon features, filtered by bbox, then even-odd test (holes honoured).

    Features are dicts with a `geometry`. `ids` optionally maps feature -> value (else the index).
    """

    def __init__(self, features, bin_deg=2.0, ids=None, keep=None):
        self.bin = bin_deg
        self.entries = []  # (key, [(outer, holes), ...])
        self.ids = []
        self.bins = defaultdict(list)
        for feat, fid in zip(features, ids if ids is not None else range(len(features))):
            if keep is not None and not keep(feat):
                continue
            parts = poly_parts(feat.get("geometry"))
            if not parts:
                continue
            k = len(self.entries)
            self.entries.append(parts)
            self.ids.append(fid)
            for outer, _ in parts:
                x0, y0, x1, y1 = ring_bbox(outer)
                for bx in range(int(math.floor(x0 / bin_deg)), int(math.floor(x1 / bin_deg)) + 1):
                    for by in range(int(math.floor(y0 / bin_deg)), int(math.floor(y1 / bin_deg)) + 1):
                        self.bins[(bx, by)].append(k)
        # de-duplicate candidate lists
        for key in self.bins:
            seen = set()
            out = []
            for k in self.bins[key]:
                if k not in seen:
                    seen.add(k)
                    out.append(k)
            self.bins[key] = out

    def query(self, lon, lat):
        """Return (found_mask, id_array) for points."""
        lon = np.asarray(lon, dtype=float)
        lat = np.asarray(lat, dtype=float)
        out = np.full(lon.shape, -1, dtype=np.int32)
        todo = np.ones(lon.shape, dtype=bool)
        bx = np.floor(lon / self.bin).astype(np.int64)
        by = np.floor(lat / self.bin).astype(np.int64)
        # Group points by bin so each polygon is tested once per bin (vectorised grouping).
        key = bx * 100000 + (by + 50000)
        uk, inv = np.unique(key, return_inverse=True)
        order = [(int(k), np.where(inv == j)[0]) for j, k in enumerate(uk)]
        for key, idxs in order:
            kx, ky = key // 100000, key % 100000 - 50000
            cand = self.bins.get((int(kx), int(ky)))
            if not cand:
                continue
            pts_lon = lon[idxs]
            pts_lat = lat[idxs]
            alive = np.ones(len(idxs), dtype=bool)
            for k in cand:
                if not alive.any():
                    break
                parts = self.entries[k]
                hit = np.zeros(len(idxs), dtype=bool)
                for outer, holes in parts:
                    x0, y0, x1, y1 = ring_bbox(outer)
                    inb = alive & (pts_lon >= x0) & (pts_lon <= x1) & (pts_lat >= y0) & (pts_lat <= y1)
                    if not inb.any():
                        continue
                    m = np.zeros(len(idxs), dtype=bool)
                    sel = np.where(inb)[0]
                    m[sel] = points_in_ring(outer, pts_lon[sel], pts_lat[sel])
                    for hole in holes:
                        hx0, hy0, hx1, hy1 = ring_bbox(hole)
                        hsel = np.where(m & (pts_lon >= hx0) & (pts_lon <= hx1) & (pts_lat >= hy0) & (pts_lat <= hy1))[0]
                        if len(hsel):
                            m[hsel] &= ~points_in_ring(hole, pts_lon[hsel], pts_lat[hsel])
                    hit |= m
                take = alive & hit
                if take.any():
                    for pos in np.where(take)[0]:
                        out[idxs[pos]] = self.ids[k]
                    alive &= ~take
        return out >= 0, out


def point_in_any(features, lon, lat):
    """Boolean mask: is each point inside at least one feature polygon?"""
    idx = PolyIndex(features)
    ok, _ = idx.query(lon, lat)
    return ok


# --- mercator <-> lon/lat ------------------------------------------------------------------------------------

def lonlat_to_merc(lon, lat):
    lon = np.asarray(lon, float)
    lat = np.clip(np.asarray(lat, float), -85.05112878, 85.05112878)
    r = np.radians(lat)
    return lon, np.degrees(np.log(np.tan(np.pi / 4 + r / 2)))


# --- rasterised masks (fast lookups for millions of sample points) ---------------------------------------------

RES = 0.05  # degrees per pixel: 7200 x 3600 over the whole world (~5.5 km at the equator)


def rasterize(features, ids=None, res=RES):
    """Paint polygon features into an int32 lon/lat raster; value id per feature, 0 outside.

    Holes are painted back to 0 after their outer ring, so a label raster treats them as unowned.
    """
    from PIL import Image, ImageDraw

    w = int(round(360 / res))
    h = int(round(180 / res))
    img = Image.new("I", (w, h), 0)
    d = ImageDraw.Draw(img)

    def xy(ring):
        return [((lon + 180.0) / res, (90.0 - lat) / res) for lon, lat in ring]

    for k, feat in enumerate(features):
        val = int(ids[k] if ids is not None else k + 1)
        for outer, holes in poly_parts(feat.get("geometry")):
            d.polygon(xy(outer), fill=val)
            for hole in holes:
                d.polygon(xy(hole), fill=0)
    return np.asarray(img, dtype=np.int32)


def rasterize_mask(features, res=RES):
    """Boolean raster: 1 where any feature polygon covers the pixel."""
    r = rasterize(features, ids=[1] * len(features), res=res)
    return r > 0


def lookup(raster, lon, lat, res=RES):
    """Nearest-pixel lookup of a raster at lon/lat (degrees)."""
    h, w = raster.shape
    x = np.clip(((np.asarray(lon) + 180.0) / res).astype(np.int64), 0, w - 1)
    y = np.clip(((90.0 - np.asarray(lat)) / res).astype(np.int64), 0, h - 1)
    return raster[y, x]

