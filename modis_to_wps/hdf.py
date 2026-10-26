"""Read MODIS HDF4 subdatasets with GDAL, without an intermediate GeoTIFF."""
from pathlib import Path


def subdatasets(path):
    from osgeo import gdal
    ds = gdal.Open(str(path))
    if ds is None:
        raise RuntimeError(f"Unable to open HDF: {path}")
    return ds.GetSubDatasets()


def find_layer(path, candidates):
    matches = [(name, desc) for name, desc in subdatasets(path)
               if any(name.rsplit(':', 1)[-1].lower() == c.lower() for c in candidates)]
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one matching layer in {Path(path).name}, got {len(matches)}. "
                         f"Candidates: {candidates}. Inspect with 'inspect-hdf'.")
    return matches[0][0]


def read_layer(path, candidates):
    from osgeo import gdal
    name = find_layer(path, candidates)
    ds = gdal.Open(name)
    if ds is None:
        raise RuntimeError(f"Unable to open subdataset {name}")
    band = ds.GetRasterBand(1)
    return band.ReadAsArray(), {
        "subdataset": name, "geotransform": ds.GetGeoTransform(),
        "projection": ds.GetProjection(), "nodata": band.GetNoDataValue(),
        "scale": band.GetScale(), "offset": band.GetOffset(),
        "metadata": band.GetMetadata(),
    }
