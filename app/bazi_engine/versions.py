"""Calculation version identifiers for reproducible Bazi charts."""

from enum import Enum


class CalculationVersion(str, Enum):
    """Supported deterministic calculation contracts."""

    LEGACY_V1 = "legacy-1"
    ENGINE_V2 = "bazi-engine-2.0"


LEGACY_CALCULATION_VERSION = CalculationVersion.LEGACY_V1
CURRENT_CALCULATION_VERSION = CalculationVersion.ENGINE_V2
SUPPORTED_CALCULATION_VERSIONS = tuple(CalculationVersion)


def is_supported_calculation_version(value: str) -> bool:
    """Return whether ``value`` is a calculation version known by this build."""

    try:
        CalculationVersion(value)
    except ValueError:
        return False
    return True
