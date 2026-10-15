"""Places: coordinates, distances, shapes and geohashes (E1).

A place is a latitude and a longitude in two number columns (WGS84 degrees),
or a shape written as WKT (``POINT (lon lat)``, ``POLYGON ((...))``) or GeoJSON
in a `geography` column. Distances on the earth are measured two ways, both
stated: **haversine**, on a sphere of radius 6,371,008.8 m (within about 0.5%
of the true distance), which is ordinary arithmetic and so pushes down to a
database; and **on the ellipsoid**, by Vincenty's method on WGS84 (to the
millimetre), which runs here. Areas are on the same sphere. Shapes are
handled by shapely; nothing calls out to a map service.
"""

from __future__ import annotations

import json
import math
import re
from typing import Any

import numpy as np
import pandas as pd

from shared_python.errors import BadRequestError
from shared_python.types import BOOLEAN, FLOAT64, GEOGRAPHY, STRING

from service_transformations.ir.expressions import Call, Case, Column, Expr, Literal
from service_transformations.ir.nodes import Node, Project
from service_transformations.tools import register
from service_transformations.tools.builders import require_column, unique_name
from service_transformations.tools.local import (
    brought,
    column_extension,
    extension,
    handles,
    other_dataset,
    require_other_columns,
)
from service_transformations.tools.spec import EXAMPLE_DATASET, Accepts, Example, Param, ParamKind, ToolSpec

CATEGORY = "Geospatial"
EARTH_RADIUS = 6_371_008.8  # metres: the mean radius, IUGG
UNITS = {"metres": 1.0, "kilometres": 1000.0, "miles": 1609.344, "nautical miles": 1852.0}
UNIT = Param("unit", "In", ParamKind.SELECT, required=False, default="kilometres", options=tuple(UNITS))
LAT = Param("lat", "Latitude", ParamKind.COLUMN)
LON = Param("lon", "Longitude", ParamKind.COLUMN)
LAT2 = Param("lat2", "To latitude", ParamKind.COLUMN)
LON2 = Param("lon2", "To longitude", ParamKind.COLUMN)
_CITIES = ({"lat": 51.5074, "lon": -0.1278, "lat2": 48.8566, "lon2": 2.3522},
           {"lat": 40.7128, "lon": -74.0060, "lat2": 34.0522, "lon2": -118.2437})


def _declare(name: str, title: str, summary: str, build, example: Example, *, params: tuple[Param, ...] = (),
             synonyms: tuple[str, ...] = (), column_scoped: bool = False, local_only: bool = True,
             reads_dataset: bool = False, accepts: Accepts = Accepts.ANY, null_answer: bool = False) -> ToolSpec:
    return register(ToolSpec(
        name=name, title=title, category=CATEGORY, summary=summary, build=build, example=example, params=params,
        synonyms=synonyms, column_scoped=column_scoped, local_only=local_only, reads_dataset=reads_dataset,
        accepts=accepts, null_answer=null_answer, warns_lost=False, row_wise=True,
    ))


def _into(node: Node, params: dict[str, Any], preferred: str) -> str:
    into = (params.get("into") or "").strip() or unique_name(node, preferred)
    if into in node.schema():
        raise BadRequestError(f"Column {into!r} already exists. Choose another name.")
    return into


def _lit(value: float) -> Literal:
    return Literal(float(value), FLOAT64)


def _call(name: str, *args: Expr) -> Call:
    return Call(name, tuple(args))


def haversine(lat1: Expr, lon1: Expr, lat2: Expr, lon2: Expr) -> Expr:
    """Great-circle distance in metres, as IR, so it pushes down."""
    phi1, phi2 = _call("radians", lat1), _call("radians", lat2)
    half_dphi = _call("mul", _call("radians", _call("sub", lat2, lat1)), _lit(0.5))
    half_dlambda = _call("mul", _call("radians", _call("sub", lon2, lon1)), _lit(0.5))
    sin_dphi, sin_dlambda = _call("sin", half_dphi), _call("sin", half_dlambda)
    a = _call("add", _call("mul", sin_dphi, sin_dphi),
              _call("mul", _call("mul", _call("cos", phi1), _call("cos", phi2)), _call("mul", sin_dlambda, sin_dlambda)))
    # Rounding can push a for antipodal points a hair past 1, outside asin.
    clamped = Case(((_call("gt", a, _lit(1.0)), _lit(1.0)),), a)
    return _call("mul", _lit(2 * EARTH_RADIUS), _call("asin", _call("sqrt", clamped)))


def vincenty(lat1: float, lon1: float, lat2: float, lon2: float) -> float | None:
    """Distance in metres on the WGS84 ellipsoid (Vincenty's inverse formula)."""
    a, f = 6_378_137.0, 1 / 298.257223563
    b = (1 - f) * a
    if lat1 == lat2 and lon1 == lon2:
        return 0.0
    u1, u2 = math.atan((1 - f) * math.tan(math.radians(lat1))), math.atan((1 - f) * math.tan(math.radians(lat2)))
    lam = big_l = math.radians(lon2 - lon1)
    sin_u1, cos_u1, sin_u2, cos_u2 = math.sin(u1), math.cos(u1), math.sin(u2), math.cos(u2)
    for _ in range(200):
        sin_lam, cos_lam = math.sin(lam), math.cos(lam)
        sin_sigma = math.hypot(cos_u2 * sin_lam, cos_u1 * sin_u2 - sin_u1 * cos_u2 * cos_lam)
        if sin_sigma == 0:
            return 0.0
        cos_sigma = sin_u1 * sin_u2 + cos_u1 * cos_u2 * cos_lam
        sigma = math.atan2(sin_sigma, cos_sigma)
        sin_alpha = cos_u1 * cos_u2 * sin_lam / sin_sigma
        cos2_alpha = 1 - sin_alpha ** 2
        cos_2sm = cos_sigma - 2 * sin_u1 * sin_u2 / cos2_alpha if cos2_alpha else 0.0
        c = f / 16 * cos2_alpha * (4 + f * (4 - 3 * cos2_alpha))
        previous = lam
        lam = big_l + (1 - c) * f * sin_alpha * (sigma + c * sin_sigma * (cos_2sm + c * cos_sigma * (
            -1 + 2 * cos_2sm ** 2)))
        if abs(lam - previous) < 1e-12:
            break
    else:
        return None  # nearly antipodal: the method does not settle
    u_sq = cos2_alpha * (a * a - b * b) / (b * b)
    big_a = 1 + u_sq / 16384 * (4096 + u_sq * (-768 + u_sq * (320 - 175 * u_sq)))
    big_b = u_sq / 1024 * (256 + u_sq * (-128 + u_sq * (74 - 47 * u_sq)))
    delta = big_b * sin_sigma * (cos_2sm + big_b / 4 * (cos_sigma * (-1 + 2 * cos_2sm ** 2) - big_b / 6 * cos_2sm * (
        -3 + 4 * sin_sigma ** 2) * (-3 + 4 * cos_2sm ** 2)))
    return b * big_a * (sigma - delta)


def _passing(node: Node, made: dict[str, Expr]) -> Project:
    return Project(node, tuple([(name, Column(name)) for name in node.schema()] + list(made.items())))


# ------------------------------------------------------------------ distance


def _distance_build(node: Node, params: dict[str, Any]) -> Node:
    names = [require_column(node, params.get(key)) for key in ("lat", "lon", "lat2", "lon2")]
    into = _into(node, params, "distance")
    unit = params.get("unit") or "kilometres"
    if (params.get("method") or "haversine") == "haversine":
        metres = haversine(*(Column(name) for name in names))
        return _passing(node, {into: _call("div", metres, _lit(UNITS[unit]))})
    return extension(node, "geo.distance", {"names": names, "into": into, "unit": unit}, {**node.schema(), into: FLOAT64})


@handles("geo.distance")
def _distance(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    numbers = frame[list(config["names"])].apply(pd.to_numeric, errors="coerce")
    scale = UNITS[config.get("unit") or "kilometres"]
    out = frame.copy()
    out[config["into"]] = [None if any(pd.isna(v) for v in row) else (lambda d: None if d is None else d / scale)(
        vincenty(*row)) for row in numbers.itertuples(index=False, name=None)]
    return out


_declare("geo.distance", "Distance between two places", "The distance between two latitude and longitude pairs: "
         "haversine on a sphere (within about 0.5%, and it runs in the database) or on the WGS84 ellipsoid by "
         "Vincenty's method (to the millimetre).", _distance_build,
         Example(rows=_CITIES, params={"lat": "lat", "lon": "lon", "lat2": "lat2", "lon2": "lon2"}, column="lat",
                 output="distance", expect=(343.556535, 3935.751691)),
         params=(LAT, LON, LAT2, LON2, UNIT,
                 Param("method", "Measured", ParamKind.SELECT, required=False, default="haversine",
                       options=("haversine", "ellipsoid")),
                 Param("into", "New column", ParamKind.TEXT, required=False, default="")),
         synonyms=("distance between", "haversine", "great circle", "how far", "vincenty", "geodesic"),
         local_only=False)


def _bearing_build(node: Node, params: dict[str, Any]) -> Node:
    lat1, lon1, lat2, lon2 = (Column(require_column(node, params.get(key))) for key in ("lat", "lon", "lat2", "lon2"))
    into = _into(node, params, "bearing")
    phi1, phi2 = _call("radians", lat1), _call("radians", lat2)
    dlambda = _call("radians", _call("sub", lon2, lon1))
    y = _call("mul", _call("sin", dlambda), _call("cos", phi2))
    x = _call("sub", _call("mul", _call("cos", phi1), _call("sin", phi2)),
              _call("mul", _call("mul", _call("sin", phi1), _call("cos", phi2)), _call("cos", dlambda)))
    degrees = _call("degrees", _call("atan2", y, x))
    # From -180..180 to 0..360, without a modulo SQLite lacks.
    compass = Case(((_call("lt", degrees, _lit(0.0)), _call("add", degrees, _lit(360.0))),), degrees)
    return _passing(node, {into: compass})


_declare("geo.bearing", "Direction to another place", "The initial compass bearing, in degrees from north (0 to "
         "360), from one place towards another along the great circle.", _bearing_build,
         Example(rows=_CITIES[:1], params={"lat": "lat", "lon": "lon", "lat2": "lat2", "lon2": "lon2"}, column="lat",
                 output="bearing", expect=(148.115617,)),
         params=(LAT, LON, LAT2, LON2, Param("into", "New column", ParamKind.TEXT, required=False, default="")),
         synonyms=("bearing", "heading", "direction", "azimuth", "compass"), local_only=False)


def _radius_build(node: Node, params: dict[str, Any]) -> Node:
    lat, lon = (Column(require_column(node, params.get(key))) for key in ("lat", "lon"))
    into = _into(node, params, "within_radius")
    metres = haversine(lat, lon, _lit(float(params["centre_lat"])), _lit(float(params["centre_lon"])))
    limit = float(params["radius"]) * UNITS[params.get("unit") or "kilometres"]
    return _passing(node, {into: _call("le", metres, _lit(limit))})


_declare("geo.within_radius", "Within a distance of a place", "True for places within a distance (haversine) of a "
         "centre you give: customers within 10 km of a shop.", _radius_build,
         Example(rows=({"lat": 51.51, "lon": -0.13}, {"lat": 53.48, "lon": -2.24}),
                 params={"lat": "lat", "lon": "lon", "centre_lat": 51.5074, "centre_lon": -0.1278, "radius": 10},
                 column="lat", output="within_radius", expect=(True, False)),
         params=(LAT, LON, Param("centre_lat", "Centre latitude", ParamKind.NUMBER, minimum=-90, maximum=90),
                 Param("centre_lon", "Centre longitude", ParamKind.NUMBER, minimum=-180, maximum=180),
                 Param("radius", "Distance", ParamKind.NUMBER, minimum=0), UNIT,
                 Param("into", "New column", ParamKind.TEXT, required=False, default="")),
         synonyms=("within radius", "nearby", "geofence", "within distance", "radius search"), local_only=False)


# ------------------------------------------------------------------- parsing

_DMS = re.compile(r"(-?\d+(?:\.\d+)?)\s*[°º d]\s*(?:(\d+(?:\.\d+)?)\s*['′m]\s*)?(?:(\d+(?:\.\d+)?)\s*[\"″s]?\s*)?"
                  r"([NSEW])?", re.I)


def _coordinate(text: str) -> tuple[float, float] | None:
    text = str(text).strip()
    point = re.fullmatch(r"(?i)POINT\s*\(\s*(-?[\d.]+)\s+(-?[\d.]+)\s*\)", text)
    if point:
        lon, lat = float(point.group(1)), float(point.group(2))
        return (lat, lon) if -90 <= lat <= 90 and -180 <= lon <= 180 else None
    plain = re.fullmatch(r"\s*(-?\d+(?:\.\d+)?)\s*[,; ]\s*(-?\d+(?:\.\d+)?)\s*", text)
    if plain:
        lat, lon = float(plain.group(1)), float(plain.group(2))
        return (lat, lon) if -90 <= lat <= 90 and -180 <= lon <= 180 else None
    found = [match for match in _DMS.finditer(text) if match.group(0).strip()]
    if len(found) != 2:
        return None
    values = []
    for match in found:
        degrees, minutes, seconds, hemisphere = match.groups()
        value = abs(float(degrees)) + float(minutes or 0) / 60 + float(seconds or 0) / 3600
        negative = float(degrees) < 0 or (hemisphere or "").upper() in ("S", "W")
        values.append((-value if negative else value, (hemisphere or "").upper()))
    (first, h1), (second, h2) = values
    if h1 in ("E", "W") or h2 in ("N", "S"):
        first, second = second, first
    return (first, second) if -90 <= first <= 90 and -180 <= second <= 180 else None


def _parse_build(node: Node, params: dict[str, Any]) -> Node:
    column = require_column(node, params.get("column"))
    prefix = params.get("prefix") if params.get("prefix") is not None else ""
    lat, lon = f"{prefix}latitude", f"{prefix}longitude"
    for name in (lat, lon):
        if name in node.schema():
            raise BadRequestError(f"Column {name!r} already exists; give a prefix.")
    return extension(node, "geo.parse_coordinates", {"column": column, "lat": lat, "lon": lon},
                     {**node.schema(), lat: FLOAT64, lon: FLOAT64})


@handles("geo.parse_coordinates")
def _parse(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    found = [None if pd.isna(v) else _coordinate(v) for v in frame[config["column"]]]
    out = frame.copy()
    out[config["lat"]] = [None if f is None else round(f[0], 7) for f in found]
    out[config["lon"]] = [None if f is None else round(f[1], 7) for f in found]
    return out.astype({config["lat"]: float, config["lon"]: float})


_declare("geo.parse_coordinates", "Read coordinates", "Read a place written as text into latitude and longitude "
         "columns: \"51.5, -0.12\", degrees, minutes and seconds such as 51°30'26\"N 0°7'39\"W, or WKT POINT "
         "(lon lat). Anything out of range is empty.", _parse_build,
         Example(rows=({"where": "51°30'26\"N 0°7'39\"W"}, {"where": "48.8566, 2.3522"}, {"where": "nowhere"}),
                 column="where", output="latitude", expect=(51.5072222, 48.8566, None)),
         params=(Param("prefix", "Start the new names with", ParamKind.TEXT, required=False, default=""),),
         synonyms=("parse coordinates", "lat long", "dms", "degrees minutes seconds", "geocoordinates"),
         column_scoped=True, accepts=Accepts.TEXTUAL)


def _point_build(node: Node, params: dict[str, Any]) -> Node:
    lat, lon = (require_column(node, params.get(key)) for key in ("lat", "lon"))
    into = _into(node, params, "place")
    return extension(node, "geo.make_point", {"lat": lat, "lon": lon, "into": into}, {**node.schema(), into: GEOGRAPHY})


@handles("geo.make_point")
def _point(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    numbers = frame[[config["lat"], config["lon"]]].apply(pd.to_numeric, errors="coerce")
    out = frame.copy()
    out[config["into"]] = [None if pd.isna(lat) or pd.isna(lon) else f"POINT ({lon:g} {lat:g})"
                           for lat, lon in numbers.itertuples(index=False, name=None)]
    return out


_declare("geo.make_point", "Make a point from coordinates", "Write a latitude and longitude as one WKT point "
         "(POINT (lon lat)) in a geography column.", _point_build,
         Example(rows=({"lat": 51.5, "lon": -0.12},), params={"lat": "lat", "lon": "lon"}, column="lat",
                 output="place", expect=("POINT (-0.12 51.5)",)),
         params=(LAT, LON, Param("into", "New column", ParamKind.TEXT, required=False, default="")),
         synonyms=("make point", "to wkt", "point from lat long"))


# ---------------------------------------------------------------- shapes


def shape(value: Any):
    """A shapely geometry from WKT or GeoJSON text, or None."""
    from shapely import wkt
    from shapely.geometry import shape as from_geojson

    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    text = str(value).strip()
    try:
        if text.startswith("{"):
            data = json.loads(text)
            return from_geojson(data.get("geometry", data) if data.get("type") == "Feature" else data)
        return wkt.loads(text)
    except Exception:  # noqa: BLE001 - not a shape is empty, as an unreadable date is
        return None


def _polygon_build(node: Node, params: dict[str, Any]) -> Node:
    lat, lon = (require_column(node, params.get(key)) for key in ("lat", "lon"))
    if shape(params.get("polygon")) is None:
        raise BadRequestError("Write the area as WKT (POLYGON ((lon lat, ...))) or GeoJSON.")
    into = _into(node, params, "inside")
    return extension(node, "geo.point_in_polygon", {"lat": lat, "lon": lon, "polygon": params["polygon"],
                                                    "into": into}, {**node.schema(), into: BOOLEAN})


@handles("geo.point_in_polygon")
def _in_polygon(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    from shapely import contains_xy, prepare

    area = shape(config["polygon"])
    prepare(area)
    numbers = frame[[config["lat"], config["lon"]]].apply(pd.to_numeric, errors="coerce")
    present = numbers.notna().all(axis=1)
    inside = pd.Series(pd.NA, index=frame.index, dtype="boolean")
    if present.any():
        inside[present] = contains_xy(area, numbers.loc[present, config["lon"]].to_numpy(),
                                      numbers.loc[present, config["lat"]].to_numpy())
    out = frame.copy()
    out[config["into"]] = inside
    return out


_SQUARE = "POLYGON ((-1 51, 1 51, 1 52, -1 52, -1 51))"
_declare("geo.point_in_polygon", "Inside an area", "True for places inside an area you give as WKT or GeoJSON (a "
         "delivery zone, a region), by longitude and latitude on the map.", _polygon_build,
         Example(rows=({"lat": 51.5, "lon": 0.1}, {"lat": 53, "lon": 0}),
                 params={"lat": "lat", "lon": "lon", "polygon": _SQUARE}, column="lat", output="inside",
                 expect=(True, False)),
         params=(LAT, LON, Param("polygon", "Area", ParamKind.TEXT, placeholder="POLYGON ((lon lat, ...))"),
                 Param("into", "New column", ParamKind.TEXT, required=False, default="")),
         synonyms=("point in polygon", "inside area", "geofence", "within region", "contains point"))


def _region_build(node: Node, params: dict[str, Any]) -> Node:
    lat, lon = (require_column(node, params.get(key)) for key in ("lat", "lon"))
    bring = list(params["bring"])
    return extension(node, "geo.region", {"lat": lat, "lon": lon, "right_dataset_id": params.get("right_dataset_id"),
                                          "right_shape": params.get("right_shape"), "bring": bring},
                     brought(node, bring))


@handles("geo.region")
def _region(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    from shapely import STRtree, points

    other = other_dataset(config).reset_index(drop=True)
    require_other_columns(other, [config["right_shape"], *config["bring"]], "Which region", config)
    shapes = [shape(v) for v in other[config["right_shape"]]]
    valid = [(index, s) for index, s in enumerate(shapes) if s is not None]
    numbers = frame[[config["lat"], config["lon"]]].apply(pd.to_numeric, errors="coerce").reset_index(drop=True)
    rows: list[int | None] = [None] * len(frame)
    present = numbers.notna().all(axis=1).to_numpy()
    if valid and present.any():
        tree = STRtree([s for _, s in valid])
        targets = points(numbers.loc[present, config["lon"]].to_numpy(), numbers.loc[present, config["lat"]].to_numpy())
        found, hit = tree.query(targets, predicate="within")
        first: dict[int, int] = {}
        for target, region in zip(found, hit):
            source = valid[int(region)][0]
            first[int(target)] = min(first.get(int(target), source), source)
        positions = np.flatnonzero(present)
        for target, source in first.items():
            rows[int(positions[target])] = source
    out = frame.reset_index(drop=True).copy()
    for name in config["bring"]:
        values = other[name].to_numpy(dtype=object)
        out[name if name not in frame.columns else f"{name}_right"] = [None if r is None else values[r] for r in rows]
    return out


_declare("geo.region", "Which region a place is in", "Bring columns from the shape (in another dataset of named "
         "areas, as WKT or GeoJSON) that contains each place: its country, sales territory, or time zone from a "
         "time zone boundary file such as timezone-boundary-builder's.", _region_build,
         Example(rows=({"lat": 51.5, "lon": 0.1}, {"lat": 60, "lon": 0}),
                 params={"lat": "lat", "lon": "lon", "right_dataset_id": EXAMPLE_DATASET, "right_shape": "shape",
                         "bring": ["name"]},
                 column="lat", output="name", expect=("South", None),
                 other=({"shape": _SQUARE, "name": "South"},)),
         params=(LAT, LON, Param("right_dataset_id", "Areas in", ParamKind.DATASET),
                 Param("right_shape", "Their shape", ParamKind.DATASET_COLUMN),
                 Param("bring", "Columns to bring", ParamKind.DATASET_COLUMNS)),
         synonyms=("region lookup", "timezone from coordinates", "spatial join", "which country", "territory",
                   "reverse geocode offline"), reads_dataset=True)


def _nearest_build(node: Node, params: dict[str, Any]) -> Node:
    lat, lon = (require_column(node, params.get(key)) for key in ("lat", "lon"))
    bring = list(params["bring"])
    distance = (params.get("distance_column") or "").strip() or "distance_km"
    return extension(node, "geo.nearest", {"lat": lat, "lon": lon, "right_dataset_id": params.get("right_dataset_id"),
                                           "right_lat": params.get("right_lat"), "right_lon": params.get("right_lon"),
                                           "bring": bring, "distance": distance},
                     brought(node, bring, extra={distance: FLOAT64}))


def _unit_vectors(lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    phi, lam = np.radians(lat), np.radians(lon)
    return np.column_stack([np.cos(phi) * np.cos(lam), np.cos(phi) * np.sin(lam), np.sin(phi)])


@handles("geo.nearest")
def _nearest(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    from scipy.spatial import cKDTree

    other = other_dataset(config).reset_index(drop=True)
    require_other_columns(other, [config["right_lat"], config["right_lon"], *config["bring"]], "Nearest place", config)
    theirs = other[[config["right_lat"], config["right_lon"]]].apply(pd.to_numeric, errors="coerce")
    usable = theirs.notna().all(axis=1).to_numpy()
    mine = frame[[config["lat"], config["lon"]]].apply(pd.to_numeric, errors="coerce").reset_index(drop=True)
    present = mine.notna().all(axis=1).to_numpy()
    out = frame.reset_index(drop=True).copy()
    rows: list[int | None] = [None] * len(frame)
    distances: list[float | None] = [None] * len(frame)
    if usable.any() and present.any():
        # Nearest by straight-line distance through the earth is nearest along it too.
        indices = np.flatnonzero(usable)
        tree = cKDTree(_unit_vectors(theirs.to_numpy()[usable, 0], theirs.to_numpy()[usable, 1]))
        chord, found = tree.query(_unit_vectors(mine.to_numpy()[present, 0], mine.to_numpy()[present, 1]))
        for position, (gap, hit) in zip(np.flatnonzero(present), zip(chord, found)):
            rows[position] = int(indices[hit])
            distances[position] = float(2 * EARTH_RADIUS * np.arcsin(min(1.0, gap / 2)) / 1000)
    for name in config["bring"]:
        values = other[name].to_numpy(dtype=object)
        out[name if name not in frame.columns else f"{name}_right"] = [None if r is None else values[r] for r in rows]
    out[config["distance"]] = pd.Series(distances, dtype="float64")
    return out


_STORES = ({"store": "Leeds", "slat": 53.8, "slon": -1.55}, {"store": "London", "slat": 51.5, "slon": -0.13})
_declare("geo.nearest", "Nearest place in another dataset", "Bring columns from the nearest place in another "
         "dataset (each customer's nearest store), with the distance to it in kilometres.", _nearest_build,
         Example(rows=({"lat": 51.6, "lon": -0.1}, {"lat": 53.5, "lon": -1.4}),
                 params={"lat": "lat", "lon": "lon", "right_dataset_id": EXAMPLE_DATASET, "right_lat": "slat",
                         "right_lon": "slon", "bring": ["store"]},
                 column="lat", output="store", expect=("London", "Leeds"), other=_STORES),
         params=(LAT, LON, Param("right_dataset_id", "Places in", ParamKind.DATASET),
                 Param("right_lat", "Their latitude", ParamKind.DATASET_COLUMN),
                 Param("right_lon", "Their longitude", ParamKind.DATASET_COLUMN),
                 Param("bring", "Columns to bring", ParamKind.DATASET_COLUMNS),
                 Param("distance_column", "Distance column", ParamKind.TEXT, required=False, default="distance_km")),
         synonyms=("nearest neighbour", "closest", "nearest store", "knn spatial"), reads_dataset=True)


def _shape_values(fn):
    def run(series: pd.Series, config: dict[str, Any]) -> list[Any]:
        return [None if (found := shape(v)) is None or found.is_empty else fn(found, config) for v in series]

    return run


def _bbox(found, config) -> str:
    left, bottom, right, top = found.bounds
    return json.dumps({"min_lon": left, "min_lat": bottom, "max_lon": right, "max_lat": top})


def _centroid(found, config) -> str:
    centre = found.centroid
    # + 0.0: a centre on the meridian is 0, not "-0".
    return f"POINT ({centre.x + 0.0:.7g} {centre.y + 0.0:.7g})"


def _spherical_area(found, config) -> float:
    """Square metres on the sphere (the Chamberlain-Duquette formula Turf and d3 use)."""
    def ring_area(coordinates) -> float:
        points = list(coordinates)
        if len(points) < 3:
            return 0.0
        total = 0.0
        for (lon1, lat1), (lon2, lat2) in zip(points, points[1:] + points[:1]):
            total += math.radians(lon2 - lon1) * (2 + math.sin(math.radians(lat1)) + math.sin(math.radians(lat2)))
        return abs(total * EARTH_RADIUS * EARTH_RADIUS / 2)

    polygons = getattr(found, "geoms", [found])
    area = 0.0
    for polygon in polygons:
        if polygon.geom_type != "Polygon":
            continue
        area += ring_area([(x, y) for x, y, *_ in polygon.exterior.coords][:-1])
        area -= sum(ring_area([(x, y) for x, y, *_ in ring.coords][:-1]) for ring in polygon.interiors)
    return area / {"square metres": 1.0, "hectares": 10_000.0, "square kilometres": 1e6}[
        config.get("unit") or "square metres"]


def _buffer(found, config) -> str:
    """A shape grown by a distance in metres, drawn on a local azimuthal equidistant projection."""
    import shapely

    metres = float(config.get("metres") or 0)
    centre = found.centroid
    lat0, lon0 = math.radians(centre.y), math.radians(centre.x)

    def forward(lon, lat, z=None):
        lam, phi = np.radians(lon), np.radians(lat)
        c = np.arccos(np.clip(np.sin(lat0) * np.sin(phi) + np.cos(lat0) * np.cos(phi) * np.cos(lam - lon0), -1, 1))
        k = np.where(c == 0, 1.0, c / np.where(np.sin(c) == 0, 1, np.sin(c)))
        x = EARTH_RADIUS * k * np.cos(phi) * np.sin(lam - lon0)
        y = EARTH_RADIUS * k * (np.cos(lat0) * np.sin(phi) - np.sin(lat0) * np.cos(phi) * np.cos(lam - lon0))
        return x, y

    def back(x, y, z=None):
        rho = np.hypot(x, y)
        c = rho / EARTH_RADIUS
        with np.errstate(invalid="ignore", divide="ignore"):
            phi = np.arcsin(np.clip(np.cos(c) * np.sin(lat0) + np.where(rho == 0, 0, y * np.sin(c) * np.cos(lat0) / np.where(
                rho == 0, 1, rho)), -1, 1))
            lam = lon0 + np.arctan2(x * np.sin(c), rho * np.cos(lat0) * np.cos(c) - y * np.sin(lat0) * np.sin(c))
        return np.degrees(lam), np.degrees(phi)

    def through(fn):
        return lambda coordinates: np.column_stack(fn(coordinates[:, 0], coordinates[:, 1]))

    flat = shapely.transform(found, through(forward))
    grown = shapely.transform(flat.buffer(metres, quad_segs=16), through(back))
    return grown.wkt


_GEOMETRY = Accepts.ANY
_declare("geo.bounding_box", "Bounding box of a shape", "The smallest box around a shape, as JSON with min_lon, "
         "min_lat, max_lon and max_lat.", column_extension("geo.bounding_box", STRING, _shape_values(_bbox)),
         Example(rows=({"s": _SQUARE},), column="s", output="s",
                 expect=('{"min_lon": -1.0, "min_lat": 51.0, "max_lon": 1.0, "max_lat": 52.0}',)),
         synonyms=("bounding box", "bbox", "extent", "envelope"), column_scoped=True, accepts=_GEOMETRY)
_declare("geo.centroid", "Centre of a shape", "The centre of a shape as a WKT point (its centre of mass on the map, "
         "which for shapes the size of a country is close to, not exactly, the centre on the globe).",
         column_extension("geo.centroid", GEOGRAPHY, _shape_values(_centroid)),
         Example(rows=({"s": _SQUARE},), column="s", output="s", expect=("POINT (0 51.5)",)),
         synonyms=("centroid", "centre", "center", "middle of shape"), column_scoped=True, accepts=_GEOMETRY)
_declare("geo.area", "Area of a shape", "The area of a polygon on the earth, on a sphere of the earth's mean "
         "radius (holes taken away), in square metres, hectares or square kilometres.",
         column_extension("geo.area", FLOAT64, _shape_values(_spherical_area), keys=("unit",)),
         Example(rows=({"s": "POLYGON ((0 0, 0.01 0, 0.01 0.01, 0 0.01, 0 0))"},), params={"unit": "hectares"},
                 column="s", output="s", expect=(123.643458,)),
         params=(Param("unit", "In", ParamKind.SELECT, required=False, default="square metres",
                       options=("square metres", "hectares", "square kilometres")),),
         synonyms=("area", "surface area", "size of polygon", "hectares"), column_scoped=True, accepts=_GEOMETRY)
_declare("geo.buffer", "Grow a shape by a distance", "A shape grown outwards by a distance in metres (a circle "
         "around a point), measured on a map centred on the shape so the distance holds in every direction.",
         column_extension("geo.buffer", GEOGRAPHY, _shape_values(_buffer), keys=("metres",)),
         Example(rows=({"s": "POINT (0 51.5)"},), params={"metres": 100}, column="s", output="s",
                 note="A 64-sided polygon whose edge is 100 m from the point."),
         params=(Param("metres", "Metres", ParamKind.NUMBER, default=100, minimum=0),),
         synonyms=("buffer", "radius polygon", "catchment", "expand shape"), column_scoped=True, accepts=_GEOMETRY)


def _geojson(found, config) -> str:
    from shapely.geometry import mapping

    return json.dumps(mapping(found))


_declare("geo.to_geojson", "Write a shape as GeoJSON", "Write a WKT shape as GeoJSON, for a map or an API.",
         column_extension("geo.to_geojson", STRING, _shape_values(_geojson)),
         Example(rows=({"s": "POINT (1 2)"},), column="s", output="s",
                 expect=('{"type": "Point", "coordinates": [1.0, 2.0]}',)),
         synonyms=("to geojson", "geojson", "wkt to json"), column_scoped=True, accepts=_GEOMETRY)

# ----------------------------------------------------------------- geohash

_BASE32 = "0123456789bcdefghjkmnpqrstuvwxyz"


def geohash(lat: float, lon: float, precision: int) -> str:
    lat_range, lon_range = [-90.0, 90.0], [-180.0, 180.0]
    bits, value, even, out = 0, 0, True, []
    while len(out) < precision:
        span = lon_range if even else lat_range
        middle = (span[0] + span[1]) / 2
        target = lon if even else lat
        if target >= middle:
            value = (value << 1) | 1
            span[0] = middle
        else:
            value <<= 1
            span[1] = middle
        even = not even
        bits += 1
        if bits == 5:
            out.append(_BASE32[value])
            bits, value = 0, 0
    return "".join(out)


def ungeohash(code: str) -> tuple[float, float] | None:
    lat_range, lon_range = [-90.0, 90.0], [-180.0, 180.0]
    even = True
    for character in code.lower().strip():
        if character not in _BASE32:
            return None
        value = _BASE32.index(character)
        for shift in range(4, -1, -1):
            span = lon_range if even else lat_range
            middle = (span[0] + span[1]) / 2
            if (value >> shift) & 1:
                span[0] = middle
            else:
                span[1] = middle
            even = not even
    return (lat_range[0] + lat_range[1]) / 2, (lon_range[0] + lon_range[1]) / 2


def _encode_build(node: Node, params: dict[str, Any]) -> Node:
    lat, lon = (require_column(node, params.get(key)) for key in ("lat", "lon"))
    into = _into(node, params, "geohash")
    return extension(node, "geo.geohash_encode", {"lat": lat, "lon": lon, "into": into,
                                                  "precision": params.get("precision")},
                     {**node.schema(), into: STRING})


@handles("geo.geohash_encode")
def _encode(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    numbers = frame[[config["lat"], config["lon"]]].apply(pd.to_numeric, errors="coerce")
    precision = int(config.get("precision") or 7)
    out = frame.copy()
    out[config["into"]] = [None if pd.isna(a) or pd.isna(b) or not (-90 <= a <= 90 and -180 <= b <= 180)
                           else geohash(a, b, precision) for a, b in numbers.itertuples(index=False, name=None)]
    return out


_declare("geo.geohash_encode", "Geohash of a place", "The geohash of a latitude and longitude: a short code for a "
         "cell on the map, longer for a smaller cell (7 characters is about 150 m), shared by places near each "
         "other.", _encode_build,
         Example(rows=({"lat": 57.64911, "lon": 10.40744},), params={"lat": "lat", "lon": "lon", "precision": 11},
                 column="lat", output="geohash", expect=("u4pruydqqvj",)),
         params=(LAT, LON, Param("precision", "Characters", ParamKind.INTEGER, default=7, minimum=1, maximum=12),
                 Param("into", "New column", ParamKind.TEXT, required=False, default="")),
         synonyms=("geohash encode", "geohash", "grid cell", "spatial index"))


def _decode_build(node: Node, params: dict[str, Any]) -> Node:
    column = require_column(node, params.get("column"))
    lat, lon = f"{column}_latitude", f"{column}_longitude"
    for name in (lat, lon):
        if name in node.schema():
            raise BadRequestError(f"Column {name!r} already exists; rename it first.")
    return extension(node, "geo.geohash_decode", {"column": column, "lat": lat, "lon": lon},
                     {**node.schema(), lat: FLOAT64, lon: FLOAT64})


@handles("geo.geohash_decode")
def _decode(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    found = [None if pd.isna(v) else ungeohash(str(v)) for v in frame[config["column"]]]
    out = frame.copy()
    out[config["lat"]] = pd.Series([None if f is None else f[0] for f in found], dtype="float64")
    out[config["lon"]] = pd.Series([None if f is None else f[1] for f in found], dtype="float64")
    return out


_declare("geo.geohash_decode", "Place of a geohash", "The latitude and longitude of the centre of a geohash's cell.",
         _decode_build,
         Example(rows=({"g": "u4pruydqqvj"},), column="g", output="g_latitude", expect=(57.649111,)),
         synonyms=("geohash decode", "from geohash", "decode geohash"), column_scoped=True, accepts=Accepts.TEXTUAL)

