# OpenGeoStreams Water Quality Dashboard

Interactive water-quality dashboard for CSV-based monitoring data from rivers. The HTML/CSS frontend uses Plotly.js for charts and Leaflet for the map.
Opengeostreams loads CSVs into RiverDataset objects, validates and analyzes
data, defines every Plotly chart, and computes ordinary-kriging interpolation.

## Run

Python 3.11 or newer is required.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m opengeostreams.server
```

Open <http://127.0.0.1:4173>. The dashboard starts empty and displays data after
a user imports a CSV.

## Opengeostreams Python API

Install it with `python -m pip install -e ".\\opengeostreams"`.

```python
import opengeostreams as ogs

data = ogs.load_csv("Datasets/consolidated_dataset.csv", rows=1000)
data, summary = data.interpolate()
data.plot(save_path="interpolation_results.png")
data.dashboard()
```

Use `rows` to choose any positive number of records at import. Omitting
`rows` loads the first 400 records. Limits larger than the file import all
available records. The trend, distribution,
stream, and map views are also available as independent methods.

## CSV schema

Required columns:

```text
Parameter, Value, Location, Latitude, Longitude
```

Dates may be supplied as a `Date` column or as separate `Month` and `Year`
columns. Dates are normalized to `dd-mm-yyyy`; absent day and month components
default to `01`.

Optional columns include `Unit`, `Data Source`, and `SrNo`.

## Current files

```text
Datasets/                  Source CSVs and generated consolidated CSV
opengeostreams/opengeostreams/dashboard_assets/  Complete browser dashboard
tools/                    River-mask utility and manual browser check
tests/                    Automated regression tests
examples/                 Single Python walkthrough
opengeostreams/opengeostreams/server.py    HTTP server, upload API, weather proxy
opengeostreams/opengeostreams/pipeline.py  Validation, analysis, boxplots, interpolation
requirements.txt           Python dependencies
```

## Data processing

The Python pipeline:

- validates and standardizes uploaded CSV rows;
- reports rows, columns, and missing values;
- does not count a blank pH unit as missing;
- generates boxplot five-number summaries;
- creates all-years and yearly ordinary-kriging surfaces when at least three
  mapped stations are available for a parameter;
- clips interpolation to the river mask; and
- writes browser-ready generated data.

Run the pipeline directly to rebuild the consolidated project dataset:

```powershell
.\.venv\Scripts\python.exe -m opengeostreams.pipeline
```

The dashboard server starts with no active CSV. Uploads create in-memory
RiverDataset objects. Dashboard data, Plotly figures, and interpolation are
served through the Python API without rewriting packaged assets.

## Combine datasets or DataFrames

```python
first = ogs.load_csv("river1.csv")  # first 400 rows
second = ogs.load_csv("river2.csv", rows=1000)
combined = ogs.concat([first, second])
# DataFrames are accepted too:
combined = ogs.concat([first.data, second.data])
print(combined.describe())
combined.plot_trend(parameter="pH")
```

`ogs.concat()` returns a new `RiverDataset` supporting interpolation, plots,
and dashboards. It combines only the loaded rows, preserves duplicates and
input order, and leaves the inputs unchanged. Row numbers and analysis
metadata are rebuilt. To convert an existing pandas DataFrame, use
`ogs.from_dataframe(frame)`. DataFrames must follow the CSV schema; all their
rows are imported. These in-memory datasets have `path=None`.

## Save visualizations as PNG

PNG files are saved only when requested with `save_path`:

```python
data.plot(save_path="interpolation.png", parameter="pH")
data.plot_trend(save_path="trend.png", parameter="pH")
data.plot_distribution(save_path="distribution.png", parameter="pH")
data.plot_stream(save_path="stream.png", parameter="pH")
data.plot_map(save_path="map.png", parameter="pH", open_browser=False)
```

Files are written relative to the current working directory, or to an absolute
path you provide. Existing files at that path are overwritten. The methods
still return their interactive figure/map objects.

Install export dependencies with `pip install 'opengeostreams[images]'`.
Chart export requires Chrome/Chromium. Map export uses Playwright with an
installed Chrome or Edge, or Chromium installed with
`python -m playwright install chromium`. Map PNG export requires internet
access for map scripts and OpenStreetMap tiles. HTML map export remains available.

## Switch CSVs in the dashboard

Use **Import CSV files** to select one or several CSVs, then click **Load CSVs**.
Choose an imported file from **Active CSV** to refresh the dashboard with that
file's data, including its charts, summary, stations, and interpolation.
The last successfully imported file becomes active. Files with the same name
remain separate entries. Failed uploads are reported without discarding the
other imported files.

Imported files are kept in memory for the running server session and remain
available after a page refresh. **Clear all data** removes the entire imported
collection; restarting the server also clears it. The active CSV is shared
by browser tabs connected to the same server.

## Library-backed dashboard

Start an empty dashboard with `python -m opengeostreams.server`, or launch one
with a loaded/combined dataset using `data.dashboard()`.

- Upload one or multiple CSVs with a positive **Rows to import per CSV** limit
  (default 400). The summary shows imported versus available rows.
- Each import is a RiverDataset, retained in memory under its own ID. Switching
  CSVs reuses the imported object without reprocessing the source file.
- Python generates figures using the library's plotting methods. Plotly.js is
  served locally from the installed Plotly package, keeping both versions aligned.
- Station, parameter, year, and month filters update the charts. The stream
  chart compares stations; interpolation surfaces represent all years or one year.
- Use the camera button on a Plotly chart to download a PNG. Browser chart
  downloads do not require the optional Python image-export dependencies.
- Interpolation is calculated when requested and cached per dataset. Figure
  responses and weather responses are also cached. Map tiles and weather still
  require internet access; weather failures leave water-quality charts usable.

The distribution chart now uses the library's Plotly boxplot convention:
whiskers extend to the last sample within 1.5 IQR, with individual points shown.

Hover directly over a distribution box to see min, Q1, median, Q3, max,
mean, IQR, sample count, and both whisker endpoints. There is no separate
statistics panel. All dashboard charts use Plotly.js; Leaflet renders the map.

The dashboard displays interpolation directly on the Leaflet map, with a
layer toggle, value legend, and click-to-inspect estimates. It has no separate
interpolation chart; the Python `data.plot()` method remains available.
The sidebar stream heatmap displays cell values with a horizontal colour scale.
Long time series and station lists scroll within the chart panel.

Dashboard uploads validate CSV, TSV, delimited TXT, JSON tables, and Excel (.xlsx/.xls). Non-CSV tables are converted to CSV in memory before library import; Excel uses the first sheet. The rows input still defaults to 400. Unsupported or malformed files show an upload error. Missing stream measurements render as gray cells without cell labels or hover text; the legend explains the gray color. Restart the dashboard server after updating Python code, then reimport your files.

Dense dashboards show eight stream stations per page, hover labels on maps with more than 12 stations, scrollable distribution categories, and smaller markers for dense series. Minimal uses subdued OpenStreetMap tiles. Precipitation sums the daily values over each reporting period and avoids duplicate bars for Min/Max endpoints. Range endpoints remain separate trend series; endpoint distribution statistics are not original-sample statistics.

The import summary counts empty source cells (with a per-column breakdown), not missing rows. Annual reports can have empty Date cells while providing Year. Interpolation uses the uploaded station extent when stations fall outside the bundled N-choe mask. Trend and precipitation hover details appear in a wrapped popup outside the sidebar.

## Upload flow and project organization

The browser uploads the original CSV (or supported table file) to Python.
The server converts non-CSV tables to CSV, then OpenGeoStreams loads the
measurements into a RiverDataset backed by a pandas DataFrame. The server
sends JSON records, Plotly figure definitions, and interpolation grids to
the browser. Plotly.js renders charts; Leaflet renders the map. Uploaded
data stays in server memory for that session; the source file is unchanged.
JSON is the browser transport format, not a replacement for the source file.

Tests, examples, and maintenance scripts live in their respective
folders. Browser tests use Chrome; PNG export also needs the optional image
dependencies (`python -m pip install -e "./opengeostreams[images]"`).
Run these commands from the project root:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_opengeostreams -v
.\.venv\Scripts\python.exe -m examples.example
.\.venv\Scripts\python.exe -m tools.check_dense_dashboard
```

`examples/example.py` is the single walkthrough; PNG export is opt-in with
`--save-png`, and `--dashboard` opens the dashboard. All automated checks are
in `tests/test_opengeostreams.py`, grouped into test classes.
The active `launch_restored_dashboard.py` helper remains at the root so the
restored dashboard continues to run without changing its workbook path.

The live dashboard serves dataset JSON and interpolation through Python endpoints. Generated `dashboard_assets/dashboard-data.js` and `dashboard_assets/interpolation-data.json` snapshots are not kept in the project. Python `__pycache__` folders are retained and remain excluded from version control.

## General-river interpolation

No bundled river mask is applied automatically. Each parameter/period uses
its own station extent, and observations at identical coordinates are averaged
without merging distant stations that share a name. Missing coordinates produce
no surface. Single-station surfaces are explicitly labeled as having no spatial
interpolation. The empty dashboard opens at a world view.

`data.interpolate(max_distance_km=8.0)` retains an 8 km maximum support distance;
choose an appropriate positive limit for your dataset. An optional custom mask
can be supplied with `river_mask_path="path/to/mask.json"`; its grid dimensions
must match and its extent must cover the stations.

The method uses a heuristic Gaussian covariance model and geographic distance,
not river-network connectivity or a fitted/validated hydrological model. Nearby
stations from different rivers are not automatically separated; import/filter
one river at a time when this matters. Min/Max records contribute endpoint
averages, not reconstructed original samples. The former bundled N-choe mask
has been removed; `tools/build-river-mask.py` remains an optional custom-mask tool.
