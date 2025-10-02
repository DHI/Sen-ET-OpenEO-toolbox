from typing import List
import numpy as np
import xarray as xr
from osgeo import gdal
import logging
from pathlib import Path


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


def resample_to_s2(
    in_dir: str,
    out_dir: str,
    s2_path: str,
    product_list: List = [
        "EA.tif",
        "p.tif",
        "u.tif",
        "S_dn_24.tif",
        "S_dn.tif",
        "T_A1.tif",
    ],
    nodata_value: int = -999,
) -> None:
    """
    Resamples and reprojects data to match a Sentinel-2 image.

    Parameters:
    - in_dir (str): Directory containing input TIFF files.
    - out_dir (str): Directory to save the resampled TIFF files.
    - s2_path (str): Path to the Sentinel-2 reference image.
    - nodata_value (int, optional): Value to use for missing data. Default is -999.

    Returns:
    - None
    """
    logging.info("Starting resample_s2 processing...")

    in_dir = Path(in_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    tiff_files = [
        x
        for x in in_dir.glob("*.tif")
        if any(x.name.endswith(product) for product in product_list)
    ]

    if not tiff_files:
        logging.warning(f"No matching TIFF files found in {in_dir}. Exiting.")
        return

    try:
        high_res_ds = gdal.Open(s2_path)
        if high_res_ds is None:
            raise ValueError(f"Failed to open Sentinel-2 file: {s2_path}")

        high_res_proj = high_res_ds.GetProjection()
        high_res_geotransform = high_res_ds.GetGeoTransform()

        xmin = high_res_geotransform[0]
        xmax = xmin + high_res_geotransform[1] * high_res_ds.RasterXSize
        ymax = high_res_geotransform[3]
        ymin = ymax + high_res_geotransform[5] * high_res_ds.RasterYSize

        logging.info(f"Using Sentinel-2 extent: ({xmin}, {ymin}, {xmax}, {ymax})")

        for low_res in tiff_files:
            output_path = out_dir / low_res.name
            logging.info(f"Processing {low_res.name} -> {output_path}")

            gdal.Warp(
                str(output_path),
                str(low_res),
                format="GTiff",
                dstSRS=high_res_proj,
                xRes=high_res_geotransform[1],
                yRes=abs(high_res_geotransform[5]),
                resampleAlg="bilinear",
                srcNodata=None,
                dstNodata=nodata_value,
                outputBounds=(xmin, ymin, xmax, ymax),
            )

        logging.info("Processing completed successfully.")

    except Exception as e:
        logging.error(f"An error occurred during processing: {e}")
        raise
