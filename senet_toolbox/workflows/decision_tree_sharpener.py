from datetime import datetime
import logging
from pathlib import Path
import tempfile
from typing import List

import rasterio
import rioxarray
import xarray as xr

from meteo_utils import dem_utils as dem
from pyDMS.pyDMS import DecisionTreeSharpener
import pyDMS.pyDMSUtils as utils

from senet_toolbox.utils.raster_utils import gdal_to_xarray, merge_raster_layers, save_raster

logger = logging.getLogger(__name__)


def sharpen_lst(
    high_res_optical_path: xr.DataArray | Path,
    high_res_dem_path: Path,
    low_res_lst: xr.DataArray | Path,
    low_res_lst_mask: xr.DataArray | Path,
    mask_values: List,
    datetime_utc: datetime,
    cv_homogeneity_threshold: int = 0,
    moving_window_size: int = 30,
    disaggregating_temperature: bool = True,
    n_jobs: int = 3,
    n_estimators: int = 30,
    max_samples: float = 0.8,
    max_features: float = 0.8,
    output_path: str = None,
) -> xr.DataArray | str:

    cos_theta_path = calc_illumination_conditions(high_res_dem_path, datetime_utc)

    vrt_filename = high_res_optical_path.with_suffix('.vrt')
    merge_raster_layers([high_res_optical_path, high_res_dem_path, cos_theta_path],
                        vrt_filename,
                        separate=True)

    sharpened_lst = run_decision_tree_sharpener(
       high_res_data=vrt_filename,
       low_res_data=low_res_lst,
       low_res_mask=low_res_lst_mask,
       mask_values=mask_values,
       cv_homogeneity_threshold=cv_homogeneity_threshold,
       moving_window_size=moving_window_size,
       disaggregating_temperature=disaggregating_temperature,
       n_jobs=n_jobs,
       n_estimators=n_estimators,
       max_samples=max_samples,
       max_features=max_features,
       output_path=output_path,
    )
    return sharpened_lst


def calc_illumination_conditions(dem_path, datetime_utc):

    slope_path = dem_path.parent / f"{dem_path.stem}_slope.tif"
    aspect_path = dem_path.parent / f"{dem_path.stem}_aspect.tif"
    lat_path = dem_path.parent / "lat.tif"
    lon_path = dem_path.parent / "lon.tif"

    cos_theta = dem.incidence_angle_tilted(
            lat=rasterio.open(lat_path).read(1),
            lon=rasterio.open(lon_path).read(1),
            doy=datetime_utc.timetuple().tm_yday,
            ftime=datetime_utc.hour + datetime_utc.minute / 60,
            stdlon=0,
            aspect=rasterio.open(aspect_path).read(1),
            slope=rasterio.open(slope_path).read(1)
        )

    date_str = datetime_utc.strftime("%Y%m%d")
    datetime_str = datetime_utc.strftime("%Y%m%dT%H%M%S")
    cos_theta_path = dem_path.parent / date_str / f"cos_theta_{datetime_str}.tif"
    with rasterio.open(dem_path) as fp:
        profile = fp.profile
    save_raster(cos_theta_path, cos_theta, profile)
    return cos_theta_path


def run_decision_tree_sharpener(
    high_res_data: xr.DataArray | Path,
    low_res_data: xr.DataArray | Path,
    low_res_mask: xr.DataArray | Path = None,
    mask_values: int = [],
    cv_homogeneity_threshold: int = 0,
    moving_window_size: int = 30,
    disaggregating_temperature: bool = True,
    n_jobs: int = 3,
    n_estimators: int = 30,
    max_samples: float = 0.8,
    max_features: float = 0.8,
    output_path: str = None,
) -> xr.DataArray | str:
    """
    Perform disaggregation of low-resolution imagery to high-resolution imagery using the
    DecisionTreeSharpener algorithm.

    Args:
        high_res_data (xr.Dataset or Path): High-resolution input data.
        low_res_Data (xr.Dataset or Path): Low-resolution input data.
        low_res_mask (xr.DataArray or Path, optional): Mask band for low-resolution data.
        mask_values (list, optional): Values to mask in the low-resolution data.
        cv_homogeneity_threshold (int, optional): Homogeneity threshold for cross-validation.
        moving_window_size (int, optional): Size of the moving window for analysis.
        disaggregating_temperature (bool, optional): Whether to disaggregate temperature data.
        n_jobs (int, optional): Number of parallel jobs for processing.
        n_estimators (int, optional): Number of decision trees in the ensemble.
        max_samples (float, optional): Proportion of samples used in training.
        max_features (float, optional): Proportion of features used in training.
        output_path (str, optional): If provided, saves the output to this file instead of returning an xarray.

    Returns:
        xarray.DataArray or str: If `output_path` is provided, returns the file path. Otherwise, returns an xarray.DataArray.
    """

    try:
        if isinstance(high_res_data, Path):
            high_res_file = high_res_data
        else:
            # Create temporary files for inputs
            with tempfile.NamedTemporaryFile(delete=False, suffix=".tiff") as high_res_temp:
                high_res_file = high_res_temp.name
                high_res_data.rio.to_raster(high_res_file)
                logger.info(f"Downloaded high-resolution file to {high_res_file}")

        if isinstance(low_res_data, Path):
            low_res_file = low_res_data
        else:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".tiff") as low_res_temp:
                low_res_file = low_res_temp.name
                low_res_data.rio.to_raster(low_res_file)
                logger.info(f"Downloaded low-resolution file to {low_res_file}")

        # Handle optional mask
        low_res_mask_files = []
        if low_res_mask is not None:
            if isinstance(low_res_mask, Path):
                low_res_mask_file = low_res_mask
            else:
                with tempfile.NamedTemporaryFile(
                    delete=False, suffix=".tiff"
                ) as low_res_mask_temp:
                    low_res_mask_file = low_res_mask_temp.name
                    low_res_mask.rio.to_raster(low_res_mask_file)
                    logger.info(f"Downloaded low-resolution mask to {low_res_mask_file}")
                    low_res_mask_files = [low_res_mask_file]

        # Decision tree configuration
        dt_opts = {
            "highResFiles": [high_res_file],
            "lowResFiles": [low_res_file],
            "lowResQualityFiles": low_res_mask_files,
            "lowResGoodQualityFlags": mask_values,
            "cvHomogeneityThreshold": cv_homogeneity_threshold,
            "movingWindowSize": moving_window_size,
            "disaggregatingTemperature": disaggregating_temperature,
            "baggingRegressorOpt": {
                "n_jobs": n_jobs,
                "n_estimators": n_estimators,
                "max_samples": max_samples,
                "max_features": max_features,
            },
            "perLeafLinearRegression": True,
            "linearRegressionExtrapolationRatio": 0.25,
        }

        # Initialize and train the sharpener
        disaggregator = DecisionTreeSharpener(**dt_opts)
        disaggregator.trainSharpener()

        # Apply the sharpener
        downscaled_image = disaggregator.applySharpener(
            highResFilename=high_res_file, lowResFilename=low_res_file
        )
        # Residual analysis and correction
        residual_image, corrected_image = disaggregator.residualAnalysis(downscaled_image,
                                                                         low_res_file,
                                                                         low_res_mask_file,
                                                                         doCorrection=True)

        # Cleanup temporary input files
        #os.remove(high_res_file)
        #os.remove(low_res_file)
        #logger.info(f"Temporary files {high_res_file} and {low_res_file} removed.")

        # If output_path is provided, save the file instead of returning an xarray
        if output_path:
            print("Saving output...")
            if corrected_image is not None:
                out_image = corrected_image
            else:
                out_image = downscaled_image
            # outData = utils.binomialSmoother(outData)
            out_file = utils.saveImg(out_image.GetRasterBand(1).ReadAsArray(),
                                     out_image.GetGeoTransform(),
                                     out_image.GetProjection(),
                                     output_path)
            out_file = None
            logger.info(f"Downscaled image saved to {output_path}")
            return output_path  # Return the file path

        # Otherwise, return as an xarray
        return gdal_to_xarray(downscaled_image)

    except Exception as e:
        logger.error(f"An error occurred during disaggregation: {e}")
        raise
