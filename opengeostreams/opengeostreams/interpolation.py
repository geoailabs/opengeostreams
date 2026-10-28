"""Along-river interpolation of water-quality measurements, for any drain/river network.

River data is modelled along the channels and in the direction of flow, not in
straight lines (Ver Hoef, Peterson & Theobald 2006; Ver Hoef & Peterson 2010;
Peterson & Ver Hoef 2010). The library picks the method from what the data has:

1. Tidy the data: one interval per station for every parameter and period. An ordinary
   reading is a single value; a Min/Max report ("BOD (Min)", "BOD (Max)") is a range.
   Each station-year uses its ordinary readings when it has any, else its Min and Max,
   and the all-years bounds are the means of the yearly bounds, so every year counts
   equally. Everything below runs twice: a lower run (Min where reported) and an upper
   run (Max where reported), so every map is an interval. A station with only a Max
   counts in the upper run only (only a Min: lower run only).
2. Find a river map: the user's own file, then India-WRIS, then a worldwide
   HydroRIVERS file in ``data/hydrorivers/`` (see ``network.network_sources``). If
   none has a line near the stations, straight-line IDW is used and every surface
   says so.
3. Pin stations to the rivers and give every channel a flow direction. Natural
   channels drain to their outlet (the lowest channel end by terrain elevation, else
   the direction most lines are drawn in). Canals, ditches and drains marked as such
   keep the direction they are drawn in (OpenStreetMap and WRIS lines are drawn
   downstream), and any canal that would make water flow in a circle is dropped, so
   water flows one way only. Splits and rejoins are kept.
4. Junctions: where channels meet, each branch's share of the water comes from its
   upstream catchment area when the network file has one, otherwise both sides count
   equally (``junction_weights="order"`` uses stream order instead). Where a channel
   splits, the water is shared by design/mean discharge when known, else canal rank
   (river > main canal > branch > distributary > minor), else equally.
5. Fill in the river (along-river IDW): a river point averages the stations upstream
   and downstream of it within ``max_distance_km`` along the flow path. Each weighs
   ``share of water that passed between them / distance ** power``. A station on a
   separate drain, or below a canal off-take, shares no water and never counts.
   With ``max_distance_km="auto"`` (the default) the limit is chosen by the data:
   2, 4, 8, 16 and 32 km and no limit are each checked by leave-one-out, and the one
   with the smallest error is kept (see ``choose_distance``).
6. Check itself: every station is hidden in turn and predicted from the others
   (leave-one-out); the average miss is reported with the map.
7. Optional extra (``advanced=True``): with at least ``MIN_KRIGING_STATIONS`` stations
   on a tree-shaped network (no splits), tail-up, tail-down and mixed stream-network
   kriging (exponential models) are fitted by leave-one-out error, and whichever
   method has the smaller error is kept.
8. Show the map: lower and upper estimates along the channels with a 0-100 confidence
   per cell (the dashboard fades low confidence), the method, and the leave-one-out error
   of each run. ``grid["values"]`` and the surface's top-level method and validation
   repeat the upper run; ``surface["runs"]`` has both.

This is a statistical estimate along mapped channels, not a hydraulic model.
"""

from __future__ import annotations

import heapq
import math
import re
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any

import numpy as np

from . import network, pipeline

GRID_COLUMNS = 192
GRID_ROWS = 192
DEFAULT_MAX_DISTANCE_KM = "auto"
DISTANCE_CANDIDATES_KM = (2.0, 4.0, 8.0, 16.0, 32.0, None)   # None: no limit
FALLBACK_DISTANCE_KM = 8.0    # used when there are too few stations to compare limits
AUTO_BUFFER_KM = 32.0         # network kept around the stations while choosing the limit
MIN_STATIONS_TO_CHOOSE = 3    # a surface needs this many stations to vote on the limit
DEFAULT_POWER = 2.0
JUNCTION_WEIGHTS = ("auto", "area", "equal", "order")
MIN_KRIGING_STATIONS = 50     # fitted models are unstable with fewer stations
JOIN_TOLERANCE_M = 100.0      # a line end this close to the middle of another line joins it there
SAMPLE_SPACING_M = 100.0      # estimates are made every 100 m along the channels
MIN_HALF_WIDTH_M = 200.0      # half-width of the river ribbon drawn on the map grid
LABEL_JUNCTION_M = 500.0      # a "D/S of X" station this close above the X junction is moved below it
MAX_OUTLET_CANDIDATES = 40
OUTLET_ELEVATION_SLACK_M = 3.0
CANAL_KINDS = {"canal", "ditch", "drain", "irrigation", "aqueduct"}
CANAL_WORDS = re.compile(r"\b(?:CANAL|NAHAR|NEHAR|BRANCH|DISTRIBUTARY|DISTY|FEEDER|MINOR)\b", re.IGNORECASE)
# Relative share of water taken at a split when no discharge is known (each rank halves it).
CANAL_RANKS = ((re.compile(r"\bMINOR\b", re.I), 1.0), (re.compile(r"\b(?:DISTRIBUTARY|DISTY)\b", re.I), 2.0),
               (re.compile(r"\bBRANCH\b", re.I), 4.0))
MAIN_CANAL_RANK, RIVER_RANK = 8.0, 16.0
KRIGING_RANGE_FACTORS = (0.5, 1.0, 2.0, 4.0)
KRIGING_NUGGET_RATIOS = (0.1, 0.3, 0.6)
MIXED_SHARES = ((0.5, 0.5, 0.0), (0.5, 0.0, 0.5), (0.0, 0.5, 0.5), (1 / 3, 1 / 3, 1 / 3),
                (0.6, 0.2, 0.2), (0.2, 0.6, 0.2), (0.2, 0.2, 0.6))   # tail-up, tail-down, straight-line
DOWNSTREAM, UPSTREAM, UNCONNECTED = 1, 2, 3   # where a position lies relative to a station
BOUNDS = ("lower", "upper")                   # the two runs that make each map an interval
VARIANT = re.compile(r"\(\s*(max|min)\s*\)\s*$", re.IGNORECASE)
METHOD_LABELS = {
    "river_idw": "Along-river IDW",
    "tail_up": "Stream-network kriging (tail-up)",
    "tail_down": "Stream-network kriging (tail-down)",
    "mixed": "Stream-network kriging (mixed tail-up, tail-down and straight-line)",
    "straight_idw": "Straight-line IDW",
    "single": "Single-station value (no spatial interpolation)",
}
NO_NETWORK_WARNING = ("No drain/river map was found near these stations, so distances are straight lines "
                      "across land and stations on different channels influence each other.")
OFF_NETWORK_WARNING = ("None of these stations lie on the river map, so distances are straight lines "
                       "across land.")
CANAL_WARNING = ("Canals run in rotation and can be dry; a canal sample reflects its source river only while "
                 "the canal runs, so compare it with river samples from the same month or season.")


# ----------------------------------------------------------------------------
# 1. One value per station
# ----------------------------------------------------------------------------

def _mean(values):
    return sum(values) / len(values) if values else None


def station_values(records: list[dict[str, Any]], positions: dict[str, tuple[float, float]] | None = None,
                   *, yearly: bool) -> dict[tuple[str, str], tuple[list[dict[str, Any]], str]]:
    """Group numeric records into one interval per station for each (period, parameter family).

    An ordinary reading gives a single value (lower = upper); "X (Min)" / "X (Max)"
    readings give a range for parameter X. Each station-year uses its ordinary readings
    when it has any, otherwise that year's Min and Max. The all-years bounds are the
    means of the yearly bounds, so every year counts equally. ``kind`` is "reading",
    "range", "max only" or "min only". ``positions`` gives each station's map position;
    otherwise its first record's coordinates are used.
    """
    positions = positions or {}
    samples: dict = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: {"reading": [], "min": [], "max": []})))
    units: dict[tuple[str, str], str] = {}
    coordinates: dict[str, tuple[float, float]] = {}
    for record in records:
        value = record.get("numericValue")
        if value is None or not math.isfinite(value) or not record.get("parameter") or not record.get("hasCoordinates"):
            continue
        station = record["locationGroup"]
        variant = VARIANT.search(record["parameter"])
        key = (str(record["year"]) if yearly else "all_years", pipeline.parameter_family(record["parameter"]))
        samples[key][station][int(record["year"])]["reading" if not variant else variant.group(1).lower()].append(float(value))
        units.setdefault(key, pipeline.clean(record.get("unit")))
        coordinates.setdefault(station, (record["latitude"], record["longitude"]))
    result = {}
    for key, stations in samples.items():
        points = []
        for station, years in sorted(stations.items()):
            latitude, longitude = positions.get(station) or coordinates[station]
            if not (math.isfinite(latitude) and math.isfinite(longitude)):
                latitude, longitude = coordinates[station]
            lows, highs, range_years = [], [], 0
            for slots in years.values():
                if slots["reading"]:
                    reading = _mean(slots["reading"])
                    lows.append(reading)
                    highs.append(reading)
                    continue
                range_years += 1
                if slots["min"]:
                    lows.append(_mean(slots["min"]))
                if slots["max"]:
                    highs.append(_mean(slots["max"]))
            lower, upper = _mean(lows), _mean(highs)
            if lower is not None and upper is not None and lower > upper:
                lower, upper = upper, lower
            kind = ("reading" if not range_years else "range" if lower is not None and upper is not None
                    else "max only" if lower is None else "min only")
            points.append({"location": station, "latitude": float(latitude), "longitude": float(longitude),
                           "lower": lower, "upper": upper,
                           "value": (lower + upper) / 2 if lower is not None and upper is not None
                           else (upper if lower is None else lower),
                           "kind": kind, "sampleCount": sum(len(v) for slots in years.values() for v in slots.values()),
                           "yearCount": len(years)})
        result[key] = (points, units[key])
    return result


# ----------------------------------------------------------------------------
# 2-4. Directed river network
# ----------------------------------------------------------------------------

class RiverGraph:
    """Drain/river/canal lines as a directed acyclic network in a metric CRS.

    A position is ``(edge, t)``: ``t`` metres upstream of the edge's downstream node.
    ``share[e]`` is the fraction of the water at ``down[e]`` that arrives through ``e``.
    """

    def __init__(self) -> None:
        self.crs = None
        self.geometry: list[Any] = []
        self.length = np.zeros(0)
        self.down: list[int] = []
        self.up: list[int] = []
        self.down_at_start: list[bool] = []
        self.names: list[str] = []
        self.canal: list[bool] = []
        self.share = np.zeros(0)
        self.incoming: dict[int, list[int]] = defaultdict(list)
        self.outgoing: dict[int, list[int]] = defaultdict(list)
        self.order: dict[int, int] = {}      # topological position of every node (upstream first)
        self.tree = True                     # no node sends water down more than one channel
        self.stations: dict[str, tuple[int, float]] = {}
        self.info: dict[str, Any] = {}

    def _connected(self, edge: int, t: float, limit: float):
        """Flow-connected positions as ``(edge, lo, hi, base, sign, relation, share)`` records.

        On ``edge`` between ``lo`` and ``hi`` the distance along the flow path is
        ``base + sign * t``. ``share`` is the fraction of the downstream position's
        water that passed the upstream one (summed over all flow paths).
        """
        length = float(self.length[edge])
        records = [(edge, 0.0, t, t, -1.0, DOWNSTREAM, 1.0), (edge, t, length, -t, 1.0, UPSTREAM, 1.0)]
        # Downstream: water leaving the station mixes in at junctions and splits at off-takes.
        distance = {self.down[edge]: t}
        frontier = [self.down[edge]]
        while frontier:
            node = frontier.pop()
            for following in self.outgoing.get(node, ()):
                step = distance[node] + float(self.length[following])
                target = self.down[following]
                if distance[node] <= limit and step < distance.get(target, math.inf):
                    distance[target] = step
                    frontier.append(target)
        node_share = {self.down[edge]: float(self.share[edge])}
        for node in sorted(distance, key=self.order.get):
            if node != self.down[edge]:
                node_share[node] = sum(self.share[item] * node_share[self.up[item]] for item in self.incoming.get(node, ())
                                       if self.up[item] in node_share and self.up[item] in distance)
            if distance[node] > limit:
                continue
            for following in self.outgoing.get(node, ()):
                step = float(self.length[following])
                records.append((following, 0.0, step, distance[node] + step, -1.0, DOWNSTREAM, node_share[node]))
        # Upstream: the share of the station's water that came through each channel above it.
        distance = {self.up[edge]: length - t}
        frontier = [self.up[edge]]
        while frontier:
            node = frontier.pop()
            for previous in self.incoming.get(node, ()):
                step = distance[node] + float(self.length[previous])
                source = self.up[previous]
                if distance[node] <= limit and step < distance.get(source, math.inf):
                    distance[source] = step
                    frontier.append(source)
        node_share = {self.up[edge]: 1.0}
        edge_share: dict[int, float] = {}
        for node in sorted(distance, key=self.order.get, reverse=True):
            if node != self.up[edge]:
                node_share[node] = sum(edge_share.get(item, 0.0) for item in self.outgoing.get(node, ()))
            if distance[node] > limit:
                continue
            for previous in self.incoming.get(node, ()):
                edge_share[previous] = float(self.share[previous]) * node_share[node]
                records.append((previous, 0.0, float(self.length[previous]), distance[node], 1.0, UPSTREAM,
                                edge_share[previous]))
        return records

    def _unconnected(self, edge: int, t: float, limit: float):
        """Positions sharing only a downstream junction with the start (tree-shaped networks only)."""
        records = []
        pending = []
        node, distance, came = self.down[edge], t, edge
        while distance <= limit:
            pending.append((node, distance, came))
            following = self.outgoing.get(node)
            if not following:
                break
            following = following[0]
            node, distance, came = self.down[following], distance + float(self.length[following]), following
        while pending:
            node, distance, exclude = pending.pop()
            for other in self.incoming.get(node, ()):
                if other == exclude:
                    continue
                step = float(self.length[other])
                records.append((other, 0.0, step, distance, 1.0, UNCONNECTED, 0.0))
                if distance + step <= limit:
                    pending.append((self.up[other], distance + step, None))
        return records

    def records(self, edge: int, t: float, limit: float):
        found = self._connected(edge, t, limit)
        if self.tree:
            found += self._unconnected(edge, t, limit)
        return found

    def samples(self, positions: list[tuple[int, float]], limit: float,
                spacing: float = SAMPLE_SPACING_M) -> tuple[np.ndarray, np.ndarray]:
        """Estimate positions every ``spacing`` metres on channels within ``limit`` of a station."""
        reached = set()
        for edge, t in positions:
            for item, low, high, base, sign, _, _ in self.records(edge, t, limit):
                if base + min(sign * low, sign * high) <= limit:
                    reached.add(item)
        edges, offsets = [], []
        for edge in sorted(reached):
            length = float(self.length[edge])
            count = max(1, int(math.ceil(length / spacing)))
            offsets.append(np.linspace(0.0, length, count + 1))
            edges.append(np.full(count + 1, edge, dtype=int))
        if not edges:
            return np.zeros(0, dtype=int), np.zeros(0)
        return np.concatenate(edges), np.concatenate(offsets)

    def relations(self, positions: list[tuple[int, float]], target_edge: np.ndarray, target_t: np.ndarray,
                  limit: float = math.inf) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Distance (m), relation and water share between every target and station.

        Arrays have shape (targets, stations); unreachable pairs have distance inf and
        relation 0. ``share`` is the fraction of the lower position's water that passed
        the upper one; it is 0 for unconnected pairs.
        """
        count = len(target_edge)
        distance = np.full((count, len(positions)), np.inf, dtype=np.float32)
        relation = np.zeros((count, len(positions)), dtype=np.int8)
        share = np.zeros((count, len(positions)), dtype=np.float32)
        by_edge: dict[int, np.ndarray] = {}
        if count:
            order = np.argsort(target_edge, kind="stable")
            edges, starts = np.unique(target_edge[order], return_index=True)
            for edge, part in zip(edges.tolist(), np.split(order, starts[1:])):
                by_edge[edge] = part
        for column, (start_edge, start_t) in enumerate(positions):
            for edge, low, high, base, sign, kind, water in self.records(start_edge, start_t, limit):
                rows = by_edge.get(edge)
                if rows is None:
                    continue
                offsets = target_t[rows]
                inside = (offsets >= low - 1e-6) & (offsets <= high + 1e-6)
                rows, offsets = rows[inside], offsets[inside]
                values = base + sign * offsets
                better = (values <= limit) & (values < distance[rows, column])
                rows, values = rows[better], values[better]
                if len(rows):
                    distance[rows, column] = values
                    relation[rows, column] = kind
                    share[rows, column] = water
        return distance, relation, share

    def coordinates(self, target_edge: np.ndarray, target_t: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Latitude and longitude of positions."""
        import shapely
        from pyproj import Transformer
        if not len(target_edge):
            return np.zeros(0), np.zeros(0)
        lines = np.asarray(self.geometry, dtype=object)[target_edge]
        along = np.where(np.asarray(self.down_at_start)[target_edge], target_t, self.length[target_edge] - target_t)
        points = shapely.line_interpolate_point(lines, along)
        longitude, latitude = Transformer.from_crs(self.crs, "EPSG:4326", always_xy=True).transform(
            shapely.get_x(points), shapely.get_y(points))
        return np.asarray(latitude, dtype=float), np.asarray(longitude, dtype=float)


class _UnionFind:
    def __init__(self, size: int) -> None:
        self.parent = list(range(size))

    def find(self, item: int) -> int:
        while self.parent[item] != item:
            self.parent[item] = self.parent[self.parent[item]]
            item = self.parent[item]
        return item

    def union(self, left: int, right: int) -> None:
        left, right = self.find(left), self.find(right)
        if left != right:
            self.parent[left] = right


def _shortest(adjacency: dict[int, list[tuple[int, int, float]]], source: int):
    """Dijkstra from ``source``: (distance per node, {node: (edge, next node towards source)})."""
    distances = {source: 0.0}
    via: dict[int, tuple[int, int]] = {}
    queue = [(0.0, source)]
    while queue:
        distance, node = heapq.heappop(queue)
        if distance > distances.get(node, math.inf):
            continue
        for neighbour, edge, cost in adjacency.get(node, ()):
            candidate = distance + cost
            if candidate < distances.get(neighbour, math.inf):
                distances[neighbour] = candidate
                via[neighbour] = (edge, node)
                heapq.heappush(queue, (candidate, neighbour))
    return distances, via


def _is_canal(name: str, map_name: str, kind: str) -> bool:
    return kind.strip().casefold() in CANAL_KINDS or bool(CANAL_WORDS.search(name) or CANAL_WORDS.search(map_name))


def _rank(name: str, canal: bool) -> float:
    if not canal:
        return RIVER_RANK
    for pattern, rank in CANAL_RANKS:
        if pattern.search(name):
            return rank
    return MAIN_CANAL_RANK


def station_key(location: Any) -> str:
    """Station name as the dashboard records use it."""
    return pipeline.location_group(pipeline.display_name(location))


def _label_hint(graph: RiverGraph, location: str) -> str | None:
    """Move a station labelled "D/S of <channel>" just below that junction when it is close.

    Coordinates a few metres off can put such a station just above the junction, on
    the wrong side of it. Returns a note when the position was changed.
    """
    match = network.DOWNSTREAM_OF.search(location)
    if not match:
        return None
    target = network.canonical_name(network.parse_water_body(match.group(1)) or match.group(1).strip(),
                                    network.load_aliases())
    edge, t = graph.stations[location]
    node, distance, came = graph.down[edge], t, edge
    while distance <= LABEL_JUNCTION_M:
        joining = [item for item in graph.incoming.get(node, ()) if item != came
                   and network.name_similarity(target, graph.names[item]) >= 0.85]
        below = sorted(graph.outgoing.get(node, ()), key=lambda item: graph.canal[item])
        if joining and below:
            graph.stations[location] = (below[0], max(float(graph.length[below[0]]) - 1.0, 0.0))
            return f"station label: placed just below the {graph.names[joining[0]]} junction"
        if not below:
            return None
        distance += float(graph.length[below[0]])
        node, came = graph.down[below[0]], below[0]
    return None


def _topological(nodes, edges_out, down):
    """Kahn order of ``nodes``; returns (order, nodes left in a cycle)."""
    indegree = Counter()
    for node in nodes:
        for edge in edges_out.get(node, ()):
            indegree[down[edge]] += 1
    ready = sorted(node for node in nodes if indegree[node] == 0)
    order = []
    while ready:
        node = ready.pop()
        order.append(node)
        for edge in edges_out.get(node, ()):
            indegree[down[edge]] -= 1
            if indegree[down[edge]] == 0:
                ready.append(down[edge])
    return order, set(nodes) - set(order)


def build_river_graph(frame, network_result: dict[str, Any] | None = None, *, lines=None,
                      network_path=None, buffer_km: float = AUTO_BUFFER_KM,
                      junction_weights: str = "auto", use_elevation: bool = True) -> RiverGraph:
    """Build the directed drain/river/canal network around the stations in ``frame``.

    ``network_result`` (from :func:`network.build_channel_network`) lets stations snap
    to the channel they were matched to; otherwise each snaps to the nearest line
    within ``network.DEFAULT_MAX_DISTANCE_KM``. ``lines`` is an optional WGS84 line
    GeoDataFrame used instead of reading ``network_path``. Raises ValueError when no
    network, or no station on it, is found.
    """
    gpd, shapely = network._geo()
    from pyproj import Transformer
    from shapely.ops import substring

    if junction_weights not in JUNCTION_WEIGHTS:
        raise ValueError(f"junction_weights must be one of {', '.join(JUNCTION_WEIGHTS)}.")
    stations = network.station_table(frame).dropna(subset=["Latitude", "Longitude"]).reset_index(drop=True)
    if stations.empty:
        raise ValueError("No stations have coordinates.")
    points = gpd.GeoSeries(gpd.points_from_xy(stations["Longitude"], stations["Latitude"]), crs="EPSG:4326")
    if lines is None:
        lines = network.load_network(tuple(points.total_bounds), network_path)
    source = lines.attrs.get("source", "custom network")
    if lines.empty:
        raise ValueError(f"{source} has no lines near these stations.")
    metric = points.estimate_utm_crs()
    to_wgs = Transformer.from_crs(metric, "EPSG:4326", always_xy=True)
    points_m = points.to_crs(metric)
    minx, miny, maxx, maxy = points_m.total_bounds
    margin = buffer_km * 1000.0 + 2000.0
    clipped = lines.to_crs(metric)
    clipped["geometry"] = shapely.intersection(clipped.geometry.values,
                                               shapely.box(minx - margin, miny - margin, maxx + margin, maxy + margin))
    clipped = clipped[~clipped.geometry.is_empty].explode(index_parts=False)
    clipped = clipped[clipped.geom_type == "LineString"]
    clipped = clipped[clipped.geometry.length > 1.0].reset_index(drop=True)
    if clipped.empty:
        raise ValueError(f"{source} has no lines near these stations.")

    def column(name, default):
        return clipped[name].tolist() if name in clipped else [default] * len(clipped)

    originals = list(clipped.geometry.values)
    line_names = [str(value or "") for value in column("name", "")]
    map_names = [str(value or "") for value in column("network_name", "")]
    kinds = [str(value or "") for value in column("kind", "")]
    line_areas = [float(value) for value in column("upstream_area", math.nan)]
    line_discharge = [float(value) for value in column("discharge", math.nan)]

    # Join a line end to the middle of another line it stops on (T-junctions).
    tree = shapely.STRtree(originals)
    cuts: dict[int, set[float]] = defaultdict(set)
    links = []
    for index, line in enumerate(originals):
        for end, xy in ((0, line.coords[0]), (1, line.coords[-1])):
            point = shapely.Point(xy)
            best = None
            for other in tree.query(point, predicate="dwithin", distance=JOIN_TOLERANCE_M):
                other = int(other)
                if other == index:
                    continue
                along = originals[other].project(point)
                if along <= network.NODE_TOLERANCE_M or along >= originals[other].length - network.NODE_TOLERANCE_M:
                    continue
                gap = originals[other].distance(point)
                if best is None or gap < best[0]:
                    best = (gap, other, along)
            if best:
                cuts[best[1]].add(best[2])
                links.append((index, end, best[1], best[2]))
    pieces: list[tuple[int, Any]] = []
    pieces_of: dict[int, list[int]] = {}
    cut_ends: dict[int, list[tuple[float, int]]] = defaultdict(list)
    for index, line in enumerate(originals):
        marks = [0.0]
        for mark in sorted(cuts.get(index, ())):
            if mark - marks[-1] >= 1.0 and line.length - mark >= 1.0:
                marks.append(mark)
        marks.append(line.length)
        ids = []
        for low, high in zip(marks, marks[1:]):
            part = substring(line, low, high)
            if part.geom_type == "LineString" and part.length >= 1.0:
                ids.append(len(pieces))
                cut_ends[index].append((high, len(pieces)))
                pieces.append((index, part))
        if ids:
            pieces_of[index] = ids
    if not pieces:
        raise ValueError(f"{source} has no usable lines near these stations.")

    # Nodes: piece ends closer than NODE_TOLERANCE_M, plus the T-junction links.
    count = len(pieces)
    slots = shapely.points([part.coords[0] for _, part in pieces] + [part.coords[-1] for _, part in pieces])
    union = _UnionFind(2 * count)
    left, right = shapely.STRtree(slots).query(slots, predicate="dwithin", distance=network.NODE_TOLERANCE_M)
    for a, b in zip(left.tolist(), right.tolist()):
        union.union(a, b)
    for index, end, other, along in links:
        if index in pieces_of and cut_ends.get(other):
            own = pieces_of[index][0] if end == 0 else count + pieces_of[index][-1]
            _, piece = min(cut_ends[other], key=lambda item: abs(item[0] - along))
            union.union(own, count + piece)
    labels: dict[int, int] = {}
    node_xy: list[tuple[float, float]] = []
    slot_node = []
    for slot in range(2 * count):
        root = union.find(slot)
        if root not in labels:
            labels[root] = len(labels)
            node_xy.append((float(shapely.get_x(slots[root])), float(shapely.get_y(slots[root]))))
        slot_node.append(labels[root])
    candidates = [(slot_node[piece], slot_node[count + piece], piece) for piece in range(count)
                  if slot_node[piece] != slot_node[count + piece]]
    if not candidates:
        raise ValueError(f"{source} has no usable lines near these stations.")
    candidate_geoms = [pieces[piece][1] for _, _, piece in candidates]
    candidate_tree = shapely.STRtree(candidate_geoms)

    # Pin stations to the rivers: their matched channel first, else the nearest line.
    preferred: dict[str, str] = {}
    for channel in (network_result or {}).get("channels", []):
        if channel.get("geometry") and channel.get("networkName"):
            for station in channel["stations"]:
                preferred[station["location"]] = channel["networkName"].casefold()
    snapped: dict[str, tuple[int, float, float]] = {}
    off_network: list[str] = []
    for location, point in zip(stations["Location"], points_m):
        chosen = None
        wanted = preferred.get(location)
        if wanted:
            near = [int(item) for item in candidate_tree.query(point, predicate="dwithin", distance=network.NAME_MATCH_RADIUS_M)
                    if map_names[pieces[candidates[int(item)][2]][0]].casefold() == wanted]
            if near:
                chosen = min(near, key=lambda item: candidate_geoms[item].distance(point))
        if chosen is None:
            near = candidate_tree.query_nearest(point, max_distance=network.DEFAULT_MAX_DISTANCE_KM * 1000.0,
                                                return_distance=False)
            if len(near):
                chosen = int(near[0])
        if chosen is None:
            off_network.append(location)
        else:
            snapped[location] = (chosen, candidate_geoms[chosen].project(point), candidate_geoms[chosen].distance(point))
    if not snapped:
        raise ValueError(f"No station lies within {network.DEFAULT_MAX_DISTANCE_KM:g} km of a channel in {source}.")

    # Keep the connected parts of the network that carry stations.
    parts = _UnionFind(len(node_xy))
    for a, b, _ in candidates:
        parts.union(a, b)
    wanted_parts = {parts.find(candidates[edge][0]) for edge, _, _ in snapped.values()}
    kept = [index for index, (a, _, _) in enumerate(candidates) if parts.find(a) in wanted_parts]
    renumber = {old: new for new, old in enumerate(kept)}
    start = [candidates[index][0] for index in kept]
    end = [candidates[index][1] for index in kept]
    original = [pieces[candidates[index][2]][0] for index in kept]
    geometry = [candidate_geoms[index] for index in kept]
    length = np.asarray([line.length for line in geometry], dtype=float)
    names = [line_names[item] or map_names[item] for item in original]
    canal = [_is_canal(line_names[item], map_names[item], kinds[item]) for item in original]

    # Natural channels drain to an outlet; canals keep the direction they are drawn in.
    natural: dict[int, list[tuple[int, int, float]]] = defaultdict(list)
    degree: Counter = Counter()
    for edge in range(len(kept)):
        if not canal[edge]:
            natural[start[edge]].append((end[edge], edge, length[edge]))
            natural[end[edge]].append((start[edge], edge, length[edge]))
            degree[start[edge]] += 1
            degree[end[edge]] += 1
    natural_parts = _UnionFind(len(node_xy))
    for edge in range(len(kept)):
        if not canal[edge]:
            natural_parts.union(start[edge], end[edge])
    groups: dict[int, list[int]] = defaultdict(list)
    for node in natural:
        groups[natural_parts.find(node)].append(node)
    leaves = sorted(node for node in natural if degree[node] == 1)
    heights: dict[int, float] = {}
    if use_elevation and leaves:
        lon, lat = to_wgs.transform([node_xy[node][0] for node in leaves], [node_xy[node][1] for node in leaves])
        found = network.fetch_point_elevations(list(zip(lon, lat)))
        for node, x, y in zip(leaves, lon, lat):
            value = found.get((round(x, 5), round(y, 5)))
            if value is not None:
                heights[node] = value

    def agreement(outlet: int) -> float:
        _, via = _shortest(natural, outlet)
        return sum(length[edge] for _, (edge, towards) in via.items() if end[edge] == towards)

    to_outlet: dict[int, float] = {}
    component_info = []
    for nodes in groups.values():
        ends_here = [node for node in nodes if degree[node] == 1]
        known = {node: heights[node] for node in ends_here if node in heights}
        if len(known) >= 2 and max(known.values()) - min(known.values()) >= network.MIN_ELEVATION_DROP_M:
            lowest = min(known.values())
            options = [node for node, value in known.items() if value <= lowest + OUTLET_ELEVATION_SLACK_M]
            method = "lowest channel end (terrain elevation)"
        else:
            drawn_ends = {node for node in ends_here if all(end[edge] == node for _, edge, _ in natural[node])}
            options = sorted(ends_here, key=lambda node: (node not in drawn_ends, node))[:MAX_OUTLET_CANDIDATES]
            method = "direction the lines are drawn in"
        if not options:
            options, method = [min(nodes)], "no channel end found (closed loop)"
        outlet = max(options, key=lambda node: (agreement(node), -node)) if len(options) > 1 else options[0]
        distances, _ = _shortest(natural, outlet)
        to_outlet.update(distances)
        x, y = to_wgs.transform(*node_xy[outlet])
        component_info.append({"outlet": {"latitude": round(y, 6), "longitude": round(x, 6)},
                               "outletElevationM": round(heights[outlet], 1) if outlet in heights else None,
                               "directionMethod": method})
    down, up = [0] * len(kept), [0] * len(kept)
    for edge in range(len(kept)):
        a, b = start[edge], end[edge]
        if canal[edge]:
            up[edge], down[edge] = a, b
        else:
            # Water runs towards the outlet; ties keep the drawn direction.
            up[edge], down[edge] = (a, b) if (to_outlet.get(a, 0.0), -a) >= (to_outlet.get(b, 0.0), -b) else (b, a)

    # Water flows one way only: drop canals that would close a cycle.
    active = set(range(len(kept)))
    dropped = []
    while True:
        outgoing: dict[int, list[int]] = defaultdict(list)
        for edge in active:
            outgoing[up[edge]].append(edge)
        nodes = {up[edge] for edge in active} | {down[edge] for edge in active}
        order, cyclic = _topological(nodes, outgoing, down)
        if not cyclic:
            break
        in_cycle = sorted((edge for edge in active if up[edge] in cyclic and down[edge] in cyclic),
                          key=lambda edge: (not canal[edge], edge))
        active.discard(in_cycle[0])
        dropped.append(names[in_cycle[0]] or "unnamed channel")
    for location, (edge, along, gap) in list(snapped.items()):
        if renumber[edge] not in active:
            off_network.append(location)
            del snapped[location]

    graph = RiverGraph()
    graph.crs = metric
    keep = sorted(active)
    final = {old: new for new, old in enumerate(keep)}
    graph.geometry = [geometry[edge] for edge in keep]
    graph.length = length[keep]
    graph.down = [down[edge] for edge in keep]
    graph.up = [up[edge] for edge in keep]
    graph.down_at_start = [down[edge] == start[edge] for edge in keep]
    graph.names = [names[edge] for edge in keep]
    graph.canal = [canal[edge] for edge in keep]
    for edge in range(len(keep)):
        graph.incoming[graph.down[edge]].append(edge)
        graph.outgoing[graph.up[edge]].append(edge)
    graph.order = {node: position for position, node in enumerate(order)}
    graph.tree = all(len(items) <= 1 for items in graph.outgoing.values())

    # Water shares: how water divides at splits and mixes at junctions.
    areas = np.asarray([line_areas[original[edge]] for edge in keep], dtype=float)
    discharge = np.asarray([line_discharge[original[edge]] for edge in keep], dtype=float)
    natural_edges = [edge for edge in range(len(keep)) if not graph.canal[edge]]
    has_area = bool(natural_edges) and bool(np.all(np.isfinite(areas[natural_edges]) & (areas[natural_edges] > 0)))
    mode, note = junction_weights, None
    if mode == "auto":
        mode = "area" if has_area else "equal"
    elif mode == "area" and not has_area:
        mode, note = "equal", "The network file has no catchment-area column, so both sides of a junction count equally."
    split = np.ones(len(keep))
    for node, items in graph.outgoing.items():
        if len(items) < 2:
            continue
        known = discharge[items]
        if np.all(np.isfinite(known) & (known > 0)):
            weights = known
        else:
            weights = np.asarray([_rank(graph.names[edge], graph.canal[edge]) for edge in items])
        split[items] = weights / weights.sum()
    flow = np.ones(len(keep))
    for node in order:
        arriving = graph.incoming.get(node, [])
        total = sum(flow[edge] for edge in arriving) if arriving else 1.0
        for edge in graph.outgoing.get(node, ()):
            flow[edge] = areas[edge] if mode == "area" and not graph.canal[edge] and math.isfinite(areas[edge]) \
                else total * split[edge]
    share = np.ones(len(keep))
    for node, arriving in graph.incoming.items():
        if mode == "equal":
            share[arriving] = 1.0 / len(arriving)
        else:
            total = sum(flow[edge] for edge in arriving)
            share[arriving] = [flow[edge] / total if total > 0 else 1.0 / len(arriving) for edge in arriving]
    graph.share = share

    station_info = []
    for location, (edge, along, gap) in snapped.items():
        edge = final[renumber[edge]]
        t = along if graph.down_at_start[edge] else graph.length[edge] - along
        key = station_key(location)
        graph.stations[key] = (edge, float(min(max(t, 0.0), graph.length[edge])))
        station_info.append({"location": key, "channel": graph.names[edge] or None,
                             "canal": graph.canal[edge], "snapDistanceM": round(gap, 1),
                             "positionFrom": _label_hint(graph, key)})
    graph.info = {
        "found": True, "source": source, "edgeCount": len(keep),
        "lengthKm": round(float(graph.length.sum()) / 1000.0, 2), "outlets": component_info,
        "canalLengthKm": round(float(graph.length[graph.canal].sum()) / 1000.0, 2) if any(graph.canal) else 0.0,
        "splits": sum(len(items) > 1 for items in graph.outgoing.values()), "treeShaped": graph.tree,
        "droppedChannels": dropped, "junctionWeights": mode, "junctionWeightsNote": note,
        "stations": sorted(station_info, key=lambda item: item["location"]),
        "offNetwork": sorted(station_key(name) for name in off_network),
    }
    return graph


# ----------------------------------------------------------------------------
# 5-7. Estimators
# ----------------------------------------------------------------------------

def _connected_mask(relation):
    return (relation == DOWNSTREAM) | (relation == UPSTREAM)


def _idw(distance, relation, share, values, max_m, power, decay_m=None):
    """Along-river IDW from flow-connected stations within ``max_m``: (estimate, confidence 0-1).

    ``max_m`` may be inf (no limit); confidence then fades over ``decay_m`` metres.
    """
    usable = _connected_mask(relation) & (distance <= max_m) & (share > 0)
    metres = np.maximum(distance.astype(float), 1.0)
    weights = np.where(usable, share / (metres / 1000.0) ** power, 0.0)
    total = weights.sum(axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        estimate = np.where(total > 0, (weights @ values) / np.where(total > 0, total, 1.0), np.nan)
    exact = usable & (distance < 1.0)
    if exact.any():
        rows = np.nonzero(exact.any(axis=1))[0]
        estimate[rows] = values[np.argmin(np.where(exact[rows], distance[rows], np.inf), axis=1)]
    closeness = np.where(usable, share * np.exp(-3.0 * distance / (decay_m or max_m)), 0.0)
    confidence = np.where(np.isfinite(estimate), closeness.max(axis=1, initial=0.0), np.nan)
    return estimate, confidence


def _loo_idw(distance, relation, share, values, max_m, power, decay_m=None):
    relation = relation.copy()
    np.fill_diagonal(relation, 0)
    return _idw(distance, relation, share, values, max_m, power, decay_m)[0]


def _covariance(model, distance, relation, share, straight=None):
    """Exponential stream-network covariance (Ver Hoef & Peterson 2010) without the nugget."""
    weights = model.get("shares", {model["kind"]: 1.0})
    result = np.zeros(distance.shape)
    if weights.get("tail_up"):
        base = np.exp(-3.0 * distance.astype(float) / model["rangeM"])
        result += weights["tail_up"] * np.where(_connected_mask(relation), np.sqrt(share) * base, 0.0)
    if weights.get("tail_down"):
        base = np.exp(-3.0 * distance.astype(float) / model["rangeM"])
        result += weights["tail_down"] * np.where(relation > 0, base, 0.0)
    if weights.get("straight") and straight is not None:
        result += weights["straight"] * np.exp(-3.0 * straight / model["rangeM"])
    return model["partialSill"] * result


def _supported(distance, relation, max_m, model=None):
    kind = model["kind"] if model else "tail_up"
    linked = _connected_mask(relation) if kind == "tail_up" else relation > 0
    return (linked & (distance <= max_m)).any(axis=1)


def _krige(model, station_cov, target_cov, values):
    """Ordinary kriging: (estimate, variance) for targets given covariance matrices."""
    count = len(values)
    system = np.ones((count + 1, count + 1))
    system[:count, :count] = station_cov
    system[count, count] = 0.0
    rhs = np.ones((count + 1, target_cov.shape[0]))
    rhs[:count] = target_cov.T
    solution = np.linalg.solve(system, rhs)
    estimate = solution[:count].T @ values
    variance = model["partialSill"] + model["nugget"] - np.sum(solution[:count] * rhs[:count], axis=0) - solution[count]
    return estimate, np.maximum(variance, 0.0)


def _station_cov(model, distance, relation, share, straight=None):
    matrix = _covariance(model, distance, relation, share, straight)
    matrix = (matrix + matrix.T) / 2.0
    np.fill_diagonal(matrix, model["partialSill"] + model["nugget"])
    return matrix


def _loo_krige(model, distance, relation, share, straight, values, max_m):
    matrix = _station_cov(model, distance, relation, share, straight)
    count = len(values)
    result = np.full(count, np.nan)
    for index in range(count):
        others = np.arange(count) != index
        if not _supported(distance[index:index + 1, others], relation[index:index + 1, others], max_m, model)[0]:
            continue
        estimate, _ = _krige(model, matrix[np.ix_(others, others)], matrix[index:index + 1, others], values[others])
        result[index] = estimate[0]
    return result


def _rmse(estimate, values, rows=None):
    finite = np.isfinite(estimate) if rows is None else rows
    if not finite.any():
        return None
    return float(np.sqrt(np.mean((estimate[finite] - values[finite]) ** 2)))


def _fit_kriging(kind, distance, relation, share, straight, values, max_m):
    """Best (model, leave-one-out estimates) over a small range/nugget grid, or None."""
    variance = float(np.var(values, ddof=1)) if len(values) > 1 else 0.0
    if not variance > 0:
        return None
    linked = _connected_mask(relation) if kind == "tail_up" else relation > 0
    pairs = distance[linked & ~np.eye(len(values), dtype=bool) & np.isfinite(distance) & (distance > 0)]
    if not len(pairs):
        return None
    median = float(np.median(pairs))
    mixes = ([{"tail_up": a, "tail_down": b, "straight": c} for a, b, c in MIXED_SHARES] if kind == "mixed"
             else [{kind: 1.0}])
    best = None
    for shares in mixes:
        for factor in KRIGING_RANGE_FACTORS:
            for ratio in KRIGING_NUGGET_RATIOS:
                model = {"kind": kind, "shares": shares, "rangeM": median * factor,
                         "partialSill": variance * (1 - ratio), "nugget": variance * ratio}
                try:
                    estimate = _loo_krige(model, distance, relation, share, straight, values, max_m)
                except np.linalg.LinAlgError:
                    continue
                error = _rmse(estimate, values)
                if error is not None and (best is None or error < best[0]):
                    best = (error, model, estimate)
    return None if best is None else (best[1], best[2])


def _others_mean(values):
    """Each station's leave-one-out baseline: the mean of all the other stations."""
    return (values.sum() - values) / (len(values) - 1) if len(values) > 1 else np.full(len(values), np.nan)


def _validation(estimate, values, names):
    finite = np.isfinite(estimate)
    errors = estimate - values
    rmse = _rmse(estimate, values)
    # Baseline on the same stations: guessing the average of the other stations.
    baseline = _rmse(_others_mean(values), values, finite) if finite.any() else None
    skill = 1 - rmse / baseline if rmse is not None and baseline else None
    return {
        "method": "leave-one-out",
        "note": "Each station is hidden in turn and predicted from the others; a station with no "
                "flow-connected neighbour within the distance limit cannot be checked. The baseline "
                "guesses the average of the other stations; skill above 0 means the map beats it.",
        "stationCount": len(values), "checkedCount": int(finite.sum()),
        "rmse": _round(rmse), "mae": _round(float(np.mean(np.abs(errors[finite])))) if finite.any() else None,
        "baselineRmse": _round(baseline), "skill": _round(skill, 3),
        "stations": [{"location": name, "observed": round(float(value), 4),
                      "predicted": round(float(guess), 4) if math.isfinite(guess) else None,
                      "error": round(float(guess - value), 4) if math.isfinite(guess) else None}
                     for name, value, guess in zip(names, values, estimate)],
    }


# ----------------------------------------------------------------------------
# 8. Map grid
# ----------------------------------------------------------------------------

def _extent(latitudes, longitudes, minimum_span: float = 0.01) -> dict[str, float]:
    """Bounding box padded by 8%, at least ``minimum_span`` degrees (~1 km) across."""
    def bounds(values):
        low, high = float(min(values)), float(max(values))
        if high - low < minimum_span:
            centre = (low + high) / 2
            low, high = centre - minimum_span / 2, centre + minimum_span / 2
        pad = (high - low) * 0.08
        return low - pad, high + pad
    (min_lat, max_lat), (min_lon, max_lon) = bounds(latitudes), bounds(longitudes)
    return {"minLatitude": max(-90.0, min_lat), "maxLatitude": min(90.0, max_lat),
            "minLongitude": max(-180.0, min_lon), "maxLongitude": min(180.0, max_lon)}


def _grid_geometry(extent):
    lat_step = (extent["maxLatitude"] - extent["minLatitude"]) / (GRID_ROWS - 1)
    lon_step = (extent["maxLongitude"] - extent["minLongitude"]) / (GRID_COLUMNS - 1)
    metres_lon = 111_320.0 * math.cos(math.radians((extent["maxLatitude"] + extent["minLatitude"]) / 2))
    return lat_step, lon_step, lat_step * 111_320.0, lon_step * metres_lon


def _grid(extent, max_distance_km, layers, confidence, half_width=None):
    """Map grid with a lower and an upper layer; ``values`` repeats the upper layer."""
    _, _, lat_m, lon_m = _grid_geometry(extent)
    return {"extent": extent, "columns": GRID_COLUMNS, "rows": GRID_ROWS, "maxDistanceKm": max_distance_km,
            "cellSizeM": round(max(lat_m, lon_m), 1), "halfWidthM": round(half_width, 1) if half_width else None,
            "lower": layers["lower"], "upper": layers["upper"], "values": layers["upper"], "confidence": confidence}


def _paint(latitude, longitude, layers, confidence, stations, max_distance_km):
    """Draw estimates at river points as a narrow ribbon on the map grid (nearest estimate wins).

    ``layers`` maps "lower"/"upper" to estimates at the points; each station's own cell
    shows its observed bounds.
    """
    extent = _extent(list(latitude) + [point["latitude"] for point in stations],
                     list(longitude) + [point["longitude"] for point in stations])
    lat_step, lon_step, lat_m, lon_m = _grid_geometry(extent)
    half_width = max(MIN_HALF_WIDTH_M, 0.75 * max(lat_m, lon_m))
    reach_rows, reach_columns = int(math.ceil(half_width / lat_m)), int(math.ceil(half_width / lon_m))
    row_float = (extent["maxLatitude"] - np.asarray(latitude, dtype=float)) / lat_step
    column_float = (np.asarray(longitude, dtype=float) - extent["minLongitude"]) / lon_step
    base_row, base_column = np.rint(row_float).astype(int), np.rint(column_float).astype(int)
    count = len(row_float)
    cells, gaps, picks = [], [], []
    for row_offset in range(-reach_rows, reach_rows + 1):
        for column_offset in range(-reach_columns, reach_columns + 1):
            rows, columns = base_row + row_offset, base_column + column_offset
            gap = np.hypot((rows - row_float) * lat_m, (columns - column_float) * lon_m)
            keep = (rows >= 0) & (rows < GRID_ROWS) & (columns >= 0) & (columns < GRID_COLUMNS) & (gap <= half_width)
            cells.append(rows[keep] * GRID_COLUMNS + columns[keep])
            gaps.append(gap[keep])
            picks.append(np.nonzero(keep)[0])
    for position, point in enumerate(stations):
        row = min(max(int(round((extent["maxLatitude"] - point["latitude"]) / lat_step)), 0), GRID_ROWS - 1)
        column = min(max(int(round((point["longitude"] - extent["minLongitude"]) / lon_step)), 0), GRID_COLUMNS - 1)
        cells.append(np.asarray([row * GRID_COLUMNS + column]))
        gaps.append(np.asarray([-1.0]))
        picks.append(np.asarray([count + position]))
    cells, gaps, picks = np.concatenate(cells), np.concatenate(gaps), np.concatenate(picks).astype(int)
    order = np.argsort(-gaps, kind="stable")
    painted = {}
    for name in BOUNDS:
        observed = [np.nan if point.get(name) is None else point[name] for point in stations]
        full = np.concatenate([np.asarray(layers[name], dtype=float), np.asarray(observed, dtype=float)])
        grid = np.full(GRID_ROWS * GRID_COLUMNS, np.nan)
        grid[cells[order]] = full[picks[order]]
        painted[name] = _rounded(grid)
    full = np.concatenate([np.asarray(confidence, dtype=float), np.ones(len(stations))])
    shown = np.full(GRID_ROWS * GRID_COLUMNS, np.nan)
    shown[cells[order]] = full[picks[order]]
    return _grid(extent, max_distance_km, painted, _percent(shown), half_width)


def _rounded(values):
    values = np.asarray(values, dtype=float)
    result = np.round(values, 4).astype(object)
    result[~np.isfinite(values)] = None
    return result.tolist()


def _percent(values):
    values = np.asarray(values, dtype=float)
    finite = np.isfinite(values)
    result = np.zeros(values.shape, dtype=object)
    result[finite] = np.rint(values[finite] * 100).astype(int).tolist()
    result[~finite] = None
    return result.tolist()


def _round(value, digits=4):
    return None if value is None else round(value, digits)


def _haversine_m(lat1, lon1, lat2, lon2) -> np.ndarray:
    lat1 = np.radians(np.asarray(lat1, dtype=float))[:, None]
    lat2 = np.radians(np.asarray(lat2, dtype=float))[None, :]
    delta_lat = lat2 - lat1
    delta_lon = np.radians(np.asarray(lon2, dtype=float))[None, :] - np.radians(np.asarray(lon1, dtype=float))[:, None]
    value = np.sin(delta_lat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(delta_lon / 2) ** 2
    return 6_371_000.0 * 2 * np.arctan2(np.sqrt(value), np.sqrt(np.maximum(0.0, 1 - value)))


# ----------------------------------------------------------------------------
# Surfaces
# ----------------------------------------------------------------------------

def _model_info(model):
    if not model:
        return None
    info = {"kind": model["kind"], "rangeKm": round(model["rangeM"] / 1000.0, 3),
            "nuggetRatio": round(model["nugget"] / (model["nugget"] + model["partialSill"]), 3)}
    if model["kind"] == "mixed":
        info["shares"] = {key: round(value, 3) for key, value in model["shares"].items()}
    return info


def _empty_run(note):
    return {"methodKey": None, "method": None, "usedStationCount": 0, "validation": None, "candidates": [],
            "model": None, "notes": [note]}


def _river_run(points, bound, context, options):
    """One bound along the river: (run summary, estimate at the targets, confidence)."""
    max_m, power, decay = options["maxM"], options["power"], options["decayM"]
    index = context["index"]
    targets = len(context["latitude"])
    used = [point for point in points if point[bound] is not None and point["location"] in index]
    if not used:
        return (_empty_run(f"No station with a {bound} bound is on the river map."),
                np.full(targets, np.nan), np.full(targets, np.nan))
    columns = [index[point["location"]] for point in used]
    used_values = np.asarray([point[bound] for point in used], dtype=float)
    used_names = [point["location"] for point in used]
    distance, relation, share = (context[key][:, columns] for key in ("distance", "relation", "share"))
    pairs = np.ix_(columns, columns)
    s_distance, s_relation, s_share = (context[key][pairs] for key in ("stationDistance", "stationRelation", "stationShare"))
    lat = [point["latitude"] for point in used]
    lon = [point["longitude"] for point in used]

    estimates = {"river_idw": _loo_idw(s_distance, s_relation, s_share, used_values, max_m, power, decay)}
    models: dict[str, dict[str, Any]] = {}
    notes = []
    if options["advanced"]:
        if len(used) < MIN_KRIGING_STATIONS:
            notes.append(f"Kriging skipped: it needs at least {MIN_KRIGING_STATIONS} stations on the "
                         f"river map (this surface has {len(used)}).")
        elif not context["tree"]:
            notes.append("Kriging skipped: the network splits (canals or braided channels), and the fitted "
                         "models need a tree-shaped network.")
        else:
            s_straight = _haversine_m(lat, lon, lat, lon)
            for kind in ("tail_up", "tail_down", "mixed"):
                fitted = _fit_kriging(kind, s_distance, s_relation, s_share, s_straight, used_values, max_m)
                if fitted:
                    models[kind], estimates[kind] = fitted
    common = np.logical_and.reduce([np.isfinite(estimate) for estimate in estimates.values()])
    candidates = [{"method": key, "label": METHOD_LABELS[key], "rmse": _round(_rmse(estimate, used_values)),
                   "rmseOnCommonStations": _round(_rmse(estimate, used_values, common)) if common.any() else None,
                   "model": _model_info(models.get(key))} for key, estimate in estimates.items()]
    chosen = "river_idw"
    if len(estimates) > 1 and common.any():
        chosen = min(estimates, key=lambda key: (_rmse(estimates[key], used_values, common), key != "river_idw"))
    if chosen == "river_idw":
        estimate, confidence = _idw(distance, relation, share, used_values, max_m, power, decay)
    else:
        model = models[chosen]
        straight = _haversine_m(context["latitude"], context["longitude"], lat, lon) if model["kind"] == "mixed" else None
        s_straight = _haversine_m(lat, lon, lat, lon) if model["kind"] == "mixed" else None
        estimate, variance = _krige(model, _station_cov(model, s_distance, s_relation, s_share, s_straight),
                                    _covariance(model, distance, relation, share, straight), used_values)
        supported = _supported(distance, relation, max_m, model)
        estimate = np.where(supported, estimate, np.nan)
        confidence = np.where(supported, np.clip(1 - np.sqrt(variance / (model["partialSill"] + model["nugget"])), 0, 1),
                              np.nan)
    run = {"methodKey": chosen, "method": METHOD_LABELS[chosen], "usedStationCount": len(used),
           "validation": _validation(estimates[chosen], used_values, used_names), "candidates": candidates,
           "model": _model_info(models.get(chosen)), "notes": notes}
    return run, estimate, confidence


def _straight_run(points, bound, cell_lat, cell_lon, options):
    """One bound with straight-line IDW over the grid cells: (run summary, estimate, confidence)."""
    max_m, power, decay = options["maxM"], options["power"], options["decayM"]
    used = [point for point in points if point[bound] is not None]
    if not used:
        return _empty_run(f"No station has a {bound} bound."), np.full(len(cell_lat), np.nan), np.full(len(cell_lat), np.nan)
    values = np.asarray([point[bound] for point in used], dtype=float)
    lat = [point["latitude"] for point in used]
    lon = [point["longitude"] for point in used]
    distance = _haversine_m(cell_lat, cell_lon, lat, lon)
    estimate, confidence = _idw(distance, np.full(distance.shape, DOWNSTREAM, dtype=np.int8), np.ones(distance.shape),
                                values, max_m, power, decay)
    station_distance = _haversine_m(lat, lon, lat, lon)
    loo = _loo_idw(station_distance, np.full(station_distance.shape, DOWNSTREAM, dtype=np.int8),
                   np.ones(station_distance.shape), values, max_m, power, decay)
    validation = _validation(loo, values, [point["location"] for point in used])
    run = {"methodKey": "straight_idw", "method": METHOD_LABELS["straight_idw"], "usedStationCount": len(used),
           "validation": validation, "model": None, "notes": [],
           "candidates": [{"method": "straight_idw", "label": METHOD_LABELS["straight_idw"], "rmse": validation["rmse"]}]}
    return run, estimate, confidence


def _surface(period, parameter, points, unit, context, options):
    """One map for a parameter and period: a lower and an upper run painted on one grid."""
    index = context["index"] if context else {}
    for point in points:
        point["onNetwork"] = point["location"] in index
    surface = {
        "id": re.sub(r"[^a-z0-9]+", "-", f"{period}:{parameter}".lower()).strip("-"),
        "parameter": parameter, "parameterFamily": parameter, "unit": unit,
        "year": None if period == "all_years" else int(period), "period": period,
        "pointCount": len(points), "samplePoints": points,
        "interval": any(point["kind"] != "reading" for point in points),
        "warning": None, "junctionWeights": context["junctionWeights"] if context else None,
    }
    warnings = []
    if len(points) == 1:
        single = {"methodKey": "single", "method": METHOD_LABELS["single"], "usedStationCount": 1, "validation": None,
                  "candidates": [], "model": None, "notes": []}
        runs = {bound: dict(single) for bound in BOUNDS}
        grid = _paint([], [], {bound: [] for bound in BOUNDS}, [], points, options["maxDistanceKm"])
    elif context and any(point["onNetwork"] for point in points):
        runs, layers, confidences = {}, {}, []
        for bound in BOUNDS:
            runs[bound], layers[bound], confidence = _river_run(points, bound, context, options)
            confidences.append(confidence)
        with np.errstate(invalid="ignore"):
            confidence = np.fmin(*confidences)  # the weaker of the two runs
        keep = np.isfinite(layers["lower"]) | np.isfinite(layers["upper"])
        grid = _paint(context["latitude"][keep], context["longitude"][keep], {bound: layers[bound][keep] for bound in BOUNDS},
                      confidence[keep], [point for point in points if point["onNetwork"]], options["maxDistanceKm"])
        left_out = [point["location"] for point in points if not point["onNetwork"]]
        if left_out:
            warnings.append(f"{len(left_out)} station(s) are not on the river map and were left out: {', '.join(left_out)}.")
        if any(context["canal"].get(point["location"]) for point in points if point["onNetwork"]):
            warnings.append(CANAL_WARNING)
    else:
        extent = _extent([point["latitude"] for point in points], [point["longitude"] for point in points])
        lat_step, lon_step, _, _ = _grid_geometry(extent)
        rows, columns = np.divmod(np.arange(GRID_ROWS * GRID_COLUMNS), GRID_COLUMNS)
        cell_lat, cell_lon = extent["maxLatitude"] - rows * lat_step, extent["minLongitude"] + columns * lon_step
        runs, layers, confidences = {}, {}, []
        for bound in BOUNDS:
            runs[bound], layers[bound], confidence = _straight_run(points, bound, cell_lat, cell_lon, options)
            confidences.append(confidence)
        with np.errstate(invalid="ignore"):
            confidence = np.fmin(*confidences)
        grid = _grid(extent, options["maxDistanceKm"], {bound: _rounded(layers[bound]) for bound in BOUNDS},
                     _percent(confidence))
        warning = OFF_NETWORK_WARNING if context else NO_NETWORK_WARNING
        if not context and options.get("networkReason"):
            warning += f" ({options['networkReason']})"
        warnings.append(warning)
    one_sided = {kind: [point["location"] for point in points if point["kind"] == kind] for kind in ("max only", "min only")}
    if one_sided["max only"]:
        warnings.append("Only a Max is reported at " + ", ".join(one_sided["max only"]) + ", so it counts for the upper bound only.")
    if one_sided["min only"]:
        warnings.append("Only a Min is reported at " + ", ".join(one_sided["min only"]) + ", so it counts for the lower bound only.")
    main = runs["upper"] if runs["upper"]["methodKey"] else runs["lower"]
    notes = list(dict.fromkeys(note for bound in BOUNDS for note in runs[bound]["notes"]))
    surface.update(methodKey=main["methodKey"], method=main["method"], usedStationCount=main["usedStationCount"],
                   validation=main["validation"], candidates=main["candidates"], model=main["model"], notes=notes,
                   runs=runs, grid=grid, warning=" ".join(warnings) or None)
    return surface


def _validate(max_distance_km, power, junction_weights):
    checks = [("power", power)] + ([] if max_distance_km == "auto" else [("max_distance_km", max_distance_km)])
    for name, value in checks:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError(f"{name} must be a positive finite number" + (' or "auto".' if name == "max_distance_km" else "."))
    if junction_weights not in JUNCTION_WEIGHTS:
        raise ValueError(f"junction_weights must be one of {', '.join(JUNCTION_WEIGHTS)}.")


def _station_matrices(points, context, bound="upper"):
    """(values, distance, relation, share) between the stations of one bound of a surface, or None."""
    points = [point for point in points if point[bound] is not None]
    if context:
        used = [point for point in points if point["location"] in context["index"]]
        columns = [context["index"][point["location"]] for point in used]
        pairs = np.ix_(columns, columns)
        matrices = tuple(context[key][pairs] for key in ("stationDistance", "stationRelation", "stationShare"))
    else:
        used = points
        lat = [point["latitude"] for point in used]
        lon = [point["longitude"] for point in used]
        distance = _haversine_m(lat, lon, lat, lon)
        matrices = (distance, np.full(distance.shape, DOWNSTREAM, dtype=np.int8), np.ones(distance.shape))
    if len(used) < MIN_STATIONS_TO_CHOOSE:
        return None
    return (np.asarray([point[bound] for point in used], dtype=float),) + matrices


def _bound_matrices(groups, context):
    """Every (surface, bound) with enough stations to be scored."""
    for points, _ in groups.values():
        for bound in BOUNDS:
            found = _station_matrices(points, context, bound)
            if found:
                yield found


def _no_limit_decay(groups, context) -> float:
    """Confidence fade length without a limit: the longest distance between linked stations."""
    longest = 1000.0
    for _, distance, relation, _ in _bound_matrices(groups, context):
        linked = distance[(relation > 0) & np.isfinite(distance)]
        if len(linked):
            longest = max(longest, float(linked.max()))
    return longest


def choose_distance(groups, context, power: float = DEFAULT_POWER,
                    candidates=DISTANCE_CANDIDATES_KM) -> dict[str, Any]:
    """Pick the distance limit with the smallest leave-one-out error.

    For both bounds of every all-years surface with at least ``MIN_STATIONS_TO_CHOOSE``
    stations, each station is hidden and predicted from the others under each limit. A
    station a limit cannot reach is scored as the mean of the other stations, so a
    short limit does not win just by skipping hard cases. Errors are divided by each
    surface's spread (standard deviation) so different parameters can be averaged.
    Ties go to the shorter limit.
    """
    no_limit_decay = _no_limit_decay(groups, context)
    baseline = []
    for values, *_ in _bound_matrices(groups, context):
        if np.std(values) > 0:
            baseline.append(float(np.sqrt(np.mean((_others_mean(values) - values) ** 2))) / float(np.std(values)))
    baseline_error = _round(float(np.mean(baseline))) if baseline else None
    table = []
    for limit_km in candidates:
        limit_m = math.inf if limit_km is None else limit_km * 1000.0
        decay_m = no_limit_decay if limit_km is None else limit_m
        scores, reached, total = [], 0, 0
        for values, distance, relation, share in _bound_matrices(groups, context):
            spread = float(np.std(values))
            if not spread > 0:
                continue
            estimate = _loo_idw(distance, relation, share, values, limit_m, power, decay_m)
            reached += int(np.isfinite(estimate).sum())
            total += len(values)
            estimate = np.where(np.isfinite(estimate), estimate, _others_mean(values))
            scores.append(float(np.sqrt(np.mean((estimate - values) ** 2))) / spread)
        table.append({"maxDistanceKm": limit_km, "relativeError": _round(float(np.mean(scores))) if scores else None,
                      "surfaces": len(scores), "stationsReached": reached, "stationsChecked": total})
    scored = [row for row in table if row["relativeError"] is not None]
    if not scored:
        return {"mode": "auto", "chosenKm": FALLBACK_DISTANCE_KM, "candidates": table, "baselineRelativeError": None,
                "beatsBaseline": None,
                "note": f"Too few stations to compare limits; {FALLBACK_DISTANCE_KM:g} km was used."}
    best = min(scored, key=lambda row: (row["relativeError"], math.inf if row["maxDistanceKm"] is None else row["maxDistanceKm"]))
    beats = baseline_error is not None and best["relativeError"] < baseline_error
    note = ("Chosen by leave-one-out: relative error is the typical miss divided by each parameter's spread "
            "(lower is better); stations a limit cannot reach count as the mean of the others.")
    if not beats:
        note += (" No limit beats simply using the average of the other stations, so nearby stations do not "
                 "predict each other well here: read the map as a sketch, not a measurement.")
    return {"mode": "auto", "chosenKm": best["maxDistanceKm"], "candidates": table,
            "baselineRelativeError": baseline_error, "beatsBaseline": beats, "note": note}


def build_interpolation_data(records: list[dict[str, Any]], *, positions: dict[str, tuple[float, float]] | None = None,
                             graph: RiverGraph | None = None, network_reason: str | None = None,
                             max_distance_km: float | str = DEFAULT_MAX_DISTANCE_KM, power: float = DEFAULT_POWER,
                             advanced: bool = False, junction_weights: str = "auto",
                             mapped_location_count: int | None = None) -> dict[str, Any]:
    """All-years and yearly surfaces for every parameter (see the module docstring)."""
    _validate(max_distance_km, power, junction_weights)
    context = None
    if graph is not None and graph.stations:
        names = sorted(graph.stations)
        station_positions = [graph.stations[name] for name in names]
        s_distance, s_relation, s_share = graph.relations(
            station_positions, np.asarray([edge for edge, _ in station_positions], dtype=int),
            np.asarray([t for _, t in station_positions], dtype=float))
        context = {"index": {name: column for column, name in enumerate(names)},
                   "stationDistance": s_distance, "stationRelation": s_relation, "stationShare": s_share,
                   "tree": graph.tree, "canal": {name: graph.canal[graph.stations[name][0]] for name in names},
                   "junctionWeights": graph.info.get("junctionWeights")}
    groups = {"allYears": station_values(records, positions, yearly=False),
              "yearly": station_values(records, positions, yearly=True)}
    if max_distance_km == "auto":
        selection = choose_distance(groups["allYears"], context, power)
        limit_km = selection["chosenKm"]
    else:
        limit_km = float(max_distance_km)
        selection = {"mode": "fixed", "chosenKm": limit_km, "candidates": [], "note": "Set by max_distance_km."}
    max_m = math.inf if limit_km is None else limit_km * 1000.0
    decay_m = _no_limit_decay(groups["allYears"], context) if limit_km is None else max_m
    if context:
        target_edge, target_t = graph.samples(station_positions, max_m)
        context["distance"], context["relation"], context["share"] = graph.relations(
            station_positions, target_edge, target_t, max_m)
        context["latitude"], context["longitude"] = graph.coordinates(target_edge, target_t)
    options = {"maxDistanceKm": limit_km, "maxM": max_m, "decayM": decay_m, "power": float(power),
               "advanced": bool(advanced), "networkReason": network_reason}
    surfaces = {}
    for key in ("allYears", "yearly"):
        surfaces[key] = sorted((_surface(period, parameter, points, unit, context, options)
                                for (period, parameter), (points, unit) in groups[key].items()),
                               key=lambda surface: (str(surface["period"]), surface["parameter"]))
    extents = [surface["grid"]["extent"] for surface in surfaces["allYears"]]
    extent = ({"minLatitude": min(item["minLatitude"] for item in extents), "maxLatitude": max(item["maxLatitude"] for item in extents),
               "minLongitude": min(item["minLongitude"] for item in extents), "maxLongitude": max(item["maxLongitude"] for item in extents)}
              if extents else None)
    return {
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        "sourceRecordCount": len(records),
        "mappedLocationCount": mapped_location_count,
        "method": {"type": "Along-river interpolation" if context else "Straight-line IDW",
                   "distanceMeasuredAlong": "river" if context else "straight line",
                   "maxDistanceKm": limit_km, "distanceSelection": selection,
                   "power": float(power), "advanced": bool(advanced),
                   "minKrigingStations": MIN_KRIGING_STATIONS,
                   "junctionWeights": graph.info.get("junctionWeights") if context else None,
                   "sampleSpacingM": SAMPLE_SPACING_M, "gridColumns": GRID_COLUMNS, "gridRows": GRID_ROWS},
        "network": graph.info if context else {"found": False, "reason": network_reason},
        "extent": extent,
        "surfaces": surfaces,
    }


def compact_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Copy of ``payload`` whose grids list only the painted cells (for the dashboard API).

    Each grid gets ``encoding: "sparse"`` with ``cells`` (row-major indices) and matching
    ``cellLower``, ``cellUpper`` and ``cellConfidence`` instead of the dense layers.
    """
    def compact(surface):
        grid = dict(surface["grid"])
        lower, upper, confidence = grid.pop("lower"), grid.pop("upper"), grid.pop("confidence")
        grid.pop("values", None)
        cells = [index for index in range(len(upper)) if upper[index] is not None or lower[index] is not None]
        grid.update(encoding="sparse", cells=cells, cellLower=[lower[index] for index in cells],
                    cellUpper=[upper[index] for index in cells], cellConfidence=[confidence[index] for index in cells])
        return {**surface, "grid": grid}
    surfaces = {key: [compact(surface) for surface in items] for key, items in payload["surfaces"].items()}
    return {**payload, "surfaces": surfaces}


def interpolate_dataset(dataset, *, max_distance_km: float | str = DEFAULT_MAX_DISTANCE_KM, power: float = DEFAULT_POWER,
                        advanced: bool = False, junction_weights: str = "auto", network_path=None) -> dict[str, Any]:
    """Run the whole method for a :class:`RiverDataset` (used by ``RiverDataset.interpolate``).

    Network files are tried in order (``network.network_sources``) until one has a
    channel near the stations.
    """
    _validate(max_distance_km, power, junction_weights)
    records = dataset._dashboard_data.get("records", [])
    positions = {}
    if len(dataset.data):
        positions = {station_key(row.Location): (row.Latitude, row.Longitude)
                     for row in network.station_table(dataset.data).itertuples()}
    graph, reasons = None, []
    if any(record.get("hasCoordinates") for record in records):
        try:
            sources = network.network_sources(network_path)
            if not sources:
                network.find_network_path(network_path)  # raises the "no network file" message
        except Exception as error:
            sources, reasons = [], [str(error)]
        for position, source in enumerate(sources):
            matched = None
            if position == 0:  # matched channel names come from the preferred map only
                try:
                    matched = dataset.channel_network(network_path=network_path) if network_path else dataset.channel_network()
                except Exception:
                    matched = None
            try:
                buffer_km = AUTO_BUFFER_KM if max_distance_km == "auto" else max_distance_km
                graph = build_river_graph(dataset.data, matched, network_path=source, buffer_km=buffer_km,
                                          junction_weights=junction_weights)
                break
            except Exception as error:  # no geopandas, or no channel near the stations
                reasons.append(f"{source.name}: {error}")
    return build_interpolation_data(records, positions=positions, graph=graph, network_reason="; ".join(reasons) or None,
                                    max_distance_km=max_distance_km, power=power, advanced=advanced,
                                    junction_weights=junction_weights,
                                    mapped_location_count=dataset._dashboard_data["summary"]["mappedLocationCount"])
