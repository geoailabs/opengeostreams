"""Interactive standalone charts and OpenStreetMap for Opengeostreams."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from . import pipeline


def _go():
    try:
        import plotly.graph_objects as go
        return go
    except ImportError as error:
        raise ImportError("Interactive charts require Plotly: pip install plotly") from error


def _select(dataset, parameter=None, location=None):
    frame = dataset.data[dataset.data["NumericValue"].notna()].copy()
    names = sorted(frame["Parameter"].dropna().astype(str).unique())
    parameter = parameter or (names[0] if names else None)
    if parameter:
        frame = frame[frame["Parameter"].astype(str).str.casefold() == pipeline.normalize_parameter(parameter).casefold()]
    if location:
        frame = frame[frame["Location"].astype(str).str.casefold() == location.casefold()]
    return frame, parameter


def _midpoint(value):
    start, end, _precision = pipeline.parse_date_bounds(value)
    return start + (end - start) / 2


def _weather_precipitation(frame):
    """Fetch and aggregate Open-Meteo precipitation for plotted observations."""
    from .server import fetch_weather_data

    results = []
    for location, group in frame.groupby("Location"):
        coordinates = group[["Latitude", "Longitude"]].apply(pd.to_numeric, errors="coerce").dropna()
        if coordinates.empty:
            continue
        bounds = group["Date"].map(pipeline.parse_date_bounds)
        start = min(item[0] for item in bounds)
        end = max(item[1] for item in bounds)
        _status, _content_type, content = fetch_weather_data({
            "latitude": str(coordinates.iloc[0]["Latitude"]),
            "longitude": str(coordinates.iloc[0]["Longitude"]),
            "start_date": start.strftime("%Y-%m-%d"),
            "end_date": end.strftime("%Y-%m-%d"),
        })
        daily = json.loads(content).get("daily", {})
        weather = pd.DataFrame({
            "Date": pd.to_datetime(daily.get("time", []), errors="coerce"),
            "Precipitation": pd.to_numeric(daily.get("precipitation_sum", []), errors="coerce"),
        }).dropna()
        for _, record in group.drop_duplicates("Date").iterrows():
            date_start, date_end, precision = pipeline.parse_date_bounds(record["Date"])
            period = weather[
                weather["Date"].between(pd.Timestamp(date_start), pd.Timestamp(date_end))
            ]
            if period.empty:
                precipitation = np.nan
            else:
                precipitation = period["Precipitation"].sum()
            results.append({
                "Location": location,
                "Date": record["Date"],
                "PlotDate": _midpoint(record["Date"]),
                "NumericValue": precipitation,
                "Unit": "mm",
                "Data Source": "Open-Meteo",
            })
    return pd.DataFrame(results)


def _style(figure, title, x_title="", y_title="", *, width=1000, height=550):
    figure.update_layout(
        title=title,
        template="plotly_white",
        autosize=False,
        width=width,
        height=height,
        xaxis_title=x_title,
        yaxis_title=y_title,
        hovermode="closest",
        margin=dict(l=90, r=100, t=80, b=75),
        font=dict(family="Arial, sans-serif"),
        legend_title_text="",
    )
    return figure


def trend_figure(dataset, parameter=None, location=None):
    """Interactive parameter and precipitation timeline."""
    go = _go()
    frame, parameter = _select(dataset, parameter, location)
    figure = go.Figure()
    if not frame.empty:
        frame["PlotDate"] = frame["Date"].map(_midpoint)
        frame["Series"] = frame["Location"].astype(str)
        if "ReportedParameter" in frame:
            variants = frame["ReportedParameter"].str.extract(r"(\((?:Min|Max)\))$", expand=False).fillna("")
            frame["Series"] = frame["Series"] + variants.map(lambda value: " " + value if value else "")
        for name, group in frame.sort_values("PlotDate").groupby("Series"):
            figure.add_trace(go.Scatter(
                x=group["PlotDate"],
                y=group["NumericValue"],
                mode="lines+markers",
                name=str(name),
                customdata=group[["Location", "Date", "Unit", "Data Source"]],
                hovertemplate=(
                    "Location: %{customdata[0]}<br>Date: %{customdata[1]}<br>"
                    "Value: %{y}<br>Unit: %{customdata[2]}<br>"
                    "Source: %{customdata[3]}<extra></extra>"
                ),
            ))
    rain = dataset.data.copy()
    rain_names = rain["Parameter"].astype(str).str.casefold()
    rain = rain[rain_names.str.contains("precipitation|rainfall", regex=True)]
    rain = rain[rain["NumericValue"].notna()]
    if location:
        rain = rain[rain["Location"].astype(str).str.casefold() == location.casefold()]
    precipitation_error = None
    if rain.empty and not frame.empty:
        try:
            rain = _weather_precipitation(frame)
        except Exception as error:
            precipitation_error = error
    if not rain.empty:
        rain = rain[rain["NumericValue"].notna()].drop_duplicates(["Location", "Date"])
    if not rain.empty:
        if "PlotDate" not in rain:
            rain["PlotDate"] = rain["Date"].map(_midpoint)
        multiple_locations = rain["Location"].nunique() > 1
        for name, group in rain.groupby("Location"):
            figure.add_trace(go.Bar(
                x=group["PlotDate"], y=group["NumericValue"],
                width=[max((pipeline.parse_date_bounds(date)[1] - pipeline.parse_date_bounds(date)[0]).total_seconds(), 86400) * 800 for date in group["Date"]],
                name=f"Precipitation - {name}" if multiple_locations else "Precipitation",
                yaxis="y2", opacity=0.32,
                hovertemplate="Period: %{customdata[1]}<br>Precipitation total: %{y:.2f} mm<extra></extra>",
                customdata=group[["Location", "Date", "Unit", "Data Source"]],
            ))
    elif precipitation_error is not None:
        figure.add_annotation(
            text="Precipitation unavailable (weather service could not be reached)",
            xref="paper", yref="paper", x=1, y=1.08, showarrow=False,
            font=dict(color="#b45309", size=12),
        )
    precipitation_by_record = {
        (str(row["Location"]), str(row["Date"])): (
            f"{float(row['NumericValue']):.3g} {row['Unit']}"
            if pd.notna(row["NumericValue"]) else "No data"
        )
        for _, row in rain.iterrows()
    }
    for trace in figure.data:
        if trace.type != "scatter" or trace.customdata is None:
            continue
        combined = []
        for details in trace.customdata:
            values = list(details)
            values.append(precipitation_by_record.get((str(values[0]), str(values[1])), "No data"))
            combined.append(values)
        trace.customdata = combined
        trace.hovertemplate = (
            f"Location: %{{customdata[0]}} | {parameter or 'Value'}: %{{y}} | "
            "Precipitation: %{customdata[4]}<extra></extra>"
        )
    unit = next(iter(frame["Unit"].dropna().astype(str)), "") if not frame.empty else ""
    _style(figure, f"{parameter or 'Parameter'} and precipitation trend",
           "Time", f"Value{f' ({unit})' if unit else ''}")
    if not frame.empty:
        bounds = frame["Date"].map(pipeline.parse_date_bounds)
        start = min(value[0] for value in bounds)
        end = max(value[1] for value in bounds)
        padding = max((end - start) / 20, pd.Timedelta(days=1))
        figure.update_xaxes(range=[start - padding, end + padding], tickformat="%b %Y" if (end - start).days > 60 else "%d %b", nticks=4)
    figure.update_layout(yaxis2=dict(
        title="Precipitation (mm)", overlaying="y", side="right", showgrid=False
    ), hovermode="closest", clickmode="event+select", barmode="overlay")
    figure.update_layout(meta={
        "precipitationStatus": "Precipitation: period total (mm)" if not rain.empty else "Precipitation unavailable",
        "precipitationUnavailable": rain.empty,
    })
    return figure


def distribution_figure(dataset, parameter=None, grouping="year", location=None):
    """Interactive monthly or yearly distribution boxplot."""
    if grouping not in {"year", "month"}:
        raise ValueError("grouping must be 'year' or 'month'.")
    go = _go()
    frame, parameter = _select(dataset, parameter, location)
    if not frame.empty:
        frame["Group"] = frame["Date"].map(
            lambda value: pipeline.parse_date_bounds(value)[0].year
            if grouping == "year" else pipeline.parse_date_bounds(value)[0].strftime("%b")
        )
    statistics = []
    if not frame.empty:
        groups = list(frame.groupby("Group", sort=True))
        if grouping == "month":
            groups.sort(key=lambda item: pipeline.MONTH_LABELS.index(item[0]))
        for label, group in groups:
            values = group["NumericValue"]
            q1, median, q3 = (float(value) for value in values.quantile([0.25, 0.5, 0.75]))
            iqr = q3 - q1
            statistics.append({
                "group": str(label), "count": len(values), "min": float(values.min()),
                "q1": q1, "median": median, "q3": q3, "max": float(values.max()),
                "mean": float(values.mean()), "iqr": iqr,
                "lowerWhisker": float(values[values >= q1 - 1.5 * iqr].min()),
                "upperWhisker": float(values[values <= q3 + 1.5 * iqr].max()),
            })
    figure = go.Figure(go.Box(
        x=[item["group"] for item in statistics],
        q1=[item["q1"] for item in statistics],
        median=[item["median"] for item in statistics],
        q3=[item["q3"] for item in statistics],
        lowerfence=[item["lowerWhisker"] for item in statistics],
        upperfence=[item["upperWhisker"] for item in statistics],
        boxpoints=False, name=parameter or "Value", showlegend=False,
        line=dict(color="#0f766e"), fillcolor="rgba(15,118,110,0.18)",
        hoveron="boxes",
    ))
    by_group = {item["group"]: item for item in statistics}
    details = []
    for _, row in frame.iterrows():
        item = by_group[str(row["Group"])]
        details.append([row["Location"], row["Date"], row["Unit"], row["Data Source"],
                        item["count"], item["min"], item["q1"], item["median"], item["q3"], item["max"]])
    figure.add_trace(go.Scatter(
        x=frame["Group"].astype(str).tolist() if not frame.empty else [],
        y=frame["NumericValue"].tolist(), mode="markers", name="Samples", showlegend=False,
        marker=dict(color="#0f766e", size=6, opacity=0.65), customdata=details,
        hovertemplate=(
            "Group: %{x}<br>Location: %{customdata[0]}<br>Date: %{customdata[1]}<br>"
            "Value: %{y} %{customdata[2]}<br>Source: %{customdata[3]}<br>"
            "Count: %{customdata[4]}<br>Min: %{customdata[5]:.6g}<br>Q1: %{customdata[6]:.6g}<br>"
            "Median: %{customdata[7]:.6g}<br>Q3: %{customdata[8]:.6g}<br>Max: %{customdata[9]:.6g}<extra></extra>"
        ),
    ))
    _style(figure, f"{parameter or 'Parameter'} distribution by {grouping}", grouping.title(), "Value")
    figure.update_layout(meta={"boxplotStatistics": statistics})
    figure.update_xaxes(type="category", categoryorder="array", categoryarray=list(by_group))
    return figure


def _channel_order(dataset, channel=None, group_by_channel=False):
    """Station order and grouping metadata from the drain/river network."""
    network = getattr(dataset, "_channel_network", None) or dataset.channel_network()
    if channel:
        key = str(channel).casefold()
        if key == "unassigned":
            stations = [item["location"] for item in network["unassigned"]]
            return stations, {"streamChannel": {"id": "unassigned", "name": "Not on a mapped drain/river",
                                                "stations": stations, "ordered": False}}
        match = next((item for item in network["channels"]
                      if item["id"] == key or item["name"].casefold() == key), None)
        if match is None:
            raise ValueError(f"Unknown drain/river: {channel}")
        stations = [item["location"] for item in match["stations"]]
        return stations, {"streamChannel": {"id": match["id"], "name": match["name"], "stations": stations,
                                            "ordered": bool(match.get("ordered", True))}}
    order, groups = [], []
    for item in network["channels"]:
        stations = [station["location"] for station in item["stations"]]
        groups.append({"id": item["id"], "name": item["name"], "start": len(order), "count": len(stations)})
        order.extend(stations)
    return order, {"streamGroups": groups}


def stream_figure(dataset, parameter=None, *, channel=None, group_by_channel=False):
    """Interactive year-by-location heatmap.

    ``group_by_channel=True`` groups rows by drain/river (upstream first within each);
    ``channel="<id or name>"`` shows only that drain/river, ordered upstream -> downstream.
    """
    go = _go()
    frame, parameter = _select(dataset, parameter)
    station_order, order_meta = (None, {})
    if channel or group_by_channel:
        station_order, order_meta = _channel_order(dataset, channel, group_by_channel)
    if not frame.empty:
        frame["Year"] = frame["Date"].map(lambda value: pipeline.parse_date_bounds(value)[0].year)
        table = frame.pivot_table(index="Location", columns="Year", values="NumericValue", aggfunc="mean")
        all_years = sorted({
            pipeline.parse_date_bounds(value)[0].year
            for value in dataset.data["Date"].dropna()
        })
        table = table.reindex(index=_stream_index(dataset, station_order, channel), columns=all_years)
    else:
        table = pd.DataFrame(index=_stream_index(dataset, station_order, channel), columns=sorted({pipeline.parse_date_bounds(value)[0].year for value in dataset.data["Date"].dropna()}), dtype=float)
    values = table.to_numpy(dtype=float) if not table.empty else np.empty((0, 0))
    display_values = np.empty(values.shape, dtype=object)
    cell_labels = np.empty(values.shape, dtype=object)
    for index, value in np.ndenumerate(values):
        if np.isfinite(value):
            display_values[index] = f"{value:.3g}"
            cell_labels[index] = display_values[index]
        else:
            display_values[index] = "No data"
            cell_labels[index] = ""
    figure = go.Figure(go.Heatmap(
        x=list(table.columns),
        y=list(table.index),
        z=values,
        customdata=display_values,
        text=cell_labels,
        texttemplate="%{text}",
        colorscale="RdYlBu_r",
        colorbar=dict(title="Value", thickness=22, len=0.78, x=1.02),
        hovertemplate="Location: %{y}<br>Year: %{x}<br>Value: %{customdata}<extra></extra>",
    ))
    # Missing cells use a separate mask so grey never changes the value colour scale.
    figure.add_trace(go.Heatmap(
        x=list(table.columns), y=list(table.index),
        z=np.where(np.isfinite(values), np.nan, 1.0),
        colorscale=[[0, "#d1d5db"], [1, "#d1d5db"]], zmin=0, zmax=1,
        showscale=False, hoverongaps=False, xgap=2, ygap=2,
        hoverinfo="skip",
        name="No data",
    ))
    figure.data[0].hoverongaps = False
    figure.add_trace(go.Scatter(
        x=[None], y=[None], mode="markers", marker=dict(color="#d1d5db", size=10, symbol="square"),
        name="No data", showlegend=True, hoverinfo="skip",
    ))
    height = max(520, 75 + (len(table.index) * 42))
    _style(
        figure, f"{parameter or 'Parameter'} across the river",
        "Year", "Location", width=1050, height=height,
    )
    figure.update_xaxes(tickangle=0, tickmode="array", tickvals=list(table.columns))
    figure.update_yaxes(automargin=True)
    if order_meta:
        if station_order is not None and not channel:
            # Everything after the grouped stations is "not on a mapped drain/river".
            grouped = sum(group["count"] for group in order_meta["streamGroups"])
            if len(table.index) > grouped:
                order_meta["streamGroups"].append({"id": "unassigned", "name": "Not on a mapped drain/river",
                                                   "start": grouped, "count": len(table.index) - grouped})
        # Rows run top to bottom in this order (upstream first).
        figure.update_yaxes(autorange="reversed")
        figure.update_layout(meta={**(figure.layout.meta or {}), **order_meta})
    return figure


def _stream_index(dataset, station_order=None, channel=None):
    locations = sorted(dataset.data["Location"].dropna().unique())
    if station_order is None:
        return locations
    if channel:
        return list(dict.fromkeys(station_order))
    ordered = list(dict.fromkeys(item for item in station_order if item in set(locations)))
    return ordered + [item for item in locations if item not in set(ordered)]


def _surface(dataset, parameter=None, year=None):
    collection = dataset._interpolation["surfaces"]["yearly" if year is not None else "allYears"]
    choices = [item for item in collection if year is None or item["year"] == year]
    if parameter:
        choices = [item for item in choices if item["parameter"].casefold() == pipeline.normalize_parameter(parameter).casefold()]
    if not choices:
        raise ValueError("No interpolation surface is available for that parameter and year.")
    return choices[0]


def _surface_arrays(surface):
    grid = surface["grid"]
    values = np.asarray([
        np.nan if value is None else float(value) for value in grid["values"]
    ]).reshape(grid["rows"], grid["columns"])
    extent = grid["extent"]
    longitude = np.linspace(extent["minLongitude"], extent["maxLongitude"], grid["columns"])
    latitude = np.linspace(extent["maxLatitude"], extent["minLatitude"], grid["rows"])
    return grid, values, longitude, latitude


def interpolation_figure(dataset, parameter=None, year=None):
    """Interactive interpolation raster with coordinate/value hover details."""
    go = _go()
    surface = _surface(dataset, parameter, year)
    _grid, values, longitude, latitude = _surface_arrays(surface)
    figure = go.Figure(go.Heatmap(
        x=longitude, y=latitude, z=values, colorscale="Turbo",
        colorbar=dict(title=surface.get("unit") or "Value"),
        hovertemplate=(
            "Longitude: %{x:.5f}<br>Latitude: %{y:.5f}<br>"
            "Estimated value: %{z:.3g}<extra></extra>"
        ),
    ))
    points = surface["samplePoints"]
    figure.add_trace(go.Scatter(
        x=[point["longitude"] for point in points],
        y=[point["latitude"] for point in points],
        mode="markers+text",
        text=[point["location"] for point in points],
        textposition="top center",
        marker=dict(size=9, color="white", line=dict(color="black", width=1)),
        name="Sampling locations",
        hovertemplate="Location: %{text}<br>Longitude: %{x:.5f}<br>Latitude: %{y:.5f}<extra></extra>",
    ))
    period = year if year is not None else "all years"
    _style(figure, f"{surface['parameter']} interpolation - {period}",
           "Longitude", "Latitude")
    # Fit the visible raster and stations, not the empty cells around the river mask.
    row_indices, column_indices = np.where(np.isfinite(values))
    visible_longitude = list(longitude[column_indices]) + [point["longitude"] for point in points]
    visible_latitude = list(latitude[row_indices]) + [point["latitude"] for point in points]
    if visible_longitude and visible_latitude:
        def padded_range(coordinates, grid_coordinates):
            low, high = min(coordinates), max(coordinates)
            cell_size = abs(float(grid_coordinates[1] - grid_coordinates[0])) if len(grid_coordinates) > 1 else 0.001
            padding = max((high - low) * 0.08, cell_size)
            return [low - padding, high + padding]
        figure.update_xaxes(range=padded_range(visible_longitude, longitude), constrain="domain")
        figure.update_yaxes(range=padded_range(visible_latitude, latitude), constrain="domain")
    return figure


def _rgba_surface(values):
    finite = np.isfinite(values)
    minimum = float(np.nanmin(values)); maximum = float(np.nanmax(values))
    normalized = np.clip((values - minimum) / (maximum - minimum or 1.0), 0, 1)
    stops = np.asarray([
        [48, 18, 59], [70, 107, 227], [42, 185, 169],
        [164, 252, 60], [253, 174, 50], [122, 4, 3],
    ], dtype=float) / 255.0
    positions = np.linspace(0, 1, len(stops))
    rgba = np.zeros((*values.shape, 4), dtype=float)
    for channel in range(3):
        rgba[..., channel] = np.interp(np.nan_to_num(normalized), positions, stops[:, channel])
    rgba[..., 3] = np.where(finite, 0.62, 0.0)
    return rgba, minimum, maximum


def map_figure(dataset, parameter=None):
    """Interactive Leaflet OpenStreetMap with a smooth interpolation raster."""
    try:
        import folium
        from branca.colormap import LinearColormap
    except ImportError as error:
        raise ImportError("Interactive maps require Folium: pip install folium") from error
    frame, parameter = _select(dataset, parameter)
    stations = frame.groupby(["Location", "Latitude", "Longitude"], as_index=False).agg(
        Value=("NumericValue", "mean")
    ) if not frame.empty else pd.DataFrame()
    if stations.empty:
        raise ValueError("No mapped monitoring stations are available.")
    river_map = folium.Map(
        location=[float(stations["Latitude"].mean()), float(stations["Longitude"].mean())],
        zoom_start=11, tiles="OpenStreetMap", control_scale=True,
    )
    surface = _surface(dataset, parameter)
    grid, values, _longitude, _latitude = _surface_arrays(surface)
    extent = grid["extent"]
    rgba, minimum, maximum = _rgba_surface(values)
    folium.raster_layers.ImageOverlay(
        image=rgba,
        bounds=[[extent["minLatitude"], extent["minLongitude"]],
                [extent["maxLatitude"], extent["maxLongitude"]]],
        name=f"{parameter or surface['parameter']} interpolation",
        opacity=1.0, interactive=True, cross_origin=False, zindex=1,
    ).add_to(river_map)
    LinearColormap(
        ["#30123b", "#466be3", "#2ab9a9", "#a4fc3c", "#fdae32", "#7a0403"],
        vmin=minimum, vmax=maximum,
        caption=f"{parameter or surface['parameter']} interpolated value",
    ).add_to(river_map)
    for station in stations.itertuples():
        folium.CircleMarker(
            location=[station.Latitude, station.Longitude], radius=7,
            color="#ffffff", weight=2, fill=True, fill_color="#0f766e",
            fill_opacity=0.95, tooltip=f"{station.Location}: {station.Value:.2f}",
            popup=(f"<strong>{station.Location}</strong><br>"
                   f"{parameter or 'Value'}: {station.Value:.2f}"),
        ).add_to(river_map)
    folium.LayerControl().add_to(river_map)
    return river_map


def save_map_png(map_object, destination):
    """Render the complete Leaflet map to PNG, including its tiles and legend."""
    from concurrent.futures import ThreadPoolExecutor
    from pathlib import Path
    from tempfile import TemporaryDirectory

    def render():
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as error:
            raise RuntimeError(
                "Map PNG export requires: pip install 'opengeostreams[images]'. "
                "Install Chrome or run: python -m playwright install chromium"
            ) from error
        with TemporaryDirectory(prefix="opengeostreams-map-") as folder:
            html_path = Path(folder) / "map.html"
            map_object.save(str(html_path))
            with sync_playwright() as playwright:
                browser = None
                for options in ({"channel": "chrome"}, {"channel": "msedge"}, {}):
                    try:
                        browser = playwright.chromium.launch(headless=True, **options)
                        break
                    except Exception:
                        continue
                if browser is None:
                    raise RuntimeError(
                        "Map PNG export needs Chrome/Chromium. "
                        "Install Chrome or run: python -m playwright install chromium"
                    )
                try:
                    page = browser.new_page(viewport={"width": 1400, "height": 900}, device_scale_factor=2)
                    page.goto(html_path.as_uri(), wait_until="load", timeout=60000)
                    page.wait_for_function("""() => {
                        const map = document.querySelector('.leaflet-container');
                        const tiles = [...document.querySelectorAll('.leaflet-tile')];
                        const overlays = [...document.querySelectorAll('.leaflet-image-layer')];
                        return map && tiles.length > 0 && overlays.length > 0 &&
                            [...tiles, ...overlays].every(img => img.complete && img.naturalWidth > 0);
                    }""", timeout=30000)
                    page.locator(".leaflet-container").screenshot(
                        path=str(destination), type="png", animations="disabled"
                    )
                except Exception as error:
                    raise RuntimeError(
                        "Map PNG export failed. Internet access is required to load "
                        "the map scripts and OpenStreetMap tiles."
                    ) from error
                finally:
                    browser.close()

    # A worker also supports notebook callers that already run an asyncio loop.
    with ThreadPoolExecutor(max_workers=1) as executor:
        executor.submit(render).result()
