from app.bazi_engine.versions import (
    CURRENT_CALCULATION_VERSION,
    CalculationVersion,
    is_supported_calculation_version,
)


def test_current_calculation_version_is_engine_v2():
    assert CURRENT_CALCULATION_VERSION == CalculationVersion.ENGINE_V2


def test_supported_calculation_versions_are_explicit():
    assert is_supported_calculation_version("legacy-1") is True
    assert is_supported_calculation_version("bazi-engine-2.0") is True
    assert is_supported_calculation_version("future-99") is False
