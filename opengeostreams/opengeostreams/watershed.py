"""Watershed analysis and sampling planner, built from an elevation tile.

The terrain steps run once per area and are stored as a packed terrain file:

1. Read a lat/lon elevation GeoTIFF (``read_geotiff``; Pillow, no GDAL needed).
2. Fill depressions with priority-flood (Barnes, Lehman & Mulla 2014, with a small
   epsilon so flats drain), give every cell its steepest downhill neighbour (D8) and
   count the cells draining through it (``flow_network``).
3. Optionally add OpenStreetMap land use and point sources drawn on the same grid
   (``read_landuse``; fetched in a browser with ``osm_landuse_fetch.js``), then pack it
   all with ``build_terrain``.

The rest runs in the browser (``dashboard_assets/watershed.js``), as the dashboard's
**Watershed analysis** panel or as a standalone page (``planner_html``): you draw an
area, it splits the area into watersheds at stream confluences and boundary crossings,
finds each watershed's pour point, and picks the pour points where samples tell you
most about the area (Sharp's method for monitoring networks, weighted by land use).

The library ships a terrain file for the N-choe (Chandigarh-Mohali); build your own
for another area with ``build_terrain``.
"""

from __future__ import annotations

import base64
import gzip
import heapq
import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np

from . import pipeline

TERRAIN_PATH = pipeline.PACKAGE_ROOT / "reference_data" / "nchoe_terrain.json"
TEMPLATE_PATH = pipeline.PACKAGE_ROOT / "templates" / "watershed_planner.html"
EPSILON_M = 1e-4              # added per step while filling, so filled flats still drain
METRES_PER_DEGREE = 111_320.0
# D8 neighbours, index k -> (row step, column step). The planner page uses the same order.
DR = np.array([-1, -1, 0, 1, 1, 1, 0, -1])
DC = np.array([0, 1, 1, 1, 0, -1, -1, -1])
OFF_GRID = 255                # flow direction of a cell that drains off the tile
LAND_USE_CLASSES = {0: "unmapped", 1: "green", 2: "water", 3: "farmland", 4: "institutional",
                    5: "residential", 6: "commercial", 7: "construction", 8: "industrial"}
# Files the standalone page embeds, relative to dashboard_assets/ (the dashboard links the same ones).
ASSETS = ("vendor/leaflet/leaflet.css", "vendor/leaflet-draw/leaflet.draw.css", "watershed.css",
          "vendor/leaflet/leaflet.js", "vendor/leaflet-draw/leaflet.draw.js", "watershed.js")


# ----------------------------------------------------------------------------
# 1. Elevation
# ----------------------------------------------------------------------------

def read_geotiff(path: str | Path) -> tuple[np.ndarray, tuple[float, ...]]:
    """Read a single-band lat/lon GeoTIFF: ``(elevation, transform)``.

    ``transform`` is ``(a, b, c, d, e, f)`` as in rasterio: ``c``/``f`` are the
    longitude/latitude of the top-left corner of the top-left cell and ``a``/``e`` the
    cell size (``e`` negative). Point-registered rasters are shifted half a cell, as
    GDAL does.
    """
    from PIL import Image

    with Image.open(path) as image:
        tags = image.tag_v2
        scale, tiepoint = tags.get(33550), tags.get(33922)
        if not scale or not tiepoint:
            raise ValueError(f"{path} has no GeoTIFF position tags (ModelPixelScale/ModelTiepoint).")
        elevation = np.asarray(image, dtype=np.float64)
        keys = tags.get(34735) or ()
        nodata = tags.get(42113)
    geo = {keys[i]: keys[i + 3] for i in range(4, len(keys) - 3, 4)}
    if geo.get(2048, 4326) != 4326:
        raise ValueError(f"{path} must be in latitude/longitude (EPSG:4326).")
    a, e = float(scale[0]), -float(scale[1])
    column, row, _, lon, lat, _ = (float(value) for value in tiepoint[:6])
    c, f = lon - column * a, lat - row * e
    if geo.get(1025) == 2:   # RasterPixelIsPoint: the tiepoint is a cell centre
        c, f = c - a / 2, f - e / 2
    if nodata is not None:
        elevation[elevation == float(str(nodata).strip("\x00"))] = np.nan
    if np.isnan(elevation).any():
        elevation = np.where(np.isnan(elevation), np.nanmin(elevation), elevation)
    return elevation, (a, 0.0, c, 0.0, e, f)


def flow_network(elevation: np.ndarray, transform) -> dict[str, Any]:
    """Depression-filled D8 flow directions and flow accumulation (cells, inclusive)."""
    dem = np.asarray(elevation, dtype=np.float64)
    height, width = dem.shape
    a, _, _, _, e, f = transform
    mid_lat = f + e * height / 2
    dy = abs(e) * METRES_PER_DEGREE
    dx = a * METRES_PER_DEGREE * math.cos(math.radians(mid_lat))
    step = np.where((DR != 0) & (DC != 0), math.hypot(dx, dy), np.where(DR != 0, dy, dx))

    # Priority-flood from the tile edge: every cell ends up just above its spill point.
    filled = dem.copy()
    closed = np.zeros((height, width), bool)
    queue = []
    for r in range(height):
        for c in (0, width - 1):
            heapq.heappush(queue, (filled[r, c], r, c))
            closed[r, c] = True
    for c in range(1, width - 1):
        for r in (0, height - 1):
            heapq.heappush(queue, (filled[r, c], r, c))
            closed[r, c] = True
    while queue:
        z, r, c = heapq.heappop(queue)
        for k in range(8):
            rr, cc = r + DR[k], c + DC[k]
            if 0 <= rr < height and 0 <= cc < width and not closed[rr, cc]:
                closed[rr, cc] = True
                if filled[rr, cc] <= z:
                    filled[rr, cc] = z + EPSILON_M
                heapq.heappush(queue, (filled[rr, cc], rr, cc))

    # Steepest drop; edge cells with no downhill neighbour inside drain off the tile.
    fdir = np.full((height, width), OFF_GRID, np.uint8)
    best = np.zeros((height, width))
    padded = np.pad(filled, 1, constant_values=np.inf)
    for k in range(8):
        neighbour = padded[1 + DR[k]:1 + DR[k] + height, 1 + DC[k]:1 + DC[k] + width]
        slope = (filled - neighbour) / step[k]
        steeper = slope > best
        best[steeper] = slope[steeper]
        fdir[steeper] = k
    edge = np.zeros((height, width), bool)
    edge[0, :] = edge[-1, :] = edge[:, 0] = edge[:, -1] = True
    fdir[edge & (best <= 0)] = OFF_GRID

    # Accumulation in topological order (upstream cells first).
    index = np.arange(height * width).reshape(height, width)
    down = np.full(height * width, -1, np.int64)
    flowing = fdir.ravel() != OFF_GRID
    rows = (index // width).ravel()[flowing] + DR[fdir.ravel()[flowing]]
    cols = (index % width).ravel()[flowing] + DC[fdir.ravel()[flowing]]
    inside = (rows >= 0) & (rows < height) & (cols >= 0) & (cols < width)
    target = np.full(int(flowing.sum()), -1)
    target[inside] = rows[inside] * width + cols[inside]
    down[flowing] = target
    indegree = np.bincount(down[down >= 0], minlength=height * width)
    accumulation = np.ones(height * width, np.float64)
    stack = list(np.nonzero(indegree == 0)[0])
    while stack:
        i = stack.pop()
        d = down[i]
        if d >= 0:
            accumulation[d] += accumulation[i]
            indegree[d] -= 1
            if indegree[d] == 0:
                stack.append(d)
    return {"dem": dem, "fdir": fdir, "accumulation": accumulation.reshape(height, width),
            "transform": tuple(float(value) for value in transform), "dx": float(dx), "dy": float(dy)}


# ----------------------------------------------------------------------------
# 2. Land use
# ----------------------------------------------------------------------------

def read_landuse(path: str | Path, shape: tuple[int, int]) -> tuple[np.ndarray, list]:
    """Land-use classes and point sources from ``osm_landuse_fetch.js`` output.

    The grid is run-length encoded as ``"<class><run length in base 36>"`` tokens and
    must have the elevation tile's ``shape``. Point sources are
    ``[type, name, latitude, longitude]``.
    """
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    height, width = shape
    if (payload["grid"]["h"], payload["grid"]["w"]) != (height, width):
        raise ValueError(f"Land-use grid is {payload['grid']['w']}x{payload['grid']['h']}, "
                         f"but the elevation tile is {width}x{height}.")
    classes = np.zeros(height * width, np.uint8)
    position = 0
    for token in payload["rle"].split(","):
        run = int(token[1:], 36)
        classes[position:position + run] = int(token[0])
        position += run
    if position != height * width:
        raise ValueError("Land-use grid does not cover the whole elevation tile.")
    return classes.reshape(height, width), payload.get("pts", [])


# ----------------------------------------------------------------------------
# 3. Packed terrain
# ----------------------------------------------------------------------------

def _packed(array) -> str:
    return base64.b64encode(gzip.compress(np.ascontiguousarray(array).tobytes(), 9, mtime=0)).decode()


def build_terrain(dem_path: str | Path, landuse_path: str | Path | None = None, *,
                  out_path: str | Path | None = None, name: str | None = None,
                  example: list[list[float]] | None = None,
                  landuse_source: str | None = None) -> dict[str, Any]:
    """Pack an elevation tile (and optional land use) into a planner terrain file.

    ``example`` is an optional ``[[lat, lon], ...]`` polygon offered as "Load example".
    Writes JSON to ``out_path`` when given. Filling a 1-arc-second tile takes about a
    minute.
    """
    elevation, transform = read_geotiff(dem_path)
    flow = flow_network(elevation, transform)
    height, width = elevation.shape
    classes, sources = (read_landuse(landuse_path, (height, width)) if landuse_path
                        else (np.zeros((height, width), np.uint8), []))
    a, _, c, _, _, f = flow["transform"]
    terrain = {
        "name": name or Path(dem_path).stem, "W": width, "H": height, "lon0": c, "lat0": f, "res": a,
        "dx": flow["dx"], "dy": flow["dy"],
        "fdir": _packed(flow["fdir"].astype(np.uint8)),
        # Decimetres, rounded in float32 like the original planner build.
        "dem": _packed(np.clip(np.round(flow["dem"].astype(np.float32) * np.float32(10)), 0, 65535).astype("<u2")),
        "lu": _packed(classes.astype(np.uint8)),
        "hasLU": landuse_path is not None, "landuseSource": landuse_source,
        "sources": sources, "example": example,
    }
    if out_path:
        Path(out_path).write_text(json.dumps(terrain, separators=(",", ":")), encoding="utf-8")
    return terrain


@lru_cache(maxsize=4)
def _cached_terrain(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def terrain_json(path: str | Path | None = None) -> str:
    """The text of a packed terrain file; the bundled N-choe tile by default."""
    return _cached_terrain(str(Path(path).expanduser().resolve()) if path else str(TERRAIN_PATH))


def load_terrain(path: str | Path | None = None) -> dict[str, Any]:
    """A packed terrain file; the bundled N-choe tile by default."""
    return json.loads(terrain_json(path))


def terrain_bounds(terrain: dict[str, Any]) -> tuple[float, float, float, float]:
    """``(south, west, north, east)`` of a packed terrain tile."""
    return (terrain["lat0"] - terrain["H"] * terrain["res"], terrain["lon0"],
            terrain["lat0"], terrain["lon0"] + terrain["W"] * terrain["res"])


# ----------------------------------------------------------------------------
# 4. Planner page
# ----------------------------------------------------------------------------

def stations_of(dataset) -> list[list]:
    """``[name, latitude, longitude]`` for every mapped station of a dataset."""
    return [[location["name"], round(float(location["latitude"]), 6), round(float(location["longitude"]), 6)]
            for location in dataset._dashboard_data.get("locations", [])
            if location.get("hasCoordinates") and location.get("latitude") is not None]


def _inline_assets() -> tuple[str, str]:
    head, scripts = [], []
    for name in ASSETS:
        text = (pipeline.ROOT / name).read_text(encoding="utf-8")
        if name.endswith(".css"):
            head.append(f"<style>{text}</style>")
        else:
            scripts.append("<script>" + text.replace("</script", "<\\/script") + "</script>")
    return "\n".join(head), "\n".join(scripts)


def planner_html(stations: list[list] | None = None, terrain: dict[str, Any] | None = None) -> str:
    """A standalone Watershed analysis page for ``stations`` on ``terrain`` (default: the bundled tile).

    It runs the same code as the dashboard's Watershed analysis panel, with Leaflet
    embedded, so the file works on its own (map tiles still need internet).
    """
    terrain = dict(terrain or load_terrain())
    terrain["stations"] = list(stations or [])
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    head, scripts = _inline_assets()
    data = "window.PLANNER_DATA=" + json.dumps(terrain, separators=(",", ":")).replace("</", "<\\/") + ";"
    for token, value in (("<!--ASSETS_HEAD-->", head), ("<!--ASSETS_SCRIPTS-->", scripts), ("/*DATA*/", data)):
        if token not in template:
            raise RuntimeError(f"Planner template is missing {token}.")
        template = template.replace(token, value)
    return template
