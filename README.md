![Project Status](https://img.shields.io/badge/Status-Development-yellow)
[![GitHub last commit](https://img.shields.io/github/last-commit/DHI/Sen-ET-OpenEO-toolbox)](#)

# Sen-ET OpenEO toolbox
> ⚠️ **Note:** This project is under active development. Features may change and bugs may exist.

**Sen-ET** is an open-source framework for modelling actual evapotranspiration (ET) at high spatio-temporal resolution using Sentinel and other Copernicus data. This repository contains Jupyter notebooks and Python scripts for end-to-end ET modelling using the Sen-ET framework with Sentinel data access and early pre-processing provided through the [Copernicus Data Space Ecosystem](https://dataspace.copernicus.eu/) (CDSE) [openEO API](https://documentation.dataspace.copernicus.eu/APIs/openEO/openEO.html). 

This implementation follows a strong legacy of the original [SNAP Sen-ET toolbox](https://www.esa-sen4et.org/) and open-source Python packages developed for ET modelling. Currently following modules are included:
* [Data Mining Sharpener (pyDMS)](https://github.com/radosuav/pyDMS) - Python implementation of Data Mining Sharpener (DMS): a decision tree based algorithm for sharpening (disaggregation) of low-resolution images (e.g. Sentinel-3 land surface temperature) using high-resolution images (e.g. Sentinel-2 reflectance).
* [Two Source Energy Balance (TSEB)](https://github.com/hectornieto/pyTSEB) - Python code for Two Source Energy Balance model (TSEB-PT) for estimating sensible and latent heat flux (evapotranspiration) based on measurements of radiometric surface temperature.
* [Meteo Utils](https://github.com/hectornieto/meteo_utils/) - Python methods that allow the automatic download and processing of ECMWF data relevant for evapotranspiration modelling.

## Installation
### Installation on Copernicus Data Space (CDSE) JupyterHub
When executed on [CDSE JupyterHub environment](https://jupyterhub.dataspace.copernicus.eu) data downloads can be minimized since data and compute are located in the same cloud infrastructure. 

1. Go to [https://jupyterhub.dataspace.copernicus.eu](https://jupyterhub.dataspace.copernicus.eu) and start a server
2. In the server either upload the notebooks manually or clone this repo by opening a terminal and running
    ```
    git clone https://github.com/DHI/Sen-ET-OpenEO-toolbox.git mystorage/sen-et-toolbox
    ```
3. Execute the first notebook using a kernel which has GDAL installed, e.g. *Geo science*. This package is installed in the first cell of the notebooks.
   >💡**Note**: You *should* be able run the notebooks out of the box without any additional setup if using a kernel with GDAL installed, but sometimes there can be conflicts with existing packages in the environment. In this case, it is recommended to do a clean kernel installation following the steps below.
3. Create a new clean kernel using the following commands in a terminal on Jupyterhub
    ```
    conda create -n gdal_env python=3.11 \
    conda activate gdal_env \
    conda install -c conda-forge gdal \
    pip install ipykernel \
    pip install senet_toolbox@git+https://github.com/DHI/Sen-ET-OpenEO-toolbox.git \
    python -m ipykernel install --user --name=gdal_env --display-name "Sen-ET Kernel" 
    ```
4. You can now select the "Sen-ET Kernel" kernel to run the notebooks

### Local Installation
To install the Sen-ET OpenEO Toolbox locally, follow these steps:

1. Install GDAL
Make sure GDAL is installed on your system. This is a required dependency for geospatial data processing.

2. Install the Toolbox from GitHub
Once GDAL is installed, you can install the toolbox directly using pip:
    ```
    pip install senet_toolbox@git+https://github.com/DHI/Sen-ET-OpenEO-toolbox.git
    ```

## Running the Evapotranspiration Workflow  
The **notebooks** provided in the [`notebooks/`](./notebooks) folder demonstrate how to use the **Sen-ET OpenEO toolbox** for evapotranspiration modeling.  

These notebooks can be run directly on **Copernicus Data Space (CDSE) JupyterHub** for efficient processing and scalability.  

### Available Notebooks  
- **[`notebooks/step1_collect_input_data.ipynb`](./notebooks/step1_collect_inputs_data.ipynb)** – This notebook collects Sentinel-2, Sentinel-3 and ancillary data (Worldcover landcover map and Copernicus Digital Elevation Model) by allowing users to define an area of interest, select suitable acquisition dates, and download the relevant datasets using openEO. It also uses [openEO BIOPAR processor](https://marketplace-portal.dataspace.copernicus.eu/catalogue/app-details/21#iss=https%3A%2F%2Fidentity.dataspace.copernicus.eu%2Fauth%2Frealms%2FCDSE) to collect / derive Sentinel-2 based biophysical parameters. 

- **[`notebooks/step2_prepare_input_data.ipynb`](./notebooks/step2_prepare_input_data.ipynb)** – The input data collected in the previous notebook is now prepared for use in ET modelling. This includes derivation of static parameters from the landcover map and sharpening of the Sentinel-3 land surface temperature to Sentinel-2 spatial resolution using the **DMS**. In addition meteorological forcings are collected from Copernicus Climate Change Service and Copernicus Atmospheric Monitoring Service and adjusted for higher-resolution topographic effects.   

- **[`notebooks/step3_model_et.ipynb`](./notebooks/step3_model_et.ipynb)** – Runs the **Two Source Energy Balance (TSEB)** model to estimate daily actual evapotranspiration. It takes as input the data prepared in the previous notebooks.

These notebooks form a complete workflow, from data retrieval and preprocessing to sharpening LST and running the ET model.

## Development
You are welcome to contribute to the project my making either a Pull Request or a Ticket.

For setting up a development environment, you have two options:
1. **Using a Dev Container**
    This repository includes a devcontainer setup, which provides a pre-configured environment for development.

2. **Manual Setup** If you prefer a local setup
    * Make sure GDAL is installed on your system.
    * Create a virtual environment and install the package with either pip or UV:
    ```sh
        python -m venv senet-env
        source senet-env/bin/activate # On Windows, use `senet-env\Scripts\activate`
        pip install .
    ```

## References
1. Guzinski, R., Nieto, H., Sandholt, I., Karamitilios, G. (2020). Modelling High-Resolution Actual Evapotranspiration through Sentinel-2 and Sentinel-3 Data Fusion. Remote Sensing 12, 1433. https://www.mdpi.com/2072-4292/12/9/1433
2. Guzinski, R., Nieto, H., Sánchez, J.M., López-Urrea, R., Boujnah, D.M., and Boulet, G. (2021). Utility of Copernicus-Based Inputs for Actual Evapotranspiration Modeling in Support of Sustainable Water Use in Agriculture. IEEE Journal of Selected Topics in Applied Earth Observations and Remote Sensing 14, 11466–11484. https://doi.org/10.1109/JSTARS.2021.3122573.
3. Guzinski, R., Nieto, H., Ramo Sánchez, R., Sánchez, J.M., Jomaa, I., Zitouna-Chebbi, R., Roupsard, O., and López-Urrea, R. (2023). Improving field-scale crop actual evapotranspiration monitoring with Sentinel-3, Sentinel-2, and Landsat data fusion. International Journal of Applied Earth Observation and Geoinformation 125, 103587. https://doi.org/10.1016/j.jag.2023.103587.
4. Nieto, H., Radoslaw Guzinski, Graae, P., Jonas, ClaireBrenner, Mike, and Gabrielmini (2023). hectornieto/pyTSEB: v2.2. Version v.2.2 (Zenodo). https://doi.org/10.5281/ZENODO.594732 https://doi.org/10.5281/ZENODO.594732.


