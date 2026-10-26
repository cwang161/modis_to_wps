"""NASA Earthaccess search/download, optional dependency and authentication."""
from pathlib import Path


def download_product(product, year, output_dir, *, bounding_box=None):
    import earthaccess
    earthaccess.login()
    kw = {"short_name": product, "temporal": (f"{year}-01-01", f"{year}-12-31")}
    if bounding_box is not None:
        kw["bounding_box"] = tuple(bounding_box)
    results = earthaccess.search_data(**kw)
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    return earthaccess.download(results, str(output_dir))
