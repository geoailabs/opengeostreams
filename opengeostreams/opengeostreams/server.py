"""Python HTTP server and CSV-upload API for the OpenGeoStreams dashboard."""

from __future__ import annotations

import copy
import io
import csv
import re
import tempfile
from collections import OrderedDict
from functools import lru_cache
import json
import os
import ssl
import threading
import time
import uuid
import urllib.error
import urllib.parse
import urllib.request
from email.parser import BytesParser
from email.policy import default
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .pipeline import ROOT, empty_dashboard_data


HOST = "127.0.0.1"
PORT = 4173
MAX_UPLOAD_BYTES = 10 * 1024 * 1024


def create_ssl_context() -> ssl.SSLContext:
    """Use certifi when available, with the operating-system store as fallback."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def fetch_weather_data(parameters: dict[str, str], timeout: int = 20) -> tuple[int, str, bytes]:
    """Fetch historical weather JSON for the local proxy endpoint."""
    return _fetch_weather_cached(tuple(sorted(parameters.items())), timeout, int(time.monotonic() // 900))


@lru_cache(maxsize=128)
def _fetch_weather_cached(items, timeout, bucket):
    parameters = dict(items)
    upstream_query = urllib.parse.urlencode({
        **parameters,
        "daily": "precipitation_sum,weather_code",
        "timezone": "auto",
    })
    request = urllib.request.Request(
        "https://archive-api.open-meteo.com/v1/archive?" + upstream_query,
        headers={"User-Agent": "OpenGeoStreams-dashboard/1.0", "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout, context=create_ssl_context()) as response:
        return response.status, response.headers.get_content_type(), response.read()


def json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def extract_uploaded_csv(headers: Any, body: bytes) -> tuple[str, bytes]:
    """Extract the first CSV part from a multipart/form-data request."""
    content_type = headers.get("Content-Type", "")
    if "multipart/form-data" not in content_type:
        raise ValueError("Upload must use multipart/form-data.")
    message = BytesParser(policy=default).parsebytes(
        f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode() + body
    )
    for part in message.iter_parts():
        filename = part.get_filename()
        if filename:
            safe_name = Path(filename).name
            return safe_name, part.get_payload(decode=True) or b""
    raise ValueError("No file was included.")


def normalize_uploaded_table(frame):
    """Reshape station-per-row water-quality tables into measurement rows."""
    import pandas as pd
    frame = frame.copy()
    frame.columns = [str(column).strip() for column in frame.columns]
    aliases = {"name of sampling point": "Location", "date and timestamp": "Date", "source": "Data Source"}
    frame = frame.rename(columns={column: aliases.get(column.casefold(), column) for column in frame.columns})
    if "Parameter" not in frame and "Location" in frame:
        parameters = {
            "temperature", "dissolved oxygen", "ph", "conductivity", "bod",
            "faecal coliform", "fecal coliform", "total coliform", "t.coliform",
            "nitrate+nitrite-n", "total kjeldahl nitrogen", "ammonical-n",
            "total organic nitrogen", "nitraten", "nitriten", "phosphate",
            "turbidity", "total dissolved solids",
        }
        measurements = []
        for column in frame.columns:
            name = re.sub(r"\s*\([^)]*\)|\s*\[[^]]*\]", "", column).strip()
            if name.casefold() in parameters:
                unit = re.search(r"\(([^)]*)\)", column)
                measurements.append((column, name, unit.group(1) if unit else ""))
        if not measurements:
            raise ValueError("No recognized water-quality parameter columns were found.")
        records = []
        metadata = [column for column in ("Location", "Latitude", "Longitude", "Date", "Year", "Month", "Data Source") if column in frame]
        for _, row in frame.iterrows():
            if pd.isna(row["Location"]) or not str(row["Location"]).strip():
                continue
            base = {column: row[column] for column in metadata}
            for column, name, unit in measurements:
                value = row[column]
                if pd.isna(value) or not str(value).strip():
                    continue
                # Preserve reported intervals as endpoints, never as invented averages.
                interval = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*[-\u2013]\s*(\d+(?:\.\d+)?)\s*", str(value))
                if interval:
                    low, high = sorted(map(float, interval.groups()))
                    records.extend({**base, "Parameter": name + qualifier, "Unit": unit, "Value": endpoint}
                                   for qualifier, endpoint in ((" (Min)", low), (" (Max)", high)))
                else:
                    records.append({**base, "Parameter": name, "Unit": unit, "Value": value})
        frame = pd.DataFrame(records)
    if "Date" in frame:
        frame["Date"] = frame["Date"].map(lambda value: value.strftime("%d-%m-%Y") if hasattr(value, "strftime") and pd.notna(value) else value)
    # Annual reports often supply the year only in the source document name.
    needs_year = frame["Date"].isna() | frame["Date"].astype(str).str.strip().eq("") if "Date" in frame else pd.Series(True, index=frame.index)
    if "Data Source" in frame and needs_year.any():
        source_year = frame["Data Source"].astype(str).str.extract(r"((?:19|20)\d{2})", expand=False)
        if "Year" not in frame and source_year[needs_year].notna().any():
            frame["Year"] = source_year.where(needs_year)
        elif "Year" in frame:
            frame["Year"] = frame["Year"].fillna(source_year.where(needs_year))
    return frame


def convert_upload_to_csv(filename: str, payload: bytes, *, include_metadata=False):
    """Validate supported tables and normalize non-CSV uploads to UTF-8 CSV."""
    import pandas as pd
    suffix = Path(filename).suffix.lower()
    if suffix not in {".csv", ".tsv", ".txt", ".json", ".xlsx", ".xls"}:
        raise ValueError("Unsupported file type. Choose CSV, TSV, delimited TXT, JSON, or Excel (.xlsx/.xls).")
    try:
        if suffix in {".xlsx", ".xls"}:
            frame = pd.read_excel(io.BytesIO(payload), sheet_name=0)
        else:
            text = payload.decode("utf-8-sig")
            if "\x00" in text:
                raise ValueError("Binary content is not a text table.")
            if suffix == ".json":
                frame = pd.read_json(io.StringIO(text))
            else:
                delimiter = "\t" if suffix == ".tsv" else csv.Sniffer().sniff(text[:65536], delimiters=",;\t|").delimiter
                frame = pd.read_csv(io.StringIO(text), sep=delimiter, dtype=str)
        source_columns = list(map(str, frame.columns))
        frame = normalize_uploaded_table(frame)
        if frame.empty or len(frame.columns) < 2:
            raise ValueError("The file must contain a table with headers and data rows.")
    except ImportError as error:
        raise ValueError("Excel import requires openpyxl and xlrd. Install the dashboard dependencies.") from error
    except Exception as error:
        raise ValueError(f"Cannot read {filename} as a table: {error}") from error
    result = (Path(filename).with_suffix(".csv").name, frame.to_csv(index=False).encode("utf-8"))
    return (*result, {"sourceColumnCount": len(source_columns), "sourceColumns": source_columns}) if include_metadata else result


def process_uploaded_csv(filename: str, payload: bytes, rows: int = 400):
    """Import through the public library without writing dashboard assets."""
    from .dataset import load_csv
    filename, payload, metadata = convert_upload_to_csv(filename, payload, include_metadata=True)
    with tempfile.TemporaryDirectory(prefix="opengeostreams-upload-") as folder:
        path = Path(folder) / Path(filename).name
        path.write_bytes(payload)
        dataset = load_csv(path, rows=rows)
    dataset._import_metadata = metadata
    dataset.path = None  # The uploaded dataset is now entirely in memory.
    return dataset


def dataset_entry(dataset, name: str) -> dict[str, Any]:
    return {"name": name, "dataset": dataset, "figures": OrderedDict(),
            "figure_lock": threading.Lock(), "chart_locks": {kind: threading.Lock() for kind in ("trend", "distribution", "stream", "interpolation")},
            "interpolation_lock": threading.Lock()}


def ensure_interpolation(entry):
    with entry["interpolation_lock"]:
        dataset = entry["dataset"]
        if dataset._interpolation is None:
            dataset.interpolate()
        return dataset._interpolation


def build_figure(entry, query):
    """Use library figures with the same station/family/time filters as the UI."""
    from . import pipeline
    kind = query.get("kind", "trend")
    if kind not in {"trend", "distribution", "stream", "interpolation"}:
        raise ValueError("Unknown chart type.")
    key = tuple(sorted(query.items()))
    with entry["chart_locks"][kind]:
        with entry["figure_lock"]:
            if key in entry["figures"]:
                entry["figures"].move_to_end(key)
                return entry["figures"][key]
        dataset = entry["dataset"]
        parameter = query.get("parameter") or None
        year = query.get("year", "all")
        year = None if year == "all" else int(year)
        if kind == "interpolation":
            ensure_interpolation(entry)
            figure = dataset.plot(parameter=parameter, year=year)
        else:
            view = copy.copy(dataset)
            frame = dataset.data.copy()
            frame["ReportedParameter"] = frame["Parameter"]
            frame["Parameter"] = frame["Parameter"].map(pipeline.parameter_family)
            frame["Location"] = frame["Location"].map(pipeline.location_group)
            location = query.get("location")
            if kind != "stream" and location:
                frame = frame[frame["Location"] == location]
            bounds = frame["Date"].map(pipeline.parse_date_bounds)
            if year is not None:
                frame = frame.loc[bounds.map(lambda value: value[0].year == year)]
            month = query.get("month")
            if month:
                month = int(month)
                if not 1 <= month <= 12:
                    raise ValueError("month must be between 1 and 12.")
                month_bounds = frame["Date"].map(pipeline.parse_date_bounds)
                frame = frame.loc[month_bounds.map(
                    lambda value: value[2] != "year" and value[0].month == month
                )]
            view.data = frame
            if kind == "trend":
                figure = view.plot_trend(parameter=parameter)
            elif kind == "distribution":
                figure = view.plot_distribution(parameter=parameter, grouping=query.get("grouping", "year"))
            else:
                figure = view.plot_stream(parameter=parameter)
        if kind != "interpolation" and "ReportedParameter" in view.data:
            has_ranges = view.data["ReportedParameter"].str.contains(r"\((?:Min|Max)\)$", case=False, regex=True).any()
            if has_ranges:
                figure.update_layout(meta={**(figure.layout.meta or {}), "rangeNote": "Reported Min/Max endpoints are included. Distribution statistics describe endpoints, not original samples; stream colours show their mean."})
        result = json.loads(figure.to_json())
        with entry["figure_lock"]:
            if not (result.get("layout", {}).get("meta", {}).get("precipitationUnavailable")):
                entry["figures"][key] = result
            if len(entry["figures"]) > 128:
                entry["figures"].popitem(last=False)
        return result


@lru_cache(maxsize=1)
def plotly_javascript():
    from plotly.offline import get_plotlyjs
    return get_plotlyjs().encode("utf-8")




class DashboardHandler(SimpleHTTPRequestHandler):
    """Serve the frontend and library-backed dataset/visualization endpoints."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def end_headers(self) -> None:
        # Uploaded data must be visible immediately after the browser reloads.
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def send_json(self, status: int, payload: dict[str, Any]) -> None:
        content = json_bytes(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)

    def do_POST(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        route = urllib.parse.urlparse(self.path).path
        if route == "/upload-csv":
            self.handle_upload()
        elif route == "/reset-data":
            with self.server.dataset_lock:
                data = empty_dashboard_data()
                self.server.datasets.clear()
                self.server.active_dataset = None
            self.send_json(HTTPStatus.OK, {"ok": True, "summary": data["summary"]})
        elif route == "/select-csv":
            self.handle_select_csv()
        else:
            self.send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "Endpoint not found."})

    def do_GET(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        route = urllib.parse.urlparse(self.path).path
        if route == "/plotly.min.js":
            self.send_content("application/javascript", plotly_javascript())
            return
        if route == "/dashboard-data.js":
            with self.server.dataset_lock:
                active = self.server.active_dataset
                entry = self.server.datasets.get(active)
                data = dict(entry["dataset"]._dashboard_data) if entry else empty_dashboard_data()
                if entry:
                    data["summary"] = entry["dataset"].summary
                data["datasetId"] = active
            self.send_content("application/javascript", b"window.NCHOE_DASHBOARD_DATA = " + json_bytes(data) + b";")
            return
        if route in {"/api/figure", "/api/interpolation"}:
            self.handle_visualization(route)
            return
        if urllib.parse.urlparse(self.path).path == "/datasets":
            with self.server.dataset_lock:
                entries = [{"id": key, "fileName": value["name"]}
                           for key, value in self.server.datasets.items()]
                active = self.server.active_dataset
            self.send_json(HTTPStatus.OK, {"datasets": entries, "activeId": active})
            return
        if urllib.parse.urlparse(self.path).path == "/weather-history":
            self.handle_weather()
            return
        super().do_GET()

    def handle_upload(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > MAX_UPLOAD_BYTES:
                raise ValueError("CSV must be between 1 byte and 10 MB.")
            filename, payload = extract_uploaded_csv(self.headers, self.rfile.read(length))
            with self.server.dataset_lock:
                row_limit = int(urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get("rows", ["400"])[0])
                dataset = process_uploaded_csv(filename, payload, rows=row_limit)
                data = {"summary": dataset.summary}
                dataset_id = uuid.uuid4().hex
                self.server.datasets[dataset_id] = dataset_entry(dataset, filename)
                self.server.active_dataset = dataset_id
            self.send_json(HTTPStatus.OK, {
                "ok": True, "fileName": filename, "summary": data["summary"],
                "message": (f"Loaded {data['summary']['recordCount']} rows and "
                            f"{data['summary']['columnCount']} columns from {filename}; "
                            f"found {data['summary']['missingValueCount']} missing values."),
            })
        except (ValueError, TypeError) as error:
            self.send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(error)})
        except Exception as error:  # keep the server responsive and return a useful error
            self.log_error("Upload failed: %s", error)
            self.send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "error": "Could not process the CSV."})

    def handle_select_csv(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 1024:
                raise ValueError("Invalid CSV selection.")
            selection = json.loads(self.rfile.read(length))
            if not isinstance(selection, dict) or not isinstance(selection.get("id"), str):
                raise ValueError("Choose an imported CSV.")
            with self.server.dataset_lock:
                entry = self.server.datasets.get(selection["id"])
                if entry is None:
                    raise ValueError("That CSV is no longer available. Please import it again.")
                if self.server.active_dataset != selection["id"]:
                    self.server.active_dataset = selection["id"]
            self.send_json(HTTPStatus.OK, {"ok": True})
        except (ValueError, TypeError) as error:
            self.send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(error)})
        except Exception as error:
            self.log_error("CSV selection failed: %s", error)
            self.send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "error": "Could not switch CSV."})


    def send_content(self, content_type, content):
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def handle_visualization(self, route):
        try:
            query = {key: values[0] for key, values in urllib.parse.parse_qs(
                urllib.parse.urlparse(self.path).query).items()}
            with self.server.dataset_lock:
                entry = self.server.datasets.get(query.pop("id", ""))
            if entry is None:
                self.send_json(HTTPStatus.NOT_FOUND, {"error": "CSV no longer available. Reload the dashboard."})
                return
            result = ensure_interpolation(entry) if route == "/api/interpolation" else build_figure(entry, query)
            self.send_json(HTTPStatus.OK, result)
        except (ValueError, TypeError) as error:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
        except Exception as error:
            self.log_error("Visualization failed: %s", error)
            self.send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "Could not generate visualization."})

    def handle_weather(self) -> None:
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        required = ("latitude", "longitude", "start_date", "end_date")
        if any(not query.get(key) for key in required):
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "Missing weather request fields."})
            return
        try:
            status, content_type, content = fetch_weather_data({key: query[key][0] for key in required})
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            self.send_json(error.code, {"error": "Weather API rejected the request.", "detail": detail})
        except (urllib.error.URLError, TimeoutError) as error:
            reason = getattr(error, "reason", error)
            self.send_json(HTTPStatus.BAD_GATEWAY, {
                "error": "The Python server could not connect to Open-Meteo.",
                "detail": str(reason),
            })


def create_server(host: str = HOST, port: int = PORT, *, dataset=None) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), DashboardHandler)
    server.datasets = {}
    server.active_dataset = None
    server.dataset_lock = threading.Lock()
    if dataset is not None:
        dataset_id = uuid.uuid4().hex
        server.datasets[dataset_id] = dataset_entry(dataset, dataset._dashboard_data.get("activeFile") or "DataFrame")
        server.active_dataset = dataset_id
    return server


def run_server(host: str = HOST, port: int = PORT) -> None:
    server = create_server(host, port)
    print(f"OpenGeoStreams dashboard running at http://{host}:{port}")
    print("Use the CSV control in the dashboard to filter all views to an uploaded file.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping dashboard server.")
    finally:
        server.server_close()


if __name__ == "__main__":
    run_server(port=int(os.environ.get("NCHOE_PORT", PORT)))
