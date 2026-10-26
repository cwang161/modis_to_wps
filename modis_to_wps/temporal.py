"""Simple temporal aggregation for already spatially aligned arrays.

Not a substitute for QA, scaling, or per-pixel valid-observation weighting.
"""
from datetime import datetime, timedelta
import numpy as np


def monthly_mean(dates, arrays, *, nodata=None):
    """Return {month: mean-array}, ignoring NaN and optional nodata."""
    if len(dates) != len(arrays):
        raise ValueError("dates and arrays lengths differ")
    output = {}
    for month in range(1, 13):
        selected = []
        for date, array in zip(dates, arrays):
            if date.month != month:
                continue
            a = np.asarray(array, dtype=np.float64).copy()
            if nodata is not None:
                a[a == nodata] = np.nan
            selected.append(a)
        if selected:
            stack = np.stack(selected)
            count = np.sum(np.isfinite(stack), axis=0)
            total = np.nansum(stack, axis=0)
            output[month] = np.divide(total, count, out=np.full_like(total, np.nan), where=count > 0)
    return output


def modis_date(year_doy):
    return datetime.strptime(year_doy, "%Y%j")
