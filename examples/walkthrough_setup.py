"""Shared setup for opengeostreams_walkthrough.ipynb.

Every notebook cell starts with ``from walkthrough_setup import *`` so any cell
can run on its own. Python imports a module once per kernel, so the dataset is
loaded only the first time.
"""
from pathlib import Path

import pandas as pd
from IPython.display import display

import opengeostreams as ogs

ROOT = Path(__file__).resolve().parent.parent
CSV = ROOT / "Datasets" / "consolidated_dataset.csv"
OUTPUT = ROOT / "outputs"
OUTPUT.mkdir(exist_ok=True)
PARAMETER = "pH"

data = ogs.load_csv(CSV, rows="all")

__all__ = ["Path", "pd", "display", "ogs", "ROOT", "CSV", "OUTPUT", "PARAMETER", "data"]
