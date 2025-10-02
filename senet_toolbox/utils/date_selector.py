import requests
import json
from typing import List
from datetime import datetime
import ipywidgets as widgets
from IPython.display import display
from pystac_client import Client

import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()],
)


def get_available_stac_dates(
    stac_url,
    collection_id,
    bbox,
    start_date,
    end_date,
    extra_query=None,
    filter=None,
):
    """
    Query a STAC endpoint using pystac-client and return a list of available acquisition dates.

    Args:
        stac_url (str): URL of the STAC API.
        collection_id (str): ID of the collection to query.
        bbox (list): [west, south, east, north] bounding box.
        start_date (str): ISO format date string (e.g. "2023-06-01").
        end_date (str): ISO format date string (e.g. "2023-06-30").
        extra_query (dict): Optional STAC query filters (e.g., {"cloud_cover": {"lt": 20}}).

    Returns:
        List of unique `datetime.date` objects.
    """
    logger = logging.getLogger(__name__)
    # Optional pre-check for non-JSON response
    test_response = requests.get(stac_url)
    test_response.raise_for_status()
    content_type = test_response.headers.get("Content-Type", "")
    if "application/json" not in content_type:
        raise ValueError("Unexpected response format (not JSON).")

    # Open STAC client and search
    catalog = Client.open(stac_url)

    if extra_query:
        search = catalog.search(
            collections=[collection_id],
            bbox=bbox,
            datetime=f"{start_date}/{end_date}",
            query=extra_query,
            max_items=100,
        )
    elif filter:
        search = catalog.search(
            collections=[collection_id],
            bbox=bbox,
            datetime=f"{start_date}/{end_date}",
            filter=filter,
            max_items=100,
        )
    else:
        search = catalog.search(
            collections=[collection_id],
            bbox=bbox,
            datetime=f"{start_date}/{end_date}",
            max_items=100,
        )

    items = list(search.items())
    dates = sorted(
        {datetime.fromisoformat(item.datetime.isoformat()).date() for item in items}
    )

    return dates


def get_available_dates(
    start_date: str, end_date: str, bbox: List, max_cloud_cover: int = 20
):
    """
    Get available dates for Sentinel-2 and Sentinel-3 collections within a specified bounding box and date range.
    Returns a dropdown widget with the allowed dates.
    """

    sentinel_3_collection_id = "sentinel-3-sl-2-lst-ntc"
    stac_url = "https://stac.dataspace.copernicus.eu/v1"

    try:
        sentinel_3_dates = get_available_stac_dates(
            stac_url,
            sentinel_3_collection_id,
            bbox,
            start_date,
            end_date,
            extra_query={"eo:cloud_cover": {"lt": max_cloud_cover}},
        )
    except:
        sentinel_3_dates = get_available_stac_dates(
            "https://catalogue.dataspace.copernicus.eu/stac",
            "SENTINEL-3",
            bbox,
            start_date,
            end_date,
            filter={"op": "<=", "args": [{"property": "cloudCover"}, max_cloud_cover]},
        )

    valid_dates = sorted([valid_date for valid_date in set(sentinel_3_dates)])

    dropdown = widgets.Dropdown(
        options=[
            (valid_date.strftime("%Y-%m-%d"), valid_date) for valid_date in valid_dates
        ],
        description="Pick a Date:",
    )
    display(dropdown)
    return dropdown
