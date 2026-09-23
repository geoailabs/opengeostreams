"""Optional, server-side Google Earth Engine station elevation connector."""
import math
import os
import threading

import pandas as pd

ASSET = "COPERNICUS/DEM/GLO30_2024_1"
_LOCK = threading.Lock()


def fetch_elevations(frame, *, project=None):
    """Return unique stations with DSM elevation (metres, EGM2008) and status."""
    project = project or os.environ.get("OPENGEOSTREAMS_EE_PROJECT")
    if not project:
        raise ValueError("Set OPENGEOSTREAMS_EE_PROJECT to your Earth Engine-enabled Google Cloud project ID, then restart the server.")
    try:
        import ee
    except ImportError as error:
        raise ValueError('Install the connector: python -m pip install -e "./opengeostreams[earthengine]"') from error
    stations = frame[["Location", "Latitude", "Longitude"]].drop_duplicates().copy()
    records = []
    points = {}
    for row in stations.to_dict("records"):
        try:
            lat, lon = float(row["Latitude"]), float(row["Longitude"])
            valid = math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180
        except (TypeError, ValueError):
            valid = False
        row.update(elevation_m=None, status="no_data" if valid else "invalid_coordinates", source=ASSET)
        if valid:
            points.setdefault((lat, lon), []).append(len(records))
        records.append(row)
    if points:
        with _LOCK:
            try:
                ee.Initialize(project=project)
                ee.data.setDeadline(60000)
            except Exception as error:
                raise ValueError("Earth Engine initialization failed. Run python -c \"import ee; ee.Authenticate()\" and check project registration and permissions.") from error
            try:
                coordinates = list(points)
                for start in range(0, len(coordinates), 500):
                    batch = coordinates[start:start + 500]
                    features = [ee.Feature(ee.Geometry.Point([lon, lat]), {"station_id": str(start + index)})
                                for index, (lat, lon) in enumerate(batch)]
                    # Select intersecting tiles before mosaicking the global collection.
                    region = ee.Geometry.MultiPoint([[lon, lat] for lat, lon in batch])
                    dem = (ee.ImageCollection(ASSET).filterBounds(region).select("DEM")
                           .mosaic().rename("elevation_m"))
                    result = dem.reduceRegions(collection=ee.FeatureCollection(features),
                                               reducer=ee.Reducer.first().setOutputs(["elevation_m"]),
                                               scale=30, crs="EPSG:4326").getInfo()
                    for feature in result.get("features", []):
                        props = feature["properties"]
                        value = props.get("elevation_m")
                        if isinstance(value, (int, float)) and math.isfinite(value):
                            for index in points[coordinates[int(props["station_id"])]]:
                                records[index].update(elevation_m=float(value), status="ok")
            except Exception as error:
                raise ValueError("Earth Engine elevation request failed. Check network access, project permissions and quota, then retry.") from error
    return pd.DataFrame(records, columns=["Location", "Latitude", "Longitude", "elevation_m", "status", "source"])
