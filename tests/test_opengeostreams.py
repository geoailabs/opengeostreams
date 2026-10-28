"""OpenGeoStreams regression suite. Browser and PNG tests need optional dependencies."""
import json
import os
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

    def test_browser_elevation_order(self):
        from playwright.sync_api import sync_playwright
        self.upload(rows="all")
        with sync_playwright() as p:
            browser = p.chromium.launch(channel='chrome', headless=True)
            try:
                page = browser.new_page()
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(self.base)
                page.wait_for_function("document.getElementById('stream-visualization').data?.length", timeout=90000)
                # Elevation ordering applies to the A-Z view (a single drain keeps its upstream order).
                page.wait_for_function("!document.getElementById('stream-channel').disabled && !/Matching/.test(document.getElementById('channel-note').textContent)", timeout=90000)
                if page.locator('#stream-channel option[value="all"]').count():
                    page.select_option('#stream-channel', 'all')
                page.wait_for_function("document.getElementById('stream-visualization').data?.length && !document.getElementById('stream-visualization').layout.meta?.streamChannel", timeout=90000)
                page.evaluate("""window.dispatchEvent(new CustomEvent('station-elevations', {detail: [
                    {Location:'A',Latitude:30.70,Longitude:76.70,elevation_m:100,status:'ok'},
                    {Location:'B',Latitude:30.71,Longitude:76.71,elevation_m:200,status:'ok'}]}))""")
                page.wait_for_function("document.getElementById('stream-visualization').layout.yaxis.categoryarray[0] === 'B'")
                self.assertIn('#1', page.locator('#stream-visualization').evaluate('(el) => el.layout.yaxis.ticktext[0]'))
                self.assertEqual(page.locator('.elevation-rank-marker').count(), 0)
                self.assertNotIn('200.0 m', page.locator('.leaflet-tooltip-pane').inner_text())
                page.evaluate("""window.dispatchEvent(new CustomEvent('station-elevations', {detail: [
                    {Location:'A',Latitude:30.70,Longitude:76.70,elevation_m:0,status:'ok'}]}))""")
                page.wait_for_function("document.getElementById('stream-visualization').layout.yaxis.categoryarray[0] === 'A'")
                self.assertEqual(page.locator('.elevation-rank-marker').count(), 0)
                self.assertEqual(errors, [])
            finally:
                browser.close()

    def test_elevation_endpoint_cache(self):
        result = self.upload(rows="all")
        dataset_id = self.get('/datasets')['activeId']
        dataset = self.httpd.datasets[dataset_id]['dataset']
        expected = pd.DataFrame([{"Location": "A", "elevation_m": 0, "status": "ok"}])
        self.httpd.datasets[dataset_id]['interpolation_lock'].acquire()
        self.addCleanup(self.httpd.datasets[dataset_id]['interpolation_lock'].release)
        with patch.object(dataset, 'fetch_elevations', return_value=expected) as fetch:
            with urllib.request.urlopen(self.base + '/api/elevations?id=' + dataset_id, timeout=5) as response:
                first = json.load(response)
            self.assertEqual(first['stations'][0]['elevation_m'], 0)
            self.assertEqual(first, self.get('/api/elevations?id=' + dataset_id))
            fetch.assert_called_once()

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
                page.locator('#analysis-body').evaluate('(el) => el.scrollTop += 80')
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
                page.locator('#csv-all-rows').uncheck()
                page.locator('#csv-row-limit').fill('2')
                page.locator('#csv-file').set_input_files([
                    {'name':'first.csv','mimeType':'text/csv','buffer':CSV},
                    {'name':'second.csv','mimeType':'text/csv','buffer':CSV.replace(b'pH,7', b'pH,6')}
                ])
                page.locator('#csv-upload-button').click()
                page.wait_for_url('**/?data=*')
                page.wait_for_function("['trend-chart','boxplot-chart','stream-visualization'].every(id => document.getElementById(id)?.data?.length)", timeout=90000)
                self.assertLessEqual(page.locator('.layers-panel').bounding_box()['width'], 340)
                self.assertGreater(page.locator('.map-area').bounding_box()['width'], 950)
                screening = page.locator('.suitability-panel').bounding_box()
                map_box = page.locator('#map').bounding_box()
                self.assertLessEqual(map_box['y'] - (screening['y'] + screening['height']), 90)
                self.assertTrue(page.locator('#parameter-scale').evaluate('(el) => !!el.closest(".map-toolbar")'))
                self.assertLess(page.locator('#parameter-scale').bounding_box()['height'], 130)
                for chart_id in ('trend-chart', 'boxplot-chart', 'stream-visualization'):
                    box = page.locator('#' + chart_id).bounding_box()
                    self.assertGreaterEqual(box['width'], 380)
                    self.assertLessEqual(box['width'], 900)
                    self.assertTrue(page.locator('#' + chart_id).evaluate('(el) => !!el.closest(".analysis-drawer")'))
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
                self.assertIn('of 3 rows', page.locator('#csv-shape-summary').inner_text())
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
                page.locator(f'.layer-row[data-id="{first}"]').click()
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
        from opengeostreams.opengeostreams import interpolation
        dataset = process_uploaded_csv("river.csv", CSV)
        self.assertEqual(sum(dataset.summary["missingByColumn"].values()), dataset.summary["missingValueCount"])
        result = interpolation.build_interpolation_data(dataset._dashboard_data["records"])
        self.assertFalse(result["network"]["found"])
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
    """Without a river map near the stations the library falls back to straight-line IDW."""

    def dataset(self):
        return ogs.from_dataframe(pd.DataFrame({
            "Parameter": ["pH", "pH", "pH", "BOD"], "Value": [6, 8, 10, 2],
            "Location": ["Upstream", "Upstream", "Duplicate sensor", "Far station"],
            "Latitude": [-3.0, -3.1, -3.1, -10.0],
            "Longitude": [-60.0, -60.1, -60.1, -70.0], "Year": [2024] * 4,
        }))

    def test_one_value_per_station_and_straight_line_fallback(self):
        data = self.dataset()
        with patch.dict(os.environ, {"OPENGEOSTREAMS_OFFLINE": "1"}):
            _, summary = data.interpolate(max_distance_km=30)
        surfaces = data._interpolation["surfaces"]["allYears"]
        ph = next(surface for surface in surfaces if surface["parameter"] == "pH")
        bod = next(surface for surface in surfaces if surface["parameter"] == "BOD")
        self.assertEqual(ph["pointCount"], 2)
        self.assertEqual(sorted(point["value"] for point in ph["samplePoints"]), [7, 10])
        self.assertEqual(ph["methodKey"], "straight_idw")
        self.assertIn("straight lines", ph["warning"])
        self.assertGreater(ph["grid"]["extent"]["minLatitude"], -4)
        self.assertEqual(ph["grid"]["maxDistanceKm"], 30)
        self.assertIsNotNone(ph["validation"]["rmse"])
        self.assertIn("no spatial interpolation", bod["method"])
        self.assertFalse(summary["networkFound"])
        self.assertTrue(summary["warnings"])

    def test_no_coordinates_and_invalid_arguments(self):
        for value in (0, -1, float('nan'), True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.dataset().interpolate(max_distance_km=value)
        with self.assertRaises(ValueError):
            self.dataset().interpolate(junction_weights="largest")
        data = self.dataset()
        for record in data._dashboard_data["records"]:
            record["hasCoordinates"] = False
        data.interpolate()
        self.assertIsNone(data._interpolation["extent"])
        self.assertEqual(data._interpolation["surfaces"]["allYears"], [])
        from opengeostreams.opengeostreams import pipeline
        self.assertEqual(pipeline.location_group("Before confluence with Ghaggar"), "Before confluence with Ghaggar")


class RiverInterpolationTests(unittest.TestCase):
    """Along-river IDW on a small synthetic network.

    Main River runs south from 30.20 to 30.00 N along 76.00 E. Side Drain joins it from
    the east at 30.10 N, and Test Canal leaves it westwards at 30.15 N (an off-take).
    """

    STATIONS = [("S1 upstream", 30.18, 76.0, 10.0), ("S2 below off-take", 30.12, 76.0, 20.0),
                ("S3 canal", 30.15, 75.95, 12.0), ("D1 drain", 30.10, 76.05, 100.0),
                ("S4 below junction", 30.05, 76.0, 30.0)]

    def setUp(self):
        patcher = patch.dict(os.environ, {"OPENGEOSTREAMS_OFFLINE": "1"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def lines(self, canal=True, area=False, rejoin=False):
        import geopandas as gpd
        from shapely.geometry import LineString
        rows = [("Main River", LineString([(76.0, 30.20), (76.0, 30.00)]), 90.0),
                ("Side Drain", LineString([(76.10, 30.10), (76.0005, 30.10)]), 10.0)]
        if canal:
            rows.append(("Test Canal", LineString([(76.0004, 30.15), (75.90, 30.15)]), float("nan")))
        if rejoin:  # drawn from the river below back to the river above: water would flow in a circle
            rows.append(("Loop Canal", LineString([(76.0004, 30.03), (76.03, 30.06), (76.0004, 30.17)]), float("nan")))
        frame = gpd.GeoDataFrame({"name": [row[0] for row in rows], "network_name": [row[0] for row in rows],
                                  "kind": [""] * len(rows)}, geometry=[row[1] for row in rows], crs="EPSG:4326")
        if area:
            frame["upstream_area"] = [row[2] for row in rows]
        return frame

    def dataset(self, stations=None, parameter="pH"):
        stations = stations or self.STATIONS
        return ogs.from_dataframe(pd.DataFrame([
            {"Parameter": parameter, "Value": value, "Location": name, "Latitude": lat, "Longitude": lon,
             "Date": "01-01-2024"} for name, lat, lon, value in stations]))

    def graph(self, data, **options):
        from opengeostreams.opengeostreams import interpolation
        lines = options.pop("lines", None)
        return interpolation.build_river_graph(data.data, None, lines=self.lines() if lines is None else lines,
                                               buffer_km=20, use_elevation=False, **options)

    def relation(self, graph, target, station):
        position = graph.stations[target]
        distance, relation, share = graph.relations([graph.stations[station]], np.array([position[0]]),
                                                    np.array([position[1]]))
        return float(distance[0, 0]), int(relation[0, 0]), float(share[0, 0])

    def test_flow_direction_canal_split_and_water_share(self):
        from opengeostreams.opengeostreams import interpolation as interp
        graph = self.graph(self.dataset())
        self.assertFalse(graph.tree)
        self.assertEqual(graph.info["splits"], 1)
        self.assertEqual(graph.info["junctionWeights"], "equal")
        self.assertEqual(graph.info["outlets"][0]["directionMethod"], "direction the lines are drawn in")
        # The canal takes water from above the off-take only.
        distance, relation, share = self.relation(graph, "S3 canal", "S1 upstream")
        self.assertEqual((relation, share), (interp.DOWNSTREAM, 1.0))
        self.assertAlmostEqual(distance / 1000, 3.3 + 4.8, delta=0.3)
        self.assertEqual(self.relation(graph, "S3 canal", "S2 below off-take")[1], 0)
        self.assertEqual(self.relation(graph, "S2 below off-take", "S3 canal")[1], 0)
        # A station on a separate drain never counts for one on another branch.
        self.assertEqual(self.relation(graph, "D1 drain", "S2 below off-take")[1], 0)
        # Below the junction, each side supplies half of the water.
        self.assertEqual(self.relation(graph, "S4 below junction", "D1 drain")[1:], (interp.DOWNSTREAM, 0.5))
        self.assertEqual(self.relation(graph, "S2 below off-take", "S4 below junction")[1:], (interp.UPSTREAM, 0.5))
        self.assertEqual(self.relation(graph, "S4 below junction", "S1 upstream")[1:], (interp.DOWNSTREAM, 0.5))

    def test_estimates_use_only_flow_connected_stations(self):
        from opengeostreams.opengeostreams import interpolation as interp
        data = self.dataset()
        graph = self.graph(data)
        payload = interp.build_interpolation_data(data._dashboard_data["records"], graph=graph, max_distance_km=20)
        (surface,) = payload["surfaces"]["allYears"]
        self.assertEqual(surface["methodKey"], "river_idw")
        self.assertEqual(surface["usedStationCount"], 5)
        self.assertEqual(payload["network"]["source"], "custom network")
        # Hidden in turn: the canal station is predicted from S1 alone, the drain station from S4 alone.
        checked = {item["location"]: item["predicted"] for item in surface["validation"]["stations"]}
        self.assertEqual(checked["S3 canal"], 10.0)
        self.assertEqual(checked["D1 drain"], 30.0)
        self.assertIsNotNone(surface["validation"]["rmse"])
        self.assertIn("Canals run in rotation", surface["warning"])
        # A point on the drain between D1 and the junction only mixes D1 and S4.
        edge, t = graph.stations["D1 drain"]
        names = sorted(graph.stations)
        distance, relation, share = graph.relations([graph.stations[name] for name in names],
                                                    np.array([edge]), np.array([t / 2]))
        values = np.array([dict((row[0], row[3]) for row in self.STATIONS)[name] for name in names])
        estimate, confidence = interp._idw(distance, relation, share, values, 20000, 2.0)
        self.assertTrue(30 < estimate[0] < 100)
        connected = {names[column] for column in np.nonzero(share[0] > 0)[0]}
        self.assertEqual(connected, {"D1 drain", "S4 below junction"})
        self.assertTrue(0 < confidence[0] <= 1)
        grid = surface["grid"]
        painted = [value for value in grid["values"] if value is not None]
        self.assertTrue(painted)
        self.assertTrue(all(0 <= value <= 100 for value in grid["confidence"] if value is not None))
        compact = interp.compact_payload(payload)["surfaces"]["allYears"][0]["grid"]
        self.assertEqual(compact["encoding"], "sparse")
        self.assertEqual(len(compact["cells"]), len(painted))
        self.assertNotIn("values", compact)

    def test_catchment_area_weights_junctions(self):
        graph = self.graph(self.dataset(), lines=self.lines(canal=False, area=True))
        self.assertEqual(graph.info["junctionWeights"], "area")
        self.assertAlmostEqual(self.relation(graph, "S4 below junction", "D1 drain")[2], 0.1, places=5)
        self.assertAlmostEqual(self.relation(graph, "S4 below junction", "S2 below off-take")[2], 0.9, places=5)
        order = self.graph(self.dataset(), lines=self.lines(canal=False), junction_weights="order")
        self.assertEqual(order.info["junctionWeights"], "order")
        self.assertAlmostEqual(self.relation(order, "S4 below junction", "D1 drain")[2], 0.5, places=5)

    def test_canal_that_closes_a_cycle_is_dropped(self):
        graph = self.graph(self.dataset(), lines=self.lines(canal=False, rejoin=True))
        self.assertEqual(graph.info["droppedChannels"], ["Loop Canal"])
        self.assertTrue(graph.tree)

    def test_downstream_label_moves_station_below_the_junction(self):
        stations = self.STATIONS[:2] + [("MAIN RIVER D/S OF SIDE DRAIN", 30.1003, 76.0, 25.0)] + self.STATIONS[3:]
        graph = self.graph(self.dataset(stations), lines=self.lines(canal=False))
        info = {item["location"]: item for item in graph.info["stations"]}
        self.assertIn("just below the Side Drain junction", info["MAIN RIVER D/S OF SIDE DRAIN"]["positionFrom"])
        self.assertEqual(self.relation(graph, "MAIN RIVER D/S OF SIDE DRAIN", "D1 drain")[1], 1)

    def test_min_max_ranges_become_intervals_year_by_year(self):
        from opengeostreams.opengeostreams import interpolation
        data = ogs.from_dataframe(pd.DataFrame({
                "Parameter": ["BOD (Max)", "BOD (Min)", "BOD", "BOD", "BOD", "BOD", "BOD (Max)", "BOD (Min)", "BOD (Max)"],
            "Value": [9, 1, 6, 8, 8, 8, 20, 10, 40],
            "Location": ["A"] * 6 + ["B", "B", "C"], "Latitude": [30.1] * 6 + [30.15] * 2 + [30.18],
            "Longitude": [76.0] * 9,
            "Date": ["01-01-2023", "01-01-2023", "01-01-2023", "01-01-2024", "01-02-2024", "01-03-2024",
                     "01-01-2024", "01-01-2024", "01-01-2024"]}))
        groups = interpolation.station_values(data._dashboard_data["records"], yearly=False)
        self.assertEqual({key[1] for key in groups}, {"BOD"})  # one map per parameter, not one per Min/Max
        points = {point["location"]: point for point in groups[("all_years", "BOD")][0]}
        # A: ordinary readings win in 2023 (6, the Min/Max are ignored) and 2024 (8); years count equally.
        self.assertEqual((points["A"]["lower"], points["A"]["upper"], points["A"]["kind"]), (7.0, 7.0, "reading"))
        self.assertEqual(points["A"]["yearCount"], 2)
        self.assertEqual((points["B"]["lower"], points["B"]["upper"], points["B"]["kind"]), (10.0, 20.0, "range"))
        self.assertEqual((points["C"]["lower"], points["C"]["upper"], points["C"]["kind"]), (None, 40.0, "max only"))

    def test_interval_runs_use_min_for_lower_and_max_for_upper(self):
        stations = [("S1 upstream", 30.18, 76.0, 10.0), ("S2 below off-take", 30.12, 76.0, 20.0),
                    ("S4 below junction", 30.05, 76.0, 30.0)]
        rows = [{"Parameter": "pH", "Value": value, "Location": name, "Latitude": lat, "Longitude": lon,
                 "Date": "01-01-2024"} for name, lat, lon, value in stations]
        rows += [{"Parameter": "pH (Min)", "Value": 12, "Location": "R range", "Latitude": 30.15, "Longitude": 76.0,
                  "Date": "01-01-2024"},
                 {"Parameter": "pH (Max)", "Value": 28, "Location": "R range", "Latitude": 30.15, "Longitude": 76.0,
                  "Date": "01-01-2024"},
                 {"Parameter": "pH (Max)", "Value": 50, "Location": "M max only", "Latitude": 30.08, "Longitude": 76.0,
                  "Date": "01-01-2024"}]
        from opengeostreams.opengeostreams import interpolation
        data = ogs.from_dataframe(pd.DataFrame(rows))
        graph = self.graph(data, lines=self.lines(canal=False))
        payload = interpolation.build_interpolation_data(data._dashboard_data["records"], graph=graph,
                                                         max_distance_km=20)
        (surface,) = payload["surfaces"]["allYears"]
        self.assertTrue(surface["interval"])
        self.assertEqual(surface["runs"]["lower"]["usedStationCount"], 4)   # the Max-only station is left out
        self.assertEqual(surface["runs"]["upper"]["usedStationCount"], 5)
        self.assertIn("Only a Max is reported at M max only", surface["warning"])
        lower = {item["location"]: item["observed"] for item in surface["runs"]["lower"]["validation"]["stations"]}
        upper = {item["location"]: item["observed"] for item in surface["runs"]["upper"]["validation"]["stations"]}
        self.assertEqual((lower["R range"], upper["R range"]), (12.0, 28.0))
        grid = surface["grid"]
        pairs = [(low, high) for low, high in zip(grid["lower"], grid["upper"]) if low is not None and high is not None]
        self.assertTrue(pairs)
        self.assertTrue(all(low <= high + 1e-9 for low, high in pairs))
        self.assertTrue(any(high > low + 1e-6 for low, high in pairs))
        self.assertEqual(grid["values"], grid["upper"])
        compact = interpolation.compact_payload(payload)["surfaces"]["allYears"][0]["grid"]
        self.assertEqual(len(compact["cellLower"]), len(compact["cellUpper"]))
        from opengeostreams.opengeostreams.plots import interpolation_figure
        data._interpolation = payload
        self.assertIn("lower bound", interpolation_figure(data, parameter="pH", bound="lower").layout.title.text)
        self.assertIn("upper bound", interpolation_figure(data, parameter="pH (Max)").layout.title.text)

    def test_auto_distance_picks_the_smallest_leave_one_out_error(self):
        from opengeostreams.opengeostreams import interpolation
        # Values follow distance along Main River, so nearby stations predict each other.
        stations = [(f"M{index}", 30.195 - index * 0.015, 76.0, 10.0 + 3 * index) for index in range(12)]
        data = self.dataset(stations)
        graph = self.graph(data, lines=self.lines(canal=False))
        payload = interpolation.build_interpolation_data(data._dashboard_data["records"], graph=graph)
        selection = payload["method"]["distanceSelection"]
        self.assertEqual(selection["mode"], "auto")
        self.assertEqual([row["maxDistanceKm"] for row in selection["candidates"]], [2.0, 4.0, 8.0, 16.0, 32.0, None])
        best = min(row["relativeError"] for row in selection["candidates"])
        chosen = next(row for row in selection["candidates"] if row["maxDistanceKm"] == selection["chosenKm"])
        self.assertEqual(chosen["relativeError"], best)
        self.assertTrue(selection["beatsBaseline"])
        self.assertEqual(payload["method"]["maxDistanceKm"], selection["chosenKm"])
        (surface,) = payload["surfaces"]["allYears"]
        self.assertGreater(surface["validation"]["skill"], 0)
        # A fixed limit skips the search; too few stations fall back to 8 km.
        fixed = interpolation.build_interpolation_data(data._dashboard_data["records"], graph=graph, max_distance_km=5)
        self.assertEqual(fixed["method"]["distanceSelection"]["mode"], "fixed")
        self.assertEqual(fixed["method"]["maxDistanceKm"], 5.0)
        few = self.dataset(stations[:2])
        sparse = interpolation.build_interpolation_data(few._dashboard_data["records"], graph=self.graph(few))
        self.assertEqual(sparse["method"]["maxDistanceKm"], interpolation.FALLBACK_DISTANCE_KM)
        # No limit: every flow-connected station counts, and confidence still fades with distance.
        unlimited = interpolation.choose_distance(
            interpolation.station_values(data._dashboard_data["records"], yearly=False), None, candidates=(None,))
        self.assertIsNone(unlimited["chosenKm"])

    def test_advanced_kriging_keeps_the_smaller_error(self):
        from opengeostreams.opengeostreams import interpolation
        rng = np.random.default_rng(3)
        stations = [(f"M{index}", 30.19 - index * 0.012, 76.0, 10 + index + rng.random()) for index in range(12)]
        stations += [(f"D{index}", 30.10, 76.09 - index * 0.012, 40 + index + rng.random()) for index in range(6)]
        data = self.dataset(stations)
        graph = self.graph(data, lines=self.lines(canal=False))
        records = data._dashboard_data["records"]
        with patch.object(interpolation, "MIN_KRIGING_STATIONS", 10):
            payload = interpolation.build_interpolation_data(records, graph=graph, max_distance_km=20, advanced=True)
            split = interpolation.build_interpolation_data(records, graph=self.graph(data), max_distance_km=20,
                                                           advanced=True)
        (surface,) = payload["surfaces"]["allYears"]
        methods = {item["method"]: item for item in surface["candidates"]}
        self.assertEqual(set(methods), {"river_idw", "tail_up", "tail_down", "mixed"})
        best = min(item["rmseOnCommonStations"] for item in methods.values())
        self.assertEqual(methods[surface["methodKey"]]["rmseOnCommonStations"], best)
        self.assertTrue(any(value is not None for value in surface["grid"]["values"]))
        self.assertIn("tree-shaped", split["surfaces"]["allYears"][0]["notes"][0])
        default = interpolation.build_interpolation_data(records, graph=graph, max_distance_km=20, advanced=True)
        self.assertIn("at least 50 stations", default["surfaces"]["allYears"][0]["notes"][0])


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


class ElevationAndAllRowsTests(unittest.TestCase):
    def test_all_rows_and_custom_limit(self):
        payload = b"Parameter,Value,Location,Latitude,Longitude,Year\n" + b"pH,7,A,30,76,2024\n" * 405
        self.assertEqual(len(process_uploaded_csv("river.csv", payload)), 405)
        self.assertEqual(len(process_uploaded_csv("river.csv", payload, rows=2)), 2)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "river.csv"
            path.write_bytes(payload)
            self.assertEqual(len(ogs.load_csv(path)), 400)
            self.assertEqual(len(ogs.load_csv(path, rows="all")), 405)

    def test_elevations_deduplicate_validate_and_preserve_zero(self):
        from unittest.mock import MagicMock
        from opengeostreams.opengeostreams.elevation import fetch_elevations
        ee = MagicMock()
        dem = ee.ImageCollection.return_value.filterBounds.return_value.select.return_value.mosaic.return_value.rename.return_value
        dem.reduceRegions.return_value.getInfo.return_value = {"features": [
            {"properties": {"station_id": "0", "elevation_m": 0}},
            {"properties": {"station_id": "1", "elevation_m": -12}},
            {"properties": {"station_id": "2"}}]}
        frame = pd.DataFrame({"Location": ["A", "A", "B", "C", "D", "E"],
                              "Latitude": [30, 30, 30, 31, 32, 100],
                              "Longitude": [76, 76, 76, 77, 78, 79]})
        with patch.dict("sys.modules", {"ee": ee}):
            result = fetch_elevations(frame, project="test-project")
        self.assertEqual(len(result), 5)
        self.assertEqual(result.elevation_m.tolist()[:3], [0, 0, -12])
        self.assertEqual(result.status.tolist(), ["ok", "ok", "ok", "no_data", "invalid_coordinates"])
        ee.Geometry.MultiPoint.assert_called_once_with([[76.0, 30.0], [77.0, 31.0], [78.0, 32.0]])
        ee.ImageCollection.return_value.filterBounds.assert_called_once_with(ee.Geometry.MultiPoint.return_value)
        self.assertEqual(ee.Geometry.Point.call_count, 3)
        ee.Geometry.Point.assert_any_call([76.0, 30.0])
        self.assertEqual(dem.reduceRegions.call_args.kwargs["scale"], 30)
        ee.Initialize.assert_called_once_with(project="test-project")

    def test_missing_project_explained(self):
        from opengeostreams.opengeostreams.elevation import fetch_elevations
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(ValueError, "OPENGEOSTREAMS_EE_PROJECT"):
                fetch_elevations(pd.DataFrame())


class ChannelNetworkTests(unittest.TestCase):
    """Drain/river grouping and upstream ordering with a small synthetic network."""

    def setUp(self):
        # Never call the elevation service from tests; individual tests patch it.
        patcher = patch.dict(os.environ, {"OPENGEOSTREAMS_OFFLINE": "1"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_water_body_names_in_station_labels(self):
        from opengeostreams.opengeostreams.network import parse_water_body, name_similarity
        cases = {
            "HUDIARA DRAIN AT VILL. DHAHUKE (WHERE IT ENTERS PAKISTAN), PUNJAB": "Hudiara Drain",
            "DHANAULA DRAIN FALLING INTO LASSARA DRAIN NEAR VILL. DHUNAS": "Dhanaula Drain",
            "POINT SOURSE BUDHA NALLAH, PUNJAB": "Budha Nallah",
            "BRIDGE ON TUNG DHAB DRAIN, FATENGARH CHURIAN ROAD": "Tung Dhab Drain",
            "RIVER BEAS U/S BEFORE CONF. OF MANALSU NALLAH": "Beas",
            "NCP05 - River Ghaggar D/S of N-choe": "Ghaggar",
            "NCP06 - N-choe before confluence with Ghaggar": "N-Choe",
            "3BRD": "",
            "DRAIN AT VILL SAGRA DIST": "",
        }
        for label, expected in cases.items():
            self.assertEqual(parse_water_body(label), expected, label)
        self.assertGreaterEqual(name_similarity("Budha Nallah", "Budda Nala"), 0.8)
        self.assertGreaterEqual(name_similarity("Sutlej", "Satluj"), 0.8)
        self.assertGreaterEqual(name_similarity("Lassara Drain", "Lissara Nala"), 0.8)
        self.assertLess(name_similarity("Attawa Choa", "Tangori Choe"), 0.8)

    def test_label_names_match_beyond_snap_limit_and_group_unmapped_names(self):
        from opengeostreams.opengeostreams.network import build_channel_network
        extra = pd.DataFrame([
            # 5.5 km from Test Drain: too far to snap, but named in the label.
            {"Parameter": "pH", "Value": 7, "Location": "TEST DRAIN AT VILLAGE", "Latitude": 30.05, "Longitude": 76.05, "Date": "01-01-2024"},
            # A drain that is not in the network: grouped by name, spelling variants merged.
            {"Parameter": "pH", "Value": 7, "Location": "HUDIARA DRAIN AT BRIDGE", "Latitude": 31.5, "Longitude": 74.9, "Date": "01-01-2024"},
            {"Parameter": "pH", "Value": 7, "Location": "OUTLET OF HUDIARA DRAIN", "Latitude": 31.6, "Longitude": 74.95, "Date": "01-01-2024"},
        ])
        result = build_channel_network(self.frame(extra), network=self.network())
        drain = next(channel for channel in result["channels"] if channel["name"] == "Test Drain")
        named = next(station for station in drain["stations"] if station["location"] == "TEST DRAIN AT VILLAGE")
        self.assertEqual(named["assignedBy"], "name in station label")
        hudiara = next(channel for channel in result["channels"] if channel["name"] == "Hudiara Drain")
        self.assertEqual(len(hudiara["stations"]), 2)
        self.assertFalse(hudiara["ordered"])
        self.assertNotIn("HUDIARA DRAIN AT BRIDGE", [item["location"] for item in result["unassigned"]])

    def test_aliases_and_local_names(self):
        from opengeostreams.opengeostreams import network
        self.assertEqual(network.canonical_name("Attawa Choa"), "N-Choe")
        self.assertEqual(network.canonical_name("Budha Nallah"), "Budha Nallah")
        with tempfile.TemporaryDirectory() as folder:
            aliases = Path(folder) / "aliases.csv"
            aliases.write_text("alias,name\nOld Test Drain,Test Drain\n", encoding="utf-8")
            with patch.dict(os.environ, {"OPENGEOSTREAMS_ALIASES": str(aliases)}):
                self.assertEqual(network.canonical_name("Old Test Drain"), "Test Drain")
        # Labels never use the WRIS name, so the local name is shown (like WRIS "Tangori Choe" = N-choe).
        rows = [("LOCAL CHOE AT BRIDGE", 30.0005, 76.05), ("SITE 2", 30.0005, 76.12), ("SITE 3", 30.0005, 76.15)]
        frame = pd.DataFrame([{"Parameter": "pH", "Value": 7, "Location": name, "Latitude": lat, "Longitude": lon,
                               "Date": "01-01-2024"} for name, lat, lon in rows])
        result = network.build_channel_network(frame, network=self.network())
        channel = result["channels"][0]
        self.assertEqual(channel["name"], "Local Choe")
        self.assertEqual(channel["networkName"], "Test Drain")

    def test_terrain_elevation_decides_direction_and_labels_break_ties(self):
        from opengeostreams.opengeostreams import network
        # Make the west end the lowest: flow now runs west, away from Big River.
        fake = lambda points, timeout=10: {(round(x, 5), round(y, 5)): 400 + 500 * (x - 76.0) for x, y in points}
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OPENGEOSTREAMS_OFFLINE", None)
            with patch.object(network, "fetch_point_elevations", fake):
                result = network.build_channel_network(self.frame(), network=self.network())
        drain = next(channel for channel in result["channels"] if channel["name"] == "Test Drain")
        self.assertEqual(drain["outletMethod"], "lowest end (terrain elevation)")
        self.assertEqual([station["location"] for station in drain["stations"]], ["Down", "Middle", "Up"])
        self.assertEqual(result["elevationSource"], "Open-Meteo elevation API (Copernicus DEM)")
        ordered = [{"location": "River X D/S of town", "distanceToOutletKm": 10.4},
                   {"location": "River X U/S town", "distanceToOutletKm": 10.0}]
        network._apply_label_hints(ordered)
        self.assertEqual(ordered[0]["location"], "River X U/S town")

    def network(self):
        import geopandas as gpd
        from shapely.geometry import LineString
        return gpd.GeoDataFrame({
            "name": ["Test Drain", "Test Drain", "Big River"],
            "kind": ["minor", "minor", "major"],
        }, geometry=[
            LineString([(76.0, 30.0), (76.1, 30.0)]),
            LineString([(76.1, 30.0), (76.2, 30.0)]),
            LineString([(76.2, 29.8), (76.2, 30.2)]),
        ], crs="EPSG:4326")

    def frame(self, extra=None):
        rows = [
            ("Down", 30.0005, 76.19), ("Up", 30.001, 76.02), ("Middle", 30.001, 76.11), ("Far away", 31.0, 77.0),
        ]
        frame = pd.DataFrame([{"Parameter": "pH", "Value": 7 + index, "Location": name, "Latitude": lat,
                               "Longitude": lon, "Date": "01-01-2024"} for index, (name, lat, lon) in enumerate(rows)])
        if extra is not None:
            frame = pd.concat([frame, extra], ignore_index=True)
        return frame

    def test_stations_are_ordered_upstream_to_confluence(self):
        from opengeostreams.opengeostreams.network import build_channel_network
        result = build_channel_network(self.frame(), network=self.network())
        drain = next(channel for channel in result["channels"] if channel["name"] == "Test Drain")
        self.assertEqual([station["location"] for station in drain["stations"]], ["Up", "Middle", "Down"])
        self.assertEqual([station["order"] for station in drain["stations"]], [1, 2, 3])
        self.assertEqual(drain["joins"], "Big River")
        self.assertEqual(drain["outletMethod"], "confluence")
        distances = [station["distanceToOutletKm"] for station in drain["stations"]]
        self.assertEqual(distances, sorted(distances, reverse=True))
        self.assertEqual([item["location"] for item in result["unassigned"]], ["Far away"])
        self.assertIsNotNone(result["unassigned"][0]["nearest"])

    def test_distance_limit_and_file_column(self):
        from opengeostreams.opengeostreams.network import build_channel_network
        # "Down" is ~55 m from the line; "Up" and "Middle" are ~110 m away.
        strict = build_channel_network(self.frame(), network=self.network(), max_distance_km=0.08)
        self.assertEqual(sorted(item["location"] for item in strict["unassigned"]), ["Far away", "Middle", "Up"])
        named = self.frame(pd.DataFrame([{"Parameter": "pH", "Value": 7, "Location": "Named", "Latitude": 30.03,
                                          "Longitude": 76.05, "Date": "01-01-2024", "Drain": "Test Drain"}]))
        dataset = ogs.from_dataframe(named)
        self.assertIn("Water Body", dataset.data)
        result = build_channel_network(dataset.data, network=self.network())
        drain = next(channel for channel in result["channels"] if channel["name"] == "Test Drain")
        self.assertIn("Named", [station["location"] for station in drain["stations"]])
        self.assertEqual(next(s for s in drain["stations"] if s["location"] == "Named")["assignedBy"], "file column")
        for value in (0, -1, float("nan"), True):
            with self.assertRaises(ValueError):
                build_channel_network(self.frame(), network=self.network(), max_distance_km=value)

    def test_stream_figure_and_dashboard_endpoint(self):
        import tempfile
        from pathlib import Path
        dataset = ogs.from_dataframe(self.frame())
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "network.parquet"
            self.network().to_parquet(path)
            table = dataset.assign_channels(network_path=path)
            self.assertEqual(table.loc[table["Channel"] == "Test Drain", "Location"].tolist(), ["Up", "Middle", "Down"])
            figure = dataset.plot_stream(parameter="pH", channel="test-drain")
            self.assertEqual(list(figure.data[0].y), ["Up", "Middle", "Down"])
            grouped = dataset.plot_stream(parameter="pH", group_by_channel=True)
            self.assertEqual(list(grouped.data[0].y)[:3], ["Up", "Middle", "Down"])
            self.assertEqual(grouped.layout.meta["streamGroups"][-1]["id"], "unassigned")
            with self.assertRaises(ValueError):
                dataset.plot_stream(parameter="pH", channel="no-such-drain")
            os.environ["OPENGEOSTREAMS_NETWORK"] = str(path)
            try:
                fresh = ogs.from_dataframe(self.frame())
                httpd = server.create_server(port=0, dataset=fresh)
                worker = threading.Thread(target=httpd.serve_forever, daemon=True)
                worker.start()
                try:
                    base = f"http://127.0.0.1:{httpd.server_address[1]}"
                    dataset_id = httpd.active_dataset
                    payload = json.loads(urllib.request.urlopen(f"{base}/api/network?id={dataset_id}").read())
                    self.assertTrue(payload["available"])
                    self.assertEqual(payload["channels"][0]["stations"][0]["location"], "Up")
                    self.assertIsNotNone(payload["channels"][0]["geometry"])
                    figure = json.loads(urllib.request.urlopen(
                        f"{base}/api/figure?id={dataset_id}&kind=stream&parameter=pH&year=all&channel=test-drain").read())
                    self.assertEqual(figure["data"][0]["y"], ["Up", "Middle", "Down"])
                finally:
                    httpd.shutdown()
                    httpd.server_close()
                    worker.join()
            finally:
                os.environ.pop("OPENGEOSTREAMS_NETWORK", None)


class StationLabelMergeTests(unittest.TestCase):
    """Label variants of the same site get one name; different sites never merge."""

    def rows(self, entries):
        return [{"Location": name, "Latitude": str(lat), "Longitude": str(lon)} for name, lat, lon in entries]

    def test_fragments_and_pasted_coordinates_merge(self):
        from opengeostreams.opengeostreams.pipeline import merge_duplicate_locations
        rows = self.rows([
            ("POINT SOURSE BUDHA NALLAH, PUNJAB", 30.920155, 75.978229),
            ("SOURSE BUDHA NALLAH, PUNJAB 30.973", 30.920155, 75.978229),
            ("OUTLET OF NADIALA DRAIN INTO DHAKANSU NALLAH, PUNJAB", 30.509242, 76.595725),
            ("OF NADIALA INTO DHAKANSU PUNJAB", 30.508634, 76.596340),
        ])
        merges = merge_duplicate_locations(rows)
        self.assertEqual({item["name"] for item in merges},
                         {"POINT SOURSE BUDHA NALLAH, PUNJAB", "OUTLET OF NADIALA DRAIN INTO DHAKANSU NALLAH, PUNJAB"})
        self.assertEqual(len({row["Location"] for row in rows}), 2)

    def test_different_sites_stay_separate(self):
        from opengeostreams.opengeostreams.pipeline import merge_duplicate_locations
        rows = self.rows([
            ("RIVER BEAS AT U/S MANALI", 32.243187, 77.189176),
            ("RIVER BEAS AT D/S MANALI", 32.243187, 77.189176),
            ("RIVER BEAS AT MANALI", 32.243187, 77.189176),
            ("MAHANADI MUHANA NORTH (5 KM FROM SHORE)", 20.3, 86.7),
            ("MAHANADI MUHANA SOUTH (5 KM FROM SHORE)", 20.3, 86.7),
            ("MAHANADI MUHANA (5 KM FROM SHORE)", 20.3, 86.7),
            ("SECTOR 36 DRAIN", 30.70, 76.75),
            ("SECTOR 36 DRAIN", 30.70, 76.75),
            ("DRAIN", 30.70, 76.75),
            ("RIVER X AT TOWN BRIDGE", 30.0, 76.0),
            ("RIVER X AT TOWN BRIDGE NORTH GATE", 30.05, 76.0),   # 5.5 km away
        ])
        merges = merge_duplicate_locations(rows)
        merged_names = [name for item in merges for name in item["merged"]]
        self.assertNotIn("RIVER BEAS AT U/S MANALI", merged_names + [item["name"] for item in merges if "D/S" in item["name"]])
        self.assertFalse(any("NORTH" in item["name"] and any("SOUTH" in name for name in item["merged"]) for item in merges))
        self.assertFalse(any("SOUTH" in item["name"] and any("NORTH" in name for name in item["merged"]) for item in merges))
        self.assertNotIn("DRAIN", merged_names)            # single-word labels never merge
        self.assertNotIn("RIVER X AT TOWN BRIDGE NORTH GATE", merged_names)
        self.assertNotIn("RIVER X AT TOWN BRIDGE", merged_names)
        locations = {row["Location"] for row in rows}
        self.assertIn("RIVER BEAS AT U/S MANALI", locations)
        self.assertIn("RIVER BEAS AT D/S MANALI", locations)

    def test_dataset_option_and_summary(self):
        frame = pd.DataFrame([
            {"Parameter": "pH", "Value": 7, "Location": "POINT SOURCE BUDHA NALLAH", "Latitude": 30.92, "Longitude": 75.97, "Date": "01-01-2024"},
            {"Parameter": "pH", "Value": 8, "Location": "SOURCE BUDHA NALLAH 30.973", "Latitude": 30.92, "Longitude": 75.97, "Date": "01-01-2025"},
        ])
        dataset = ogs.from_dataframe(frame)
        self.assertEqual(dataset.data["Location"].nunique(), 1)
        self.assertEqual(dataset.summary["mergedLocations"][0]["merged"], ["SOURCE BUDHA NALLAH 30.973"])
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "stations.csv"
            frame.to_csv(path, index=False)
            self.assertEqual(ogs.load_csv(path, rows="all", merge_stations=False).data["Location"].nunique(), 2)
            self.assertEqual(ogs.load_csv(path, rows="all").data["Location"].nunique(), 1)


class CombineDatasetsTests(unittest.TestCase):
    """Combining imported files (ogs.concat) from the Python API and the dashboard."""

    def frame(self, location, value, date):
        return pd.DataFrame([{"Parameter": "pH", "Value": value, "Location": location,
                              "Latitude": 30.7, "Longitude": 76.7, "Date": date}])

    def test_concat_name_station_and_csv_round_trip(self):
        first = ogs.from_dataframe(self.frame("NCM03 - Sector 83", 7, "01-01-2018"))
        second = ogs.from_dataframe(self.frame("Sector 83 drain outfall", 8, "01-01-2024"))
        combined = ogs.concat([first, second], name="sector83.csv", station="Sector 83")
        self.assertEqual(combined.data["Location"].unique().tolist(), ["Sector 83"])
        self.assertEqual(combined._dashboard_data["activeFile"], "sector83.csv")
        self.assertEqual(len(first), 1)  # inputs unchanged
        self.assertEqual(first.data["Location"].iloc[0], "NCM03 - Sector 83")
        text = combined.to_csv()
        self.assertTrue(text.startswith("SrNo,Parameter,Unit,Date,Value,Data Source,Location,Latitude,Longitude"))
        again = ogs.from_dataframe(pd.read_csv(io.StringIO(text)))
        self.assertEqual(len(again), 2)
        with tempfile.TemporaryDirectory() as folder:
            written = combined.to_csv(Path(folder) / "out" / "sector83.csv")
            self.assertTrue(written.is_file())
        with self.assertRaises(ValueError):
            ogs.concat([first, second], station="   ")

    def test_dashboard_combine_and_download(self):
        httpd = server.create_server(port=0)
        worker = threading.Thread(target=httpd.serve_forever, daemon=True)
        worker.start()
        try:
            base = f"http://127.0.0.1:{httpd.server_address[1]}"
            ids = []
            for name, frame in (("a.csv", self.frame("Site A", 7, "01-01-2020")), ("b.csv", self.frame("Site B", 8, "01-01-2021"))):
                dataset = ogs.from_dataframe(frame)
                key = f"id-{name}"
                httpd.datasets[key] = server.dataset_entry(dataset, name)
                ids.append(key)

            def post(body):
                request = urllib.request.Request(f"{base}/combine-csv", data=json.dumps(body).encode(),
                                                 headers={"Content-Type": "application/json"}, method="POST")
                try:
                    with urllib.request.urlopen(request) as response:
                        return response.status, json.loads(response.read())
                except urllib.error.HTTPError as error:
                    return error.code, json.loads(error.read())

            status, result = post({"ids": ids, "name": "both", "station": None})
            self.assertEqual(status, 200)
            self.assertEqual(result["fileName"], "both.csv")
            self.assertEqual(result["summary"]["recordCount"], 2)
            self.assertEqual(result["summary"]["combinedFrom"], ["a.csv", "b.csv"])
            self.assertEqual(httpd.active_dataset, result["id"])
            status, single = post({"ids": ids, "name": "", "station": "One site"})
            self.assertEqual(status, 200)
            self.assertEqual(single["summary"]["locationCount"], 1)
            self.assertTrue(single["fileName"].startswith("combined_"))
            self.assertEqual(post({"ids": ids[:1]})[0], 400)
            self.assertEqual(post({"ids": [ids[0], ids[0]]})[0], 400)
            self.assertEqual(post({"ids": ids + ["missing"]})[0], 400)
            self.assertEqual(post({"ids": ids, "station": " "})[0], 400)
            with urllib.request.urlopen(f"{base}/api/download?id={result['id']}") as response:
                self.assertIn('filename="both.csv"', response.headers["Content-Disposition"])
                rows = response.read().decode().splitlines()
            self.assertEqual(len(rows), 3)
            self.assertTrue(rows[0].startswith("SrNo,Parameter"))
        finally:
            httpd.shutdown()
            httpd.server_close()
            worker.join()


class QualityCheckTests(unittest.TestCase):
    def _record(self, parameter, value, location="A", sort_key=202401, file_name="f.csv"):
        return {"locationGroup": location, "parameter": parameter, "numericValue": value, "fileName": file_name,
                "sortKey": sort_key, "year": sort_key // 100, "monthIndex": sort_key % 100, "dateLabel": str(sort_key)}

    def test_rules_status_and_reasons(self):
        from opengeostreams.opengeostreams import qualitycheck as qc
        failing = qc.fit_for_agriculture(pH=9.0, boron_mg_l=1.0, chloride_mg_l=200)
        self.assertEqual(qc.suitability_status("agriculture", failing), "unsafe")
        self.assertEqual(failing["core_reasons"], ["pH 9 outside 6.0-8.5"])
        caution = qc.fit_for_agriculture(pH=7.0, chloride_mg_l=200)
        self.assertEqual(qc.suitability_status("agriculture", caution), "caution")
        self.assertEqual(qc.suitability_status("agriculture", qc.fit_for_agriculture(pH=7.2)), "safe")
        self.assertEqual(qc.suitability_status("agriculture", qc.fit_for_agriculture(chloride_mg_l=10)), "unknown")
        # Faecal coliform overrides total coliform for bathing.
        bathing = qc.fit_for_bathing(total_coliform_mpn_100ml=50, fecal_coliform_mpn_100ml=0)
        self.assertTrue(bathing["fit_core"])

    def test_sample_matching_prefers_plain_reading_and_reports_proxies(self):
        from opengeostreams.opengeostreams import qualitycheck as qc
        records = [self._record("pH (max)", 9.5), self._record("pH", 7.0), self._record("NO3-N", 60)]
        result = qc.evaluate_sample(records, "human_consumption")
        self.assertEqual(result["status"], "safe")
        self.assertIn("pH via pH", result["coverage"]["confirmed"])
        self.assertIn("Nitrate via NO3-N", result["coverage"]["proxy"])

    def test_scales_and_latest_sample(self):
        from opengeostreams.opengeostreams import qualitycheck as qc
        self.assertEqual(qc.scale_key("Boron(B)"), "boron")
        self.assertEqual(qc.scale_key("T-Coliform"), "total_coliform")
        do = qc.scale_definition("aquatic_life", "DO")
        self.assertEqual((qc.scale_status(do, 3.0), qc.scale_status(do, 6.0), qc.scale_status(do, None)), ("unsafe", "safe", "unknown"))
        self.assertIsNone(qc.scale_definition("agriculture", "Colour"))
        self.assertEqual(qc.scale_definition("agriculture", "Total Coliform")["label"], "Total Coliform")
        records = [self._record("pH", 9.5, sort_key=202301), self._record("pH", 7.0, sort_key=202405)]
        self.assertEqual(qc.screen_stations(records, "bathing")[0]["status"], "safe")
        self.assertEqual(qc.screen_stations(records, "bathing", year=2023)[0]["status"], "unsafe")
        self.assertEqual(qc.screen_stations(records, "bathing", month=2)[0]["status"], "unknown")

    def test_dashboard_payload_includes_quality(self):
        dataset = ogs.from_dataframe(pd.DataFrame({
            "Parameter": ["pH", "DO (min)"], "Value": ["9.1", "6"], "Location": ["A", "A"],
            "Latitude": [30.7, 30.7], "Longitude": [76.7, 76.7], "Date": ["01-03-2024", "01-03-2024"]}))
        quality = dataset._dashboard_data["quality"]
        self.assertEqual([item["key"] for item in quality["useCases"]][0], "human_consumption")
        self.assertEqual(quality["scaleKeys"]["DO"], "do")
        (sample,) = quality["samples"]["A"].values()
        self.assertEqual(sample["bathing"]["status"], "unsafe")
        self.assertEqual(sample["bathing"]["reasons"], ["pH 9.1 outside 6.5-8.5"])
