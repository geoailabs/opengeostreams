"""CSV preparation and geographic interpolation for OpenGeoStreams."""

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
GRID_COLUMNS = 192
GRID_ROWS = 192
MAX_DISTANCE_KM = 8.0
MAX_NEIGHBORS = 8
MIN_INTERPOLATION_POINTS = 1
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
    return standardized


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
        display_location = clean(row.get("Location")).replace("parK", "Park")
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


def distance_km(left: dict[str, Any], right: dict[str, Any]) -> float:
    radius = 6371.0
    lat1, lat2 = math.radians(left["latitude"]), math.radians(right["latitude"])
    delta_lat = math.radians(right["latitude"] - left["latitude"])
    delta_lon = math.radians(right["longitude"] - left["longitude"])
    value = math.sin(delta_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    return radius * 2 * math.atan2(math.sqrt(value), math.sqrt(max(0.0, 1 - value)))


def interpolation_model(points: list[dict[str, Any]], max_distance_km: float = MAX_DISTANCE_KM) -> dict[str, float]:
    values = np.asarray([point["value"] for point in points], dtype=float)
    sample_variance = float(np.var(values, ddof=1)) if len(values) > 1 else 0.0
    total_sill = sample_variance if sample_variance > 0 else max(abs(float(np.mean(values))) * 0.01, 1.0)
    pair_distances = [distance_km(left, right) for index, left in enumerate(points) for right in points[index + 1:]]
    nearest = [
        min(distance_km(point, other) for other in points if other is not point)
        for point in points
        if len(points) > 1
    ]
    positive_nearest = [value for value in nearest if value > 0]
    average_nearest = (
        sum(positive_nearest) / len(positive_nearest)
        if positive_nearest else max_distance_km / 1.75
    )
    nugget = total_sill * 0.05
    return {
        "maxDistanceKm": max_distance_km,
        "rangeKm": max(max(pair_distances, default=0.0) * 0.6, 0.75),
        "supportDistanceKm": min(max_distance_km, max(average_nearest * 1.75, 0.9)),
        "nugget": nugget,
        "partialSill": max(total_sill - nugget, total_sill * 0.25),
        "sill": nugget + max(total_sill - nugget, total_sill * 0.25),
    }


def covariance(distance: float, model: dict[str, float]) -> float:
    if distance <= 0:
        return model["sill"]
    return model["partialSill"] * math.exp(-((distance / model["rangeKm"]) ** 2))


def interpolate_ordinary_kriging(points: list[dict[str, Any]], model: dict[str, float], target: dict[str, float]) -> tuple[float | None, float | None]:
    neighbors = sorted(((distance_km(point, target), point) for point in points), key=lambda item: item[0])
    if neighbors and neighbors[0][0] > model["supportDistanceKm"]:
        return None, neighbors[0][0]
    if neighbors and neighbors[0][0] < 0.0001:
        return neighbors[0][1]["value"], 0.0
    nearby = [item for item in neighbors if item[0] <= model["maxDistanceKm"]][:MAX_NEIGHBORS]
    if len(nearby) < MIN_INTERPOLATION_POINTS:
        nearby = neighbors[:MAX_NEIGHBORS]
    if len(nearby) < MIN_INTERPOLATION_POINTS:
        return None, nearby[0][0] if nearby else None
    size = len(nearby)
    matrix = np.zeros((size + 1, size + 1), dtype=float)
    vector = np.zeros(size + 1, dtype=float)
    for row in range(size):
        for column in range(size):
            matrix[row, column] = covariance(distance_km(nearby[row][1], nearby[column][1]), model)
        matrix[row, size] = matrix[size, row] = 1.0
        vector[row] = covariance(nearby[row][0], model)
    vector[size] = 1.0
    try:
        weights = np.linalg.solve(matrix, vector)[:size]
        value = float(sum(weights[index] * nearby[index][1]["value"] for index in range(size)))
        if not math.isfinite(value) or abs(value) > 1e15:
            raise np.linalg.LinAlgError
    except np.linalg.LinAlgError:
        inverse = [1 / max(item[0], 0.001) ** 2 for item in nearby]
        value = sum(weight * item[1]["value"] for weight, item in zip(inverse, nearby)) / sum(inverse)
    return value, nearby[0][0]


def load_river_mask(path: Path | None = None) -> dict[str, Any] | None:
    if path is None:
        return None
    path = Path(path)
    if not path.is_file():
        raise ValueError(f"River mask file not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("rows") != GRID_ROWS or payload.get("cols") != GRID_COLUMNS:
        raise ValueError("River mask dimensions do not match the interpolation grid.")
    if len(payload.get("maskValues", [])) != GRID_ROWS * GRID_COLUMNS:
        raise ValueError("River mask has an invalid number of cells.")
    return payload


def interpolation_extent(records: list[dict[str, Any]], river_mask: dict[str, Any] | None) -> dict[str, float] | None:
    if river_mask:
        return river_mask["extent"]
    mapped = [record for record in records if record["hasCoordinates"]]
    if not mapped:
        return None
    latitudes = [record["latitude"] for record in mapped]
    longitudes = [record["longitude"] for record in mapped]
    lat_span, lon_span = max(max(latitudes) - min(latitudes), 0.01), max(max(longitudes) - min(longitudes), 0.01)
    return {"minLatitude": max(-90, min(latitudes) - lat_span * 0.08), "maxLatitude": min(90, max(latitudes) + lat_span * 0.08),
            "minLongitude": max(-180, min(longitudes) - lon_span * 0.08), "maxLongitude": min(180, max(longitudes) + lon_span * 0.08)}


def build_interpolation_grid(points: list[dict[str, Any]], extent: dict[str, float], river_mask: dict[str, Any] | None, max_distance_km: float = MAX_DISTANCE_KM) -> dict[str, Any]:
    model = interpolation_model(points, max_distance_km)
    values: list[float | None] = [None] * (GRID_ROWS * GRID_COLUMNS)
    active = {index for index, weight in enumerate(river_mask["maskValues"]) if float(weight or 0) > 0} if river_mask else set(range(len(values)))
    lat_step = (extent["maxLatitude"] - extent["minLatitude"]) / (GRID_ROWS - 1)
    lon_step = (extent["maxLongitude"] - extent["minLongitude"]) / (GRID_COLUMNS - 1)
    # Always anchor observed samples even when the narrow river mask misses their cell.
    for point in points:
        row = round((extent["maxLatitude"] - point["latitude"]) / lat_step)
        column = round((point["longitude"] - extent["minLongitude"]) / lon_step)
        for row_offset in (-1, 0, 1):
            for column_offset in (-1, 0, 1):
                next_row, next_column = row + row_offset, column + column_offset
                if 0 <= next_row < GRID_ROWS and 0 <= next_column < GRID_COLUMNS:
                    active.add(next_row * GRID_COLUMNS + next_column)
    for index in active:
        row, column = divmod(index, GRID_COLUMNS)
        target = {"latitude": extent["maxLatitude"] - row * lat_step, "longitude": extent["minLongitude"] + column * lon_step}
        value, nearest = interpolate_ordinary_kriging(points, model, target)
        if value is not None and nearest is not None and nearest <= model["supportDistanceKm"]:
            values[index] = round(value, 4)
    for point in points:
        row = max(0, min(GRID_ROWS - 1, round((extent["maxLatitude"] - point["latitude"]) / lat_step)))
        column = max(0, min(GRID_COLUMNS - 1, round((point["longitude"] - extent["minLongitude"]) / lon_step)))
        values[row * GRID_COLUMNS + column] = round(point["value"], 4)
    return {"extent": extent, "columns": GRID_COLUMNS, "rows": GRID_ROWS, "maxDistanceKm": max_distance_km,
            "variogram": {key: round(value, 6) for key, value in model.items()},
            "riverMaskApplied": river_mask is not None, "values": values}


def collect_interpolation_surfaces(records: list[dict[str, Any]], extent: dict[str, float], river_mask: dict[str, Any] | None, yearly: bool, max_distance_km: float = MAX_DISTANCE_KM) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        if record["hasCoordinates"] and record["numericValue"] is not None and record["parameter"]:
            period = str(record["year"]) if yearly else "all_years"
            grouped[(period, parameter_family(record["parameter"]))].append(record)
    surfaces = []
    for (period, parameter), group in grouped.items():
        by_location: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for record in group:
            by_location[(record["latitude"], record["longitude"])].append(record)
        points = [{"location": samples[0]["locationGroup"], "latitude": samples[0]["latitude"], "longitude": samples[0]["longitude"],
                   "value": sum(sample["numericValue"] for sample in samples) / len(samples), "sampleCount": len(samples)}
                  for location, samples in by_location.items()]
        if len(points) < MIN_INTERPOLATION_POINTS:
            continue
        points.sort(key=lambda point: point["location"])
        surfaces.append({"id": re.sub(r"[^a-z0-9]+", "-", f"{period}:{parameter}".lower()).strip("-"),
                         "parameter": parameter, "parameterFamily": parameter, "unit": clean(group[0]["unit"]),
                         "year": None if period == "all_years" else int(period), "period": period,
                         "method": "Ordinary Kriging" if len(points) > 1 else "Single-station value (no spatial interpolation)",
                         "pointCount": len(points), "samplePoints": points,
                         "grid": build_interpolation_grid(points, interpolation_extent(group, river_mask), river_mask, max_distance_km)})
    return sorted(surfaces, key=lambda surface: (str(surface["period"]), surface["parameter"]))


def build_interpolation_data(dashboard_data: dict[str, Any], output_path: Path | None = None, *, max_distance_km: float = MAX_DISTANCE_KM, river_mask_path: Path | None = None) -> dict[str, Any]:
    """Generate all-year and yearly ordinary-kriging surfaces in Python."""
    if isinstance(max_distance_km, bool) or not isinstance(max_distance_km, (int, float)) or not math.isfinite(max_distance_km) or max_distance_km <= 0:
        raise ValueError("max_distance_km must be a positive finite number.")
    records = dashboard_data.get("records", [])
    river_mask = load_river_mask(river_mask_path) if river_mask_path is not None else None
    if river_mask:
        boundary = river_mask["extent"]
        if any(record["hasCoordinates"] and not (
            boundary["minLatitude"] <= record["latitude"] <= boundary["maxLatitude"] and
            boundary["minLongitude"] <= record["longitude"] <= boundary["maxLongitude"]
        ) for record in records):
            raise ValueError("The supplied river mask does not cover all mapped stations.")
    extent = interpolation_extent(records, river_mask)
    payload = {"generatedAt": datetime.now().isoformat(timespec="seconds"),
               "sourceRecordCount": len(records), "mappedLocationCount": dashboard_data["summary"]["mappedLocationCount"],
               "method": {"type": "Ordinary Kriging", "variogramModel": "gaussian", "maxDistanceKm": max_distance_km,
                          "maxNeighbors": MAX_NEIGHBORS, "nuggetRatio": 0.05, "gridColumns": GRID_COLUMNS,
                          "gridRows": GRID_ROWS, "minimumPointCount": MIN_INTERPOLATION_POINTS},
               "extent": extent,
               "riverMask": ({"generatedFrom": river_mask.get("generatedFrom"), "activeCellCount": river_mask.get("activeCellCount"),
                              "widthStats": river_mask.get("widthStats")} if river_mask else None),
               "surfaces": {"allYears": [], "yearly": []}}
    if records and extent is not None:
        payload["surfaces"]["allYears"] = collect_interpolation_surfaces(records, extent, river_mask, False, max_distance_km)
        payload["surfaces"]["yearly"] = collect_interpolation_surfaces(records, extent, river_mask, True, max_distance_km)
    if output_path is not None:
        output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return payload


if __name__ == "__main__":
    result = consolidate_datasets()
    dashboard = build_from_csv()
    print(f"Created {result['output_path']} with {dashboard['summary']['recordCount']} records.")
