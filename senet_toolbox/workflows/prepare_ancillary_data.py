# -*- coding: utf-8 -*-
"""
Created on Tue Mar  3 12:51:33 2026

@author: rmgu
"""

import logging
from pathlib import Path


import numpy as np
import rasterio
from rasterio.warp import calculate_default_transform, reproject, Resampling
import rioxarray
import xarray as xr

from meteo_utils import dem_utils as du

from senet_toolbox.utils.raster_utils import save_lat_lon_as_tifs, save_raster


logger = logging.getLogger(__name__)


def prepare_dem(dem_path: Path):

    # Produce 300 m version of the DEM
    dem_300_path = dem_path.parent / f"{dem_path.stem}_300.tif"
    # 300 m = 0.0027 degrees (approx) at the equator
    dst_resolution = 300 / 111320    # ~0.002694 degrees per pixel
    dst_crs = "EPSG:4326"
    with rasterio.open(dem_path) as src:
        # Compute transform for new projection and resolution
        transform, width, height = calculate_default_transform(
            src.crs, dst_crs,
            src.width, src.height,
            *src.bounds,
            resolution=dst_resolution
        )
        # Update metadata
        kwargs = src.meta.copy()
        kwargs.update({
            "crs": dst_crs,
            "transform": transform,
            "width": width,
            "height": height
        })
        # Reproject and write out GeoTIFF
        with rasterio.open(dem_300_path, "w", **kwargs) as dst:
            for band in range(1, src.count + 1):
                reproject(
                    source=rasterio.band(src, band),
                    destination=rasterio.band(dst, band),
                    src_transform=src.transform,
                    src_crs=src.crs,
                    dst_transform=transform,
                    dst_crs=dst_crs,
                    resampling=Resampling.average  # good for downsampling
                )

    # Calculate slope and aspect for both original and 300 m DEM
    du.slope_from_dem(dem_path, dem_path.parent / f"{dem_path.stem}_slope.tif")
    du.aspect_from_dem(dem_path, dem_path.parent / f"{dem_path.stem}_aspect.tif")
    du.slope_from_dem(dem_300_path, dem_300_path.parent / f"{dem_300_path.stem}_slope.tif")
    du.aspect_from_dem(dem_300_path, dem_300_path.parent / f"{dem_300_path.stem}_aspect.tif")

    # Save latitude and longitude maps at 300 m (for LST sharpening)
    save_lat_lon_as_tifs(dem_path, dem_path.parent)


def prepare_lut_maps(
    worldcover_path: str | Path,
    lut: xr.Dataset,
) -> np.ndarray:
    """
    Estimate parameter value (e.g., leaf width) from land cover using a LUT.

    Args:
        worldcover_path (Union[str, Path]): Path to land cover GeoTIFF.
        lut (xr.Dataset): Lookup table mapping land cover class to param value.
        band (str): Parameter name (column in LUT).
        output_path (Union[str, Path]): Output GeoTIFF path.

    Returns:
        np.ndarray: Array of estimated values.

    """

    lc_params = {"W_C": "veg_height_width_ratio",
                 "LEAF_WIDTH": "veg_leaf_width",
                 "F_C": "veg_fractional_cover",
                 "IGBP": "igbp_classification",
                 "X_LAD": "veg_inclination_distribution"}

    with rasterio.open(worldcover_path) as worldcover_src:
        landcover = worldcover_src.read(1).astype(np.int32)
        landcover = 10 * (landcover // 10)
        profile = worldcover_src.profile

    param_value = np.full(landcover.shape, np.nan, dtype=np.float32)

    for param in lc_params.keys():
        for lc_class in np.unique(landcover[~np.isnan(landcover)]):
            lc_pixels = np.where(landcover == lc_class)
            lc_index = lut[lut["landcover_class"] == lc_class].index[0]
            param_value[lc_pixels] = lut[lc_params[param]][lc_index]

        profile.update({"dtype": "float32"})
        output_path = worldcover_path.parent / f"{param}.tif"
        save_raster(output_path, param_value, profile)

        logging.info(f"Saved {lc_params[param]} to {output_path}")
    return
