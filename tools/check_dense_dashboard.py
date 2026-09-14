from pathlib import Path
import threading, tempfile
from playwright.sync_api import sync_playwright
from opengeostreams.opengeostreams import server
from unittest.mock import patch

def run():
    d=server.process_uploaded_csv('WQuality_River-Data-2024.xlsx',Path('WQuality_River-Data-2024.xlsx').read_bytes(), rows=1000)
    http=server.create_server(port=0,dataset=d)
    thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(channel='chrome',headless=True)
            page=browser.new_page(viewport={'width':1440,'height':1000})
            errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
            page.goto(f'http://127.0.0.1:{http.server_port}')
            page.wait_for_function("['trend-chart','boxplot-chart','stream-visualization'].every(id => document.getElementById(id)?.data?.length)",timeout=90000)
            page.wait_for_function("!document.getElementById('map-interpolation-legend').hidden",timeout=90000)
            assert 'Date: 1000' in page.locator('#csv-shape-summary').inner_text()
            assert d._interpolation['riverMask'] is None
            extent = d._interpolation['extent']
            assert extent['maxLatitude'] > 34
            for selector in ('#trend-chart .scatterlayer .point', '#trend-chart .barlayer .point path'):
                point = page.locator(selector).first
                point.scroll_into_view_if_needed()
                page.wait_for_timeout(300)
                page.mouse.move(5, 5)
                point.hover(force=True)
                page.wait_for_function("!document.getElementById('trend-tooltip').classList.contains('is-hidden')")
                tooltip = page.locator('#trend-tooltip')
                box = tooltip.bounding_box()
                assert box['x'] >= 0 and box['x'] + box['width'] <= 1440
                assert box['y'] >= 0 and box['y'] + box['height'] <= 1000
                assert 'Period' in tooltip.inner_text()
                assert page.locator('#trend-chart .hoverlayer').text_content().strip() == ''
            assert page.locator('#stream-pagination').is_visible()
            before=page.locator('#stream-page-label').inner_text()
            page.locator('#stream-next').click()
            assert page.locator('#stream-page-label').inner_text()!=before
            assert page.locator('#stream-visualization').bounding_box()['height'] < 650
            assert page.locator('.leaflet-tooltip').count() <= 2
            page.locator('[data-basemap=minimal]').click()
            assert page.locator('.minimal-basemap').count() > 0
            page.locator('#stream-visualization').screenshot(path=str(Path(tempfile.gettempdir())/'dense-stream.png'))
            page.locator('#trend-chart').screenshot(path=str(Path(tempfile.gettempdir())/'dense-trend.png'))
            page.locator('.sidebar').evaluate('(el) => el.scrollTop = 0')
            page.screenshot(path=str(Path(tempfile.gettempdir())/'dense-dashboard.png'))
            print('Weather:',page.locator('#weather-status').inner_text())
            print('Range note:',page.locator('#range-note').inner_text())
            page.set_viewport_size({'width':390,'height':844})
            page.wait_for_timeout(500)
            assert page.evaluate('document.documentElement.scrollWidth') <= 390
            assert not errors,errors
            browser.close()
    finally:
        http.shutdown();http.server_close();thread.join()
if __name__=='__main__':run()
