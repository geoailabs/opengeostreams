# Opengeostreams

Opengeostreams provides a pandas-style Python API for loading, analysing,
interpolating, and visualising water-quality data from any river CSV.

```python
import opengeostreams as ogs

data = ogs.load_csv("river.csv", rows=1000)
data.head()
data.describe()

data, summary = data.interpolate()
data.plot(save_path="interpolation.png")
data.dashboard()
```

Choose any positive number of CSV records with `rows` (excluding the header).
Omitting `rows` loads the first 400 records. Limits larger than the file
import all available records.

```python
data = ogs.load_csv("river.csv")             # first 400 records
data = ogs.load_csv("river.csv", rows=1000)  # first 1000 records
```

Each dashboard view is independently available:

```python
data.plot_trend(parameter="pH")
data.plot_distribution(parameter="pH", grouping="year")
data.plot_stream(parameter="pH")
data.plot_map(parameter="pH")
```

Standalone charts use Plotly and are interactive automatically in notebooks
and browsers. Hover over a trend marker or distribution point to see its
location, date, value, unit, and source. Hover over a stream cell or
interpolation position to inspect its value. `plot_map()` remains an
independent Folium/Leaflet OpenStreetMap and can be saved with
`save_path="station_map.html"`.

`data.dashboard()` launches a dashboard backed by that same RiverDataset.
The frontend renders the library's trend, distribution, stream, and
interpolation figures using Plotly.js. Leaflet retains the interactive map,
station selection, suitability indicators, and interpolation overlay.

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
