"""OpenGeoStreams regression suite. Browser and PNG tests need optional dependencies."""
import json
import threading
import unittest
import urllib.request
from unittest.mock import patch
from pathlib import Path
from opengeostreams.opengeostreams import server
import io
import urllib.error
import opengeostreams as ogs
import pandas as pd
import numpy as np
from opengeostreams.opengeostreams.server import process_uploaded_csv
import tempfile
from PIL import Image


class CsvSwitcherTests(unittest.TestCase):
    def test_registry_switch_and_clear(self):
        with patch.object(server, "process_uploaded_csv", wraps=server.process_uploaded_csv) as process:
            httpd = server.create_server(port=0)
            worker = threading.Thread(target=httpd.serve_forever, daemon=True)
            worker.start()
            base = "http://127.0.0.1:" + str(httpd.server_port)
            def request(route, body=None, content_type="application/json"):
                req = urllib.request.Request(base + route, data=body, headers={"Content-Type": content_type})
                with urllib.request.urlopen(req) as response:
                    return json.load(response)
            try:
                for payload in (b"Parameter,Value,Location,Latitude,Longitude,Year\npH,7,A,30.7,76.7,2024\n", b"Parameter,Value,Location,Latitude,Longitude,Year\npH,8,B,30.8,76.8,2024\n"):
                    body = b'--boundary\r\nContent-Disposition: form-data; name="file"; filename="same.csv"\r\nContent-Type: text/csv\r\n\r\n' + payload + b'\r\n--boundary--\r\n'
                    request('/upload-csv', body, 'multipart/form-data; boundary=boundary')
                listing = request('/datasets')
                self.assertEqual(len(listing['datasets']), 2)
                first = listing['datasets'][0]['id']
                self.assertNotEqual(first, listing['activeId'])
                request('/select-csv', json.dumps({'id': first}).encode())
                self.assertEqual(process.call_count, 2)
                self.assertEqual(httpd.datasets[first]["dataset"].data.iloc[0]["Value"], "7")
                self.assertEqual(request('/datasets')['activeId'], first)
                request('/reset-data', b'')
                self.assertEqual(request('/datasets')['datasets'], [])
            finally:
                httpd.shutdown()
                httpd.server_close()
                worker.join()

    def test_frontend_selector(self):
        from playwright.sync_api import sync_playwright
        html = (server.ROOT / 'index.html').read_text(encoding='utf-8')
        import re
        html = re.sub(r'<script[^>]*src=[^>]*></script>', '', html)
        html = re.sub(r'<link[\s\S]*?>', '', html)
        html = html.replace('<script>', '<script>window.NCHOE_DASHBOARD_DATA = {summary: {}};', 1)
        selected = []
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel='chrome', headless=True)
            try:
                page = browser.new_page()
                def route_handler(route):
                    path = route.request.url.split('http://switcher.test')[-1]
                    if path == '/datasets':
                        route.fulfill(json={'datasets': [{'id':'one','fileName':'same.csv'}, {'id':'two','fileName':'same.csv'}], 'activeId':'two'})
                    elif path == '/select-csv':
                        selected.append(route.request.post_data_json['id'])
                        route.fulfill(json={'ok':True})
                    else:
                        route.fulfill(content_type='text/html', body=html)
                page.route('http://switcher.test/**', route_handler)
                page.goto('http://switcher.test/')
                page.wait_for_function("document.querySelector('#csv-dataset-select').options.length === 2")
                self.assertEqual(page.locator('#csv-dataset-select').input_value(), 'two')
                self.assertEqual(page.locator('#csv-dataset-select option').all_text_contents(), ['same.csv', 'same.csv (2)'])
                self.assertTrue(page.locator('#csv-file').evaluate('(el) => el.multiple'))
                page.select_option('#csv-dataset-select', 'one')
                page.wait_for_url('**/?data=*')
                self.assertEqual(selected, ['one'])
            finally:
                browser.close()


CSV = b"Parameter,Value,Location,Latitude,Longitude,Date\npH,7,A,30.70,76.70,01-01-2024\npH,8,A,30.70,76.70,01-02-2024\npH,9,B,30.71,76.71,01-01-2025\n"


class DashboardLibraryTests(unittest.TestCase):
    def setUp(self):
        self.httpd = server.create_server(port=0)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.base = 'http://127.0.0.1:' + str(self.httpd.server_port)
        self.weather = patch.object(server, 'fetch_weather_data', side_effect=OSError('offline weather'))
        self.weather.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join()
        self.weather.stop()

    def get(self, route):
        with urllib.request.urlopen(self.base + route) as response:
            return json.load(response)

    def upload(self, rows=400, filename='river.csv', content=CSV):
        body = ('--boundary\r\nContent-Disposition: form-data; name="file"; filename="' + filename + '"\r\nContent-Type: text/csv\r\n\r\n').encode() + content + b'\r\n--boundary--\r\n'
        req = urllib.request.Request(self.base + '/upload-csv?rows=' + str(rows), data=body,
                                     headers={'Content-Type':'multipart/form-data; boundary=boundary'})
        with urllib.request.urlopen(req) as response:
            return json.load(response)

    def test_upload_filters_and_cache(self):
        result = self.upload(rows=2)
        self.assertEqual(result['summary']['loadedRows'], 2)
        self.assertEqual(result['summary']['totalRows'], 3)
        listing = self.get('/datasets')
        dataset_id = listing['activeId']
        entry = self.httpd.datasets[dataset_id]
        self.assertIsInstance(entry['dataset'], ogs.RiverDataset)
        self.assertIsNone(entry['dataset']._interpolation)
        query = '/api/figure?id=' + dataset_id + '&kind=distribution&parameter=pH&location=A&month=2&year=2024'
        figure = self.get(query)
        self.assertEqual(figure['data'][0]['type'], 'box')
        self.assertEqual(figure['data'][1]['customdata'][0][1], '01-02-2024')
        count = len(entry['figures'])
        self.assertEqual(figure, self.get(query))
        self.assertEqual(count, len(entry['figures']))
        for kind in ('trend', 'stream'):
            self.assertTrue(self.get('/api/figure?id=' + dataset_id + '&kind=' + kind + '&parameter=pH')['data'])
        for route in ('/api/figure?id=missing', '/api/figure?id=' + dataset_id + '&kind=invalid'):
            with self.assertRaises(urllib.error.HTTPError):
                self.get(route)
        with self.assertRaises(urllib.error.HTTPError):
            self.upload(rows=0)
        self.assertEqual(len(self.get('/datasets')['datasets']), 1)

    def test_interpolation_cached_and_dataset_dashboard(self):
        self.upload()
        entry = self.httpd.datasets[self.httpd.active_dataset]
        with patch.object(entry['dataset'], 'interpolate', wraps=entry['dataset'].interpolate) as interpolate:
            first = self.get('/api/interpolation?id=' + self.httpd.active_dataset)
            self.assertEqual(first, self.get('/api/interpolation?id=' + self.httpd.active_dataset))
            self.assertEqual(interpolate.call_count, 1)
        dataset = entry['dataset']
        other = dataset.dashboard(port=0, open_browser=False)
        try:
            self.assertIs(other.datasets[other.active_dataset]['dataset'], dataset)
        finally:
            other.shutdown()
            other.server_close()

    def test_global_parameters_and_hover_dismissal(self):
        from playwright.sync_api import sync_playwright
        payload = CSV + b"Faecal Coliform,200,C,30.72,76.72,01-01-2024\n"
        self.upload(content=payload)
        with sync_playwright() as p:
            browser = p.chromium.launch(channel='chrome', headless=True)
            try:
                page = browser.new_page(viewport={"width": 1440, "height": 1000})
                page.goto(self.base)
                page.wait_for_function("document.getElementById('trend-chart')?.data?.length")
                button = page.locator('#parameter-tabs button').filter(has_text='Faecal Coliform')
                self.assertEqual(button.count(), 1)
                button.click()
                page.wait_for_function("document.getElementById('trend-chart')?.data?.some(t => t.customdata?.[0]?.[0] === 'C')")
                point = page.locator('#trend-chart .scatterlayer .point').first
                point.scroll_into_view_if_needed()
                page.wait_for_timeout(300)
                point.hover(force=True)
                page.locator('#trend-tooltip').wait_for(state='visible')
                page.locator('.sidebar').evaluate('(el) => el.scrollTop += 80')
                page.locator('#trend-tooltip').wait_for(state='hidden')
                point.scroll_into_view_if_needed()
                page.wait_for_timeout(300)
                page.mouse.move(5,5)
                point.hover(force=True)
                page.locator('#trend-tooltip').wait_for(state='visible')
                page.keyboard.press('Escape')
                self.assertFalse(page.locator('#trend-tooltip').is_visible())
                stream = page.locator('#stream-visualization')
                stream.scroll_into_view_if_needed()
                page.wait_for_timeout(300)
                position = stream.evaluate("""el => {
                    const layout = el._fullLayout;
                    return {x: layout.xaxis._offset + layout.xaxis.d2p(2024), y: layout.yaxis._offset + layout.yaxis.d2p('C')};
                }""")
                stream.hover(position=position, force=True)
                tooltip = page.locator('#stream-tooltip')
                tooltip.wait_for(state='visible')
                self.assertIn('Faecal Coliform', tooltip.inner_text())
                bounds = tooltip.bounding_box()
                self.assertGreaterEqual(bounds['x'], 0)
                self.assertLessEqual(bounds['x'] + bounds['width'], 1440)
                self.assertLessEqual(bounds['y'] + bounds['height'], 1000)
                self.assertEqual(page.locator('#stream-visualization .hoverlayer').text_content().strip(), '')
                page.mouse.move(5, 5)
                tooltip.wait_for(state='hidden')
                self.assertIn('OpenGeoStreams', page.locator('h1').inner_text())
                self.assertNotIn('Empty source cells', page.locator('#csv-shape-summary').inner_text())
            finally:
                browser.close()

    def test_browser_upload_charts_switch_download(self):
        from playwright.sync_api import sync_playwright
        errors = []
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel='chrome', headless=True)
            try:
                page = browser.new_page(viewport={'width':1440, 'height':1000})
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(self.base)
                page.locator('#csv-row-limit').fill('2')
                page.locator('#csv-file').set_input_files([
                    {'name':'first.csv','mimeType':'text/csv','buffer':CSV},
                    {'name':'second.csv','mimeType':'text/csv','buffer':CSV.replace(b'pH,7', b'pH,6')}
                ])
                page.locator('#csv-upload-button').click()
                page.wait_for_url('**/?data=*')
                page.wait_for_function("['trend-chart','boxplot-chart','stream-visualization'].every(id => document.getElementById(id)?.data?.length)", timeout=90000)
                self.assertLessEqual(page.locator('.sidebar').bounding_box()['width'], 390)
                self.assertGreater(page.locator('.map-area').bounding_box()['width'], 950)
                screening = page.locator('.suitability-panel').bounding_box()
                map_box = page.locator('#map').bounding_box()
                self.assertLessEqual(map_box['y'] - (screening['y'] + screening['height']), 90)
                self.assertTrue(page.locator('#parameter-scale').evaluate('(el) => !!el.closest(".map-toolbar")'))
                self.assertLess(page.locator('#parameter-scale').bounding_box()['height'], 130)
                for chart_id in ('trend-chart', 'boxplot-chart', 'stream-visualization'):
                    box = page.locator('#' + chart_id).bounding_box()
                    self.assertGreaterEqual(box['width'], 260)
                    self.assertLessEqual(box['width'], 420)
                    self.assertTrue(page.locator('#' + chart_id).evaluate('(el) => !!el.closest(".sidebar")'))
                    self.assertGreaterEqual(box['height'], 280 if chart_id == 'stream-visualization' else 380)
                import tempfile
                from pathlib import Path
                page.locator('#trend-chart').screenshot(path=str(Path(tempfile.gettempdir()) / 'opengeostreams-trend-layout.png'))
                page.set_viewport_size({'width':390, 'height':844})
                page.wait_for_function("['trend-chart', 'boxplot-chart'].every(id => {const el = document.getElementById(id); return Math.abs(el._fullLayout.width - el.clientWidth) < 1;})")
                self.assertTrue(page.locator('.chart-scroll').evaluate('(el) => el.scrollWidth <= el.clientWidth + 1'))
                self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), 390)
                page.set_viewport_size({'width':1440, 'height':1000})
                page.wait_for_function("['trend-chart', 'boxplot-chart'].every(id => {const el = document.getElementById(id); return Math.abs(el._fullLayout.width - el.clientWidth) < 1;})")
                self.assertEqual(page.locator('#interpolation-chart').count(), 0)
                page.wait_for_function("!document.getElementById('map-interpolation-legend').hidden")
                self.assertEqual(page.locator('#map .leaflet-image-layer').count(), 1)
                page.locator('#map-interpolation-toggle').uncheck()
                self.assertEqual(page.locator('#map .leaflet-image-layer').count(), 0)
                page.locator('#map-interpolation-toggle').check()
                self.assertEqual(page.locator('#map .leaflet-image-layer').count(), 1)
                self.assertEqual(page.evaluate("document.getElementById('stream-visualization').data[0].colorbar.orientation"), 'h')
                self.assertIn('2 of 3 rows', page.locator('#csv-shape-summary').inner_text())
                self.assertEqual(page.locator('#csv-dataset-select option').count(), 2)
                self.assertTrue(page.evaluate("document.getElementById('trend-chart').data.some(trace => trace.type === 'scatter')"))
                self.assertTrue(page.evaluate("document.getElementById('stream-visualization').data.some(trace => trace.type === 'heatmap')"))
                box = page.locator('#boxplot-chart .boxlayer path.box').first
                box.scroll_into_view_if_needed()
                bounds = box.bounding_box()
                box.hover(position={'x': bounds['width'] * 0.3, 'y': bounds['height'] * 0.4}, force=True)
                page.wait_for_function("!document.getElementById('boxplot-tooltip').classList.contains('is-hidden')")
                tooltip = page.locator('#boxplot-tooltip').inner_text()
                for label in ('Q1', 'Median', 'Q3', 'Maximum', 'Mean', 'IQR', 'Sample count', 'Lower whisker', 'Upper whisker'):
                    self.assertIn(label, tooltip)
                page.mouse.move(0, 0)
                page.wait_for_function("document.getElementById('boxplot-tooltip').classList.contains('is-hidden')")
                page.locator('[data-boxplot-grouping="month"]').click()
                page.wait_for_function("document.getElementById('boxplot-chart').layout.xaxis.title.text === 'Month'")
                self.assertEqual(page.locator('#boxplot-statistics').count(), 0)
                self.assertTrue(page.evaluate("typeof window.Chart === 'undefined' && !!window.Plotly && !!window.L"))
                self.assertEqual(page.locator('#boxplot-chart canvas').count(), 0)
                point = page.locator('#boxplot-chart .scatterlayer .point').first
                point.scroll_into_view_if_needed()
                point.hover(force=True)
                page.wait_for_function("!document.getElementById('boxplot-tooltip').classList.contains('is-hidden')")
                self.assertIn('Sample count', page.locator('#boxplot-tooltip').inner_text())
                self.assertEqual(page.locator('#boxplot-chart .hoverlayer').text_content().strip(), '')
                page.mouse.move(0, 0)
                with page.expect_download() as download:
                    page.locator('#boxplot-chart .modebar-btn[data-title="Download plot as a PNG"]').click()
                self.assertTrue(download.value.suggested_filename.endswith('.png'))
                first = page.locator('#csv-dataset-select option').first.get_attribute('value')
                page.select_option('#csv-dataset-select', first)
                page.wait_for_url('**/?data=*')
                page.wait_for_function("window.NCHOE_DASHBOARD_DATA?.activeFile === 'first.csv'")
                page.wait_for_function("document.getElementById('trend-chart')?.data?.length")
                import tempfile
                from pathlib import Path
                page.screenshot(path=str(Path(tempfile.gettempdir()) / 'opengeostreams-dashboard-preview.png'), full_page=True)
                page.locator('#csv-reset-button').click()
                page.wait_for_url('**/?cleared=*')
                self.assertEqual(page.locator('#csv-dataset-select option').count(), 1)
                self.assertFalse(page.evaluate('window.NCHOE_DASHBOARD_DATA.records.length'))
                self.assertEqual(errors, [])
            finally:
                browser.close()


class DataFrameConcatTests(unittest.TestCase):
    def frame(self):
        return pd.DataFrame({
            "Parameter": ["t.coliform", "Total Coliform"],
            "Value": [10, 20], "Location": ["Station", "Station"],
            "Latitude": [30.7, 30.7], "Longitude": [76.7, 76.7],
            "Year": [2024, 2024], "Unit": [pd.NA, "MPN/100mL"],
        })

    def test_combine_and_plot_without_mutating_inputs(self):
        frame = self.frame()
        original = frame.copy(deep=True)
        first = ogs.from_dataframe(frame)
        combined = ogs.concat([first, frame])
        pd.testing.assert_frame_equal(frame, original)
        self.assertEqual(first.loaded_rows, 2)
        self.assertEqual(combined.loaded_rows, 4)
        self.assertEqual(combined.total_rows, 4)
        self.assertEqual(combined.remaining_rows, 0)
        self.assertEqual(combined.data.SrNo.tolist(), [1, 2, 3, 4])
        self.assertEqual(combined.data.Value.tolist(), ["10", "20", "10", "20"])
        self.assertEqual(combined.describe().loc["Total Coliform", "count"], 4)
        self.assertEqual(len(combined._dashboard_data["records"]), 4)
        self.assertIsNone(combined._interpolation)
        self.assertTrue(combined.plot_trend(parameter="Total Coliform").data)
        combined.data.loc[0, "Value"] = "999"
        self.assertEqual(first.data.loc[0, "Value"], "10")

    def test_no_400_row_limit_for_frames(self):
        frame = pd.concat([self.frame()] * 250, ignore_index=True)
        self.assertEqual(ogs.from_dataframe(frame).loaded_rows, 500)

    def test_reject_invalid_inputs(self):
        for items in ([], [123]):
            with self.assertRaises((TypeError, ValueError)):
                ogs.concat(items)
        with self.assertRaises(ValueError):
            ogs.from_dataframe(pd.DataFrame())
        with self.assertRaises(ValueError):
            ogs.from_dataframe(self.frame().drop(columns="Parameter"))
        with self.assertRaises(TypeError):
            ogs.from_dataframe([])


class DistributionStatisticsTests(unittest.TestCase):
    def test_quartiles_and_outliers_match_boxes(self):
        data = ogs.from_dataframe(pd.DataFrame({
            "Parameter": ["pH"] * 5, "Value": [1, 2, 3, 4, 100],
            "Location": ["A"] * 5, "Latitude": [30.7] * 5,
            "Longitude": [76.7] * 5, "Year": [2024] * 5,
        }))
        figure = data.plot_distribution()
        stats = figure.layout.meta["boxplotStatistics"][0]
        for key, expected in {"count": 5, "min": 1, "q1": 2, "median": 3, "q3": 4,
                              "max": 100, "iqr": 2, "mean": 22, "lowerWhisker": 1,
                              "upperWhisker": 4}.items():
            self.assertEqual(stats[key], expected)
        self.assertEqual(list(figure.data[0].q1), [2])
        self.assertEqual(list(figure.data[0].upperfence), [4])
        self.assertEqual(figure.data[1].customdata[-1][-1], 100)
        empty = data.plot_distribution(parameter="missing")
        self.assertEqual(empty.layout.meta["boxplotStatistics"], [])


class ImportAndStreamTests(unittest.TestCase):
    def test_conversions_and_limit(self):
        frame = pd.read_csv(io.BytesIO(CSV))
        excel = io.BytesIO()
        frame.to_excel(excel, index=False)
        for name, payload in [('river.csv', CSV), ('river.tsv', frame.to_csv(index=False, sep='\t').encode()), ('river.json', frame.to_json(orient='records').encode()), ('river.xlsx', excel.getvalue())]:
            with self.subTest(name=name):
                dataset = process_uploaded_csv(name, payload, rows=2)
                self.assertEqual(dataset.summary['loadedRows'], 2)
                self.assertEqual(dataset.summary['totalRows'], 3)
        for name, payload in [('image.png', b'fake'), ('fake.csv', b'not a table'), ('binary.csv', b'\x00\x01')]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                process_uploaded_csv(name, payload)

    def test_wide_excel_report(self):
        frame = pd.DataFrame({
            "Name of Sampling Point": [None, "Station A", "Station B"],
            "Latitude": [None, 30.7, 30.8], "Longitude": [None, 76.7, 76.8],
            "Date and Timestamp": [None, None, None],
            "Source": ["river-2024.pdf"] * 3,
            "BOD (mg/l)": [100, "3.0-0.32", "0"],
            "Total Coliform (MPN/100ml)": [None, 200, 300],
        })
        output = io.BytesIO()
        frame.to_excel(output, index=False)
        dataset = process_uploaded_csv("river.xlsx", output.getvalue())
        self.assertEqual(dataset.loaded_rows, 5)
        self.assertEqual(dataset.data.iloc[0]["Parameter"], "BOD (Min)")
        self.assertEqual(dataset.data.iloc[0]["NumericValue"], 0.32)
        self.assertEqual(dataset.data.iloc[1]["NumericValue"], 3)
        self.assertEqual(dataset.data.iloc[3]["NumericValue"], 0)
        self.assertTrue(dataset.data["Date"].str.contains("2024").all())
        self.assertIn("Total Coliform", dataset.data["Parameter"].tolist())
        self.assertEqual(dataset.data.iloc[2]["Unit"], "MPN/100ml")

    def test_annual_weather_total_and_deduplication(self):
        import json
        from unittest.mock import patch
        from opengeostreams.opengeostreams.plots import _weather_precipitation
        data = pd.DataFrame({"Location": ["A", "A"], "Latitude": [30.7, 30.7],
                             "Longitude": [76.7, 76.7], "Date": ["[01-01-2024, 31-12-2024]"] * 2})
        response = json.dumps({"daily": {"time": ["2024-01-01", "2024-02-01"], "precipitation_sum": [10, 20]}}).encode()
        with patch("opengeostreams.opengeostreams.server.fetch_weather_data", return_value=(200, "application/json", response)):
            rain = _weather_precipitation(data)
        self.assertEqual(len(rain), 1)
        self.assertEqual(rain.iloc[0]["NumericValue"], 30)

    def test_missing_breakdown_and_uploaded_extent(self):
        from unittest.mock import patch
        from opengeostreams.opengeostreams import pipeline
        dataset = process_uploaded_csv("river.csv", CSV)
        self.assertEqual(sum(dataset.summary["missingByColumn"].values()), dataset.summary["missingValueCount"])
        mask = {"extent": {"minLatitude": 10, "maxLatitude": 11, "minLongitude": 10, "maxLongitude": 11}}
        with patch.object(pipeline, "load_river_mask", return_value=mask), patch.object(pipeline, "GRID_ROWS", 4), patch.object(pipeline, "GRID_COLUMNS", 4):
            result = pipeline.build_interpolation_data(dataset._dashboard_data, output_path=None)
        self.assertIsNone(result["riverMask"])
        self.assertGreater(result["extent"]["minLatitude"], 30)
        self.assertTrue(result["surfaces"]["allYears"])
        self.assertTrue(any(value is not None for value in result["surfaces"]["allYears"][0]["grid"]["values"]))

    def test_eight_column_csv_does_not_gain_year(self):
        payload = b"Parameter,Value,Location,Latitude,Longitude,Date,Unit,Source\npH,7,A,30.7,76.7,01-01-2024,,report-2024.pdf\n"
        dataset = process_uploaded_csv("river.csv", payload)
        self.assertEqual(dataset.summary["columnCount"], 8)
        self.assertEqual(dataset.summary["sourceColumnCount"], 8)
        self.assertNotIn("Year", dataset.summary["missingByColumn"])

    def test_missing_cells_stay_grey(self):
        payload = CSV + b'pH,,C,30.72,76.72,01-01-2024\n'
        dataset = process_uploaded_csv('river.csv', payload)
        figure = dataset.plot_stream(parameter='pH')
        self.assertIn('C', figure.data[0].y)
        mask = np.asarray(figure.data[1].z)
        self.assertTrue(np.isfinite(mask).any())
        self.assertEqual(figure.data[1].hoverinfo, 'skip')
        labels = np.asarray(figure.data[0].text)
        self.assertTrue((labels[np.isfinite(mask)] == '').all())
        dataset.data['NumericValue'] = np.nan
        empty = dataset.plot_stream(parameter='pH')
        self.assertTrue((np.asarray(empty.data[1].z) == 1).all())
        self.assertEqual(len(empty.data[1].y), 3)


class GeneralRiverInterpolationTests(unittest.TestCase):
    def dataset(self):
        return ogs.from_dataframe(pd.DataFrame({
            "Parameter": ["pH", "pH", "pH", "BOD"], "Value": [6, 8, 10, 2],
            "Location": ["Upstream", "Upstream", "Duplicate sensor", "Far station"],
            "Latitude": [-3.0, -3.1, -3.1, -10.0],
            "Longitude": [-60.0, -60.1, -60.1, -70.0], "Year": [2024] * 4,
        }))

    def test_coordinate_grouping_and_parameter_extent(self):
        from opengeostreams.opengeostreams import pipeline
        data = self.dataset()
        with patch.object(pipeline, "GRID_ROWS", 5), patch.object(pipeline, "GRID_COLUMNS", 5):
            data.interpolate(max_distance_km=30)
        surfaces = data._interpolation["surfaces"]["allYears"]
        ph = next(surface for surface in surfaces if surface["parameter"] == "pH")
        bod = next(surface for surface in surfaces if surface["parameter"] == "BOD")
        self.assertEqual(ph["pointCount"], 2)
        self.assertEqual(sorted(point["value"] for point in ph["samplePoints"]), [6, 9])
        self.assertGreater(ph["grid"]["extent"]["minLatitude"], -4)
        self.assertEqual(ph["grid"]["maxDistanceKm"], 30)
        self.assertIn("no spatial interpolation", bod["method"])
        self.assertIsNone(data._interpolation["riverMask"])

    def test_no_coordinates_and_invalid_distance(self):
        from opengeostreams.opengeostreams import pipeline
        self.assertIsNone(pipeline.interpolation_extent([], None))
        for value in (0, -1, float('nan'), True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.dataset().interpolate(max_distance_km=value)
        data = self.dataset()
        for record in data._dashboard_data["records"]:
            record["hasCoordinates"] = False
        data.interpolate()
        self.assertIsNone(data._interpolation["extent"])
        self.assertEqual(data._interpolation["surfaces"]["allYears"], [])
        self.assertEqual(pipeline.location_group("Before confluence with Ghaggar"), "Before confluence with Ghaggar")


class PngExportTests(unittest.TestCase):
    def test_all_plot_exports(self):
        data = ogs.from_dataframe(pd.DataFrame({
            "Parameter": ["pH"] * 3, "Value": [7, 8, 7.5],
            "Location": ["A", "B", "C"], "Latitude": [30.70, 30.71, 30.72],
            "Longitude": [76.70, 76.71, 76.72], "Year": [2024] * 3,
        }))
        data._interpolation = {"surfaces": {"allYears": [{
            "parameter": "pH", "unit": "", "samplePoints": [],
            "grid": {"rows": 2, "columns": 2, "values": [7, 8, 7.5, 7.2],
                     "extent": {"minLatitude": 30.69, "maxLatitude": 30.73,
                                "minLongitude": 76.69, "maxLongitude": 76.73}},
        }], "yearly": []}}
        with tempfile.TemporaryDirectory() as folder:
            for method in ("plot", "plot_trend", "plot_distribution", "plot_stream", "plot_map"):
                with self.subTest(method=method):
                    destination = Path(folder) / (method + ".png")
                    options = {"open_browser": False} if method == "plot_map" else {}
                    getattr(data, method)(save_path=destination, parameter="pH", **options)
                    with Image.open(destination) as picture:
                        self.assertEqual(picture.format, "PNG")
                        self.assertGreater(picture.width, 100)
                        self.assertGreater(picture.height, 100)
                        self.assertIsNotNone(picture.convert("RGB").getbbox())


if __name__ == "__main__":
    unittest.main()
