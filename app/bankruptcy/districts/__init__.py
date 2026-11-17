"""California federal bankruptcy district adapters (`CACB` and `CAEB`)."""

from app.bankruptcy.districts.base import DistrictAdapter, get_district_adapter
from app.bankruptcy.districts.cacb import CACBDistrictAdapter
from app.bankruptcy.districts.caeb import CAEBDistrictAdapter

__all__ = [
    "DistrictAdapter",
    "CACBDistrictAdapter",
    "CAEBDistrictAdapter",
    "get_district_adapter",
]
