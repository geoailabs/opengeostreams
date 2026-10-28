# OpenGeoStreams Water Quality Dashboard

Interactive water-quality dashboard for CSV-based monitoring data from rivers. The HTML/CSS frontend uses Plotly.js for charts and Leaflet for the map.
Opengeostreams loads CSVs into RiverDataset objects, validates and analyzes
data, defines every Plotly chart, and interpolates along the river network.

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
tools/                    Manual dashboard browser check
tests/                    Automated regression tests
examples/                 Single Python walkthrough
opengeostreams/opengeostreams/server.py    HTTP server, upload API, weather proxy
opengeostreams/opengeostreams/pipeline.py  Validation, analysis, boxplots
opengeostreams/opengeostreams/interpolation.py  Along-river interpolation
requirements.txt           Python dependencies
```

## Data processing

The Python pipeline:

- validates and standardizes uploaded CSV rows;
- reports rows, columns, and missing values;
- does not count a blank pH unit as missing;
- generates boxplot five-number summaries;
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

## Dashboard layout

The dashboard opens in a dark theme (toggle light/dark with the sun/moon button;
the choice is remembered in the browser). The map fills the window and the
controls float over it:

- **Top bar** — active dataset, current parameter (click it to jump to the
  parameter filter), mapped-station count, theme toggle, and the **Analysis**
  button that shows or hides the chart drawer.
- **Left panel** — *Data layers* (imported files; click one to make it active),
  *Add data*, a searchable parameter list, a searchable station list with
  pass/caution/fail dots and latest values, and *Station elevation*.
- **Right drawer** — trend, distribution, and stream charts for the selected
  station and parameter. The Trend / Distribution / Stream tabs jump to each
  chart; drag the drawer's left edge (or focus it and use the arrow keys) to
  resize it.
- **On the map** — use-case screening (with the Pass / Caution / Fail /
  Insufficient data marker legend) and the parameter safety scale at the top;
  zoom, fit-to-stations and basemap buttons on the right (OSM — the default —
  Minimal, and Satellite with labels); the Layers card (station and
  interpolation toggles, interpolation colour scale) and the period/year
  timeline at the bottom.
- Files can be dropped anywhere on the map to import them. Status messages
  appear as short notifications.

On phones the data panel slides in from the top-bar button and the charts sit
in a bottom sheet. Shell behaviour lives in `dashboard_assets/ui.js`; it reads
state from `app.js` through `window.OGS` and does not change any analysis.

## Duplicate station labels

Files converted from PDFs often split one site into several labels, e.g.
"POINT SOURSE BUDHA NALLAH, PUNJAB" and "SOURSE BUDHA NALLAH, PUNJAB 30.973".
On import these are given one name when every word of one label appears in the
other (pasted coordinates ignored, at most 3 extra words) and their coordinates
agree (same point, or within 1 km for labels of 3+ words). Labels are never
merged across U/S / D/S, or when the extra words change the site (before, after,
outlet, north, ...), unless the shorter label is an obvious fragment. The data
panel lists every merge under "duplicate station labels merged". Use
`ogs.load_csv(path, merge_stations=False)` to keep labels exactly as written.

## Drains and rivers: upstream order

The Stream card has a **Drain / river** picker. Stations are matched to the
India-WRIS river/drain network with geopandas (`opengeostreams/network.py`):

- Each station's drain/river comes from, in order: a name column in the file
  (`Drain`, `River`, `Water Body`, `Channel`, ...); a water-body name written in
  the station label (e.g. "HUDIARA DRAIN AT ...", "RIVER BEAS AT ...",
  "BUDHA NALLAH"), fuzzy-matched to a WRIS line nearby (within 2 km first, then
  15 km; spelling variants such as Budha/Budda or Sutlej/Satluj match); and
  finally the nearest WRIS line within **2 km**. Text after "into", "falling",
  "before confluence", etc. is ignored because it names the receiving river.
  Works for any file, with no editing needed.
- A named drain that is not in WRIS still groups its stations. Stations whose
  name matches a drain but whose coordinates are more than 15 km from it stay in
  the group with "position unknown". Stations with no name and no line within
  2 km are listed as not on a mapped drain/river.
- Direction: water flows downhill, so the outlet is the lowest end of the drain
  by terrain elevation (Open-Meteo elevation API, Copernicus DEM, looked up only
  for channel ends), preferring an end that joins another river. Offline or on
  very flat drains, the confluence and then the direction the WRIS lines are
  drawn in decide. Within 2 km, a station labelled U/S is placed before one
  labelled D/S. Set `OPENGEOSTREAMS_OFFLINE=1` to skip the elevation lookup.
- The stream view shows **one drain/river at a time**: it opens on the drain of
  the selected station (or the drain with most stations). Use the picker or the
  ‹ › buttons to step through drains, or click a drain line on the map. Only
  that drain's stations are shown, numbered upstream → downstream; the drain is
  highlighted on the map and each station's distance above the confluence and
  from the line is listed (amber when more than 500 m away). Selecting a
  station on another drain switches the view to that drain.
- The **Overview** options show all stations grouped by drain/river, the
  unmatched stations, or all stations A–Z.

The network file is looked up in this order: the `network_path` argument, the
`OPENGEOSTREAMS_NETWORK` environment variable, `data/indiawris/WRIS_Rivers_2024.parquet`,
then the bundled Punjab channels shapefile.

`WRIS_Rivers_2024.parquet` (157 MB) is not stored in the repository because it is
over GitHub's 100 MB file limit. Place a copy in `data/indiawris/` (or set
`OPENGEOSTREAMS_NETWORK`); without it, matching uses the bundled Punjab channels
shapefile in `opengeostreams/opengeostreams/reference_data/`. Matching runs once per imported file
(a few seconds for all-India files) and is cached.

```python
data = ogs.load_csv("Datasets/consolidated_dataset.csv", rows="all")
data.assign_channels()                       # one row per station: channel, order, distances
data.assign_channels(max_distance_km=1.0)    # stricter snapping
data.plot_stream(parameter="BOD", channel="tangori-choe")   # one drain, upstream first
data.plot_stream(parameter="BOD", group_by_channel=True)    # all stations, grouped
```

Names: the dashboard shows the local name from the station labels when most
stations carry it, or when no label uses the WRIS name (WRIS calls the N-choe
"Tangori Choe"; the WRIS name is still shown beside it). Local names that mean
the same water body are listed in
`opengeostreams/opengeostreams/reference_data/water_body_aliases.csv`
(`alias,name`, e.g. `Attawa Choe,N-Choe`). Add your own in
`data/water_body_aliases.csv` or a file named by `OPENGEOSTREAMS_ALIASES`.

This is a geometric approximation of the network, not a hydrological model:
WRIS names can differ from local names (the N-choe is "Tangori Choe" in WRIS),
and coarse coordinates can land on a neighbouring drain, so check the
"from the line" distances.

## Combine files in the dashboard

When two or more files are imported, each layer in **Data layers** gets a
checkbox. Tick the files to combine, name the result, and click **Combine**.
This runs `ogs.concat()` on the server and adds the result as a new layer (the
originals are unchanged). Tick **All selected files are one station** and enter
a name when the files describe one monitoring site under different labels (for
example one CSV per year or per agency); otherwise stations keep their own
names, with obvious label variants merged automatically. Every layer has a
download button that saves it as one CSV in the standard schema.

```python
combined = ogs.concat([first, second], name="sector83.csv", station="Sector 83")
combined.to_csv("sector83_all_years.csv")   # or combined.to_csv() for the text
```

## Switch CSVs in the dashboard

Use **Add data** in the Data layers panel (or drop files on the map) to select
one or several files, then click **Load files**. Click an imported file in
**Data layers** to refresh the dashboard with that file's data, including its
charts, summary, stations, and interpolation.
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

- Upload one or multiple CSVs with a positive **Rows per file** limit
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

## Along-river interpolation

River data is interpolated along the channels and in the direction of flow, not
in straight lines (after Ver Hoef, Peterson & Theobald 2006 and Ver Hoef &
Peterson 2010). It works for any river: the library picks the method from what
each dataset has.

```python
data, summary = data.interpolate()                    # distance limit chosen by the data
data, summary = data.interpolate(max_distance_km=5)   # or a fixed limit along the river
data, summary = data.interpolate(network_path="my_drains.gpkg", advanced=True)
```

1. **Tidy the data.** One interval per station for each parameter and period.
   An ordinary reading is a single value; a Min/Max report (`BOD (Min)`,
   `BOD (Max)`) is a range. Each station-year uses its ordinary readings when it
   has any, otherwise its Min and Max, and the all-years bounds are the means of
   the yearly bounds, so every year counts equally. Every map is then built
   twice: a **lower** run (Min where reported) and an **upper** run (Max), so the
   result is an interval and no range station is left out. A station with only a
   Max counts for the upper bound only, and says so.
2. **Find a river map.** Your own line file (`network_path` or the
   `OPENGEOSTREAMS_NETWORK` variable) first, then India-WRIS (small drains in
   India), then any HydroRIVERS file you put in `data/hydrorivers/`. Shapefile,
   GeoPackage and GeoParquet line files work, including OpenStreetMap waterway
   exports. If no map has a channel within 2 km of the stations, straight-line
   IDW is used and every surface says so.
3. **Pin stations to the rivers.** Each station snaps to its matched channel.
   Natural channels drain to their outlet: the lowest channel end by terrain
   elevation, else the direction most lines are drawn in. Canals, ditches and
   drains marked as such keep the direction they are drawn in. A canal that
   would make water flow in a circle is dropped. A station labelled
   "D/S of X" within 500 m above the X junction is moved just below it.
4. **Junctions and splits.** Where channels meet, each branch's share of the
   water comes from its catchment area when the map has an area column
   (HydroRIVERS `UPLAND_SKM`, MERIT `uparea`, NHDPlus `TotDASqKm`, ...),
   otherwise both sides count equally (`junction_weights="order"` uses stream
   order). Where a channel splits, water is shared by discharge when known,
   else canal rank (river > main canal > branch > distributary > minor), else
   equally.
5. **Fill in the river.** Each river point averages the stations upstream and
   downstream of it, weighted by the share of water that passed between them
   divided by the squared distance along the flow path. A station on a separate
   drain, or below a canal off-take, shares no water and never counts.
6. **Choose the reach.** With `max_distance_km="auto"` (the default), limits of
   2, 4, 8, 16 and 32 km and no limit are each tested by leave-one-out and the
   smallest error wins. A station a limit cannot reach counts as the mean of
   the others, so a short limit does not win by skipping hard cases. The
   choice is reported in `data._interpolation["method"]["distanceSelection"]`.
7. **Check itself.** Every station is hidden in turn and predicted from the
   others. Each surface reports this leave-one-out error, the error of simply
   using the average of the other stations, and a skill score (above 0 means
   the map beats that average).
8. **Optional extra.** With `advanced=True` and at least 50 stations on a
   tree-shaped network (no splits), tail-up, tail-down and mixed stream-network
   kriging are fitted too, and whichever method has the smallest leave-one-out
   error is kept.
9. **Show the map.** Values are coloured along the channels, faded where
   confidence is low, with the method, reach, error and skill beside them. A
   Lower / Upper switch picks which bound colours the map; clicking the river
   shows the whole interval. In Python, `data.plot(parameter="BOD", bound="lower")`
   (the default is the upper bound; `parameter="BOD (Min)"` picks the lower).

Canals run in rotation and can be dry, so a canal sample reflects its source
river only while the canal runs; surfaces that use a canal station say so.
This is a statistical estimate along mapped channels, not a hydraulic model.


### All rows and Google Earth Engine elevations

Dashboard uploads default to **Import all rows**. Uncheck this to set a positive
row limit. Limits apply to converted measurement records for wide tables.
The Python API still defaults to 400; use `load_csv(path, rows="all")` for all records.

Install and authenticate the optional elevation connector from the project folder:

```powershell
.\.venv\Scripts\python.exe -m pip install -e "./opengeostreams[earthengine]"
.\.venv\Scripts\python.exe -c "import ee; ee.Authenticate()"
$env:OPENGEOSTREAMS_EE_PROJECT = "your-google-cloud-project-id"
.\.venv\Scripts\python.exe -m opengeostreams.server
```

For Windows Command Prompt use `set OPENGEOSTREAMS_EE_PROJECT=your-google-cloud-project-id`
instead of the PowerShell environment assignment. The project must be registered
for Earth Engine and your account must have access:
https://developers.google.com/earth-engine/guides/auth
Never put credentials in source code or upload them to GitHub.

Upload/select a file and click **Fetch elevations** under Station elevation.
The server samples Copernicus DEM GLO-30 (2024_1) at each unique coordinate,
batches requests, and caches successful results for that imported file. Missing
coverage and invalid coordinates are reported rather than assigned zero.
Python callers can use `dataset.fetch_elevations(project="your-project-id")`
to obtain a pandas DataFrame. Elevations remain separate from water-quality measurements
and are not automatically used in water-quality interpolation.

These are 30 m digital **surface** model elevations in metres above EGM2008,
including buildings and vegetation, not measured riverbed elevations or water levels.
Source and attribution: https://developers.google.com/earth-engine/datasets/catalog/COPERNICUS_DEM_GLO30_2024_1
