from typing import List
import json
import datetime
from pathlib import Path
import pandas as pd
import importlib.resources as pkg_resources
import senet_toolbox.static_data


def load_lut():
    """Loads the WorldCover10m lookup table from the package data directory."""
    with (
        pkg_resources.files(senet_toolbox.static_data)
        .joinpath("WorldCover10m_2020_LUT.csv")
        .open("r") as file
    ):
        lut = pd.read_csv(file, sep=";")
    return lut


def dump_area_date_info(date: datetime.date, bbox: List, out_dir: str | Path):
    """Dumps area information to a Json file."""
    # Serialize to a JSON-compatible format
    data = {
        "date": date.isoformat(),  # Convert date to string
        "bbox": bbox,
    }

    # Save to file
    with open(Path(out_dir) / "params.json", "w") as f:
        json.dump(data, f)


def read_area_date_info(dir: str | Path) -> dict:
    """Reads area information from a Json file."""
    with open(Path(dir) / "params.json", "r") as f:
        data = json.load(f)

    # Parse values
    date = datetime.date.fromisoformat(data["date"])
    bbox = data["bbox"]
    return date, bbox
