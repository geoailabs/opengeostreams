"""CSV preparation and dashboard payloads for OpenGeoStreams (interpolation lives in ``interpolation``)."""

from __future__ import annotations

import csv
import calendar
import json
import math
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import numpy as np

try:
    from . import qualitycheck
except ImportError:  # run as a script: python pipeline.py
    import qualitycheck

PACKAGE_ROOT = Path(__file__).resolve().parent
ROOT = PACKAGE_ROOT / "dashboard_assets"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATASET_DIR = PROJECT_ROOT / "Datasets"
CONSOLIDATED_FILE = DATASET_DIR / "consolidated_dataset.csv"
OUTPUT_COLUMNS = [
    "SrNo", "Parameter", "Unit", "Date", "Value", "Data Source",
    "Location", "Latitude", "Longitude",
]
MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2,
    "mar": 3, "march": 3, "apr": 4, "april": 4, "may": 5,
    "jun": 6, "june": 6, "jul": 7, "july": 7, "aug": 8,
    "august": 8, "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}
MONTH_LABELS = ("", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
KNOWN_LOCATIONS = {
    "cpcb_2020_station2047.csv": "CPCB Station Code 2047",
    "combined_cpcb_3BRD_2018_2020.csv": "3BRD",
    "combined_cpcb_Diggian_2018_2020.csv": "Diggian",
}


def clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\ufeff", "").replace("Â", "").replace("–", "-")).strip()


def normalize_parameter(value: Any) -> str:
    """Unify total-coliform aliases while preserving Min/Max qualifiers."""
    parameter = clean(value)
    match = re.fullmatch(r"(?:t[.\-\s]*coliform|total\s+coliform)(\s*\((?:max|min)\))?", parameter, re.I)
    if match:
        suffix = match.group(1)
        return "Total Coliform" + (" " + suffix.strip().title() if suffix else "")
    return parameter


def read_csv_rows(source: Path | Any) -> list[dict[str, str]]:
    """Read UTF-8 CSV rows from a path or text file object."""
    if hasattr(source, "read"):
        return [{clean(k): clean(v) for k, v in row.items()} for row in csv.DictReader(source)]
    with Path(source).open("r", encoding="utf-8-sig", newline="") as handle:
        return [{clean(k): clean(v) for k, v in row.items()} for row in csv.DictReader(handle)]


def parse_month(value: Any, default: int = 1) -> int:
    text = clean(value).lower()
    if not text:
        return default
    if text in MONTHS:
        return MONTHS[text]
    try:
        number = int(text)
        return number if 1 <= number <= 12 else default
    except ValueError:
        return default


def normalize_date(row: dict[str, str], filename: str = "") -> str:
    """Return an exact date or a bracketed range when day/month is unknown."""
    supplied = clean(row.get("Date"))
    if supplied:
        for date_format in ("%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"):
            try:
                return datetime.strptime(supplied, date_format).strftime("%d-%m-%Y")
            except ValueError:
                pass
        range_match = re.fullmatch(
            r"(?:\[\s*)?(\d{2}-\d{2}-\d{4})\s*(?:,|/)\s*(\d{2}-\d{2}-\d{4})(?:\s*\])?",
            supplied,
        )
        if range_match:
            start_text, end_text = range_match.groups()
            start = datetime.strptime(start_text, "%d-%m-%Y")
            end = datetime.strptime(end_text, "%d-%m-%Y")
            if end < start:
                raise ValueError(f"Date range ends before it starts: '{supplied}'.")
            return f"[{start:%d-%m-%Y}, {end:%d-%m-%Y}]"
        raise ValueError(f"Unsupported date '{supplied}'. Use dd-mm-yyyy.")
    year_text = clean(row.get("Year"))
    if not year_text:
        match = re.search(r"(?:19|20)\d{2}", filename)
        year_text = match.group(0) if match else ""
    if not year_text.isdigit():
        raise ValueError("Each row needs Date or Year.")
    year = int(year_text)
    month_text = clean(row.get("Month"))
    if not month_text:
        return f"[01-01-{year:04d}, 31-12-{year:04d}]"
    month = parse_month(month_text)
    last_day = calendar.monthrange(year, month)[1]
    return f"[01-{month:02d}-{year:04d}, {last_day:02d}-{month:02d}-{year:04d}]"


def parse_date_bounds(value: Any) -> tuple[datetime, datetime, str]:
    """Parse a normalized date into start/end bounds and its precision."""
    text = clean(value)
    range_match = re.fullmatch(
        r"(?:\[\s*)?(\d{2}-\d{2}-\d{4})\s*(?:,|/)\s*(\d{2}-\d{2}-\d{4})(?:\s*\])?",
        text,
    )
    if not range_match:
        date = datetime.strptime(text, "%d-%m-%Y")
        return date, date, "day"
    start_text, end_text = range_match.groups()
    start = datetime.strptime(start_text, "%d-%m-%Y")
    end = datetime.strptime(end_text, "%d-%m-%Y")
    precision = "year" if start.month == 1 and start.day == 1 and end.month == 12 and end.day == 31 else "month"
    return start, end, precision


WATER_BODY_COLUMNS = (
    "Water Body", "Water Body Name", "Waterbody", "Drain", "Drain Name",
    "River", "River Name", "Channel", "Stream",
)


def resolve_location(row: dict[str, str], filename: str) -> str:
    return clean(row.get("Location")) or KNOWN_LOCATIONS.get(filename, "")


def standardize_rows(rows: Iterable[dict[str, str]], filename: str) -> list[dict[str, str | int]]:
    standardized = []
    for row_number, row in enumerate(rows, 1):
        if not any(clean(value) for value in row.values()):
            continue
        standardized.append({
            "SrNo": row_number,
            "Parameter": normalize_parameter(row.get("Parameter")),
            "Unit": clean(row.get("Unit")),
            "Date": normalize_date(row, filename),
            "Value": clean(row.get("Value")),
            "Data Source": clean(row.get("Data Source")),
            "Location": resolve_location(row, filename),
            "Latitude": clean(row.get("Latitude")),
            "Longitude": clean(row.get("Longitude")),
        })
        # Optional drain/river name used to group stations (see network.py).
        water_body = next((clean(row.get(key)) for key in WATER_BODY_COLUMNS if clean(row.get(key))), "")
        if water_body:
            standardized[-1]["Water Body"] = water_body
    return standardized


_COORDINATE_NUMBER = re.compile(r"(?<![A-Za-z0-9])\d{1,3}\.\d+(?![A-Za-z0-9])")
_US_LABEL = re.compile(r"\b(?:U\s*/\s*S|UPSTREAM)\b", re.IGNORECASE)
_DS_LABEL = re.compile(r"\b(?:D\s*/\s*S|DOWNSTREAM)\b", re.IGNORECASE)
# Extra words that make a label a different site, not a variant of the same one.
_SITE_WORDS = {"U", "S", "D", "UPSTREAM", "DOWNSTREAM", "BEFORE", "AFTER", "CONFLUENCE", "CONF",
               "ABOVE", "BELOW", "INLET", "OUTLET", "INTAKE", "EXIT", "ENTRY", "ORIGIN",
               "NORTH", "SOUTH", "EAST", "WEST", "LEFT", "RIGHT", "OLD", "NEW"}
# Labels that start like this are fragments of a longer label split by PDF extraction.
_FRAGMENT_START = {"OF", "INTO", "AT", "ON", "FALLING", "TO", "AND", "WITH", "IN", "NEAR", "FROM"}


def _label_tokens(label: str) -> frozenset[str]:
    """Words in a station label, ignoring coordinates pasted into it (e.g. "... PUNJAB 30.973")."""
    return frozenset(re.findall(r"[A-Z0-9]+", _COORDINATE_NUMBER.sub(" ", str(label).upper())))


def _flow_marker(label: str) -> str:
    upstream, downstream = bool(_US_LABEL.search(label)), bool(_DS_LABEL.search(label))
    return "US" if upstream and not downstream else "DS" if downstream and not upstream else ""


def merge_duplicate_locations(rows: list[dict[str, Any]], *, same_point_m: float = 150.0,
                              nearby_m: float = 1000.0, max_extra_words: int = 3) -> list[dict[str, Any]]:
    """Give one name to station labels that are variants of the same site.

    Two labels merge when every word of one appears in the other (numbers that look
    like coordinates are ignored) and the longer adds at most ``max_extra_words``;
    their median coordinates agree (within ``same_point_m``, or ``nearby_m`` when
    the shorter label has 3+ words); the extra words do not change the site (U/S,
    D/S, before, outlet, north ...) unless the shorter label is an obvious
    fragment; every label in a merged group is a sub-label of the others (no
    chaining); and an upstream label is never merged with a downstream one.
    Rows are updated in place; a list of {"name", "merged"} is returned.
    """
    coordinates: dict[str, list[tuple[float, float]]] = defaultdict(list)
    counts: dict[str, int] = defaultdict(int)
    for row in rows:
        name = str(row.get("Location") or "")
        if not name:
            continue
        counts[name] += 1
        lat, lon = number(row.get("Latitude")), number(row.get("Longitude"))
        if lat is not None and lon is not None and -90 <= lat <= 90 and -180 <= lon <= 180:
            coordinates[name].append((lat, lon))
    names = [name for name in counts if coordinates.get(name)]
    if len(names) < 2:
        return []
    centre = {name: (float(np.median([lat for lat, _ in coordinates[name]])),
                     float(np.median([lon for _, lon in coordinates[name]]))) for name in names}
    tokens = {name: _label_tokens(name) for name in names}

    def fragment(name: str) -> bool:
        words = re.findall(r"[A-Z]+", name.upper())
        return bool(_COORDINATE_NUMBER.search(name)) or (bool(words) and words[0] in _FRAGMENT_START)

    def comparable(a: str, b: str) -> bool:
        return tokens[a] <= tokens[b] or tokens[b] <= tokens[a]
    markers = {name: _flow_marker(name) for name in names}

    def metres(a: str, b: str) -> float:
        (lat1, lon1), (lat2, lon2) = centre[a], centre[b]
        dy = (lat2 - lat1) * 111_320.0
        dx = (lon2 - lon1) * 111_320.0 * math.cos(math.radians((lat1 + lat2) / 2))
        return math.hypot(dx, dy)

    parent = {name: name for name in names}
    members = {name: {name} for name in names}

    def find(name: str) -> str:
        while parent[name] != name:
            parent[name] = parent[parent[name]]
            name = parent[name]
        return name

    # Only compare labels in neighbouring ~2 km grid cells.
    cell_size = max(nearby_m, same_point_m) / 111_320.0
    grid: dict[tuple[int, int], list[str]] = defaultdict(list)
    for name in names:
        grid[(int(centre[name][0] // cell_size), int(centre[name][1] // cell_size))].append(name)
    for (row_cell, col_cell), cell_names in grid.items():
        neighbours = [other for dr in (-1, 0, 1) for dc in (-1, 0, 1) for other in grid.get((row_cell + dr, col_cell + dc), [])]
        for a in cell_names:
            for b in neighbours:
                if a >= b:
                    continue
                short_name, long_name = sorted((a, b), key=lambda item: len(tokens[item]))
                small, large = tokens[short_name], tokens[long_name]
                if len(small) < 2 or not small <= large or len(large - small) > max_extra_words:
                    continue
                if (large - small) & _SITE_WORDS and not fragment(short_name):
                    continue
                distance = metres(a, b)
                if not (distance <= same_point_m or (distance <= nearby_m and len(small) >= 3)):
                    continue
                root_a, root_b = find(a), find(b)
                if root_a == root_b:
                    continue
                if not all(comparable(x, y) for x in members[root_a] for y in members[root_b]):
                    continue  # e.g. "MUHANA NORTH" and "MUHANA SOUTH" via a generic "MUHANA"
                cluster_markers = {markers[item] for item in members[root_a] | members[root_b]} - {""}
                if len(cluster_markers) > 1:  # never merge an upstream station with a downstream one
                    continue
                parent[root_b] = root_a
                members[root_a] |= members.pop(root_b)

    def preference(name: str):
        # Prefer a whole label (not starting mid-sentence, no pasted coordinates), then the most words, then the most rows.
        words = re.findall(r"[A-Z]+", name.upper())
        starts_mid_sentence = bool(words) and words[0] in _FRAGMENT_START
        return (starts_mid_sentence, bool(_COORDINATE_NUMBER.search(name)), -len(tokens[name]), -counts[name], name)

    mapping, merges = {}, []
    for root, cluster in members.items():
        if len(cluster) < 2:
            continue
        best = min(cluster, key=preference)
        # Drop a pasted coordinate from the kept name ("... VILL. 30.318 PUNJAB" -> "... VILL. PUNJAB").
        canonical = " ".join(_COORDINATE_NUMBER.sub(" ", best).split()).strip(" ,") or best
        merged = sorted(item for item in cluster if item != canonical)
        merges.append({"name": canonical, "merged": merged})
        mapping.update({item: canonical for item in merged})
    if mapping:
        for row in rows:
            name = row.get("Location")
            if name in mapping:
                row["Location"] = mapping[name]
    return sorted(merges, key=lambda item: item["name"])


def validate_rows(rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError("The CSV contains no data rows.")
    required = ("Parameter", "Value", "Location", "Latitude", "Longitude")
    missing = [name for name in required if not any(clean(row.get(name)) for row in rows)]
    if missing:
        raise ValueError("Missing required data: " + ", ".join(missing))


def count_missing_values(rows: list[dict[str, Any]]) -> int:
    """Count empty cells and conventional missing-value markers in source rows."""
    missing_markers = {"", "na", "n/a", "null", "none", "nan"}
    missing_count = 0
    for row in rows:
        parameter = clean(row.get("Parameter")).lower()
        for column, value in row.items():
            is_missing = clean(value).lower() in missing_markers
            # pH is known to be dimensionless in this water-quality schema.
            if clean(column).lower() == "unit" and parameter == "ph":
                is_missing = False
            if is_missing:
                missing_count += 1
    return missing_count


def consolidate_datasets(dataset_dir: Path = DATASET_DIR, output_path: Path = CONSOLIDATED_FILE) -> dict[str, Any]:
    """Combine source CSVs into the canonical nine-column CSV."""
    files = sorted(path for path in dataset_dir.glob("*.csv") if path.resolve() != output_path.resolve())
    combined: list[dict[str, Any]] = []
    for path in files:
        combined.extend(standardize_rows(read_csv_rows(path), path.name))
    validate_rows(combined)
    for index, row in enumerate(combined, 1):
        row["SrNo"] = index
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(combined)
    return {"output_path": str(output_path), "file_count": len(files), "record_count": len(combined)}


def number(value: Any) -> float | None:
    text = clean(value).replace(",", "")
    if not text:
        return None
    exponent = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)x10\^([0-9]+)", text)
    try:
        result = float(exponent.group(1)) * 10 ** int(exponent.group(2)) if exponent else float(text)
        return result if math.isfinite(result) else None
    except ValueError:
        return None


def display_name(location: Any) -> str:
    """Station name as the dashboard shows it."""
    return clean(location).replace("parK", "Park")


def location_group(location: str) -> str:
    """Preserve uploaded station identities without river-specific aliases."""
    return " ".join(clean(location).split())


def build_dashboard_data(
    rows: list[dict[str, Any]],
    source_name: str,
    imported: bool = False,
    column_count: int | None = None,
    missing_value_count: int = 0,
) -> dict[str, Any]:
    """Convert standardized rows into the object expected by the existing UI."""
    validate_rows(rows)
    records = []
    locations: dict[str, dict[str, Any]] = {}
    for row in rows:
        date_start, date_end, date_precision = parse_date_bounds(row.get("Date"))
        represents_month = date_precision in {"day", "month"}
        date_label = (
            date_start.strftime("%d %b %Y") if date_precision == "day"
            else date_start.strftime("%b %Y") if date_precision == "month"
            else str(date_start.year)
        )
        display_location = display_name(row.get("Location"))
        group = location_group(display_location)
        latitude, longitude = number(row.get("Latitude")), number(row.get("Longitude"))
        raw_value = clean(row.get("Value"))
        record = {
            "fileName": source_name, "location": display_location, "locationGroup": group,
            "parameter": normalize_parameter(row.get("Parameter")), "unit": clean(row.get("Unit")),
            "month": MONTH_LABELS[date_start.month] if represents_month else "",
            "monthIndex": date_start.month if represents_month else 0, "year": date_start.year,
            "date": clean(row.get("Date")), "dateStart": date_start.strftime("%d-%m-%Y"),
            "dateEnd": date_end.strftime("%d-%m-%Y"), "datePrecision": date_precision,
            "dateLabel": date_label, "sortKey": date_start.year * 100 + (date_start.month if represents_month else 0),
            "rawValue": raw_value,
            "numericValue": number(raw_value), "source": clean(row.get("Data Source")),
            "latitude": latitude, "longitude": longitude, "originalLatitude": latitude,
            "originalLongitude": longitude, "coordinateInferred": False,
            "hasCoordinates": latitude is not None and longitude is not None and -90 <= latitude <= 90 and -180 <= longitude <= 180,
        }
        records.append(record)
        if group not in locations:
            locations[group] = {
                "id": re.sub(r"[^a-z0-9]+", "-", group.lower()).strip("-"), "name": group,
                "latitude": latitude, "longitude": longitude, "originalLatitude": latitude,
                "originalLongitude": longitude, "coordinateInferred": False,
                "hasCoordinates": record["hasCoordinates"], "sources": [source_name],
            }
    records.sort(key=lambda item: (item["locationGroup"], item["parameter"], item["sortKey"], item["fileName"]))
    location_list = sorted(locations.values(), key=lambda item: item["name"])
    return {
        "generatedAt": datetime.now().isoformat(timespec="seconds"), "imported": imported,
        "activeFile": source_name,
        "summary": {"fileCount": 1, "recordCount": len(records),
                    "columnCount": column_count if column_count is not None else len(OUTPUT_COLUMNS),
                    "missingValueCount": missing_value_count,
                    "mappedLocationCount": sum(item["hasCoordinates"] for item in location_list),
                    "unmappedLocationCount": sum(not item["hasCoordinates"] for item in location_list)},
        "locations": location_list,
        "records": records,
        "analytics": {"boxplots": build_boxplot_statistics(records)},
        "quality": qualitycheck.build_quality_payload(records),
    }


def write_dashboard_data(data: dict[str, Any], output_path: Path = ROOT / "dashboard-data.js") -> Path:
    output_path.write_text("window.NCHOE_DASHBOARD_DATA = " + json.dumps(data, indent=2, ensure_ascii=False) + ";", encoding="utf-8")
    return output_path


def empty_dashboard_data() -> dict[str, Any]:
    """Return a valid dashboard payload with no active CSV or measurements."""
    return {
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        "imported": False,
        "activeFile": "",
        "summary": {
            "fileCount": 0,
            "recordCount": 0,
            "columnCount": 0,
            "missingValueCount": 0,
            "mappedLocationCount": 0,
            "unmappedLocationCount": 0,
        },
        "locations": [],
        "records": [],
        "analytics": {"boxplots": []},
        "quality": qualitycheck.build_quality_payload([]),
    }


def build_from_csv(path: Path = CONSOLIDATED_FILE, imported: bool = False) -> dict[str, Any]:
    raw_rows = read_csv_rows(path)
    rows = standardize_rows(raw_rows, path.name)
    data = build_dashboard_data(
        rows, path.name, imported,
        len(raw_rows[0]) if raw_rows else 0,
        count_missing_values(raw_rows),
    )
    write_dashboard_data(data)
    return data


def parameter_family(parameter: str) -> str:
    family = re.sub(r"\s*\((?:max|min)\)\s*$", "", normalize_parameter(parameter), flags=re.I)
    if re.fullmatch(r"t-?coliform|total coliform", family, re.I):
        return "Total Coliform"
    if re.fullmatch(r"faecal coliform|fecal coliform", family, re.I):
        return "Faecal Coliform"
    return family


def build_boxplot_statistics(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build five-number summaries by year and by calendar month in Python."""
    grouped: dict[tuple[str, str, str, int], list[float]] = defaultdict(list)
    for record in records:
        value = record.get("numericValue")
        if value is None or not math.isfinite(value):
            continue
        location = record["locationGroup"]
        parameter = parameter_family(record["parameter"])
        grouped[(location, parameter, "year", int(record["year"]))].append(float(value))
        grouped[(location, parameter, "month", int(record["monthIndex"]))].append(float(value))

    statistics = []
    for (location, parameter, grouping, key), values in grouped.items():
        sample = np.asarray(values, dtype=float)
        minimum, q1, median, q3, maximum = np.percentile(sample, [0, 25, 50, 75, 100])
        statistics.append({
            "location": location,
            "parameter": parameter,
            "grouping": grouping,
            "key": key,
            "label": str(key) if grouping == "year" else MONTH_LABELS[key],
            "count": len(values),
            "min": round(float(minimum), 4),
            "q1": round(float(q1), 4),
            "median": round(float(median), 4),
            "q3": round(float(q3), 4),
            "max": round(float(maximum), 4),
        })
    return sorted(statistics, key=lambda item: (
        item["location"], item["parameter"], item["grouping"], item["key"]
    ))


if __name__ == "__main__":
    result = consolidate_datasets()
    dashboard = build_from_csv()
    print(f"Created {result['output_path']} with {dashboard['summary']['recordCount']} records.")
