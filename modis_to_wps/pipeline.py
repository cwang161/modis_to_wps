"""WPS output intentionally gated until categorical and geogrid tests exist."""
from .products import PRODUCTS

def plan(kind):
    if kind not in PRODUCTS:
        raise KeyError(f"Unknown kind {kind}; choose from {list(PRODUCTS)}")
    return PRODUCTS[kind]

def convert_to_wps(*args, **kwargs):
    raise NotImplementedError("WPS writer, class mapping, QA, and reprojection are planned for a subsequent validated implementation")
