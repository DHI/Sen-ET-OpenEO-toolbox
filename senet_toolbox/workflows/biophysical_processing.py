import logging
from pathlib import Path
import re
from typing import Union, List

import numpy as np
import rasterio
import xarray as xr

from senet_toolbox.utils.general_utils import load_lut
from senet_toolbox.utils.raster_utils import save_raster, default_profile

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()],
)

lut = load_lut()


def get_biopar(
    connection, product: str, date: Union[str, List[str]], aoi: dict
) -> xr.Dataset:
    """
    Retrieve BIOPAR product from an openEO connection.

    Args:
        connection: openEO connection instance.
        product (str): Product type name (e.g. 'LAI', 'FAPAR').
        date (Union[str, List[str]]): Single date or date range [start, end].
        aoi (dict): GeoJSON-like polygon area of interest.

    Returns:
        xr.Dataset: BIOPAR dataset.
    """
    if isinstance(date, str):
        date = [date, date]

    biopar = connection.datacube_from_process(
        "BIOPAR",
        namespace=(
            "https://openeo.dataspace.copernicus.eu/openeo/1.1/processes/"
            "u:3e24e251-2e9a-438f-90a9-d4500e576574/BIOPAR"
        ),
        date=date,
        polygon=aoi,
        biopar_type=product,
    )
    return biopar


def calc_canopy_height(
    lai_path: Union[str, Path],
    worldcover_path: Union[str, Path],
    fg_path: Union[str, Path],
) -> None:
    """
    Estimate canopy height based on LAI, land cover, and green fraction.

    Args:
        lai_path (str | Path): Path to LAI GeoTIFF file.
        worldcover_path (str | Path): Path to land cover GeoTIFF file.
        fg_path (str | Path): Path to fraction green GeoTIFF file.

    Returns:
        None. Saves an H_C GeoTIFF to disk.
    """
    with rasterio.open(lai_path) as lai_src:
        lai = lai_src.read(1).astype(np.float32)
        profile = lai_src.profile

    with rasterio.open(worldcover_path) as worldcover_src:
        landcover = worldcover_src.read(1).astype(np.int32)
        landcover = 10 * (landcover // 10)

    with rasterio.open(fg_path) as fg_src:
        fg = fg_src.read(1).astype(np.float32)

    param_value = np.full_like(landcover, np.nan, dtype=np.float32)

    for lc_class in np.unique(landcover[~np.isnan(landcover)]):
        lc_pixels = np.where(landcover == lc_class)
        lc_index = lut[lut["landcover_class"] == lc_class].index[0]
        param_value[lc_pixels] = lut["veg_height"][lc_index]

        if lut["is_herbaceous"][lc_index] == 1:
            pai = lai / fg
            pai = pai[lc_pixels]
            param_value[lc_pixels] = 0.1 * param_value[lc_pixels] + 0.9 * param_value[
                lc_pixels
            ] * np.minimum((pai / lut["veg_height"][lc_index]) ** 3.0, 1.0)

    output_path = str(lai_path).replace("LAI", "H_C")
    save_raster(output_path, param_value, profile)

    logging.info(f"Saved H_C to {output_path}")


def calc_fg(
    fapar_path: Union[str, Path], lai_path: Union[str, Path], sza_path: Union[str, Path]
) -> None:
    """
    Estimate green fraction (F_G) using FAPAR, LAI, and solar zenith angle.

    Args:
        fapar_path (Union[str, Path]): Path to FAPAR GeoTIFF.
        lai_path (Union[str, Path]): Path to LAI GeoTIFF.
        sza_path (Union[str, Path]): Path to solar zenith angle GeoTIFF.

    Returns:
        None. Saves F_G as GeoTIFF.
    """
    from pyTSEB import TSEB

    with rasterio.open(fapar_path) as fapar_src:
        fapar = fapar_src.read(1).astype(np.float32)
        profile = fapar_src.profile

    with rasterio.open(lai_path) as lai_src:
        lai = lai_src.read(1).astype(np.float32)

    with rasterio.open(sza_path) as sza_src:
        sza = sza_src.read(1).astype(np.float32)

    f_g = np.ones(lai.shape, dtype=np.float32)
    converged = np.zeros(lai.shape, dtype=bool)
    converged[np.logical_or(lai <= 0.2, fapar <= 0.1)] = True
    min_frac_green = 0.01

    for _ in range(50):
        f_g_old = f_g.copy()
        fipar = TSEB.calc_F_theta_campbell(
            sza[~converged], lai[~converged] / f_g[~converged], w_C=1, Omega0=1, x_LAD=1
        )
        f_g[~converged] = fapar[~converged] / fipar
        f_g = np.clip(f_g, min_frac_green, 1.0)
        converged = np.logical_or(np.isnan(f_g), np.abs(f_g - f_g_old) < 0.02)
        if np.all(converged):
            break

    profile.update(dtype=rasterio.float32, count=1)
    output_path = str(lai_path).replace("LAI", "F_G")
    save_raster(output_path, f_g, profile)

    logging.info(f"Saved frac_green to {output_path}")


def split_nc_to_tifs(nc_file: Union[str, Path], date_str: str) -> None:
    """
    Splits NetCDF bands into separate GeoTIFF files per variable.

    Args:
        nc_file (Union[str, Path]): Path to input NetCDF.
        date_str (str): Date string to include in output filenames.

    Returns:
        None. GeoTIFFs are written to disk.
    """
    out_dir = Path(nc_file).parent
    data = xr.open_dataset(nc_file)
    s2_bands = ["B02", "B03", "B04", "B05", "B06", "B07", "B08", "B8A", "B11", "B12"]

    if Path(nc_file).stem == f"s2_{date_str}_data":
        refl = data[s2_bands] / 10000
        refl = refl.rio.write_crs(data.crs.crs_wkt)
        output_file = out_dir / f"{date_str}_REFL.tif"
        refl.rio.to_raster(output_file, **default_profile())

    for var_name in data.data_vars:
        if var_name in s2_bands + ["crs"]:
            continue

        band = data[var_name]
        band.attrs.pop("grid_mapping", None)
        band = band.rio.write_crs(data.crs.crs_wkt)

        if var_name == "sunZenithAngles":
            output_file = out_dir / f"{date_str}_SZA.tif"
        else:
            output_file = out_dir / f"{date_str}_{var_name}.tif"

        band.rio.to_raster(output_file, **default_profile())
        logging.info(f"Saved {var_name} to {output_file}")


def watercloud_model(param, a, b, c):
    result = a + b * (1.0 - np.exp(c * param))

    return result


def cab_to_vis_spectrum(
    cab,
    coeffs_wc_rho_vis=[0.14096573, -0.09648072, -0.06328343],
    coeffs_wc_tau_vis=[0.08543707, -0.08072709, -0.06562554],
):
    rho_leaf_vis = watercloud_model(cab, *coeffs_wc_rho_vis)
    tau_leaf_vis = watercloud_model(cab, *coeffs_wc_tau_vis)

    rho_leaf_vis = np.clip(rho_leaf_vis, 0, 1)
    tau_leaf_vis = np.clip(tau_leaf_vis, 0, 1)

    return rho_leaf_vis, tau_leaf_vis


def cw_to_nir_spectrum(
    cw,
    coeffs_wc_rho_nir=[0.38976106, -0.17260689, -65.7445699],
    coeffs_wc_tau_nir=[0.36187620, -0.18374560, -65.3125878],
):
    rho_leaf_nir = watercloud_model(cw, *coeffs_wc_rho_nir)
    tau_leaf_nir = watercloud_model(cw, *coeffs_wc_tau_nir)

    rho_leaf_nir = np.clip(rho_leaf_nir, 0, 1)
    tau_leaf_nir = np.clip(tau_leaf_nir, 0, 1)

    return rho_leaf_nir, tau_leaf_nir


def process_ccc_to_vis(ccc_path, lai_path):
    """Processes a LAI raster file to generate visible spectrum reflectance and transmittance TIFFs."""
    try:
        if not Path(ccc_path).exists():
            raise FileNotFoundError(f"CCC file not found: {ccc_path}")

        with rasterio.open(ccc_path) as src, rasterio.open(lai_path) as src_lai:
            meta = src.meta.copy()
            meta.update(dtype="float32")

            ccc = src.read(1)
            lai = src_lai.read(1)
            lai = np.clip(lai, 0.01, 8)
            # Convert from canopy chlorophyl content to leaf chrolophyl content
            cab = np.clip(np.array(ccc) / np.array(lai), 0.0, 140.0)
            refl_vis, trans_vis = cab_to_vis_spectrum(cab)  # Function assumed to exist

            rho_vis_path = str(lai_path).replace("LAI", "RHO_VIS_C")
            tau_vis_path = str(lai_path).replace("LAI", "TAU_VIS_C")

            save_raster(rho_vis_path, refl_vis, meta)
            save_raster(tau_vis_path, trans_vis, meta)

            logging.info(f"Processed LAI to VIS: {rho_vis_path}, {tau_vis_path}")

    except Exception as e:
        logging.error(f"Error processing LAI: {e}")
        raise  # Ensure function fails on error


def process_cwc_to_nir(cwc_path, lai_path):
    """Processes a CWC raster file to generate NIR reflectance and transmittance TIFFs."""
    try:
        if not Path(cwc_path).exists():
            raise FileNotFoundError(f"CWC file not found: {cwc_path}")

        with rasterio.open(cwc_path) as src, rasterio.open(lai_path) as src_lai:
            meta = src.meta.copy()
            meta.update(dtype="float32")

            cwc = src.read(1)
            lai = src_lai.read(1)
            lai = np.clip(lai, 0.01, 8)
            # Convert from canopy water content to leaf water content
            cw = np.clip(np.array(cwc) / np.array(lai), 0.0, 0.1)
            refl_nir, trans_nir = cw_to_nir_spectrum(cw)  # Function assumed to exist

            rho_nir_path = str(lai_path).replace("LAI", "RHO_NIR_C")
            tau_nir_path = str(lai_path).replace("LAI", "TAU_NIR_C")

            save_raster(rho_nir_path, refl_nir, meta)
            save_raster(tau_nir_path, trans_nir, meta)

            logging.info(f"Processed CWC to NIR: {rho_nir_path}, {tau_nir_path}")

    except Exception as e:
        logging.error(f"Error processing CWC: {e}")
        raise  # Ensure function fails on error


def calc_canopy_rho_tau(lai_path, cwc_path, ccc_path):
    process_ccc_to_vis(ccc_path, lai_path)
    process_cwc_to_nir(cwc_path, lai_path)


def biopar_biophysical_params(s2_path, worldcover_path, out_dir: str | Path = None):
    if out_dir:
        base_dir = Path(out_dir)
    else:
        base_dir = Path(s2_path).parent
    datestr = re.search(r"_(\d{8})_", s2_path.name).group(1)

    split_nc_to_tifs(s2_path, datestr)

    lai_path = base_dir / f"{datestr}_LAI.tif"
    fapar_path = base_dir / f"{datestr}_FAPAR.tif"
    sza_path = base_dir / f"{datestr}_SZA.tif"
    fg_path = base_dir / f"{datestr}_F_G.tif"

    calc_fg(fapar_path, lai_path, sza_path)
    calc_canopy_height(lai_path, worldcover_path, fg_path)

    cwc_path = base_dir / f"{datestr}_CWC.tif"
    ccc_path = base_dir / f"{datestr}_CCC.tif"
    calc_canopy_rho_tau(lai_path, cwc_path, ccc_path)

    return base_dir
