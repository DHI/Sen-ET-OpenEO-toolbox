import os
from typing import List
import logging
import tempfile
import xarray as xr
import rasterio
import rioxarray
from pyDMS.pyDMS import DecisionTreeSharpener
from senet_toolbox.utils.raster_utils import gdal_to_xarray

logger = logging.getLogger(__name__)


def run_decision_tree_sharpener(
    high_res_dataarray: xr.DataArray,
    low_res_dataarray: xr.DataArray,
    low_res_mask: xr.DataArray = None,
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
        high_res_dataset (xr.Dataset): High-resolution input data.
        low_res_cube (xr.Dataset): Low-resolution input data.
        low_res_mask_band (xr.DataArray, optional): Mask band for low-resolution data.
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
        # Create temporary files for inputs
        with tempfile.NamedTemporaryFile(delete=False, suffix=".tiff") as high_res_temp:
            high_res_file = high_res_temp.name
            high_res_dataarray.rio.to_raster(high_res_file)
            logger.info(f"Downloaded high-resolution file to {high_res_file}")

        with tempfile.NamedTemporaryFile(delete=False, suffix=".tiff") as low_res_temp:
            low_res_file = low_res_temp.name
            low_res_dataarray.rio.to_raster(low_res_file)
            logger.info(f"Downloaded low-resolution file to {low_res_file}")

        # Handle optional mask
        low_res_mask_files = []
        if low_res_mask is not None:
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

        # Cleanup temporary input files
        os.remove(high_res_file)
        os.remove(low_res_file)
        logger.info(f"Temporary files {high_res_file} and {low_res_file} removed.")

        # If output_path is provided, save the file instead of returning an xarray
        if output_path:
            downscaled_image.save(output_path)
            logger.info(f"Downscaled image saved to {output_path}")
            return output_path  # Return the file path

        # Otherwise, return as an xarray
        return gdal_to_xarray(downscaled_image)

    except Exception as e:
        logger.error(f"An error occurred during disaggregation: {e}")
        raise
