import json
from pathlib import Path
from ipyleaflet import Map, basemaps, basemap_to_tiles, DrawControl, Polygon
import folium
import rasterio
import numpy as np
import xarray as xr
import matplotlib.cm as cm
from matplotlib.colors import Normalize

from senet_toolbox.utils.general_utils import dump_area_date_info


def show_raster_map(
    raster_path,
    bbox=None,
    rgb=False,
    cmap="viridis",
    opacity=0.7,
):
    """
    Display raster (GeoTIFF or NetCDF) on a Folium map.

    Parameters
    ----------
    raster_path : str or Path
        Path to raster file (.tif or .nc)

    bbox : list [minx, miny, maxx, maxy], optional
        Bounding box to draw on map

    rgb : bool
        If True and raster has >=3 bands, display RGB

    cmap : str
        Matplotlib colormap for single band

    opacity : float
        Raster overlay opacity

    Returns
    -------
    folium.Map
    """

    raster_path = Path(raster_path)
    file_extension = raster_path.suffix.lower()

    bounds = None

    # --------------------------------------------------
    # GeoTIFF
    # --------------------------------------------------

    if file_extension in [".tif", ".tiff"]:

        with rasterio.open(raster_path) as src:

            bounds = [
                [src.bounds.bottom, src.bounds.left],
                [src.bounds.top, src.bounds.right],
            ]

            if src.count >= 3 and rgb:

                r = src.read(1).astype(float)
                g = src.read(2).astype(float)
                b = src.read(3).astype(float)

                data = np.stack([r, g, b], axis=-1)

            else:

                data = src.read(1).astype(float)

    # --------------------------------------------------
    # NetCDF
    # --------------------------------------------------

    elif file_extension == ".nc":

        ds = xr.open_dataset(raster_path)

        data_vars = [v for v in ds.data_vars if v != "spatial_ref"]

        if len(data_vars) == 0:
            raise ValueError("No data variables found")

        if rgb and len(data_vars) >= 3:
            required = ["B04", "B03", "B02"]

            if all(b in ds.data_vars for b in required):

                r = np.squeeze(ds["B04"].values)
                g = np.squeeze(ds["B03"].values)
                b = np.squeeze(ds["B02"].values)

                data = np.stack([r, g, b], axis=-1)
            else:
                raise ValueError("B02/B03/B04 not found in dataset")
        else:

            data = ds[data_vars[0]].values

        data = np.squeeze(data)

        # coordinates
        if "x" in ds.coords and "y" in ds.coords:
            x = ds["x"].values
            y = ds["y"].values
        elif "lon" in ds.coords and "lat" in ds.coords:
            x = ds["lon"].values
            y = ds["lat"].values
        else:
            raise ValueError("No spatial coordinates found")

        bounds = [
            [float(y.min()), float(x.min())],
            [float(y.max()), float(x.max())],
        ]

        ds.close()

    else:
        raise ValueError(f"Unsupported file format: {file_extension}")

    # --------------------------------------------------
    # Normalize data
    # --------------------------------------------------

    if data.ndim == 3:

        data = np.nan_to_num(data)

        for i in range(3):
            band = data[:, :, i]
            p2, p98 = np.percentile(band, (2, 98))
            data[:, :, i] = np.clip((band - p2) / (p98 - p2), 0, 1)

        rgb_arr = (data * 255).astype(np.uint8)

    else:

        norm = Normalize(
            vmin=np.nanpercentile(data, 2),
            vmax=np.nanpercentile(data, 98),
        )

        cmap_obj = cm.get_cmap(cmap)

        rgba = cmap_obj(norm(data))
        rgb_arr = (rgba[:, :, :3] * 255).astype(np.uint8)

    # --------------------------------------------------
    # Create map
    # --------------------------------------------------

    center = [
        (bounds[0][0] + bounds[1][0]) / 2,
        (bounds[0][1] + bounds[1][1]) / 2,
    ]

    m = folium.Map(location=center, zoom_start=10)

    # raster overlay
    folium.raster_layers.ImageOverlay(
        image=rgb_arr,
        bounds=bounds,
        opacity=opacity,
        interactive=True,
        cross_origin=False,
    ).add_to(m)

    # AOI bounding box
    if bbox is not None:

        bbox_bounds = [
            [bbox[1], bbox[0]],
            [bbox[3], bbox[2]],
        ]

        folium.Rectangle(
            bounds=bbox_bounds,
            color="red",
            weight=2,
            fill=False,
        ).add_to(m)

    folium.LayerControl().add_to(m)

    return m


def select_aoi(aoi_data_dir=Path("./aoi_data")):
    """
    Select or load AOI. Returns bbox.
    Updates params.json automatically.
    """
    Path(aoi_data_dir).mkdir(exist_ok=True, parents=True)
    params_file = Path(aoi_data_dir) / "params.json"

    # Load existing bbox if present
    if params_file.exists():
        with open(params_file, "r") as f:
            params = json.load(f)
        bbox = params.get("bbox")
        date = params.get("date")
    else:
        bbox = None
        date = None

    # switch the base map here
    base_map = basemap_to_tiles(basemaps.Esri.WorldStreetMap)
    m = Map(layers=(base_map,), center=(40, 10), zoom=2)
    draw_control = DrawControl(
        polyline={},
        polygon={
            "shapeOptions": {"color": "#6bc2e5", "fillOpacity": 0.5}
        },  # Allow polygons
        circlemarker={},  # Disable circlemarker
        circle={},  # Disable circles
        rectangle={},  # Disable rectangles
    )
    bboxs = []

    # --- If AOI exists, show it as editable polygon ---
    if bbox:
        minx, miny, maxx, maxy = bbox
        coords = [(miny, minx), (miny, maxx), (maxy, maxx), (maxy, minx), (miny, minx)]
        polygon = Polygon(
            locations=coords, color="#6bc2e5", fill_color="#6bc2e5", fill_opacity=0.5
        )
        m.add_layer(polygon)
        # Center map on AOI
        m.center = [(miny + maxy) / 2, (minx + maxx) / 2]
        m.zoom = 10
        bboxs.append(bbox)

    def handle_draw(self, action, geo_json):
        """Do something with the GeoJSON when it's drawn on the map"""
        # Print the GeoJSON
        polygon = geo_json["geometry"]

        coords = polygon["coordinates"][0]
        lons, lats = zip(*coords)
        bboxs.append([min(lons), min(lats), max(lons), max(lats)])
        dump_area_date_info(date=date, bbox=bboxs[-1], out_dir=aoi_data_dir)

    draw_control.on_draw(handle_draw)
    m.add_control(draw_control)

    return m, bboxs
