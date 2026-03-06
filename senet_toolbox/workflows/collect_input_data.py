import datetime
from dateutil.relativedelta import relativedelta
import hashlib
import logging
import os
from pathlib import Path
import time
from typing import List, Tuple

import openeo

from shapely.geometry import box
from shapely import to_geojson
import rioxarray as rio
import xarray as xr


from senet_toolbox.workflows import biophysical_processing
from senet_toolbox.utils.raster_utils import resample_to_template

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


def get_scene_output_dir(
    out_dir: str,
    bbox: List | Tuple,
    date: datetime.date | datetime.datetime,
    aoi_name: str
):
    # Convert date to string for path name
    date_str = str(date).replace("-", "")

    # Generate a hash based on the bounding box coordinates
    if not aoi_name:
        aoi_name = hashlib.md5(str(bbox).encode()).hexdigest()[
            :8
        ]  # Short hash for path name

    # Base directory includes date and bbox hash
    base_dir = Path(out_dir) / aoi_name / date_str
    base_dir.mkdir(parents=True, exist_ok=True)

    aoi = dict(zip(["west", "south", "east", "north"], bbox))

    return base_dir, aoi


def collect_sentinel3_data(
    connection: openeo.Connection,
    bbox: List | Tuple,
    date: datetime.date | datetime.datetime,
    aoi_name: str = "",
    out_dir: str = "./data",
):

    base_dir, aoi = get_scene_output_dir(out_dir, bbox, date, aoi_name)

    jobs = []

    # Collect Sentinel-3 data
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

    s3_path = Path(base_dir) / "s3_data.nc"
    if not os.path.exists(s3_path):
        s3_job = s3_cube.create_job(out_format="netcdf")
        s3_job.start()
        jobs.append((s3_job, s3_path))
    else:
        logging.info("Cached Sentinel 3 data found. Skipping download.")

    # Call for all jobs
    for job, path in jobs:
        wait_and_download(job, path)

    with xr.open_dataset(s3_path) as nc_fp:
        # For now just pick the first Sentinel-3 acquisition of the day
        acq_time = str(nc_fp.t.values[0]).replace("-", "").replace(":", "").replace(".000000000", "")
        data = nc_fp.isel(t=0)
        data.rio.write_crs("EPSG:4326", inplace=True)
        lst_path = Path(base_dir) / f"s3_{acq_time}_LST.tif"
        data["LST"].rio.to_raster(lst_path)
        vza_path = Path(base_dir) / f"s3_{acq_time}_VZA.tif"
        data["viewZenithAngles"].rio.to_raster(vza_path)
        mask_path = Path(base_dir) / f"s3_{acq_time}_mask.tif"
        data["confidence_in"].rio.to_raster(mask_path)

    logging.info("Sentinel-3 data prepared and saved.")

    return lst_path, vza_path, mask_path


def collect_sentinel2_data(
    connection: openeo.Connection,
    bbox: List | Tuple,
    date: datetime.date | datetime.datetime,
    aoi_name: str = "",
    out_dir: str = "./data",
    sentinel2_search_range: int = 15,
    use_biopar_processor: bool = True
):

    base_dir, aoi = get_scene_output_dir(out_dir, bbox, date, aoi_name)
    s2_path = Path(base_dir) / f"s2_{str(date).replace('-', '')}_data.nc"

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

    # The start date is included, end date is excluded in the collection search, which is why we
    # add one day
    time_window = [
        str(date - relativedelta(days=sentinel2_search_range)),
        str(date + relativedelta(days=1)),
    ]
    bbox_polygon = eval(to_geojson(box(*bbox)))

    # Load Sentinel-2 cube and merge with Biopar
    s2_cube = connection.load_collection(
        "SENTINEL2_L2A", spatial_extent=aoi, temporal_extent=time_window, bands=s2_bands
    )

    if use_biopar_processor:
        # Load Biopar data
        fapar = biophysical_processing.get_biopar(
            connection, "FAPAR", time_window, bbox_polygon
        )
        lai = biophysical_processing.get_biopar(
            connection, "LAI", time_window, bbox_polygon
        )
        ccc = biophysical_processing.get_biopar(
            connection, "CCC", time_window, bbox_polygon
        )
        cwc = biophysical_processing.get_biopar(
            connection, "CWC", time_window, bbox_polygon
        )

        s2_cube = (
            s2_cube.merge_cubes(lai)
            .merge_cubes(ccc)
            .merge_cubes(cwc)
            .merge_cubes(fapar)
        )

    # Apply cloud and shadow mask using SCL (keep only class 4 and 5 = vegetation/bare)
    mask = ~((s2_cube.band("SCL") == 4) | (s2_cube.band("SCL") == 5))
    masked = s2_cube.mask(mask)

    # Reduce time dimension by selecting the first valid observation
    s2_best_pixel = masked.reduce_dimension(dimension="t", reducer="first")

    # Resample to 20 m and warp to geographic projection
    warped = s2_best_pixel.resample_cube_spatial(get_s2_reference_cube(connection, aoi, date),
                                                 method="average")

    if not os.path.exists(s2_path):
        s2_job = warped.create_job(out_format="netcdf")
        s2_job.start()
        jobs.append((s2_job, s2_path))
    else:
        logging.info("Cached Sentinel 2 data found. Skipping download.")

    # Call for all jobs
    for job, path in jobs:
        wait_and_download(job, path)

    logging.info("Sentinel-2 data prepared and saved.")

    return s2_path


# Reference cube has the spatial extent of the AOI and is resampled first to 20 m and then to
# EPSG:4326 projection.
def get_s2_reference_cube(
    connection: openeo.Connection,
    aoi: dict,
    date: datetime.date | datetime.datetime,
):
    # There should be S2 scene every 5 days
    time_window = [
        str(date + relativedelta(days=-4)),
        str(date + relativedelta(days=1)),
    ]
    s2_reference_cube = (
        connection.load_collection(
            "SENTINEL2_L2A", spatial_extent=aoi, temporal_extent=time_window, bands=["B02"]
        )
        .reduce_dimension(dimension="t", reducer="first")
        .resample_spatial(resolution=20, method="average")
        .resample_spatial(projection=4326)
    )

    return s2_reference_cube


def collect_worldcover_data(
    connection: openeo.Connection,
    bbox: List | Tuple,
    date: datetime.date | datetime.datetime,
    aoi_name: str = "",
    s2_template_path: str = "",
    out_dir: str = "./data",
):

    base_dir, aoi = get_scene_output_dir(out_dir, bbox, date, aoi_name)
    # World cover is time invariant so save it in the AOI folder
    worldcover_path = base_dir.parent / "WorldCover2021.tif"

    s2_reference_cube = get_s2_reference_cube(connection, aoi, date)

    jobs = []

    worldcover = (
        connection.load_collection(
            "ESA_WORLDCOVER_10M_2021_V2", spatial_extent=aoi, temporal_extent=["2021-01-01", "2021-12-31"]
        ).reduce_dimension(dimension="t", reducer="first")
    )
    wc_resampled_s2_cube = worldcover.resample_cube_spatial(
        s2_reference_cube, method="near"
    )
    if not os.path.exists(worldcover_path):
        wc_job = wc_resampled_s2_cube.create_job(out_format="GTiff")
        wc_job.start()
        jobs.append((wc_job, worldcover_path))
    else:
        logging.info("Cached Worldcover data found. Skipping download.")

    # Call for all jobs
    for job, path in jobs:
        wait_and_download(job, path)
        # Sometimes s2_cube and s2_reference_cube have different sizes by 1 pixel, and this seems
        # to be caused by the BIOPAR processor. So to be 100% sure that all data aligns, Worldcover
        # is resampled again using GDAL after download
        if s2_template_path.suffix == ".nc":
            s2_template_path = f'NETCDF:"{s2_template_path}":SCL'
        resample_to_template(path, path, s2_template_path, "near")

    logging.info("Worldcover data prepared and saved.")

    return worldcover_path


def collect_dem_data(
    connection: openeo.Connection,
    bbox: List | Tuple,
    date: datetime.date | datetime.datetime,
    aoi_name: str = "",
    s2_template_path: str = "",
    out_dir: str = "./data",
):

    base_dir, aoi = get_scene_output_dir(out_dir, bbox, date, aoi_name)
    # World cover is time invariant so save it in the AOI folder
    dem_s2_path = base_dir.parent / "cdem.tif"

    s2_reference_cube = get_s2_reference_cube(connection, aoi, date)

    jobs = []

    dem_cube = connection.load_collection(
        "COPERNICUS_30", spatial_extent=aoi
    ).reduce_dimension(dimension="t", reducer="first")

    dem_resampled_s2_cube = dem_cube.resample_cube_spatial(
        s2_reference_cube, method="bilinear"
    )
    if not os.path.exists(dem_s2_path):
        dem_s2_job = dem_resampled_s2_cube.create_job(out_format="GTiff")
        dem_s2_job.start()
        jobs.append((dem_s2_job, dem_s2_path))
    else:
        logging.info("Cached DEM data found. Skipping download.")

    # Call for all jobs
    for job, path in jobs:
        wait_and_download(job, path)
        # Sometimes s2_cube and s2_reference_cube have different sizes by 1 pixel, and this seems
        # to be caused by the BIOPAR processor. So to be 100% sure that all data aligns, DEM
        # is resampled again using GDAL after download
        if s2_template_path.suffix == ".nc":
            s2_template_path = f'NETCDF:"{s2_template_path}":SCL'
        resample_to_template(path, path, s2_template_path, "near")

    logging.info("Copernicus DEM cube prepared and saved.")

    return dem_s2_path
