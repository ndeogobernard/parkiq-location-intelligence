"""Unit conversions (ADR-0019). The only place distance/area conversions happen.

These are physical constants, not modelling assumptions, so they live in code.
CRS linear units are read from the CRS itself (pyproj), never assumed from the config.
"""

from __future__ import annotations

from pyproj import CRS

M_PER_FT_INTL = 0.3048
M_PER_MILE = 1609.344
SQFT_PER_M2 = 1.0 / (M_PER_FT_INTL**2)  # 10.7639104...
M2_PER_KM2 = 1_000_000.0
SECONDS_PER_MINUTE = 60.0


def crs_unit_to_m(crs: CRS | str) -> float:
    """Return metres per CRS linear unit.

    Args:
        crs: A projected CRS (pyproj CRS or any string pyproj accepts, e.g. ``"EPSG:3735"``).

    Returns:
        Metres per unit (1.0 for metres, 0.3048006096... for US survey feet).

    Raises:
        ValueError: If the CRS is geographic or has no linear unit.
    """
    c = CRS.from_user_input(crs)
    if not c.is_projected:
        raise ValueError(f"CRS {c.to_string()} is not projected; analysis_crs must be projected")
    factor = c.axis_info[0].unit_conversion_factor
    if not factor:
        raise ValueError(f"CRS {c.to_string()} has no linear unit conversion factor")
    return float(factor)


def crs_unit_kind(crs: CRS | str) -> str:
    """Classify a projected CRS's linear unit as ``"m"`` or ``"ft"``.

    Args:
        crs: Projected CRS.

    Returns:
        ``"m"`` if the unit is the metre, ``"ft"`` for international or US survey feet.

    Raises:
        ValueError: For any other unit.
    """
    f = crs_unit_to_m(crs)
    if abs(f - 1.0) < 1e-12:
        return "m"
    if abs(f - M_PER_FT_INTL) < 1e-5:  # covers US survey foot 0.30480061
        return "ft"
    raise ValueError(f"Unsupported CRS linear unit ({f} m per unit)")


def m_to_crs(value_m: float, crs: CRS | str) -> float:
    """Convert metres to CRS units."""
    return value_m / crs_unit_to_m(crs)


def crs_to_m(value: float, crs: CRS | str) -> float:
    """Convert CRS units to metres."""
    return value * crs_unit_to_m(crs)


def crs_area_to_sqft(area: float, crs: CRS | str) -> float:
    """Convert an area in CRS units² to square feet (international)."""
    return area * crs_unit_to_m(crs) ** 2 * SQFT_PER_M2


def crs_area_to_km2(area: float, crs: CRS | str) -> float:
    """Convert an area in CRS units² to km²."""
    return area * crs_unit_to_m(crs) ** 2 / M2_PER_KM2


def ft_to_m(value_ft: float) -> float:
    """International feet → metres."""
    return value_ft * M_PER_FT_INTL


def miles_to_m(value_mi: float) -> float:
    """Statute miles → metres."""
    return value_mi * M_PER_MILE


def walk_minutes(length_m: float, speed_m_s: float) -> float:
    """Walking time in minutes for a length in metres at ``speed_m_s`` metres per second."""
    if speed_m_s <= 0:
        raise ValueError("walking speed must be > 0 m/s")
    return length_m / speed_m_s / SECONDS_PER_MINUTE
