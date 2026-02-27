![Project Status](https://img.shields.io/badge/Status-Development-yellow)
[![GitHub last commit](https://img.shields.io/github/last-commit/DHI/Sen-ET-OpenEO-toolbox)](#)

# Sen-ET OpenEO toolbox
> ⚠️ **Note:** This project is under active development. Features may change and bugs may exist.

This repository contains openEO workflows for various python modules used in Evapotranspiration (ET) modeling and Irrigation mapping. 
Following modules are currently included:
* [Data Mining Sharpener (pyDMS)](https://github.com/radosuav/pyDMS)
* [Two Source Energy Balance (TSEB)](https://github.com/hectornieto/pyTSEB)


## Installation
### Installation on Copernicus Data Space (CDSE) JupyterHub
1. Go to [https://jupyterhub.dataspace.copernicus.eu](https://jupyterhub.dataspace.copernicus.eu) and start a server
2. In the server either upload the notebooks manually or clone this repo by opening a terminal and running
    ```
    git clone https://github.com/DHI/Sen-ET-OpenEO-toolbox.git mystorage/sen-et-toolbox
    ```
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

  >💡**Note**: The package is installed in the first cell of the notebooks. You *should* be able run the notebooks out of the box without any additional setup if using a kernel with GDAL installed, but sometimes there can be conflics with existing packages in the environment. It is recommended to to a clean kernel installation

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
- **[`notebooks/step1_prepare_data.ipynb`](./notebooks/step1_prepare_data.ipynb)** – This notebook prepares Sentinel-2 and Sentinel-3 data for PyDMS and ET Flows by allowing users to define an area of interest, select suitable acquisition dates, and download the relevant datasets using OpenEO. It extracts vegetation indices and land cover parameters from **Sentinel-2** and **ESA WorldCover** datasets. 

- **[`notebooks/step2_pydms.ipynb`](./notebooks/step2_pydms.ipynb)** – Demonstrates how to use the **Data Mining Sharpener (pyDMS)** to refine Sentinel-3 Land Surface Temperature (LST) using Sentinel-2 reflectance data.  

- **[`notebooks/step3_et_input_parameters.ipynb`](./notebooks/step3_et_input_parameters.ipynb)** – Focuses on preprocessing meteorological and biophysical input data. This includes:  
  - Retrieving meteorological parameters from the **Copernicus Climate Data Store (CDS)**.  
  - Resampling the meteorological parameters to the Sentinel 2 resolution

- **[`notebooks/step4_et_tseb.ipynb`](./notebooks/step4_et_tseb.ipynb)** – Runs the **Two Source Energy Balance (TSEB)** model to estimate evapotranspiration. It takes as input:  
  - Sharpened LST from pyDMS.  
  - Preprocessed meteorological and vegetation parameters.  

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
