# N-choe Dashboard Interview Notes

## Project Summary

This project is a lightweight environmental data dashboard for the N-choe basin. It was built as a static frontend using HTML, CSS, and vanilla JavaScript, with a small Node.js server used only to serve the files locally. The purpose of the dashboard is to help users explore water quality measurements across multiple sampling locations, compare parameters, inspect time trends, and visualize mapped stations interactively.

## Core Files

- `index.html` - main dashboard structure
- `styles.css` - visual design, layout, responsiveness
- `app.js` - dashboard logic, state management, map, filtering, chart rendering
- `build-dashboard-data.ps1` - data preprocessing and transformation pipeline
- `dashboard-data.js` - generated browser-ready dataset
- `serve-dashboard.js` - lightweight local HTTP server

## Overall Architecture

The architecture is intentionally simple:

1. Raw CSV files in `Datasets` are the source data.
2. A PowerShell preprocessing script combines and normalizes the datasets.
3. The script generates `dashboard-data.js`, which exposes one structured data object for the browser.
4. `index.html` loads the page shell and required assets.
5. `app.js` reads the prepared data and renders the interactive dashboard.
6. `serve-dashboard.js` runs a local server so the dashboard can be opened correctly in a browser.

This approach keeps data cleaning separate from frontend rendering, which makes the UI simpler and faster.

## Libraries and Tools Used

### Frontend Libraries

- Leaflet.js for the interactive map
- OpenStreetMap tile layer for the standard basemap
- Esri World Imagery tile layer for the satellite basemap

### Native Browser Features

- SVG for the custom trend chart
- HTML `<dialog>` element for the About popup
- Plain DOM APIs and event listeners for interactivity

### Build / Runtime Tools

- PowerShell for ETL-style preprocessing of CSV and Excel-based coordinate data
- Node.js built-in `http` server for local hosting

## Why This Stack Was Chosen

I chose a simple stack because this project is a focused, data-driven dashboard rather than a large web application. Using vanilla JavaScript reduced complexity, made deployment easier, and gave direct control over how the interface behaves. Since the dataset is preprocessed ahead of time, the frontend can stay lightweight and responsive without requiring a backend or database.

## Data Pipeline Explanation

The preprocessing is handled in `build-dashboard-data.ps1`.

### What the script does

- Reads coordinate information directly from the dataset CSVs
- Applies manual coordinate overrides where needed
- Reads the available CSV datasets
- Normalizes the files into one common schema
- Creates a `records` collection for measurement rows
- Creates a `locations` collection for station metadata
- Creates a `summary` section with dashboard counts
- Sorts and exports everything into `dashboard-data.js`

### Why preprocessing was important

The raw data comes from multiple files and not all of them are naturally ready for direct browser rendering. By preprocessing first, the frontend does not need to perform expensive cleaning logic in the browser. This improves performance and keeps presentation logic separate from transformation logic.

## Frontend Logic Explanation

The main dashboard logic lives in `app.js`.

### Initial load

The app reads data from `window.NCHOE_DASHBOARD_DATA`. If the data file is missing, the page shows a fallback message telling the user to rebuild the dataset.

### State management

The app uses a small plain JavaScript state object to track:

- selected location
- selected parameter
- selected timeline entry
- monthly vs yearly mode
- selected basemap

This state is then used to keep the map, sidebar, timeline, and chart synchronized.

### Location grouping

The code builds maps and grouped collections from the dataset so that records can be filtered efficiently by location and parameter.

### Map rendering

Leaflet is used to:

- initialize the map
- add OSM and satellite tile layers
- place markers for sampling locations
- zoom to mapped locations
- react to marker clicks

When a marker is selected, the dashboard updates the sidebar and chart for that station.

### Parameter filtering

Each location may have multiple measured parameters. The UI dynamically creates tabs/buttons based on what parameters are available for the selected location.

### Timeline rendering

The dashboard supports:

- monthly timeline view
- yearly aggregated timeline view

The yearly mode groups records by year and computes a representative yearly value.

### Trend chart

The trend chart is custom-built using SVG rather than a charting library.

The code:

- calculates chart bounds
- computes min/max values
- maps values to SVG coordinates
- draws the line path
- renders gridlines and labels
- highlights the selected point

This is a strong technical point because it shows manual rendering logic rather than full dependency on a chart package.

### Dynamic map labels

The app updates map labels based on the selected parameter and latest available measurement for each location, helping the map act as both a geographic and analytical interface.

## UI and Design Decisions

The page uses a two-column layout:

- left side for controls, station details, timeline, and trend chart
- right side for the map and legend

The design choices include:

- soft environmental color palette
- glass-like panels with blur effects
- rounded cards and badges
- responsive layout for smaller screens
- a clear separation between spatial exploration and analytical detail

The map is the main exploration surface, while the sidebar functions as the analysis panel.

## Key Features Implemented

- Interactive map with clickable sampling points
- OSM and satellite basemap switching
- Parameter-based filtering
- Selected location detail panel
- Monthly and yearly timeline modes
- Custom SVG trend chart
- Summary counters for mapped locations and measurements
- About N-choe popup
- Responsive layout for desktop and mobile
- Generated unified data file for efficient frontend loading

## Changes Made During Development

The dashboard work included:

- creating the page structure in `index.html`
- building the full visual design in `styles.css`
- implementing map logic and UI interactions in `app.js`
- preprocessing multiple data sources into one unified output file in `build-dashboard-data.ps1`
- creating a simple local server in `serve-dashboard.js`
- adding the About dialog for project context
- adding basemap switching between OSM and satellite
- adding monthly and yearly timeline modes
- implementing a custom SVG-based trend chart
- improving layout behavior of the left sidebar so it better fills the full page column

## Interview-Friendly Explanation

You can describe the project like this:

"I built a lightweight environmental monitoring dashboard for the N-choe basin using HTML, CSS, vanilla JavaScript, Leaflet, PowerShell, and a small Node.js local server. I first created a preprocessing pipeline that merged multiple CSV sources and coordinate metadata into a single browser-ready data file. Then I built an interactive frontend with a two-panel layout, map-based station selection, parameter filtering, monthly and yearly timeline views, and a custom SVG trend chart. I kept the stack intentionally lightweight because the project was primarily focused on data transformation, interactive exploration, and clear visual communication rather than complex application infrastructure."

## Why Not React

If asked why I did not use React or another framework:

- the project scope was contained
- there was no need for routing or a complex component hierarchy
- vanilla JavaScript was enough for the interactivity needed
- a lighter stack reduced setup overhead and made the project easier to explain and maintain

## What Was Technically Interesting

- parsing Excel coordinate data in PowerShell
- normalizing multiple CSV datasets into one schema
- keeping data transformation separate from UI rendering
- manually building a chart in SVG
- synchronizing map state, parameter state, timeline selection, and chart rendering without a framework

## What I Would Improve Next

- add stronger validation and error handling in preprocessing
- add export options for filtered data views
- improve legends and unit handling
- add automated tests for transformation logic
- introduce a framework only if the dashboard grows substantially in scope

## Short 60-Second Interview Answer

"This dashboard was built to visualize N-choe water quality data in a simple but interactive way. I used PowerShell to preprocess multiple CSV files and coordinate data into one structured dataset, then built the frontend using HTML, CSS, vanilla JavaScript, and Leaflet. The dashboard lets users explore stations on a map, switch parameters, compare monthly and yearly trends, and inspect measurements through a custom SVG chart. I chose a lightweight architecture because the main challenge was data normalization and clear visualization, not large-scale application complexity."

## 2-Minute Detailed Interview Answer

"I designed the N-choe dashboard as a lightweight environmental data exploration tool. The first step was handling the raw inputs, which came from multiple CSV files and an Excel sheet containing coordinates. I wrote a PowerShell script that parses, cleans, and combines those files into a single browser-ready dataset called `dashboard-data.js`. That preprocessing step was important because it moved the heavy transformation work out of the browser and made the frontend much simpler.

On the frontend, I used plain HTML, CSS, and vanilla JavaScript because the project did not need a full framework. I used Leaflet for the map, OpenStreetMap and Esri imagery for basemaps, and built the trend visualization manually using SVG. The interface has a two-panel layout: the right side is an interactive map for selecting stations, and the left side acts as an analysis panel with parameter filtering, timeline navigation, and trend inspection. I also added monthly and yearly views so users can analyze short-term versus aggregated trends.

From an engineering perspective, the most interesting parts were normalizing heterogeneous environmental datasets, synchronizing multiple UI states without a framework, and creating a custom chart instead of relying on a heavy charting library. If I extended it further, I would add validation, testing, and export features."

## Likely Interview Questions and Model Answers

### 1. What problem does this dashboard solve?

It helps users explore water quality measurements spatially and over time. Instead of reading many separate files, users can inspect locations on a map, switch parameters, and understand trends more clearly.

### 2. Why did you preprocess the data instead of loading raw CSVs directly in the browser?

Preprocessing gave me one clean, consistent dataset and kept the frontend focused on presentation. It improved load simplicity, made filtering easier, and reduced repeated parsing work in the browser.

### 3. Why did you choose Leaflet?

Leaflet is lightweight, easy to integrate, and works well for custom marker-based dashboards. It gave me the mapping features I needed without unnecessary complexity.

### 4. Why did you build the chart manually?

Building it in SVG gave me full control over how the data was displayed and reduced external dependencies. It also demonstrates a stronger understanding of rendering logic.

### 5. What was the biggest challenge?

The biggest challenge was unifying multiple data files with different formats and making them consistent enough for a clean interactive experience.

### 6. How did you manage UI state without a framework?

I used a centralized JavaScript state object and re-rendered the dependent UI pieces when selections changed. Since the app scope was manageable, this approach stayed simple and readable.

### 7. What would you improve if given more time?

I would add validation, automated tests, export functionality, and possibly a more scalable component structure if the project expanded further.

## Practical Commands

### To rebuild the generated dashboard dataset

```powershell
powershell -ExecutionPolicy Bypass -File .\build-dashboard-data.ps1
```

### To run the dashboard locally

```powershell
node .\serve-dashboard.js
```

### Local dashboard URL

```text
http://127.0.0.1:4173
```
