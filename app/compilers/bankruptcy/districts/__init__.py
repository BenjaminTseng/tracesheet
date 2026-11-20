"""California federal bankruptcy district adapters (`CACB` and `CAEB`)."""

from app.compilers.bankruptcy.districts.base import DistrictAdapter, get_district_adapter
from app.compilers.bankruptcy.districts.cacb import CACBDistrictAdapter
from app.compilers.bankruptcy.districts.caeb import CAEBDistrictAdapter

__all__ = [
    "DistrictAdapter",
    "CACBDistrictAdapter",
    "CAEBDistrictAdapter",
    "get_district_adapter",
]
