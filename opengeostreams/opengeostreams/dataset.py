"""Pandas-style public interface for river water-quality CSV files."""

from __future__ import annotations

import csv
import tempfile
import threading
import webbrowser
from itertools import islice
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from . import pipeline


MAX_PAGE_SIZE = 400


class RiverDataset:
    """A processed river dataset with analysis, plotting, and dashboard methods."""

    def __init__(self, csv_path: str | Path, *, rows: int = MAX_PAGE_SIZE) -> None:
        self.path = Path(csv_path).expanduser().resolve()
        if not self.path.is_file():
            raise FileNotFoundError(f"CSV file not found: {self.path}")
        if self.path.suffix.lower() != ".csv":
            raise ValueError("Opengeostreams accepts CSV files only.")
        self._validate_rows(rows)
        self.total_rows = self._count_rows()
        self._row_limit: int = rows
        self._dashboard_data: dict[str, Any] = {}
        self._interpolation: dict[str, Any] | None = None
        self.data = pd.DataFrame()
        self._reload()

    @staticmethod
    def _validate_rows(rows: int) -> None:
        if not isinstance(rows, int) or isinstance(rows, bool) or rows < 1:
            raise ValueError("rows must be a positive integer.")

    def _count_rows(self) -> int:
        with self.path.open("r", encoding="utf-8-sig", newline="") as handle:
            return max(sum(1 for _ in csv.reader(handle)) - 1, 0)

    def _read_rows(self) -> list[dict[str, str]]:
        with self.path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            source = islice(reader, self._row_limit)
            return [
                {pipeline.clean(key): pipeline.clean(value) for key, value in row.items()}
                for row in source
            ]

    def _reload(self) -> None:
        raw = self._read_rows()
        self._set_data(raw, self.path.name)

    def _set_data(self, raw: list[dict[str, Any]], source_name: str) -> None:
        columns = list(raw[0]) if raw else []
        self._missing_by_column = {column: sum(
            pipeline.clean(row.get(column)).lower() in {"", "na", "n/a", "null", "none", "nan"}
            and not (column.lower() == "unit" and pipeline.clean(row.get("Parameter")).lower() == "ph")
            for row in raw) for column in columns}
        processed = pipeline.standardize_rows(raw, source_name)
        pipeline.validate_rows(processed)
        self._dashboard_data = pipeline.build_dashboard_data(
            processed,
            source_name,
            imported=True,
            column_count=len(raw[0]) if raw else 0,
            missing_value_count=pipeline.count_missing_values(raw),
        )
        self.data = pd.DataFrame(processed)
        self.data["NumericValue"] = pd.to_numeric(self.data["Value"], errors="coerce")
        self.data["Latitude"] = pd.to_numeric(self.data["Latitude"], errors="coerce")
        self.data["Longitude"] = pd.to_numeric(self.data["Longitude"], errors="coerce")
        self._interpolation = None

    def __len__(self) -> int:
        return len(self.data)

    @property
    def loaded_rows(self) -> int:
        return len(self)

    @property
    def remaining_rows(self) -> int:
        return max(self.total_rows - self.loaded_rows, 0)

    @property
    def has_more(self) -> bool:
        return self.remaining_rows > 0

    @property
    def summary(self) -> dict[str, Any]:
        return {
            **self._dashboard_data["summary"],
            **getattr(self, "_import_metadata", {}),
            "missingByColumn": self._missing_by_column,
            "loadedRows": self.loaded_rows,
            "totalRows": self.total_rows,
            "remainingRows": self.remaining_rows,
            "parameterCount": int(self.data["Parameter"].nunique()),
            "locationCount": int(self.data["Location"].nunique()),
        }

    def head(self, rows: int = 5) -> pd.DataFrame:
        """Return the first processed rows, like pandas.DataFrame.head()."""
        return self.data.drop(columns=["NumericValue"], errors="ignore").head(rows).copy()

    def describe(self, parameter: str | None = None) -> pd.DataFrame:
        """Return descriptive statistics for all or one numeric parameter."""
        frame = self.data
        if parameter:
            frame = frame[frame["Parameter"].astype(str).str.casefold() == pipeline.normalize_parameter(parameter).casefold()]
        return frame.groupby("Parameter")["NumericValue"].describe()

    def interpolate(self, *, max_distance_km: float = 8.0, river_mask_path: str | Path | None = None) -> tuple["RiverDataset", dict[str, Any]]:
        """Interpolate numeric measurements and return ``(data, summary)``."""
        self._interpolation = pipeline.build_interpolation_data(
            self._dashboard_data, output_path=None, max_distance_km=max_distance_km, river_mask_path=river_mask_path
        )
        all_years = self._interpolation["surfaces"]["allYears"]
        yearly = self._interpolation["surfaces"]["yearly"]
        result = {
            "method": self._interpolation["method"]["type"],
            "sourceRows": self.loaded_rows,
            "mappedLocations": self._interpolation["mappedLocationCount"],
            "allYearSurfaces": len(all_years),
            "yearlySurfaces": len(yearly),
            "parameters": sorted({item["parameter"] for item in all_years}),
        }
        return self, result

    def _output(self, figure: Any, save_path: str | Path | None):
        if save_path is None:
            return figure
        destination = Path(save_path).expanduser().resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.suffix.lower() in {".html", ".htm"}:
            figure.write_html(destination, include_plotlyjs=True)
        else:
            try:
                figure.write_image(destination)
            except Exception as error:
                raise RuntimeError(
                    "Image export failed. Install opengeostreams[images] and Chrome/Chromium; see the underlying error for details."
                ) from error
        return figure

    def plot(self, save_path: str | Path | None = None, **kwargs: Any):
        """Plot the interpolation result, running interpolation when necessary."""
        from .plots import interpolation_figure
        if self._interpolation is None:
            self.interpolate()
        return self._output(interpolation_figure(self, **kwargs), save_path)

    def plot_trend(self, save_path: str | Path | None = None, **kwargs: Any):
        """Plot the combined parameter and precipitation timeline."""
        from .plots import trend_figure
        return self._output(trend_figure(self, **kwargs), save_path)

    def plot_distribution(self, save_path: str | Path | None = None, **kwargs: Any):
        """Plot the yearly or monthly parameter distribution."""
        from .plots import distribution_figure
        return self._output(distribution_figure(self, **kwargs), save_path)

    def plot_stream(self, save_path: str | Path | None = None, **kwargs: Any):
        """Plot yearly measurements across monitoring locations."""
        from .plots import stream_figure
        return self._output(stream_figure(self, **kwargs), save_path)

    def plot_map(self, save_path: str | Path | None = None, *,
                 open_browser: bool = True, **kwargs: Any):
        """Return an interactive map; optionally save it as HTML or PNG."""
        from .plots import map_figure
        if self._interpolation is None:
            self.interpolate()
        map_object = map_figure(self, **kwargs)
        destination = (
            Path(save_path).expanduser().resolve()
            if save_path is not None
            else Path(tempfile.gettempdir()) / "opengeostreams-map.html"
        )
        if destination.suffix.lower() not in {".html", ".htm", ".png"}:
            raise ValueError("Maps must be saved as .html or .png files.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.suffix.lower() == ".png":
            from .plots import save_map_png
            save_map_png(map_object, destination)
        else:
            map_object.save(str(destination))
        map_object.path = destination
        if open_browser:
            webbrowser.open(destination.as_uri())
        return map_object

    def dashboard(self, *, host: str = "127.0.0.1", port: int = 4173,
                  open_browser: bool = True):
        """Start the Plotly.js/Leaflet dashboard backed by this dataset."""
        from . import server
        httpd = server.create_server(host, port, dataset=self)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        httpd.thread = thread
        httpd.url = f"http://{host}:{port}"
        if open_browser:
            webbrowser.open(httpd.url)
        return httpd


def load_csv(csv_path: str | Path, *, rows: int = MAX_PAGE_SIZE) -> RiverDataset:
    """Load the first ``rows`` CSV records (default: 400), excluding the header.

    Accepts any positive integer.
    Limits larger than the file import all available records.
    """
    return RiverDataset(csv_path, rows=rows)


def from_dataframe(frame: pd.DataFrame) -> RiverDataset:
    """Create an independent dataset from all DataFrame rows, using the CSV schema.

    Revalidates data and rebuilds analysis metadata. Missing pandas values are
    treated as empty CSV fields. Extra columns are omitted during standardization.
    """
    if not isinstance(frame, pd.DataFrame):
        raise TypeError("frame must be a pandas DataFrame.")
    if not frame.columns.is_unique:
        raise ValueError("DataFrame column names must be unique.")
    raw_frame = frame.drop(columns=["NumericValue"], errors="ignore")
    raw = raw_frame.astype(object).where(raw_frame.notna(), "").to_dict(orient="records")
    dataset = RiverDataset.__new__(RiverDataset)
    dataset.path = None
    dataset._row_limit = len(raw)
    dataset._set_data(raw, "dataframe")
    dataset.total_rows = dataset.loaded_rows
    return dataset


def concat(datasets: Iterable[RiverDataset | pd.DataFrame]) -> RiverDataset:
    """Combine loaded dataset rows or DataFrames into a new RiverDataset.

    Preserves input order and duplicate measurements, resets row numbering,
    and leaves inputs unchanged. Unloaded CSV rows are not read.
    """
    frames = []
    for item in datasets:
        if isinstance(item, RiverDataset):
            frames.append(item.data)
        elif isinstance(item, pd.DataFrame):
            frames.append(from_dataframe(item).data)
        else:
            raise TypeError("concat accepts RiverDataset objects or pandas DataFrames.")
    if not frames:
        raise ValueError("Provide at least one dataset or DataFrame to concatenate.")
    return from_dataframe(pd.concat(frames, ignore_index=True))
