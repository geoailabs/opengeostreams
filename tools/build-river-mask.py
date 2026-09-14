import argparse
import json
from pathlib import Path

import geopandas as gpd
from shapely.geometry import Point, box
from shapely.strtree import STRtree


def build_parser():
    parser = argparse.ArgumentParser(description="Build a river width mask grid from a GeoPackage.")
    parser.add_argument("--gpkg", required=True, help="Path to the river GeoPackage")
    parser.add_argument("--output", required=True, help="Output JSON path")
    parser.add_argument("--min-lat", type=float, required=True)
    parser.add_argument("--max-lat", type=float, required=True)
    parser.add_argument("--min-lon", type=float, required=True)
    parser.add_argument("--max-lon", type=float, required=True)
    parser.add_argument("--rows", type=int, required=True)
    parser.add_argument("--cols", type=int, required=True)
    parser.add_argument("--layer", default="segments")
    return parser


def repair_geometry(geometry):
    if geometry is None or geometry.is_empty:
        return geometry

    try:
        repaired = geometry.buffer(0)
        if repaired is not None and not repaired.is_empty:
            return repaired
    except Exception:
        pass

    return geometry


def clip_geometry(geometry, boundary):
    if geometry is None or geometry.is_empty:
        return geometry

    try:
        clipped = geometry.intersection(boundary)
        if clipped is not None and not clipped.is_empty:
            return clipped
    except Exception:
        pass

    try:
        repaired = repair_geometry(geometry)
        clipped = repaired.intersection(boundary)
        if clipped is not None and not clipped.is_empty:
            return clipped
    except Exception:
        pass

    return None


def main():
    args = build_parser().parse_args()
    gpkg_path = Path(args.gpkg)
    output_path = Path(args.output)

    study_bounds = box(args.min_lon, args.min_lat, args.max_lon, args.max_lat)
    frame = gpd.read_file(gpkg_path, layer=args.layer, bbox=study_bounds.bounds)
    if frame.empty:
        raise SystemExit("No river segments intersect the requested study extent.")

    frame = frame[frame.geometry.notnull() & frame["width_m"].notnull()].copy()
    frame["geometry"] = frame.geometry.apply(repair_geometry)
    frame = frame[frame.intersects(study_bounds)]
    if frame.empty:
        raise SystemExit("No valid river polygons with width values intersect the requested study extent.")

    frame["geometry"] = frame.geometry.apply(lambda geometry: clip_geometry(geometry, study_bounds))
    frame = frame[~frame.geometry.is_empty].copy()
    frame = frame[frame.geometry.notnull()].copy()

    geometries = list(frame.geometry)
    widths = [float(value) for value in frame["width_m"]]
    tree = STRtree(geometries)
    geometry_index = {id(geometry): index for index, geometry in enumerate(geometries)}

    min_width = min(widths)
    max_width = max(widths)
    width_span = max(max_width - min_width, 1e-9)

    lat_step = (args.max_lat - args.min_lat) / max(args.rows - 1, 1)
    lon_step = (args.max_lon - args.min_lon) / max(args.cols - 1, 1)

    mask_values = []
    active_cells = 0

    for row_index in range(args.rows):
        latitude = args.max_lat - (row_index * lat_step)
        for column_index in range(args.cols):
            longitude = args.min_lon + (column_index * lon_step)
            cell = box(
                longitude - (lon_step / 2),
                latitude - (lat_step / 2),
                longitude + (lon_step / 2),
                latitude + (lat_step / 2),
            )
            hits = tree.query(cell)
            hit_widths = []
            for geometry in hits:
                if isinstance(geometry, (int,)):
                    geometry = geometries[geometry]
                elif hasattr(geometry, "item") and isinstance(geometry.item(), int):
                    geometry = geometries[int(geometry.item())]
                if geometry.intersects(cell):
                    hit_widths.append(widths[geometry_index[id(geometry)]])

            if not hit_widths:
                mask_values.append(0)
                continue

            active_cells += 1
            width_value = max(hit_widths)
            normalized = (width_value - min_width) / width_span
            adjusted = normalized ** 0.5
            mask_values.append(round(max(0.12, adjusted), 4))

    payload = {
        "generatedFrom": str(gpkg_path),
        "layer": args.layer,
        "rows": args.rows,
        "cols": args.cols,
        "extent": {
            "minLatitude": round(args.min_lat, 6),
            "maxLatitude": round(args.max_lat, 6),
            "minLongitude": round(args.min_lon, 6),
            "maxLongitude": round(args.max_lon, 6),
        },
        "widthStats": {
            "minWidthM": round(min_width, 4),
            "maxWidthM": round(max_width, 4),
        },
        "activeCellCount": active_cells,
        "maskValues": mask_values,
    }

    output_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"Created {output_path} with {active_cells} active river cells.")


if __name__ == "__main__":
    main()
