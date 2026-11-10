"""Pack the India-WRIS river/drain network into a small, bbox-filterable GeoParquet.

Usage: python tools/pack_wris.py data/indiawris/WRIS_Rivers_2024.parquet \
           opengeostreams/opengeostreams/reference_data/indiawris_rivers_2024.parquet [tolerance_deg]

The source file draws its 30,546 lines in great detail (155 MB of geometry in five
row groups), so reading even a small area loads most of it. This keeps only the
columns opengeostreams.network uses, simplifies lines by ``tolerance_deg`` (default
0.0001, about 10 m), sorts them along a Morton curve of 0.1-degree cells and writes
small row groups, so a station area reads a few row groups only.
"""
import sys
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import shapely

SRC, OUT = Path(sys.argv[1]), Path(sys.argv[2])
TOLERANCE = float(sys.argv[3]) if len(sys.argv) > 3 else 0.0001
ROW_GROUP = 500


def morton(ix, iy):
    def spread(v):
        v = v.astype(np.uint64)
        for shift, mask in ((16, 0x0000FFFF0000FFFF), (8, 0x00FF00FF00FF00FF), (4, 0x0F0F0F0F0F0F0F0F),
                            (2, 0x3333333333333333), (1, 0x5555555555555555)):
            v = (v | (v << np.uint64(shift))) & np.uint64(mask)
        return v
    return spread(ix) | (spread(iy) << np.uint64(1))


table = pq.read_table(SRC, columns=["rivname", "layer", "geometry"])
geom = shapely.simplify(shapely.from_wkb(table["geometry"].to_numpy(zero_copy_only=False)), TOLERANCE,
                        preserve_topology=False)
bounds = shapely.bounds(geom)
cx, cy = (bounds[:, 0] + bounds[:, 2]) / 2, (bounds[:, 1] + bounds[:, 3]) / 2
order = np.argsort(morton(((cx + 180) * 10).astype(np.int64), ((cy + 90) * 10).astype(np.int64)), kind="stable")
out = pa.table({
    "rivname": table["rivname"].take(order),
    "layer": table["layer"].take(order),
    "geometry": pa.array(shapely.to_wkb(geom[order]), pa.binary()),
    "xmin": bounds[order, 0], "ymin": bounds[order, 1], "xmax": bounds[order, 2], "ymax": bounds[order, 3],
})
pq.write_table(out, OUT, compression="zstd", compression_level=19, row_group_size=ROW_GROUP)
print(f"wrote {OUT}: {len(out):,} lines, {shapely.get_num_coordinates(geom).sum():,} vertices, "
      f"{OUT.stat().st_size / 1e6:.1f} MB (tolerance {TOLERANCE} deg)")
