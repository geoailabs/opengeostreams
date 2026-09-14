"""Opengeostreams public API."""

from .dataset import MAX_PAGE_SIZE, RiverDataset, concat, from_dataframe, load_csv

__all__ = ["MAX_PAGE_SIZE", "RiverDataset", "concat", "from_dataframe", "load_csv"]
__version__ = "2.0.0"
