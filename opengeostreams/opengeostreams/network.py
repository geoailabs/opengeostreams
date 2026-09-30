"""Assign monitoring stations to drains/rivers and order them upstream -> downstream.

Uses geopandas with the India-WRIS river/drain network:

1. Each station gets its drain/river from, in order of priority:
   a. a name column in the file ("Water Body", "Drain", "River", ...);
   b. a water-body name written in the station label ("HUDIARA DRAIN AT ...",
      "RIVER BEAS AT ...", "BUDHA NALLAH"), fuzzy-matched to a nearby network line;
   c. the nearest network line within ``max_distance_km``.
   A name from (a) or (b) that is not in the network still groups its stations.
   Stations with none of these are reported as unassigned with the nearest line.
2. Same-named network lines that connect to the matched line form one channel.
3. The downstream outlet is the lowest end of the channel by terrain elevation
   (Open-Meteo elevation API, Copernicus DEM), preferring an end that joins a
   differently named line (a confluence). Offline, or when the ends differ by
   less than a few metres, the confluence and then the direction the lines are
   drawn in decide; the method used is reported for each channel.
4. Stations are ordered by distance along the channel to the outlet: the farthest
   station is the most upstream.

This is a geometric approximation of the network, not a hydrological model.
"""

from __future__ import annotations

import heapq
import json
import math
import ssl
import urllib.parse
import urllib.request
from difflib import SequenceMatcher
import os
import re
from pathlib import Path
from typing import Any

import pandas as pd

from . import pipeline

WATER_BODY_KEYS = (
    "Water Body", "Water Body Name", "Waterbody", "Drain", "Drain Name",
    "River", "River Name", "Channel", "Stream",
)
DEFAULT_MAX_DISTANCE_KM = 2.0
NETWORK_ENV = "OPENGEOSTREAMS_NETWORK"
NETWORK_CANDIDATES = (
    pipeline.PROJECT_ROOT / "data" / "indiawris" / "WRIS_Rivers_2024.parquet",
    pipeline.PACKAGE_ROOT / "reference_data" / "indiawris_punjab_channels_2024.shp",
)
# Local names that mean the same water body ("alias,name" CSV). Users can add their own
# file with OPENGEOSTREAMS_ALIASES or data/water_body_aliases.csv in the project folder.
ALIASES_ENV = "OPENGEOSTREAMS_ALIASES"
ALIAS_FILES = (
    pipeline.PACKAGE_ROOT / "reference_data" / "water_body_aliases.csv",
    pipeline.PROJECT_ROOT / "data" / "water_body_aliases.csv",
)
NODE_TOLERANCE_M = 30.0      # endpoints closer than this are the same network node
CONFLUENCE_TOLERANCE_M = 250.0  # a channel end this close to another line is a confluence
EXTENDED_SNAP_M = 5000.0  # beyond the limit, only onto a channel that already has stations
EXTENDED_NEIGHBOUR_M = 10000.0  # ... and one of them within this distance
NAME_MATCH_RADIUS_M = 15000.0   # search radius for lines matching a station's water-body name
NAME_MATCH_THRESHOLD = 0.8
ELEVATION_URL = "https://api.open-meteo.com/v1/elevation"
OFFLINE_ENV = "OPENGEOSTREAMS_OFFLINE"
MIN_ELEVATION_DROP_M = 5.0
MAX_ELEVATION_LEAVES = 6         # channel ends looked up per channel      # smaller differences between channel ends are treated as flat
CONFLUENCE_ELEVATION_SLACK_M = 3.0
_ELEVATION_CACHE: dict[tuple[float, float], float | None] = {}


def fetch_point_elevations(points: list[tuple[float, float]], timeout: float = 10.0,
                           budget_s: float = 20.0, workers: int = 6) -> dict[tuple[float, float], float]:
    """Terrain elevation (m) for (lon, lat) points from Open-Meteo; {} when offline.

    Requests (100 points each) run in parallel and the whole lookup stops after
    ``budget_s`` seconds; points without an answer simply fall back to topology.
    """
    if os.environ.get(OFFLINE_ENV):
        return {}
    from concurrent.futures import ThreadPoolExecutor, wait
    keys = [(round(lon, 5), round(lat, 5)) for lon, lat in points]
    missing = [key for key in dict.fromkeys(keys) if key not in _ELEVATION_CACHE]
    try:
        import certifi
        context = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        context = ssl.create_default_context()

    def fetch(batch):
        query = urllib.parse.urlencode({"latitude": ",".join(str(lat) for _, lat in batch),
                                        "longitude": ",".join(str(lon) for lon, _ in batch)})
        request = urllib.request.Request(f"{ELEVATION_URL}?{query}", headers={"User-Agent": "OpenGeoStreams/2.0"})
        with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
            values = json.loads(response.read().decode("utf-8")).get("elevation", [])
        for key, value in zip(batch, values):
            _ELEVATION_CACHE[key] = float(value) if isinstance(value, (int, float)) and math.isfinite(value) else None

    if missing:
        batches = [missing[start:start + 100] for start in range(0, len(missing), 100)]
        pool = ThreadPoolExecutor(max_workers=max(1, min(workers, len(batches))))
        try:
            futures = [pool.submit(fetch, batch) for batch in batches]
            wait(futures, timeout=budget_s)  # failed or late batches are skipped
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
    return {key: _ELEVATION_CACHE[key] for key in keys if _ELEVATION_CACHE.get(key) is not None}

# Words that describe the kind of water body; the word(s) before them are its name.
TYPE_WORDS = {
    "DRAIN", "NALLAH", "NALLA", "NALA", "NULLAH", "NULLA", "NALAH", "CHOE", "CHOA", "KHAD",
    "RAO", "CANAL", "NADI", "NAHAR", "BEIN", "CREEK", "STREAM", "RIVER", "NADDI",
}
# Words that end a name when reading outwards from the type word.
NAME_STOP_WORDS = {
    "AT", "ON", "OF", "THE", "IN", "TO", "FROM", "AND", "NEAR", "BRIDGE", "POINT", "SOURCE", "SOURSE",
    "OUTLET", "VILL", "VILLAGE", "DIST", "DISTT", "DISTRICT", "MAIN", "NEW", "OLD", "ROAD", "CITY",
    "UPSTREAM", "DOWNSTREAM", "BELOW", "ABOVE", "SAMPLING", "STATION", "SITE", "NO", "EXIT", "ENTRY",
}
# Everything after these words describes the receiving water body, not the station's own.
RECEIVING_CLAUSE = re.compile(
    r"\b(?:INTO|FALLING|FALLS|JOINS?|JOINING|MEETS?|CONFLUENCE|CONF|BEFORE|AFTER|ENTERS?|WHERE|MERGES?)\b")


def parse_water_body(label: str) -> str:
    """Return the drain/river named in a station label, e.g. "Hudiara Drain", or ""."""
    text = re.sub(r"[^A-Za-z0-9\-/ ]+", " ", str(label or "")).upper()
    text = RECEIVING_CLAUSE.split(text)[0]
    tokens = text.split()

    def usable(token):
        return token.isalpha() and len(token) > 1 and token not in NAME_STOP_WORDS and token not in TYPE_WORDS

    for index, token in enumerate(tokens):
        head, _, tail = token.rpartition("-")
        if tail in TYPE_WORDS and head and head.replace("-", "").isalpha():   # e.g. N-CHOE
            return f"{head.title()}-{tail.title()}"
        if token not in TYPE_WORDS:
            continue
        if token == "RIVER":
            after = []
            for word in tokens[index + 1:index + 3]:
                if not usable(word):
                    break
                after.append(word)
            if after:
                return " ".join(after).title()
        before = []
        for word in reversed(tokens[max(0, index - 2):index]):
            if not usable(word):
                break
            before.insert(0, word)
        if before:
            name = " ".join(before).title()
            return name if token == "RIVER" else f"{name} {token.title()}"
    return ""


def load_aliases() -> dict[str, str]:
    """Map normalised local names to one preferred name, from the alias CSV files."""
    import csv
    paths = list(ALIAS_FILES)
    if os.environ.get(ALIASES_ENV):
        paths.append(Path(os.environ[ALIASES_ENV]))
    aliases: dict[str, str] = {}
    for path in paths:
        path = Path(path).expanduser()
        if not path.is_file():
            continue
        with path.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                alias, name = (row.get("alias") or "").strip(), (row.get("name") or "").strip()
                if alias and name:
                    aliases[_base_name(alias)] = name
                    aliases.setdefault(_base_name(name), name)
    return aliases


def canonical_name(name: str, aliases: dict[str, str] | None = None) -> str:
    """Preferred name for a water body (e.g. "Attawa Choa" -> "N-Choe"); unchanged if unknown."""
    if not name:
        return name
    aliases = load_aliases() if aliases is None else aliases
    return aliases.get(_base_name(name), name)


def _base_name(name: str) -> str:
    words = re.findall(r"[a-z]+", str(name).casefold())
    return " ".join(word for word in words if word.upper() not in TYPE_WORDS)


def name_similarity(left: str, right: str) -> float:
    """Similarity of two water-body names, tolerant of transliteration (Budha/Budda, Sutlej/Satluj)."""
    a, b = _base_name(left), _base_name(right)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    short, long = sorted((a, b), key=len)
    if len(short) >= 4 and short in long.split():
        return 0.9
    ratio = SequenceMatcher(None, a, b).ratio()
    skeleton_a, skeleton_b = re.sub(r"[aeiouy ]+", "", a), re.sub(r"[aeiouy ]+", "", b)
    skeleton = SequenceMatcher(None, skeleton_a, skeleton_b).ratio() if min(len(skeleton_a), len(skeleton_b)) >= 3 else 0.0
    return max(ratio, 0.95 * skeleton)


def _geo():
    try:
        import geopandas as gpd
        import shapely
    except ImportError as error:  # pragma: no cover - depends on the environment
        raise ValueError("River-network matching needs geopandas: python -m pip install geopandas pyarrow") from error
    return gpd, shapely


def find_network_path(path: str | Path | None = None) -> Path:
    candidates = [Path(path)] if path else []
    if os.environ.get(NETWORK_ENV):
        candidates.append(Path(os.environ[NETWORK_ENV]))
    candidates.extend(NETWORK_CANDIDATES)
    for candidate in candidates:
        if candidate.expanduser().is_file():
            return candidate.expanduser()
    raise ValueError(
        "No river network file found. Put WRIS_Rivers_2024.parquet in data/indiawris/ "
        f"or set {NETWORK_ENV} to a river/drain line file."
    )


_NETWORK_CACHE: dict[tuple, Any] = {}


def load_network(bounds: tuple[float, float, float, float], path: str | Path | None = None,
                 buffer_deg: float = 0.25):
    """Read network lines intersecting ``bounds`` (min lon, min lat, max lon, max lat).

    Results are cached in memory per file and (rounded) area, so importing more
    files from the same region does not re-read the network.
    """
    gpd, _ = _geo()
    source = find_network_path(path)
    minx, miny, maxx, maxy = bounds
    box = tuple(round(value, 1) for value in (minx - buffer_deg, miny - buffer_deg, maxx + buffer_deg, maxy + buffer_deg))
    cache_key = (str(source.resolve()), source.stat().st_mtime, box)
    if cache_key in _NETWORK_CACHE:
        return _NETWORK_CACHE[cache_key].copy()
    result = _read_network(source, box, gpd)
    if len(_NETWORK_CACHE) >= 4:
        _NETWORK_CACHE.pop(next(iter(_NETWORK_CACHE)))
    _NETWORK_CACHE[cache_key] = result
    return result.copy()


def _read_parquet_bbox(source: Path, box: tuple[float, float, float, float]) -> pd.DataFrame:
    try:
        import pyarrow.dataset as ds
    except ImportError:
        # pyarrow.dataset can be unavailable (e.g. its DLLs blocked by Windows Application
        # Control); scan row groups with pyarrow.parquet instead.
        ds = None
    if ds is not None:
        field = ds.field
        table = ds.dataset(str(source)).to_table(filter=(field("xmax") >= box[0]) & (field("xmin") <= box[2])
                                                 & (field("ymax") >= box[1]) & (field("ymin") <= box[3]))
        return table.to_pandas()
    import pyarrow.parquet as pq
    parquet = pq.ParquetFile(str(source))
    parts = []
    for index in range(parquet.num_row_groups):
        part = parquet.read_row_group(index).to_pandas()
        mask = ((part["xmax"] >= box[0]) & (part["xmin"] <= box[2])
                & (part["ymax"] >= box[1]) & (part["ymin"] <= box[3]))
        if mask.any():
            parts.append(part[mask])
    if not parts:
        return parquet.schema_arrow.empty_table().to_pandas()
    return pd.concat(parts, ignore_index=True)


def _read_network(source: Path, box: tuple[float, float, float, float], gpd):
    if source.suffix.lower() == ".parquet":
        import pyarrow.parquet as pq
        names = set(pq.read_schema(str(source)).names)
        if {"xmin", "ymin", "xmax", "ymax"} <= names:
            frame = _read_parquet_bbox(source, box)
            lines = gpd.GeoDataFrame(frame.drop(columns="geometry"),
                                     geometry=gpd.GeoSeries.from_wkb(frame["geometry"]), crs="EPSG:4326")
        else:
            lines = gpd.read_parquet(source).to_crs("EPSG:4326").cx[box[0]:box[2], box[1]:box[3]]
    else:
        try:
            lines = gpd.read_file(source, bbox=box).to_crs("EPSG:4326")
        except ImportError:
            # read_file needs GDAL (pyogrio/fiona), whose DLLs can be missing or blocked
            # on Windows; plain WGS84 polyline shapefiles are simple enough to read directly.
            if source.suffix.lower() != ".shp":
                raise
            lines = _read_shapefile_lines(source, box, gpd)
    name_column = next((column for column in ("rivname", "channel", "name", "NAME", "river", "Name") if column in lines), None)
    kind_column = next((column for column in ("layer", "kind") if column in lines), None)
    raw_names = lines[name_column].fillna("").astype(str).str.strip() if name_column else pd.Series("", index=lines.index)
    aliases = load_aliases()
    result = gpd.GeoDataFrame({
        # Local preferred names (alias list) for display; the map's own name is kept too.
        "name": [canonical_name(value, aliases) for value in raw_names],
        "network_name": raw_names.tolist(),
        "kind": lines[kind_column].fillna("").astype(str) if kind_column else "",
    }, geometry=lines.geometry.values, crs="EPSG:4326")
    result = result[result.geometry.notna() & ~result.geometry.is_empty]
    result = result.explode(index_parts=False).reset_index(drop=True)
    result = result[result.geom_type == "LineString"].reset_index(drop=True)
    result.attrs["source"] = source.name
    return result


def _read_shapefile_lines(source: Path, box: tuple[float, float, float, float], gpd):
    """Read a geographic (WGS84) polyline shapefile without GDAL, keeping lines inside ``box``."""
    import struct
    from shapely.geometry import LineString, MultiLineString

    prj = source.with_suffix(".prj")
    if prj.is_file() and not prj.read_text(errors="ignore").lstrip().upper().startswith("GEOGCS"):
        raise ImportError(f"{source.name} is projected; install pyogrio (GDAL) to read it.")

    # Attribute table (.dbf): header, field descriptors, then fixed-width records.
    attributes: list[dict[str, str]] = []
    dbf = source.with_suffix(".dbf")
    if dbf.is_file():
        data = dbf.read_bytes()
        count, header_size, record_size = struct.unpack("<IHH", data[4:12])
        fields, offset = [], 32
        while data[offset] != 0x0D:
            name = data[offset:offset + 11].split(b"\0")[0].decode("ascii", "ignore")
            fields.append((name, data[offset + 16]))
            offset += 32
        encoding = "utf-8"
        cpg = source.with_suffix(".cpg")
        if cpg.is_file():
            encoding = cpg.read_text(errors="ignore").strip() or encoding
        for index in range(count):
            start = header_size + index * record_size + 1  # skip the deletion flag
            row = {}
            for name, width in fields:
                row[name] = data[start:start + width].decode(encoding, "replace").strip()
                start += width
            attributes.append(row)

    # Geometry (.shp): 100-byte header, then one record per feature.
    data = source.read_bytes()
    geometries, offset = [], 100
    while offset + 8 <= len(data):
        _, length = struct.unpack(">ii", data[offset:offset + 8])
        body = offset + 8
        offset = body + 2 * length
        shape_type = struct.unpack("<i", data[body:body + 4])[0]
        if shape_type not in (3, 13, 23):  # PolyLine, PolyLineZ, PolyLineM
            geometries.append(None)
            continue
        xmin, ymin, xmax, ymax = struct.unpack("<4d", data[body + 4:body + 36])
        if xmax < box[0] or xmin > box[2] or ymax < box[1] or ymin > box[3]:
            geometries.append(None)
            continue
        num_parts, num_points = struct.unpack("<ii", data[body + 36:body + 44])
        parts = list(struct.unpack(f"<{num_parts}i", data[body + 44:body + 44 + 4 * num_parts])) + [num_points]
        start = body + 44 + 4 * num_parts
        coords = struct.unpack(f"<{2 * num_points}d", data[start:start + 16 * num_points])
        points = list(zip(coords[0::2], coords[1::2]))
        pieces = [points[a:b] for a, b in zip(parts, parts[1:]) if b - a >= 2]
        geometries.append(None if not pieces else LineString(pieces[0]) if len(pieces) == 1 else MultiLineString(pieces))

    frame = pd.DataFrame(attributes) if len(attributes) == len(geometries) else pd.DataFrame(index=range(len(geometries)))
    lines = gpd.GeoDataFrame(frame, geometry=geometries, crs="EPSG:4326")
    return lines[lines.geometry.notna()].reset_index(drop=True)


def station_table(frame: pd.DataFrame) -> pd.DataFrame:
    """One row per station (dashboard location name) with a representative coordinate."""
    data = frame.copy()
    data["Location"] = data["Location"].map(pipeline.location_group)
    data["Latitude"] = pd.to_numeric(data["Latitude"], errors="coerce")
    data["Longitude"] = pd.to_numeric(data["Longitude"], errors="coerce")
    water_column = next((column for column in WATER_BODY_KEYS if column in data), None)
    aliases = load_aliases()
    rows = []
    for location, group in data.groupby("Location", sort=True):
        if not location:
            continue
        valid = group[group["Latitude"].between(-90, 90) & group["Longitude"].between(-180, 180)]
        body = ""
        if water_column:
            names = group[water_column].dropna().astype(str).str.strip()
            names = names[names != ""]
            body = names.mode().iloc[0] if len(names) else ""
        rows.append({
            "Location": location,
            # Same position as the station's map marker (its first valid row), so the
            # drain/river match always agrees with what the user sees on the map.
            "Latitude": float(valid["Latitude"].iloc[0]) if len(valid) else math.nan,
            "Longitude": float(valid["Longitude"].iloc[0]) if len(valid) else math.nan,
            "WaterBody": canonical_name(body, aliases),
            "ParsedName": canonical_name(parse_water_body(location), aliases),
        })
    return pd.DataFrame(rows, columns=["Location", "Latitude", "Longitude", "WaterBody", "ParsedName"])


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.casefold()).strip("-") or "channel"


class _Nodes:
    """Union of line endpoints within NODE_TOLERANCE_M into shared graph nodes."""

    def __init__(self, lines):
        _, shapely = _geo()
        starts = [line.coords[0] for line in lines.geometry]
        ends = [line.coords[-1] for line in lines.geometry]
        points = shapely.points(starts + ends)
        parent = list(range(len(points)))

        def find(item):
            while parent[item] != item:
                parent[item] = parent[parent[item]]
                item = parent[item]
            return item

        tree = shapely.STRtree(points)
        left, right = tree.query(points, predicate="dwithin", distance=NODE_TOLERANCE_M)
        for a, b in zip(left, right):
            ra, rb = find(int(a)), find(int(b))
            if ra != rb:
                parent[ra] = rb
        count = len(lines)
        self.start = [find(index) for index in range(count)]
        self.end = [find(count + index) for index in range(count)]
        self.coords = {}
        all_coords = starts + ends
        for index in range(len(points)):
            self.coords.setdefault(find(index), all_coords[index])


def _dijkstra(adjacency: dict[int, list[tuple[int, float]]], source: int) -> dict[int, float]:
    distances = {source: 0.0}
    queue = [(0.0, source)]
    while queue:
        distance, node = heapq.heappop(queue)
        if distance > distances.get(node, math.inf):
            continue
        for neighbour, weight in adjacency.get(node, ()):
            candidate = distance + weight
            if candidate < distances.get(neighbour, math.inf):
                distances[neighbour] = candidate
                heapq.heappush(queue, (candidate, neighbour))
    return distances


def river_corridor_mask(network_result: dict[str, Any], extent: dict[str, float], stations: list[tuple[float, float]],
                        *, rows: int = pipeline.GRID_ROWS, columns: int = pipeline.GRID_COLUMNS,
                        min_half_width_m: float = 400.0) -> dict[str, Any] | None:
    """Rasterise the matched drains/rivers into an interpolation mask.

    Kriging is only meaningful along the water: cells within a narrow corridor
    around the channels that carry stations (plus a small disc around every
    station) are kept, everything else stays transparent. The corridor is at
    least one grid cell wide so the ribbon never breaks up on coarse grids.
    """
    import geopandas as gpd
    import numpy as np
    import shapely
    from shapely.geometry import shape

    lines = [shape(channel["geometry"]) for channel in network_result.get("channels", []) if channel.get("geometry")]
    if not lines or not stations:
        return None
    points = gpd.GeoSeries(gpd.points_from_xy([lon for _, lon in stations], [lat for lat, _ in stations]), crs="EPSG:4326")
    metric = points.estimate_utm_crs()
    lat_step = (extent["maxLatitude"] - extent["minLatitude"]) / (rows - 1)
    lon_step = (extent["maxLongitude"] - extent["minLongitude"]) / (columns - 1)
    mid_lat = math.radians((extent["maxLatitude"] + extent["minLatitude"]) / 2)
    cell_m = max(lat_step * 111_320.0, lon_step * 111_320.0 * math.cos(mid_lat))
    half_width = max(min_half_width_m, 0.75 * cell_m)
    corridor = gpd.GeoSeries(lines, crs="EPSG:4326").to_crs(metric).buffer(half_width)
    discs = points.to_crs(metric).buffer(half_width * 1.5)
    area = shapely.union_all(list(corridor) + list(discs))
    grid_rows, grid_columns = np.divmod(np.arange(rows * columns), columns)
    cell_lat = extent["maxLatitude"] - grid_rows * lat_step
    cell_lon = extent["minLongitude"] + grid_columns * lon_step
    cells = gpd.GeoSeries(gpd.points_from_xy(cell_lon, cell_lat), crs="EPSG:4326").to_crs(metric)
    inside = shapely.contains_xy(area, cells.x.to_numpy(), cells.y.to_numpy())
    return {"rows": rows, "cols": columns, "extent": extent, "maskValues": inside.astype(int).tolist(),
            "generatedFrom": "matched drain/river network", "activeCellCount": int(inside.sum()),
            "widthStats": {"halfWidthM": round(half_width, 1)}}


def _rounded_geojson(geometry, digits=5):
    """GeoJSON dict with coordinates rounded to ~1 m (keeps the payload small)."""
    def walk(value):
        if isinstance(value, (list, tuple)):
            if value and isinstance(value[0], (int, float)):
                return [round(float(item), digits) for item in value]
            return [walk(item) for item in value]
        return value
    shape = geometry.__geo_interface__
    if "coordinates" not in shape:
        return shape
    return {"type": shape["type"], "coordinates": walk(shape["coordinates"])}


def build_channel_network(frame: pd.DataFrame, *, max_distance_km: float = DEFAULT_MAX_DISTANCE_KM,
                          network=None, network_path: str | Path | None = None,
                          use_elevation: bool = True) -> dict[str, Any]:
    """Group stations by drain/river and order each group upstream -> downstream."""
    gpd, shapely = _geo()
    if isinstance(max_distance_km, bool) or not isinstance(max_distance_km, (int, float)) \
            or not math.isfinite(max_distance_km) or max_distance_km <= 0:
        raise ValueError("max_distance_km must be a positive number.")
    stations = station_table(frame)
    mapped = stations.dropna(subset=["Latitude", "Longitude"]).reset_index(drop=True)
    result: dict[str, Any] = {
        "method": "Drain/river column, else the water-body name in the station label matched to a nearby "
                  "network line, else the nearest line within the distance limit; order follows distance "
                  "along the channel to its confluence.",
        "maxDistanceKm": float(max_distance_km),
        "source": None,
        "channels": [],
        "unassigned": [],
        "noCoordinates": sorted(stations.loc[stations["Latitude"].isna() | stations["Longitude"].isna(), "Location"].tolist()),
    }
    if mapped.empty:
        return result
    points = gpd.GeoDataFrame(mapped, geometry=gpd.points_from_xy(mapped["Longitude"], mapped["Latitude"]), crs="EPSG:4326")
    if network is None:
        network = load_network(tuple(points.total_bounds), network_path)
    result["source"] = network.attrs.get("source", "custom network")
    if network.empty:
        result["unassigned"] = [{"location": name, "nearest": None, "distanceM": None} for name in mapped["Location"]]
        return result
    metric = points.estimate_utm_crs()
    points_m = points.to_crs(metric)
    lines = network.to_crs(metric).reset_index(drop=True)
    lines["key"] = lines["name"].str.casefold()
    keys = lines["key"].tolist()
    names = lines["name"].tolist()
    network_names = (lines["network_name"] if "network_name" in lines else lines["name"]).tolist()
    kinds = lines["kind"].tolist()
    geoms = lines.geometry.values
    nodes = _Nodes(lines)
    tree = shapely.STRtree(geoms)
    limit_m = float(max_distance_km) * 1000.0

    # 1. Which line does each station sit on?
    station_line: dict[int, tuple[int, float]] = {}
    station_source: dict[int, str] = {}
    name_only: dict[int, str] = {}
    deferred: list[tuple[int, int | None, float]] = []  # (station, nearest line, metres) beyond the limit
    for index, row in points_m.iterrows():
        point = row.geometry
        column_name = str(row["WaterBody"]).strip()
        parsed_name = str(row["ParsedName"]).strip()
        name = column_name or parsed_name
        chosen = None
        if name:
            # Look for a line with a matching name close by first, then farther out.
            for radius in (limit_m, NAME_MATCH_RADIUS_M):
                candidates = [int(item) for item in tree.query(point, predicate="dwithin", distance=radius)]
                scored = [(name_similarity(name, names[item]), -geoms[item].distance(point), item) for item in candidates if keys[item]]
                scored = [entry for entry in scored if entry[0] >= NAME_MATCH_THRESHOLD]
                if scored:
                    chosen = max(scored)[2]
                    station_source[index] = "file column" if column_name else "name in station label"
                    break
        if chosen is None and not column_name:
            nearest = [int(item) for item in tree.query_nearest(point, max_distance=limit_m, return_distance=False)]
            nearest = [item for item in nearest if keys[item]]
            if nearest:
                chosen = nearest[0]
                station_source[index] = "nearest line"
        if chosen is None:
            if name:
                name_only[index] = name
                continue
            any_line = tree.query_nearest(point, return_distance=False)
            near = int(any_line[0]) if len(any_line) else None
            deferred.append((index, near, float(geoms[near].distance(point)) if near is not None else math.inf))
            continue
        station_line[index] = (chosen, float(geoms[chosen].distance(point)))

    # 2. Build channels (connected same-name lines) and order their stations.
    component_of: dict[int, int] = {}
    components: list[list[int]] = []
    by_name: dict[str, list[int]] = {}
    for line_index, key in enumerate(keys):
        by_name.setdefault(key, []).append(line_index)

    def component_for(seed: int) -> int:
        if seed in component_of:
            return component_of[seed]
        key = keys[seed]
        same = set(by_name.get(key, [seed]))
        members, frontier = {seed}, [seed]
        while frontier:
            current = frontier.pop()
            ends = {nodes.start[current], nodes.end[current]}
            for other in same - members:
                if ends & {nodes.start[other], nodes.end[other]}:
                    members.add(other)
                    frontier.append(other)
        component_id = len(components)
        components.append(sorted(members))
        for member in members:
            component_of[member] = component_id
        return component_id

    # Stations whose name is not in the network follow other stations with the same
    # name that were placed on a line (e.g. one Hudiara row snapped, the rest named).
    votes: dict[str, dict[int, int]] = {}
    for station_index, (line_index, _) in station_line.items():
        label = str(points_m.at[station_index, "WaterBody"]).strip() or str(points_m.at[station_index, "ParsedName"]).strip()
        if label:
            tally = votes.setdefault(_base_name(label), {})
            tally[component_for(line_index)] = tally.get(component_for(line_index), 0) + 1
    for station_index, name in list(name_only.items()):
        tally = votes.get(_base_name(name))
        if not tally:
            continue
        component = max(tally, key=tally.get)
        point = points_m.geometry.iat[station_index]
        line_index = min(components[component], key=lambda member: geoms[member].distance(point))
        station_line[station_index] = (line_index, float(geoms[line_index].distance(point)))
        station_source[station_index] = "same name as other stations"
        del name_only[station_index]

    # A station a little beyond the limit still joins a drain/river that already carries
    # other stations of this file (e.g. a WRIS line drawn a few km off the real channel).
    placed_on: dict[int, list[int]] = {}
    for placed_index, (line_index, _) in station_line.items():
        placed_on.setdefault(component_for(line_index), []).append(placed_index)

    def next_to_placed(station_index: int, component: int) -> bool:
        point = points_m.geometry.iat[station_index]
        return any(points_m.geometry.iat[other].distance(point) <= EXTENDED_NEIGHBOUR_M for other in placed_on.get(component, []))

    for station_index, near, distance in deferred:
        if near is not None and distance <= EXTENDED_SNAP_M and next_to_placed(station_index, component_for(near)):
            station_line[station_index] = (near, distance)
            station_source[station_index] = "nearest line (beyond 2 km, next to other stations)"
            continue
        result["unassigned"].append({
            "location": points_m.at[station_index, "Location"],
            "nearest": names[near] if near is not None else None,
            "distanceM": round(distance, 1) if near is not None else None,
        })

    grouped: dict[int, list[int]] = {}
    for station_index, (line_index, _) in station_line.items():
        grouped.setdefault(component_for(line_index), []).append(station_index)
    # Names that are not in the network still group their stations (spelling variants merged).
    body_only: dict[str, list[int]] = {}
    for station_index, name in name_only.items():
        key = next((existing for existing in body_only if name_similarity(existing, name) >= 0.9), name)
        body_only.setdefault(key, []).append(station_index)

    graphs: dict[int, tuple[dict[int, list[tuple[int, float]]], list[int]]] = {}
    for component_id in grouped:
        adjacency: dict[int, list[tuple[int, float]]] = {}
        degree: dict[int, int] = {}
        for member in components[component_id]:
            a, b, length = nodes.start[member], nodes.end[member], geoms[member].length
            adjacency.setdefault(a, []).append((b, length))
            adjacency.setdefault(b, []).append((a, length))
            degree[a] = degree.get(a, 0) + 1
            degree[b] = degree.get(b, 0) + 1
        graphs[component_id] = (adjacency, [node for node, count in degree.items() if count == 1])
    # Terrain elevation of every channel end (one batched request).
    leaf_elevation: dict[int, float] = {}
    if use_elevation:
        # Only the ends that can decide direction: for branchy channels, the ends farthest from
        # the channel's centre (source and mouth are almost always among them).
        candidate_leaves = set()
        for _, leaves in graphs.values():
            if len(leaves) > MAX_ELEVATION_LEAVES:
                xs = [nodes.coords[leaf][0] for leaf in leaves]
                ys = [nodes.coords[leaf][1] for leaf in leaves]
                cx, cy = sum(xs) / len(xs), sum(ys) / len(ys)
                leaves = sorted(leaves, key=lambda leaf: -math.hypot(nodes.coords[leaf][0] - cx, nodes.coords[leaf][1] - cy))
                leaves = leaves[:MAX_ELEVATION_LEAVES]
            candidate_leaves.update(leaves)
        leaf_nodes = sorted(candidate_leaves)
        if leaf_nodes:
            wgs = gpd.GeoSeries(gpd.points_from_xy([nodes.coords[leaf][0] for leaf in leaf_nodes],
                                                   [nodes.coords[leaf][1] for leaf in leaf_nodes]), crs=metric).to_crs("EPSG:4326")
            lonlat = [(point.x, point.y) for point in wgs]
            found = fetch_point_elevations(lonlat)
            for leaf, (lon, lat) in zip(leaf_nodes, lonlat):
                value = found.get((round(lon, 5), round(lat, 5)))
                if value is not None:
                    leaf_elevation[leaf] = value
    result["elevationSource"] = "Open-Meteo elevation API (Copernicus DEM)" if leaf_elevation else None

    used_ids: set[str] = set()
    channel_geometries = []
    for component_id, station_indexes in grouped.items():
        members = components[component_id]
        member_set = set(members)
        adjacency, leaves = graphs[component_id]
        channel_key = keys[members[0]]
        end_nodes = {nodes.end[member] for member in members}
        start_nodes = {nodes.start[member] for member in members}
        # WRIS lines are mostly drawn source -> mouth, so a leaf that only ends lines is downstream.
        drawn_outlets = [leaf for leaf in leaves if leaf in end_nodes and leaf not in start_nodes]
        touching: dict[int, tuple[float, str | None]] = {}
        for leaf in leaves:
            leaf_point = shapely.Point(nodes.coords[leaf])
            for candidate in tree.query(leaf_point, predicate="dwithin", distance=CONFLUENCE_TOLERANCE_M):
                candidate = int(candidate)
                if candidate in member_set or keys[candidate] == channel_key:
                    continue
                distance = geoms[candidate].distance(leaf_point)
                if distance < touching.get(leaf, (math.inf, None))[0]:
                    touching[leaf] = (distance, names[candidate] or None)
        both = [leaf for leaf in drawn_outlets if leaf in touching]
        joins = None
        heights = {leaf: leaf_elevation[leaf] for leaf in leaves if leaf in leaf_elevation}
        if len(heights) >= 2 and max(heights.values()) - min(heights.values()) >= MIN_ELEVATION_DROP_M:
            # Water runs downhill: the outlet is the lowest end, preferring a confluence close to it.
            lowest = min(heights, key=heights.get)
            near_low = [leaf for leaf in touching if leaf in heights
                        and heights[leaf] <= heights[lowest] + CONFLUENCE_ELEVATION_SLACK_M]
            outlet = min(near_low, key=lambda leaf: touching[leaf][0]) if near_low else lowest
            joins = touching[outlet][1] if outlet in touching else None
            outlet_method = "confluence" if outlet in touching else "lowest end (terrain elevation)"
        elif both:
            outlet = min(both, key=lambda leaf: touching[leaf][0])
            outlet_method, joins = "confluence", touching[outlet][1]
        elif len(touching) == 1:
            outlet = next(iter(touching))
            outlet_method, joins = "confluence", touching[outlet][1]
        elif drawn_outlets:
            outlet = drawn_outlets[0]
            outlet_method = "direction the line is drawn (no confluence in the loaded area)"
        elif touching:
            outlet = min(touching, key=lambda leaf: touching[leaf][0])
            outlet_method, joins = "confluence", touching[outlet][1]
        else:
            longest = max(members, key=lambda member: geoms[member].length)
            outlet = nodes.end[longest]
            outlet_method = "direction the line is drawn (no confluence in the loaded area)"
        to_outlet = _dijkstra(adjacency, outlet)
        ordered = []
        for station_index in station_indexes:
            line_index, snap_distance = station_line[station_index]
            geometry = geoms[line_index]
            along = geometry.project(points_m.geometry.iat[station_index])
            distance = min(along + to_outlet.get(nodes.start[line_index], math.inf),
                           geometry.length - along + to_outlet.get(nodes.end[line_index], math.inf))
            if snap_distance > NAME_MATCH_RADIUS_M:
                distance = math.inf  # same name, but coordinates too far from the line to place it
            ordered.append({
                "location": points_m.at[station_index, "Location"],
                "distanceToOutletKm": round(distance / 1000.0, 3) if math.isfinite(distance) else None,
                "snapDistanceM": round(snap_distance, 1),
                "assignedBy": station_source.get(station_index, "nearest line"),
            })
        ordered.sort(key=lambda item: (-(item["distanceToOutletKm"] if item["distanceToOutletKm"] is not None else -1), item["location"]))
        _apply_label_hints(ordered)
        for order, item in enumerate(ordered, 1):
            item["order"] = order
        name = names[members[0]] or "Unnamed channel"
        map_name = network_names[members[0]] or name
        file_names = {str(points_m.at[index, "WaterBody"]).strip() for index in station_indexes} - {""}
        display = next(iter(file_names)) if len(file_names) == 1 else name
        label_counts: dict[str, int] = {}
        for index in station_indexes:
            label = str(points_m.at[index, "ParsedName"]).strip()
            if label:
                label_counts[label] = label_counts.get(label, 0) + 1
        if not file_names and label_counts:
            # Prefer the local name from the station labels: when most stations carry it, or when
            # no label uses the WRIS name at all (e.g. WRIS "Tangori Choe" is locally the N-choe).
            top = max(sorted(label_counts), key=label_counts.get)
            wris_used = any(name_similarity(label, name) >= NAME_MATCH_THRESHOLD for label in label_counts)
            if name_similarity(top, name) < NAME_MATCH_THRESHOLD and (
                    label_counts[top] * 2 >= len(station_indexes) or not wris_used):
                display = top
        aliases = [alias for alias in sorted(label_counts) if name_similarity(alias, display) < NAME_MATCH_THRESHOLD
                   and name_similarity(alias, name) < NAME_MATCH_THRESHOLD]
        channel_id = _slug(display)
        while channel_id in used_ids:
            channel_id += "-2"
        used_ids.add(channel_id)
        channel_geometries.append(shapely.union_all(geoms[members]))
        result["channels"].append({
            "id": channel_id,
            "name": display,
            "networkName": map_name,
            "kind": kinds[members[0]],
            "lengthKm": round(sum(geoms[member].length for member in members) / 1000.0, 2),
            "outletMethod": outlet_method,
            "ordered": True,
            "joins": joins,
            "outletElevationM": round(heights[outlet], 1) if outlet in heights else None,
            "highestEndElevationM": round(max(heights.values()), 1) if heights else None,
            "aliases": aliases,
            "stations": ordered,
            "geometry": None,  # filled in one batch below
        })
    # Simplify and reproject all channel lines in one vectorised step. Small study
    # areas keep 20 m detail; country-wide files use a coarser tolerance so the
    # browser is not asked to draw millions of vertices.
    if channel_geometries:
        series = gpd.GeoSeries(channel_geometries, crs=metric)
        total_km = float(series.length.sum()) / 1000.0
        tolerance = 20.0 if total_km <= 1000 else min(150.0, 20.0 * (total_km / 1000.0) ** 0.5)
        simplified = series.simplify(tolerance).to_crs("EPSG:4326")
        for channel, geometry in zip(result["channels"], simplified):
            channel["geometry"] = _rounded_geojson(geometry)
    for body, station_indexes in body_only.items():
        channel_id = _slug(body)
        while channel_id in used_ids:
            channel_id += "-2"
        used_ids.add(channel_id)
        result["channels"].append({
            "id": channel_id, "name": body, "networkName": None, "kind": "", "lengthKm": None,
            "outletMethod": "not in network (file order)", "ordered": False, "joins": None, "geometry": None, "aliases": [],
            "outletElevationM": None, "highestEndElevationM": None,
            "stations": [{"location": points_m.at[index, "Location"], "distanceToOutletKm": None,
                          "snapDistanceM": None,
                          "assignedBy": "file column" if str(points_m.at[index, "WaterBody"]).strip() else "name in station label",
                          "order": order}
                         for order, index in enumerate(station_indexes, 1)],
        })
    result["channels"].sort(key=lambda channel: (-len(channel["stations"]), channel["name"].casefold()))
    result["unassigned"].sort(key=lambda item: item["location"])
    _attach_downstream_references(result)
    return result


DOWNSTREAM_OF = re.compile(r"\b(?:D\s*/\s*S|DOWN\s*STREAM|DOWNSTREAM)\b\.?\s*(?:OF\s+)?(?:THE\s+)?(.+)$", re.IGNORECASE)


AT_CONFLUENCE = re.compile(r"\b(?:BEFORE|AT|NEAR|U\s*/\s*S\s+OF)\s+(?:THE\s+)?(?:CONFLUENCE|CONF)\b", re.IGNORECASE)


def _attach_downstream_references(result: dict[str, Any]) -> None:
    """Show a receiving-river station labelled "D/S of <drain>" at the end of that drain.

    Such a station sits on the bigger river just after the drain joins it, so it
    shows what the drain does to the river. It keeps its own river assignment and
    is only added (as ``downstream``) to the single-drain view of that drain.
    """
    aliases = load_aliases()
    # A station far from the mapped line but labelled "before confluence" is at the outlet.
    for channel in result["channels"]:
        if channel.get("outletMethod") != "confluence":
            continue
        for station in channel["stations"]:
            if station.get("distanceToOutletKm") is None and AT_CONFLUENCE.search(str(station["location"])):
                station["distanceToOutletKm"] = 0.0
                station["positionFrom"] = "station label (at the confluence)"
    candidates = [(channel["id"], station["location"]) for channel in result["channels"] for station in channel["stations"]]
    candidates += [(None, item["location"]) for item in result.get("unassigned", [])]
    for channel in result["channels"]:
        names = {channel["name"], *(channel.get("aliases") or [])}
        if channel.get("networkName"):
            names.add(channel["networkName"])
        own = {station["location"] for station in channel["stations"]}
        references = []
        for owner, location in candidates:
            if owner == channel["id"] or location in own:
                continue
            match = DOWNSTREAM_OF.search(str(location))
            if not match:
                continue
            target = parse_water_body(match.group(1)) or match.group(1).strip()
            target = canonical_name(target, aliases)
            if any(name_similarity(target, name) >= 0.85 for name in names):
                references.append({"location": location, "channel": owner,
                                   "note": "on the receiving river, downstream of this drain"})
        channel["downstream"] = references


_UPSTREAM_LABEL = re.compile(r"\b(?:U/?S|UPSTREAM)\b", re.IGNORECASE)
_DOWNSTREAM_LABEL = re.compile(r"\b(?:D/?S|DOWNSTREAM)\b", re.IGNORECASE)


def _apply_label_hints(ordered: list[dict[str, Any]], window_km: float = 2.0) -> None:
    """Within a couple of km, a station labelled U/S goes before one labelled D/S."""
    changed = True
    while changed:
        changed = False
        for index in range(len(ordered) - 1):
            first, second = ordered[index], ordered[index + 1]
            a, b = first["distanceToOutletKm"], second["distanceToOutletKm"]
            if a is None or b is None or abs(a - b) > window_km:
                continue
            if _DOWNSTREAM_LABEL.search(first["location"]) and _UPSTREAM_LABEL.search(second["location"]) \
                    and not _UPSTREAM_LABEL.search(first["location"]):
                ordered[index], ordered[index + 1] = second, first
                changed = True


def channel_table(network_result: dict[str, Any]) -> pd.DataFrame:
    """Flatten ``build_channel_network`` output into one row per station."""
    rows = []
    for channel in network_result["channels"]:
        for station in channel["stations"]:
            rows.append({"Channel": channel["name"], "NetworkName": channel["networkName"],
                         "Order": station["order"], "Location": station["location"],
                         "DistanceToOutletKm": station["distanceToOutletKm"],
                         "SnapDistanceM": station["snapDistanceM"], "AssignedBy": station["assignedBy"]})
    for station in network_result["unassigned"]:
        rows.append({"Channel": None, "NetworkName": station["nearest"], "Order": None,
                     "Location": station["location"], "DistanceToOutletKm": None,
                     "SnapDistanceM": station["distanceM"], "AssignedBy": "unassigned"})
    return pd.DataFrame(rows, columns=["Channel", "NetworkName", "Order", "Location",
                                       "DistanceToOutletKm", "SnapDistanceM", "AssignedBy"])
