# modis_to_wps (v0.1.0 — initial scaffold)

A new, standalone Python package to progressively implement **MODIS HDF4 → WPS geogrid** conversion for WPS v4.0 / WRF v3.6.1. Based on a source review of the user's `pm25_ds.zip`.

## Four target fields

| WPS target | MODIS product | Native frequency | Planned output |
|---|---|---|---|
| LANDUSEF | MCD12Q1 LC_Type1 | Annual | Year-specific land cover |
| GREENFRAC | MOD13A3 NDVI **or** MCD15A2H FPAR | Monthly / 8-day | 12 monthly layers |
| LAI12M | MCD15A2H Lai_500m | 8-day | 12 monthly layers |
| ALBEDO12M (verify WPS field name) | MCD43A3 **or** MCD43C3 | Daily | 12 monthly layers |

## What works now

- Installable Python package and CLI.
- Product registry for all four fields and both alternative sources.
- NASA Earthaccess product search/download (`download`), requiring credentials and internet.
- Scan local HDF files by MODIS acquisition date (`scan`).
- List HDF subdatasets and read a selected HDF4 layer directly with GDAL (`inspect-hdf`, Python API `read_layer`).
- Unit-tested, elementary monthly aggregation of aligned, already scaled and QC'd arrays (`monthly_mean`).
- Reference copies of relevant original `pm25_ds` scripts in `legacy_reference/`, **not imported** into the new package, since they depend on the old project configuration.

## Not implemented yet (important)

- Full HDF tile mosaicking/reprojection in the new pipeline; global blockwise processing.
- Product-specific QA, scale/offset, temporal compositing, leap year and observation weighting.
- NDVI → GVF calibration (or FPAR-as-GVF assumption).
- MCD12Q1 IGBP → WRF MODIS 20/21-class handling, lakes and masks.
- WPS geogrid binary tiles, `index`, and GEOGRID.TBL generation; **no WPS output yet**.
- Integration tests using real HDF and geogrid.exe.

The legacy code includes mosaic and GDAL processing logic for reference; do not assume it can be directly applied to all four products without adaptation.

## Installation

```bash
conda create -n modis_wps -c conda-forge python=3.11 gdal numpy pyyaml python-dateutil pytest -y
conda activate modis_wps
pip install -e '.[nasa,test]'
```

## Commands

```bash
modis-to-wps products
modis-to-wps scan /path/to/hdf --product MCD12Q1 --year 2019
modis-to-wps inspect-hdf /path/to/MCD12Q1.A2019001.h25v06.061.xxx.hdf
modis-to-wps download MCD12Q1 2019 ./data/hdf --bbox 65 0 135 55
pytest -q
```

`download` contacts NASA and may require Earthdata login. No data are downloaded automatically.

## Development order

1. Inspect real sample HDF for all products; confirm exact layer names, QA, fill values, scales.
2. Implement validated local MODIS tile mosaic and blockwise EPSG:4326 reprojection.
3. Implement WPS binary/index writer with synthetic-array round-trip tests.
4. Complete landcover class mapping and lake policy; validate with WPS v4.0.
5. Add monthly LAI/GVF/albedo compositing and QA.
6. Run real-data end-to-end tests and compare `geo_em.d01.nc` against source.
