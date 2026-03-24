from copy import deepcopy
from typing import Any, Dict, List, Tuple

from lib.aliases import ALIASES

ALLOWED_PROPERTIES = {
    "polyName",
    "plantStart",
    "practice",
    "targetSys",
    "distr",
    "numTrees",
    "siteId",
}

PRACTICE_VALUES = {
    "tree-planting",
    "direct-seeding",
    "assisted-natural-regeneration",
}

TARGET_SYS_VALUES = {
    "agroforest",
    "natural-forest",
    "mangrove",
    "grassland",
    "peatland",
    "riparian-area-or-wetland",
    "silvopasture",
    "woodlot-or-plantation",
    "urban-forest",
}

DISTR_VALUES = {
    "single-line",
    "partial",
    "full",
}


def sanitize_geojson(data: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    report = {
        "input_feature_count": 0,
        "output_feature_count": 0,
        "dropped_features": 0,
        "fixes": [],
    }

    if not isinstance(data, dict):
        raise ValueError("GeoJSON root must be an object")

    if data.get("type") != "FeatureCollection":
        report["fixes"].append("Root type was invalid; forced to FeatureCollection.")

    raw_features = data.get("features", [])
    if not isinstance(raw_features, list):
        raw_features = []
        report["fixes"].append("features was not an array; replaced with empty array.")

    report["input_feature_count"] = len(raw_features)

    cleaned_features = []
    for idx, feature in enumerate(raw_features):
        cleaned_feature, feature_fixes = sanitize_feature(feature, idx)
        report["fixes"].extend(feature_fixes)
        if cleaned_feature is None:
            report["dropped_features"] += 1
        else:
            cleaned_features.append(cleaned_feature)

    report["output_feature_count"] = len(cleaned_features)

    return {
        "type": "FeatureCollection",
        "features": cleaned_features,
    }, report


def sanitize_feature(feature: Dict[str, Any], idx: int):
    fixes = []

    if not isinstance(feature, dict):
        fixes.append(f"Feature {idx}: dropped because it is not an object.")
        return None, fixes

    geometry, geometry_fixes = sanitize_geometry(feature.get("geometry"), idx)
    fixes.extend(geometry_fixes)
    if geometry is None:
        fixes.append(f"Feature {idx}: dropped because geometry is invalid.")
        return None, fixes

    properties, property_fixes = sanitize_properties(feature.get("properties", {}), idx)
    fixes.extend(property_fixes)

    return {
        "type": "Feature",
        "geometry": geometry,
        "properties": properties,
    }, fixes


def sanitize_geometry(geometry: Dict[str, Any], idx: int):
    fixes = []

    if not isinstance(geometry, dict):
        fixes.append(f"Feature {idx}: geometry missing or invalid.")
        return None, fixes

    gtype = geometry.get("type")
    coords = geometry.get("coordinates")

    if gtype == "Polygon":
        cleaned = sanitize_polygon(coords, idx, fixes)
        if cleaned is None:
            return None, fixes
        return {"type": "Polygon", "coordinates": cleaned}, fixes

    if gtype == "MultiPolygon":
        cleaned = sanitize_multipolygon(coords, idx, fixes)
        if cleaned is None:
            return None, fixes
        return {"type": "MultiPolygon", "coordinates": cleaned}, fixes

    fixes.append(f"Feature {idx}: unsupported geometry type {gtype}; dropped.")
    return None, fixes


def sanitize_polygon(coords: Any, idx: int, fixes: List[str]):
    if not isinstance(coords, list) or not coords:
        fixes.append(f"Feature {idx}: polygon coordinates invalid.")
        return None

    cleaned_rings = []
    for ring_i, ring in enumerate(coords):
        cleaned_ring = sanitize_ring(ring, idx, ring_i, fixes)
        if cleaned_ring is None:
            continue
        cleaned_rings.append(cleaned_ring)

    if not cleaned_rings:
        fixes.append(f"Feature {idx}: no valid polygon rings remained.")
        return None

    return cleaned_rings


def sanitize_multipolygon(coords: Any, idx: int, fixes: List[str]):
    if not isinstance(coords, list) or not coords:
        fixes.append(f"Feature {idx}: multipolygon coordinates invalid.")
        return None

    cleaned_polygons = []
    for poly_i, polygon in enumerate(coords):
        if not isinstance(polygon, list):
            fixes.append(f"Feature {idx}: polygon {poly_i} in multipolygon is invalid.")
            continue

        cleaned_rings = []
        for ring_i, ring in enumerate(polygon):
            cleaned_ring = sanitize_ring(ring, idx, ring_i, fixes)
            if cleaned_ring is None:
                continue
            cleaned_rings.append(cleaned_ring)

        if cleaned_rings:
            cleaned_polygons.append(cleaned_rings)

    if not cleaned_polygons:
        fixes.append(f"Feature {idx}: no valid polygons remained in multipolygon.")
        return None

    return cleaned_polygons


def sanitize_ring(ring: Any, idx: int, ring_i: int, fixes: List[str]):
    if not isinstance(ring, list):
        fixes.append(f"Feature {idx}: ring {ring_i} is invalid.")
        return None

    cleaned = []
    stripped_any_z = False

    for point in ring:
        if not isinstance(point, list) or len(point) < 2:
            continue

        x = point[0]
        y = point[1]

        if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
            continue

        if len(point) > 2:
            stripped_any_z = True

        cleaned.append([x, y])

    if stripped_any_z:
        fixes.append(f"Feature {idx}: stripped Z values from ring {ring_i}.")

    if len(cleaned) < 3:
        fixes.append(f"Feature {idx}: ring {ring_i} has fewer than 3 valid points.")
        return None

    if cleaned[0] != cleaned[-1]:
        cleaned.append(deepcopy(cleaned[0]))
        fixes.append(f"Feature {idx}: auto-closed ring {ring_i}.")

    if len(cleaned) < 4:
        fixes.append(f"Feature {idx}: ring {ring_i} invalid after closing.")
        return None

    return cleaned


def sanitize_properties(properties: Any, idx: int):
    fixes = []

    if not isinstance(properties, dict):
        fixes.append(f"Feature {idx}: properties invalid; replaced with empty object.")
        properties = {}

    normalized = {}
    for key, value in properties.items():
        canonical = canonical_property_name(key)
        if canonical is None:
            fixes.append(f"Feature {idx}: removed unsupported property '{key}'.")
            continue
        if canonical != key:
            fixes.append(f"Feature {idx}: mapped property '{key}' to '{canonical}'.")
        normalized[canonical] = value

    result = {key: None for key in ALLOWED_PROPERTIES}

    if "polyName" in normalized:
        result["polyName"] = normalized["polyName"] if isinstance(normalized["polyName"], str) else None
        if normalized["polyName"] is not None and result["polyName"] is None:
            fixes.append(f"Feature {idx}: set invalid polyName to null.")

    if "plantStart" in normalized:
        value = normalized["plantStart"]
        result["plantStart"] = value if is_valid_date_string(value) else None
        if value is not None and result["plantStart"] is None:
            fixes.append(f"Feature {idx}: set invalid plantStart to null.")

    if "practice" in normalized:
        cleaned = normalize_enum_field(normalized["practice"], PRACTICE_VALUES)
        result["practice"] = cleaned
        if cleaned is None and normalized["practice"] is not None:
            fixes.append(f"Feature {idx}: set invalid practice to null.")

    if "targetSys" in normalized:
        value = normalized["targetSys"]
        result["targetSys"] = value if isinstance(value, str) and value in TARGET_SYS_VALUES else None
        if value is not None and result["targetSys"] is None:
            fixes.append(f"Feature {idx}: set invalid targetSys to null.")

    if "distr" in normalized:
        cleaned = normalize_enum_field(normalized["distr"], DISTR_VALUES)
        result["distr"] = cleaned
        if cleaned is None and normalized["distr"] is not None:
            fixes.append(f"Feature {idx}: set invalid distr to null.")

    if "numTrees" in normalized:
        result["numTrees"] = normalize_number_or_null(normalized["numTrees"])
        if normalized["numTrees"] not in (None, "", result["numTrees"]):
            fixes.append(f"Feature {idx}: normalized invalid numTrees to null.")

    if "siteId" in normalized:
        value = normalized["siteId"]
        if value is None or value == "":
            result["siteId"] = None
        else:
            result["siteId"] = str(value)

    return result, fixes


def canonical_property_name(key: Any):
    if not isinstance(key, str):
        return None

    if key in ALLOWED_PROPERTIES:
        return key

    squeezed = key.replace("-", "").replace("_", "").replace(" ", "")
    return ALIASES.get(key) or ALIASES.get(squeezed.lower())


def normalize_enum_field(value: Any, allowed: set):
    if value is None or value == "":
        return None

    if isinstance(value, str):
        return value if value in allowed else None

    if isinstance(value, list):
        valid = [item for item in value if isinstance(item, str) and item in allowed]
        if not valid:
            return None
        if len(valid) == 1:
            return valid[0]
        return valid

    return None


def normalize_number_or_null(value: Any):
    if value is None or value == "":
        return None

    if isinstance(value, (int, float)):
        return value

    if isinstance(value, str):
        try:
            if "." in value:
                return float(value)
            return int(value)
        except ValueError:
            return None

    return None


def is_valid_date_string(value: Any):
    if not isinstance(value, str):
        return False

    parts = value.split("-")
    if len(parts) != 3:
        return False

    y, m, d = parts
    if len(y) != 4 or len(m) != 2 or len(d) != 2:
        return False

    return y.isdigit() and m.isdigit() and d.isdigit()
