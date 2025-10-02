from typing import List, Tuple
import datetime
import time
import os
from pathlib import Path
import openeo
import hashlib
import logging
from shapely.geometry import box
from shapely import to_geojson
from dateutil.relativedelta import relativedelta
from senet_toolbox.workflows import sentinel2_preprocessing

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()],
)


def wait_and_download(job, path, max_wait=6000, poll_interval=10):
    """
    Wait for an OpenEO job to finish and download the result.
    Retries if result is not immediately ready after finishing.
    """
    start_time = time.time()

    while True:
        status = job.status()
        logging.info(f"Job {job.job_id} status: {status}")
        if status in ["running", "queued", "created"]:
            if time.time() - start_time > max_wait:
                logging.warning(f"Timeout waiting for job {job.job_id}")
                return
            time.sleep(poll_interval)
        elif status == "finished":
            # Try downloading with retry in case results aren't ready yet
            for retry in range(5):
                try:
                    job.get_results().download_file(path)
                    logging.info(f"Downloaded result for job {job.job_id} to {path}")
                    return
                except openeo.rest.job.JobFailedException as e:
                    logging.error(f"Job {job.job_id} failed: {e}")
                    return
                except Exception as e:
                    logging.warning(f"Result not ready yet for job {job.job_id}: {e}")
                    time.sleep(5)
            logging.error(
                f"Failed to download results for job {job.job_id} after retries."
            )
            return
        else:
            logging.error(f"Job {job.job_id} failed or unknown status: {status}")
            return


def prepare_data_cubes(
    connection: openeo.Connection,
    bbox: List | Tuple,
    date: datetime.date | datetime.datetime,
    sentinel2_search_range: int = 3,
    out_dir: str = "./data",
):
    """
    Prepare and cache Sentinel-2 and Sentinel-3 data cubes for a given AOI and date.

    This function retrieves and preprocesses remote sensing datasets from the OpenEO platform:
    - Sentinel-2: Optical bands and biophysical variables (e.g., LAI, FAPAR, FCOVER, CCC, CWC)
    - Sentinel-3: Land Surface Temperature (LST), confidence and viewing angle
    - WorldCover 2021: Land cover classification
    - Copernicus DEM: Digital elevation model for spatial resampling

    All data is masked, reduced, and resampled as appropriate, and stored locally as NetCDF or GeoTIFF files.
    Existing outputs are reused to avoid unnecessary recomputation.

    Args:
        connection (openeo.Connection): An active OpenEO connection.
        bbox (List[float] | Tuple[float, float, float, float]): Bounding box (west, south, east, north).
        date (datetime.date | datetime.datetime): Center date for data search and acquisition.
        sentinel2_search_range (int, optional): Number of days before and after `date` for to search for cloud free Sentinel-2. Defaults to 3.
        out_dir (str, optional): Directory to store the cached files. Defaults to "./data".

    Returns:
        Tuple[str, str, str, str, str, float]:
            - s2_path (str): Path to saved Sentinel-2 data cube (.nc)
            - s3_path (str): Path to saved Sentinel-3 data cube (.nc)
            - worldcover_path (str): Path to WorldCover 2021 GeoTIFF
            - dem_s2_path (str): Path to DEM resampled to Sentinel-2 resolution (.tif)
            - dem_s3_path (str): Path to DEM resampled to Sentinel-3 resolution (.tif)
            - acq_time (float): Sentinel-3 acquisition hour (UTC)
    """

    # Convert date to string for path name
    date_str = str(date).replace("-", "")

    # Generate a hash based on the bounding box coordinates
    bbox_hash = hashlib.md5(str(bbox).encode()).hexdigest()[
        :8
    ]  # Short hash for path name

    # Base directory includes date and bbox hash
    base_dir = os.path.join(out_dir, f"{date_str}_{bbox_hash}")
    os.makedirs(base_dir, exist_ok=True)

    # Define output file paths
    s2_path = Path(base_dir) / "s2_data.nc"
    s3_path = Path(base_dir) / "s3_data.nc"
    dem_s2_path = Path(base_dir) / f"{date_str}_ELEV.tif"
    dem_s3_path = Path(base_dir) / "meteo_dem.tif"
    worldcover_path = Path(base_dir) / "WordlCover2021.tif"

    # Prepare AOI and date range
    aoi = dict(zip(["west", "south", "east", "north"], bbox))
    bbox_polygon = eval(to_geojson(box(*bbox)))
    time_window = [
        str(date + relativedelta(days=-sentinel2_search_range)),
        str(date + relativedelta(days=+sentinel2_search_range)),
    ]

    # for jobs
    jobs = []
    # Define bands
    s2_bands = [
        "B02",
        "B03",
        "B04",
        "B05",
        "B06",
        "B07",
        "B08",
        "B8A",
        "B11",
        "B12",
        "SCL",
        "sunZenithAngles",
    ]

    # Load Biopar data
    fapar = sentinel2_preprocessing.get_biopar(
        connection, "FAPAR", time_window, bbox_polygon
    )
    lai = sentinel2_preprocessing.get_biopar(
        connection, "LAI", time_window, bbox_polygon
    )
    fcover = sentinel2_preprocessing.get_biopar(
        connection, "FCOVER", time_window, bbox_polygon
    )
    ccc = sentinel2_preprocessing.get_biopar(
        connection, "CCC", time_window, bbox_polygon
    )
    cwc = sentinel2_preprocessing.get_biopar(
        connection, "CWC", time_window, bbox_polygon
    )

    # Load Sentinel-2 cube and merge with Biopar
    s2_cube = connection.load_collection(
        "SENTINEL2_L2A", spatial_extent=aoi, temporal_extent=time_window, bands=s2_bands
    )
    s2_reference_cube = connection.load_collection(
        "SENTINEL2_L2A", spatial_extent=aoi, temporal_extent=time_window, bands=["B02"]
    ).reduce_dimension(dimension="t", reducer="first")

    merged = (
        fapar.merge_cubes(lai)
        .merge_cubes(fcover)
        .merge_cubes(ccc)
        .merge_cubes(cwc)
        .merge_cubes(s2_cube)
    )

    # Apply cloud and shadow mask using SCL (keep only class 4 and 5 = vegetation/bare)
    mask = ~((merged.band("SCL") == 4) | (merged.band("SCL") == 5))
    masked = merged.mask(mask)

    # Reduce time dimension by selecting the first valid observation
    s2_best_pixel = masked.reduce_dimension(dimension="t", reducer="first")

    if not os.path.exists(s2_path):
        s2_job = s2_best_pixel.create_job(out_format="netcdf")
        s2_job.start()
        jobs.append((s2_job, s2_path))
    else:
        logging.info("Cached Sentinel 2 data cube found. Skipping download.")

    # Load Sentinel-3 data
    s3_cube = connection.load_collection(
        "SENTINEL3_SLSTR_L2_LST",
        spatial_extent=aoi,
        temporal_extent=[str(date), str(date)],
        bands=["LST", "confidence_in", "viewZenithAngles"],
        properties={
            "timeliness": lambda x: x == "NT",
            "orbitDirection": lambda x: x == "DESCENDING",
        },
    )
    sentinel3_acq_time = float(
        s3_cube.metadata.temporal_dimension.extent[0].split("T")[1].split(":")[0]
    )
    if not os.path.exists(s3_path):
        s3_job = s3_cube.create_job(out_format="netcdf")
        s3_job.start()
        jobs.append((s3_job, s3_path))

    # === Extract and save viewZenithAngles (VZA) separately ===
    vza_path = Path(base_dir) / f"{date_str}_VZA.tif"

    if not os.path.exists(vza_path):
        vza_cube = s3_cube.band("viewZenithAngles").reduce_dimension(
            dimension="t", reducer="first"
        )
        vza_resampled = vza_cube.resample_cube_spatial(
            s2_reference_cube, method="bilinear"
        )
        vza_job = vza_resampled.create_job(out_format="GTiff")
        vza_job.start()
        jobs.append((vza_job, vza_path))
    else:
        logging.info("Cached VZA cube found. Skipping download.")

    dem_cube = connection.load_collection(
        "COPERNICUS_30", spatial_extent=aoi
    ).reduce_dimension(dimension="t", reducer="first")

    dem_resampled_s2_cube = dem_cube.resample_cube_spatial(
        s2_reference_cube, method="bilinear"
    )
    dem_resampled_s3_cube = dem_cube.resample_cube_spatial(
        s3_cube.reduce_dimension(dimension="t", reducer="first"), method="bilinear"
    )
    if not os.path.exists(dem_s2_path):
        dem_s2_job = dem_resampled_s2_cube.create_job(out_format="GTiff")
        dem_s2_job.start()
        jobs.append((dem_s2_job, dem_s2_path))
    else:
        logging.info("Cached DEM data cube found. Skipping download.")
    if not os.path.exists(dem_s3_path):
        dem_s3_job = dem_resampled_s3_cube.create_job(out_format="GTiff")
        dem_s3_job.start()
        jobs.append((dem_s3_job, dem_s3_path))
    else:
        logging.info("Cached DEM cube found. Skipping download.")

    worldcover = (
        connection.load_collection(
            "ESA_WORLDCOVER_10M_2021_V2", temporal_extent=["2021-01-01", "2021-12-31"]
        )
        .filter_bbox(bbox)
        .reduce_dimension(dimension="t", reducer="first")
    )
    wc_resampled_s2_cube = worldcover.resample_cube_spatial(
        s2_reference_cube, method="near"
    )
    if not os.path.exists(worldcover_path):
        wc_job = wc_resampled_s2_cube.create_job(out_format="GTiff")
        wc_job.start()
        jobs.append((wc_job, worldcover_path))
    else:
        logging.info("Cached Worldcover cube found. Skipping download.")

    # Call for all jobs
    for job, path in jobs:
        wait_and_download(job, path)

    logging.info("Data cubes prepared and saved.")

    return (
        s2_path,
        s3_path,
        vza_path,
        worldcover_path,
        dem_s2_path,
        dem_s3_path,
        sentinel3_acq_time,
    )
