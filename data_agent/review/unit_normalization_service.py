"""Shared unit normalization and conversion helpers for aero review services."""

from __future__ import annotations

import math
from collections import deque


def _unit_key(unit: str) -> str:
    return (
        str(unit or "")
        .strip()
        .replace("／", "/")
        .replace("﹒", "·")
        .replace("⋅", "·")
        .lower()
    )


UNIT_ALIASES: dict[str, str] = {
    "deg": "deg",
    "degree": "deg",
    "degrees": "deg",
    "°": "deg",
    "度": "deg",
    "rad": "rad",
    "radian": "rad",
    "radians": "rad",
    "弧度": "rad",
    "mrad": "mrad",
    "毫弧度": "mrad",
    "ms": "ms",
    "millisecond": "ms",
    "milliseconds": "ms",
    "毫秒": "ms",
    "s": "s",
    "sec": "s",
    "second": "s",
    "seconds": "s",
    "秒": "s",
    "min": "min",
    "minute": "min",
    "minutes": "min",
    "分钟": "min",
    "hz": "Hz",
    "hertz": "Hz",
    "赫兹": "Hz",
    "db": "dB",
    "分贝": "dB",
    "deg/s": "deg/s",
    "deg/sec": "deg/s",
    "degree/s": "deg/s",
    "degrees/s": "deg/s",
    "°/s": "deg/s",
    "°/秒": "deg/s",
    "度/s": "deg/s",
    "度/秒": "deg/s",
    "deg/min": "deg/min",
    "degree/min": "deg/min",
    "°/min": "deg/min",
    "度/min": "deg/min",
    "度/分钟": "deg/min",
    "deg/h": "deg/h",
    "deg/hour": "deg/h",
    "degree/h": "deg/h",
    "degree/hour": "deg/h",
    "°/h": "deg/h",
    "度/h": "deg/h",
    "度/小时": "deg/h",
    "rad/s": "rad/s",
    "rad/sec": "rad/s",
    "radian/s": "rad/s",
    "radians/s": "rad/s",
    "弧度/s": "rad/s",
    "弧度/秒": "rad/s",
    "rad/h": "rad/h",
    "rad/hour": "rad/h",
    "radian/h": "rad/h",
    "弧度/h": "rad/h",
    "弧度/小时": "rad/h",
    "n·m": "N·m",
    "n*m": "N·m",
    "nm": "N·m",
    "牛顿米": "N·m",
    "n·m·s": "N·m·s",
    "n*m*s": "N·m·s",
    "nms": "N·m·s",
    "牛米秒": "N·m·s",
    "牛·米·秒": "N·m·s",
    "牛顿·米·秒": "N·m·s",
    "mn·s": "mN·s",
    "mn*s": "mN·s",
    "毫牛秒": "mN·s",
    "毫牛·秒": "mN·s",
    "mnm·s": "mN·m·s",
    "mnm*s": "mN·m·s",
    "mnms": "mN·m·s",
    "毫牛米秒": "mN·m·s",
    "毫牛·米·秒": "mN·m·s",
    "m/s²": "m/s^2",
    "m/s^2": "m/s^2",
    "m/s2": "m/s^2",
    "米/秒²": "m/s^2",
    "米/秒^2": "m/s^2",
    "米每秒平方": "m/s^2",
    "m/s": "m/s",
    "米/秒": "m/s",
    "米每秒": "m/s",
    "mm/s": "mm/s",
    "毫米/秒": "mm/s",
    "毫米每秒": "mm/s",
    "km/s": "km/s",
    "千米/秒": "km/s",
    "m": "m",
    "meter": "m",
    "metre": "m",
    "meters": "m",
    "metres": "m",
    "米": "m",
    "mm": "mm",
    "millimeter": "mm",
    "millimetre": "mm",
    "millimeters": "mm",
    "millimetres": "mm",
    "毫米": "mm",
    "km": "km",
    "kilometer": "km",
    "kilometre": "km",
    "kilometers": "km",
    "kilometres": "km",
    "千米": "km",
    "公里": "km",
    "g": "g",
    "gram": "g",
    "grams": "g",
    "克": "g",
    "gee": "g0",
    "g0": "g0",
    "重力加速度": "g0",
    "w": "W",
    "watt": "W",
    "watts": "W",
    "瓦": "W",
    "mw": "mW",
    "milliwatt": "mW",
    "milliwatts": "mW",
    "毫瓦": "mW",
    "kw": "kW",
    "kilowatt": "kW",
    "千瓦": "kW",
    "n": "N",
    "newton": "N",
    "newtons": "N",
    "牛顿": "N",
    "mn": "mN",
    "millinewton": "mN",
    "millinewtons": "mN",
    "毫牛": "mN",
    "pa": "Pa",
    "pascal": "Pa",
    "pascals": "Pa",
    "帕": "Pa",
    "kpa": "kPa",
    "kilopascal": "kPa",
    "kilopascals": "kPa",
    "千帕": "kPa",
    "mhz": "mHz",
    "millihertz": "mHz",
    "毫赫": "mHz",
    "kgf": "kgf",
    "千克力": "kgf",
    "kg": "kg",
    "kilogram": "kg",
    "kilograms": "kg",
    "千克": "kg",
    "公斤": "kg",
}


UNIT_DIMENSIONS: dict[str, str] = {
    "deg": "angle",
    "rad": "angle",
    "mrad": "angle",
    "deg/s": "angular_rate",
    "deg/min": "angular_rate",
    "deg/h": "angular_rate",
    "rad/s": "angular_rate",
    "rad/h": "angular_rate",
    "ms": "time",
    "s": "time",
    "min": "time",
    "Hz": "frequency",
    "dB": "dimensionless_db",
    "N·m": "torque",
    "N·m·s": "angular_momentum",
    "mN·s": "impulse",
    "mN·m·s": "angular_momentum_small",
    "m/s^2": "acceleration",
    "g": "mass",
    "g0": "acceleration",
    "m/s": "velocity",
    "mm/s": "velocity",
    "km/s": "velocity",
    "m": "length",
    "mm": "length",
    "km": "length",
    "W": "power",
    "mW": "power",
    "kW": "power",
    "N": "force",
    "mN": "force",
    "kgf": "force",
    "kg": "mass",
    "Pa": "pressure",
    "kPa": "pressure",
    "mHz": "frequency",
    "%": "percent",
}


_CONVERSION_PAIRS: tuple[tuple[str, str, float], ...] = (
    ("ms", "s", 0.001),
    ("s", "min", 1.0 / 60.0),
    ("deg", "rad", math.pi / 180.0),
    ("rad", "mrad", 1000.0),
    ("deg/s", "rad/s", math.pi / 180.0),
    ("deg/s", "deg/h", 3600.0),
    ("deg/s", "deg/min", 60.0),
    ("rad/s", "rad/h", 3600.0),
    ("km/s", "m/s", 1000.0),
    ("m/s", "mm/s", 1000.0),
    ("km", "m", 1000.0),
    ("m", "mm", 1000.0),
    ("kg", "g", 1000.0),
    ("N", "mN", 1000.0),
    ("Hz", "mHz", 1000.0),
    ("Pa", "kPa", 0.001),
    ("W", "mW", 1000.0),
    ("W", "kW", 0.001),
    ("N", "kgf", 1.0 / 9.80665),
    ("g0", "m/s^2", 9.80665),
)


def _build_conversion_graph() -> dict[str, list[tuple[str, float]]]:
    graph: dict[str, list[tuple[str, float]]] = {}
    for source, target, factor in _CONVERSION_PAIRS:
        graph.setdefault(source, []).append((target, factor))
        graph.setdefault(target, []).append((source, 1.0 / factor))
    return graph


UNIT_CONVERSIONS: dict[str, list[tuple[str, float]]] = _build_conversion_graph()

# Backward-compatible alias for code that inspects the old table shape.
DIRECT_UNIT_CONVERSIONS: dict[str, list[tuple[str, float]]] = {
    "ms": [("s", 0.001)],
    "s": [("ms", 1000.0), ("min", 1.0 / 60.0)],
    "min": [("s", 60.0)],
    "deg": [("rad", math.pi / 180.0), ("mrad", math.pi / 180.0 * 1000.0)],
    "rad": [("deg", 180.0 / math.pi), ("mrad", 1000.0)],
    "mrad": [("rad", 0.001), ("deg", 180.0 / (math.pi * 1000.0))],
    "deg/s": [("rad/s", math.pi / 180.0), ("deg/h", 3600.0), ("deg/min", 60.0)],
    "rad/s": [("deg/s", 180.0 / math.pi), ("rad/h", 3600.0), ("deg/h", (180.0 * 3600.0) / math.pi)],
    "deg/h": [("deg/s", 1.0 / 3600.0), ("rad/s", math.pi / (180.0 * 3600.0))],
    "deg/min": [("deg/s", 1.0 / 60.0)],
    "rad/h": [("rad/s", 1.0 / 3600.0)],
    "g0": [("m/s^2", 9.80665)],
    "m/s^2": [("g0", 1.0 / 9.80665)],
    "km/s": [("m/s", 1000.0)],
    "m/s": [("km/s", 0.001)],
    "W": [("kW", 0.001)],
    "kW": [("W", 1000.0)],
    "N": [("kgf", 1.0 / 9.80665)],
    "kgf": [("N", 9.80665)],
}


def normalize_unit(raw_unit: str) -> str | None:
    if raw_unit is None:
        return None
    raw = str(raw_unit).strip()
    if not raw:
        return None
    return UNIT_ALIASES.get(_unit_key(raw), raw)


def get_dimension(canonical_unit: str) -> str | None:
    unit = normalize_unit(canonical_unit)
    if not unit:
        return None
    return UNIT_DIMENSIONS.get(unit)


def is_compatible(unit_a: str, unit_b: str) -> bool:
    dim_a = get_dimension(unit_a)
    dim_b = get_dimension(unit_b)
    return bool(dim_a and dim_b and dim_a == dim_b)


def convert_value(value: float, from_unit: str, to_unit: str) -> float | None:
    source = normalize_unit(from_unit)
    target = normalize_unit(to_unit)
    if not source or not target:
        return None
    if source == target:
        return float(value)
    if not is_compatible(source, target):
        return None
    queue: deque[tuple[str, float]] = deque([(source, 1.0)])
    visited = {source}
    while queue:
        current, factor_to_current = queue.popleft()
        for candidate, factor in UNIT_CONVERSIONS.get(current, []):
            if candidate in visited:
                continue
            next_factor = factor_to_current * factor
            if candidate == target:
                return float(value) * next_factor
            visited.add(candidate)
            queue.append((candidate, next_factor))
    return None


def canonicalize_value(value: float, raw_unit: str) -> tuple[float, str]:
    unit = normalize_unit(raw_unit)
    if not unit:
        return float(value), ""
    return float(value), unit
