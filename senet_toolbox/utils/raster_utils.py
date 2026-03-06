import logging
from pathlib import Path
import tempfile
from typing import List

import numpy as np
from osgeo import gdal
import rasterio
import xarray as xr


def gdal_to_xarray(gdal_dataset: gdal.Dataset):
    """
    Convert a GDAL dataset to an xarray Dataset.

    This function extracts raster data (bands, geospatial coordinates, and projection information)
    from a GDAL dataset and returns it as an xarray Dataset. Each band in the GDAL dataset is
    represented as a 2D array, and the xarray Dataset includes coordinates for both spatial
    dimensions (x, y) and the bands.

    Args:
        gdal_dataset (gdal.Dataset): The GDAL dataset object containing raster data. This should be
                                      a loaded raster image or a spatial dataset (e.g., a GeoTIFF).

    Returns:
        xarray.Dataset: An xarray Dataset containing the raster data, with coordinates for x, y,
                        and band dimensions, and attributes for CRS (coordinate reference system)
                        and geotransform.
    """
    # Get the dimensions of the raster (x, y, number of bands)
    x_size = gdal_dataset.RasterXSize
    y_size = gdal_dataset.RasterYSize
    num_bands = gdal_dataset.RasterCount

    # Initialize an empty array to store the data (shape: [num_bands, y_size, x_size])
    data = np.zeros((num_bands, y_size, x_size), dtype=np.float32)

    # Loop through each band and read the data into the array
    for i in range(num_bands):
        band = gdal_dataset.GetRasterBand(i + 1)  # Bands are 1-indexed in GDAL
        data[i, :, :] = band.ReadAsArray()

    # Get geotransform and projection information
    geotransform = gdal_dataset.GetGeoTransform()
    projection = gdal_dataset.GetProjection()

    # Define the x and y coordinates based on the geotransform
    x_coords = (
        geotransform[0] + np.arange(x_size) * geotransform[1]
    )  # X coordinates (longitude)
    y_coords = (
        geotransform[3] + np.arange(y_size) * geotransform[5]
    )  # Y coordinates (latitude)
    band_coords = np.arange(1, num_bands + 1)  # Band coordinates (starting from 1)

    # Create an xarray Dataset with the raster data
    ds = xr.Dataset(
        {"band_data": (["band", "y", "x"], data)},  # Data variable with coordinates
        coords={
            "x": x_coords,  # X coordinates (e.g., longitude or easting)
            "y": y_coords,  # Y coordinates (e.g., latitude or northing)
            "band": band_coords,  # Band index coordinates
        },
        attrs={
            "crs": projection,  # Coordinate Reference System
            "transform": geotransform,  # Geotransform (affine transformation)
        },
    )

    return ds


def resample_to_template(
    in_file: str | gdal.Dataset,
    output_path: str,
    template_path: str,
    resample_alg: str = "bilinear",
    nodata_value: int = -999,
) -> None:
    """
    Resamples and reprojects data to match a Sentinel-2 image.

    Parameters:
    - in_file (str | gdal.Dataset): File to be resampled
    - output_path (str): Location to save the output
    - template_path (str): Path to the tempalte image
    - nodata_value (int, optional): Value to use for missing data. Default is -999.

    Returns:
    - None
    """
    logging.info("Starting resample_to_template...")

    try:
        high_res_ds = gdal.Open(template_path)
        if high_res_ds is None:
            raise ValueError(f"Failed to open Sentinel-2 file: {template_path}")

        high_res_proj = high_res_ds.GetProjection()
        high_res_geotransform = high_res_ds.GetGeoTransform()

        xmin = high_res_geotransform[0]
        xmax = xmin + high_res_geotransform[1] * high_res_ds.RasterXSize
        ymax = high_res_geotransform[3]
        ymin = ymax + high_res_geotransform[5] * high_res_ds.RasterYSize

        gdal.Warp(
            output_path,
            in_file,
            format="GTiff",
            dstSRS=high_res_proj,
            xRes=high_res_geotransform[1],
            yRes=abs(high_res_geotransform[5]),
            resampleAlg=resample_alg,
            srcNodata=None,
            dstNodata=nodata_value,
            outputBounds=(xmin, ymin, xmax, ymax),
        )

        logging.info("Processing completed successfully.")

    except Exception as e:
        logging.error(f"An error occurred during processing: {e}")
        raise


def save_raster(output_path, data, meta):
    """Saves an array as a GeoTIFF using Rasterio."""
    try:
        meta.update(default_profile())
        with rasterio.open(output_path, "w", **meta) as dst:
            dst.write(data.astype("float32"), 1)
        logging.info(f"Saved raster: {output_path}")
    except Exception as e:
        logging.error(f"Failed to save raster {output_path}: {e}")
        raise  # Ensure function fails on error


def save_lat_lon_as_tifs(nc_file, out_dir):
    data = xr.open_dataset(nc_file)

    lat, lon = xr.broadcast(data["y"], data["x"])

    lat = lat.rio.write_crs(data.rio.crs)
    lat.rio.to_raster(f"{out_dir}/lat.tif")

    lon = lon.rio.write_crs(data.rio.crs)
    lon.rio.to_raster(f"{out_dir}/lon.tif")


# This is not easy to do with rasterio for images with multiple bands so it's done with GDAL
def merge_raster_layers(input_list, output_filename, separate=False, geotiff=False):
    merge_list = []
    nodata_str = ""
    for input_file in input_list:
        with rasterio.open(input_file, "r") as fp:
            nodata_value = fp.nodata
            if nodata_value is None:
                nodata_value = np.nan
            bands = fp.count
        # GDAL Build VRT cannot stack multiple multi-band images, so they have to be split into
        # multiple singe-band images first.
        if bands > 1:
            for band in range(1, bands+1):
                temp_filename = tempfile.mkstemp(suffix="_"+str(band)+".vrt")[1]
                gdal.BuildVRT(temp_filename, [input_file], bandList=[band])
                merge_list.append(temp_filename)
                nodata_str = nodata_str + f" {nodata_value}"
        else:
            merge_list.append(input_file)
            nodata_str = nodata_str + f" {nodata_value}"

    if geotiff:
        temp_filename = tempfile.mkstemp(suffix="_temp.vrt")[1]
        gdal.BuildVRT(temp_filename, merge_list, separate=separate, VRTNodata=nodata_str)
        fp = gdal.Translate(output_filename, temp_filename, format="COG",
                            creationOptions=["COMPRESS=DEFLATE", "PREDICTOR=2"])
    else:
        fp = gdal.BuildVRT(output_filename, merge_list, separate=separate, VRTNodata=nodata_str)
    return fp


def default_profile():

    default_profile = {"driver": "GTiff",
                       "interleave": "band",
                       "tiled": True,
                       "blockxsize": 512,
                       "blockysize": 512,
                       "compress": "ZSTD",
                       "predictor": 2,
                       "dtype": "float32"}

    return default_profile
