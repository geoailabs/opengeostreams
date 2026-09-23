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
NODE_TOLERANCE_M = 30.0      # endpoints closer than this are the same network node
CONFLUENCE_TOLERANCE_M = 250.0  # a channel end this close to another line is a confluence
NAME_MATCH_RADIUS_M = 15000.0   # search radius for lines matching a station's water-body name
NAME_MATCH_THRESHOLD = 0.8
ELEVATION_URL = "https://api.open-meteo.com/v1/elevation"
OFFLINE_ENV = "OPENGEOSTREAMS_OFFLINE"
MIN_ELEVATION_DROP_M = 5.0      # smaller differences between channel ends are treated as flat
CONFLUENCE_ELEVATION_SLACK_M = 3.0
_ELEVATION_CACHE: dict[tuple[float, float], float | None] = {}


def fetch_point_elevations(points: list[tuple[float, float]], timeout: float = 10.0) -> dict[tuple[float, float], float]:
    """Terrain elevation (m) for (lon, lat) points from Open-Meteo; {} when offline."""
    if os.environ.get(OFFLINE_ENV):
        return {}
    keys = [(round(lon, 5), round(lat, 5)) for lon, lat in points]
    missing = [key for key in dict.fromkeys(keys) if key not in _ELEVATION_CACHE]
    try:
        try:
            import certifi
            context = ssl.create_default_context(cafile=certifi.where())
        except ImportError:
            context = ssl.create_default_context()
        for start in range(0, len(missing), 100):
            batch = missing[start:start + 100]
            query = urllib.parse.urlencode({"latitude": ",".join(str(lat) for _, lat in batch),
                                            "longitude": ",".join(str(lon) for lon, _ in batch)})
            request = urllib.request.Request(f"{ELEVATION_URL}?{query}", headers={"User-Agent": "OpenGeoStreams/2.0"})
            with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
                values = json.loads(response.read().decode("utf-8")).get("elevation", [])
            for key, value in zip(batch, values):
                _ELEVATION_CACHE[key] = float(value) if isinstance(value, (int, float)) and math.isfinite(value) else None
    except Exception:  # network or service unavailable: fall back to topology
        return {key: _ELEVATION_CACHE[key] for key in keys if _ELEVATION_CACHE.get(key) is not None}
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


def load_network(bounds: tuple[float, float, float, float], path: str | Path | None = None,
                 buffer_deg: float = 0.25):
    """Read network lines intersecting ``bounds`` (min lon, min lat, max lon, max lat)."""
    gpd, _ = _geo()
    source = find_network_path(path)
    minx, miny, maxx, maxy = bounds
    box = (minx - buffer_deg, miny - buffer_deg, maxx + buffer_deg, maxy + buffer_deg)
    if source.suffix.lower() == ".parquet":
        import pyarrow.dataset as ds
        dataset = ds.dataset(str(source))
        names = set(dataset.schema.names)
        if {"xmin", "ymin", "xmax", "ymax"} <= names:
            field = ds.field
            table = dataset.to_table(filter=(field("xmax") >= box[0]) & (field("xmin") <= box[2])
                                     & (field("ymax") >= box[1]) & (field("ymin") <= box[3]))
            frame = table.to_pandas()
            lines = gpd.GeoDataFrame(frame.drop(columns="geometry"),
                                     geometry=gpd.GeoSeries.from_wkb(frame["geometry"]), crs="EPSG:4326")
        else:
            lines = gpd.read_parquet(source).to_crs("EPSG:4326").cx[box[0]:box[2], box[1]:box[3]]
    else:
        lines = gpd.read_file(source, bbox=box).to_crs("EPSG:4326")
    name_column = next((column for column in ("rivname", "channel", "name", "NAME", "river", "Name") if column in lines), None)
    kind_column = next((column for column in ("layer", "kind") if column in lines), None)
    result = gpd.GeoDataFrame({
        "name": lines[name_column].fillna("").astype(str).str.strip() if name_column else "",
        "kind": lines[kind_column].fillna("").astype(str) if kind_column else "",
    }, geometry=lines.geometry.values, crs="EPSG:4326")
    result = result[result.geometry.notna() & ~result.geometry.is_empty]
    result = result.explode(index_parts=False).reset_index(drop=True)
    result = result[result.geom_type == "LineString"].reset_index(drop=True)
    result.attrs["source"] = source.name
    return result


def station_table(frame: pd.DataFrame) -> pd.DataFrame:
    """One row per station (dashboard location name) with a representative coordinate."""
    data = frame.copy()
    data["Location"] = data["Location"].map(pipeline.location_group)
    data["Latitude"] = pd.to_numeric(data["Latitude"], errors="coerce")
    data["Longitude"] = pd.to_numeric(data["Longitude"], errors="coerce")
    water_column = next((column for column in WATER_BODY_KEYS if column in data), None)
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
            "Latitude": float(valid["Latitude"].median()) if len(valid) else math.nan,
            "Longitude": float(valid["Longitude"].median()) if len(valid) else math.nan,
            "WaterBody": body,
            "ParsedName": parse_water_body(location),
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
    kinds = lines["kind"].tolist()
    geoms = lines.geometry.values
    nodes = _Nodes(lines)
    tree = shapely.STRtree(geoms)
    limit_m = float(max_distance_km) * 1000.0

    # 1. Which line does each station sit on?
    station_line: dict[int, tuple[int, float]] = {}
    station_source: dict[int, str] = {}
    name_only: dict[int, str] = {}
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
            result["unassigned"].append({
                "location": row["Location"],
                "nearest": names[near] if near is not None else None,
                "distanceM": round(float(geoms[near].distance(point)), 1) if near is not None else None,
            })
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
        leaf_nodes = sorted({leaf for _, leaves in graphs.values() for leaf in leaves})
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
        file_names = {str(points_m.at[index, "WaterBody"]).strip() for index in station_indexes} - {""}
        display = next(iter(file_names)) if len(file_names) == 1 else name
        label_counts: dict[str, int] = {}
        for index in station_indexes:
            label = str(points_m.at[index, "ParsedName"]).strip()
            if label:
                label_counts[label] = label_counts.get(label, 0) + 1
        if not file_names and label_counts:
            # Use the local name when most stations on this channel carry it (e.g. WRIS "Para" = "Sagarpara Drain").
            top = max(label_counts, key=label_counts.get)
            if label_counts[top] * 2 >= len(station_indexes) and name_similarity(top, name) < NAME_MATCH_THRESHOLD:
                display = top
        aliases = [alias for alias in sorted(label_counts) if name_similarity(alias, display) < NAME_MATCH_THRESHOLD
                   and name_similarity(alias, name) < NAME_MATCH_THRESHOLD]
        channel_id = _slug(display)
        while channel_id in used_ids:
            channel_id += "-2"
        used_ids.add(channel_id)
        geometry = gpd.GeoSeries(lines.geometry.iloc[members].values, crs=metric).union_all()
        geometry_wgs = gpd.GeoSeries([geometry], crs=metric).to_crs("EPSG:4326").simplify(0.0002).iloc[0]
        result["channels"].append({
            "id": channel_id,
            "name": display,
            "networkName": name,
            "kind": kinds[members[0]],
            "lengthKm": round(sum(geoms[member].length for member in members) / 1000.0, 2),
            "outletMethod": outlet_method,
            "ordered": True,
            "joins": joins,
            "outletElevationM": round(heights[outlet], 1) if outlet in heights else None,
            "highestEndElevationM": round(max(heights.values()), 1) if heights else None,
            "aliases": aliases,
            "stations": ordered,
            "geometry": geometry_wgs.__geo_interface__,
        })
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
    return result


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
