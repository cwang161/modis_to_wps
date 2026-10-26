from datetime import datetime
import numpy as np
from modis_to_wps.catalog import scan
from modis_to_wps.temporal import monthly_mean, modis_date
from modis_to_wps.products import PRODUCTS
from modis_to_wps.pipeline import convert_to_wps
import pytest

def test_product_catalog():
    assert len(PRODUCTS) == 6
    assert PRODUCTS['landcover'].product == 'MCD12Q1'

def test_scan(tmp_path):
    (tmp_path / 'MCD12Q1.A2019001.h25v06.061.123.hdf').touch()
    (tmp_path / 'MCD12Q1.A2020001.h25v06.061.123.hdf').touch()
    assert len(scan(tmp_path, 'MCD12Q1', 2019)) == 1

def test_monthly():
    result = monthly_mean([datetime(2019, 1, 1), datetime(2019, 1, 9)],
                          [np.array([[1., -999]]), np.array([[3., 4.]])], nodata=-999)
    assert np.allclose(result[1], [[2., 4.]])
    assert modis_date('2019001') == datetime(2019, 1, 1)

def test_unimplemented_wps_is_explicit():
    with pytest.raises(NotImplementedError):
        convert_to_wps()
