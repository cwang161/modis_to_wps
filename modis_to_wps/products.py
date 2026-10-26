"""Product definitions. HDF subdataset selection must be confirmed against files."""
from dataclasses import dataclass

@dataclass(frozen=True)
class Product:
    product: str
    frequency: str
    target: str
    candidate_layers: tuple[str, ...]
    resampling: str
    notes: str

PRODUCTS = {
    "landcover": Product("MCD12Q1", "annual", "LANDUSEF", ("LC_Type1",), "nearest", "IGBP categories; WRF class mapping not yet implemented"),
    "gvf_ndvi": Product("MOD13A3", "monthly", "GREENFRAC", ("1 km monthly NDVI", "NDVI"), "average", "NDVI-to-GVF formula must be configured and validated"),
    "gvf_fpar": Product("MCD15A2H", "8-day", "GREENFRAC", ("Fpar_500m",), "average", "FPAR proxy for GVF; scale and QA required"),
    "lai": Product("MCD15A2H", "8-day", "LAI12M", ("Lai_500m",), "average", "Scale and QA required"),
    "albedo_a3": Product("MCD43A3", "daily", "ALBEDO12M", ("Albedo_WSA_shortwave", "Albedo_BSA_shortwave"), "average", "Select black/white sky convention explicitly"),
    "albedo_c3": Product("MCD43C3", "daily", "ALBEDO12M", ("Albedo_WSA_shortwave", "Albedo_BSA_shortwave"), "average", "CMG product; check band names and scale"),
}
