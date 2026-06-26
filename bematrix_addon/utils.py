"""
Shared helpers for the BeMatrix Graphic Panels add-on.

This module holds constants, unit conversion, frame-name parsing, frame size /
depth detection, generated-object naming, and the source-frame selection logic.
It must not import any other module of this package, so it stays at the bottom of
the dependency graph and can never cause a circular import.
"""

import re

import bpy
from mathutils import Vector


# Human-readable add-on version. Bump this on every meaningful change so the
# version shown in the sidebar and printed to the console proves Blender loaded
# the latest file (Blender caches enabled add-ons aggressively).
ADDON_VERSION = "0.9.1-curved-0248-svg"


# Common BeMatrix frame dimensions from your chart.
# The add-on does not require these, but uses them as a validation/detection aid.
BEMATRIX_FRAME_SIZES_MM = [
    434,
    496,
    744,
    992,
    1426,
    1488,
    1984,
    2418,
    2480,
    2976,
]

BEMATRIX_DIMENSION_TABLE_MM = {
    434: {"frame": 434, "infill": 428, "inside": 303},
    496: {"frame": 496, "infill": 490, "inside": 365},
    744: {"frame": 744, "infill": 738, "inside": 613},
    992: {"frame": 992, "infill": 986, "inside": 861},
    1426: {"frame": 1426, "infill": 1420, "inside": 1295},
    1488: {"frame": 1488, "infill": 1482, "inside": 1357},
    1984: {"frame": 1984, "infill": 1978, "inside": 1853},
    2418: {"frame": 2418, "infill": 2412, "inside": 2287},
    2480: {"frame": 2480, "infill": 2474, "inside": 2349},
    2976: {"frame": 2976, "infill": 2970, "inside": 2845},
}


# Each generated panel gets its own material named MATERIAL_PREFIX + panel name
# (spaces -> underscores), e.g. MAT_BM_PANEL_FRONT_B62_0992_0992_A001.
MATERIAL_PREFIX = "MAT_"
GENERATED_PANEL_PREFIX = "BM_PANEL_"
GENERATED_SEG_PREFIX = "BM_SEG_"
GENERATED_ARRAY_PREFIX = "BM_SYNC_ARRAY_"


def mm_to_m(value_mm: float) -> float:
    return value_mm / 1000.0


def get_frame_dimension_mm(code):
    """Return an official BeMatrix frame dimension F in mm, or None."""
    try:
        value = int(round(float(code)))
    except (TypeError, ValueError):
        return None
    if value in BEMATRIX_DIMENSION_TABLE_MM:
        return BEMATRIX_DIMENSION_TABLE_MM[value]["frame"]
    return None


def get_infill_panel_dimension_mm(frame_dimension_mm, fallback_trim_mm=6.0):
    """
    Return official BeMatrix hard infill panel dimension P for frame F.

    If the frame dimension is not in the official table, fall back to the legacy
    trim behavior so custom/unknown frames continue to work.
    """
    frame = get_frame_dimension_mm(frame_dimension_mm)
    if frame is not None:
        return BEMATRIX_DIMENSION_TABLE_MM[frame]["infill"]
    try:
        return float(frame_dimension_mm) - float(fallback_trim_mm)
    except (TypeError, ValueError):
        return None


def get_inside_frame_dimension_mm(frame_dimension_mm):
    """Return official BeMatrix inside frame dimension I in mm, or None."""
    frame = get_frame_dimension_mm(frame_dimension_mm)
    if frame is not None:
        return BEMATRIX_DIMENSION_TABLE_MM[frame]["inside"]
    return None


def get_hard_panel_size_mm(frame_width_mm, frame_height_mm, fallback_trim_mm=6.0):
    """
    Hard-panel size from the official F -> P lookup table.

    This preserves the old configurable-trim fallback for dimensions that are
    not present in the BeMatrix table.
    """
    return (
        get_infill_panel_dimension_mm(frame_width_mm, fallback_trim_mm),
        get_infill_panel_dimension_mm(frame_height_mm, fallback_trim_mm),
    )


def format_dimension_validation(label, expected_w_mm, expected_h_mm,
                                actual_w_mm, actual_h_mm, tolerance_mm=0.25):
    """Readable OK/WARNING line for console validation output."""
    dw = abs(float(actual_w_mm) - float(expected_w_mm))
    dh = abs(float(actual_h_mm) - float(expected_h_mm))
    status = "OK" if dw <= tolerance_mm and dh <= tolerance_mm else "WARNING"
    return (
        f"{label}: {status} - expected "
        f"{expected_w_mm:g} x {expected_h_mm:g} mm, actual "
        f"{actual_w_mm:.3f} x {actual_h_mm:.3f} mm"
    )


def strip_blender_duplicate_suffix(name: str) -> str:
    """
    Converts names like:
    B62 0496 2418.001 -> B62 0496 2418
    """
    return re.sub(r"\.\d{3}$", "", name)


def parse_frame_size_from_name(obj_name: str):
    """
    Looks for BeMatrix-style dimensions in object names.

    Example:
    B62 0496 2418
    B62 0992 2418.001

    Returns:
    (width_mm, height_mm) or None
    """
    base_name = strip_blender_duplicate_suffix(obj_name)

    numbers = re.findall(r"(?<!\d)(\d{3,4})(?!\d)", base_name)
    valid_numbers = []

    for number in numbers:
        value = int(number)
        if value in BEMATRIX_FRAME_SIZES_MM:
            valid_numbers.append(value)

    if len(valid_numbers) >= 2:
        return valid_numbers[0], valid_numbers[1]

    return None


def parse_frame_depth_mm(obj_name: str):
    """
    Parses the BeMatrix frame DEPTH (profile size) from the leading code.

    BeMatrix frame names start with the system code, where the number is the
    profile depth in millimeters:

        B62 0992 0992  ->  depth 62 mm
        B100 0992 2418 ->  depth 100 mm

    Returns depth_mm (float) or None if not found. This is used for the local-Y
    array step so it never depends on the evaluated bounding box (which can
    include the Array result).
    """
    base_name = strip_blender_duplicate_suffix(obj_name).strip()

    match = re.match(r"B(\d{2,3})\b", base_name)
    if match:
        return float(match.group(1))

    return None


def closest_bematrix_size(value_mm: float, tolerance_mm: float = 20.0):
    closest = min(BEMATRIX_FRAME_SIZES_MM, key=lambda size: abs(size - value_mm))
    if abs(closest - value_mm) <= tolerance_mm:
        return closest
    return None


def get_local_bbox_size_mm(obj):
    """
    Fallback method when the object name does not include dimensions.
    Uses local bounding box size and object scale.

    Expected object axes:
    X = width
    Y = depth
    Z = height
    """
    bbox = [Vector(corner) for corner in obj.bound_box]

    min_x = min(v.x for v in bbox)
    max_x = max(v.x for v in bbox)
    min_z = min(v.z for v in bbox)
    max_z = max(v.z for v in bbox)

    width_m = (max_x - min_x) * abs(obj.scale.x)
    height_m = (max_z - min_z) * abs(obj.scale.z)

    width_mm = width_m * 1000.0
    height_mm = height_m * 1000.0

    width_match = closest_bematrix_size(width_mm)
    height_match = closest_bematrix_size(height_mm)

    if width_match and height_match:
        return width_match, height_match

    return None


def get_frame_size_mm(obj):
    """
    First tries object name.
    Then falls back to local bounding box dimensions.
    """
    from_name = parse_frame_size_from_name(obj.name)
    if from_name:
        return from_name

    curved_size = parse_curved_frame_size_from_name(obj.name)
    if curved_size:
        return curved_size

    return get_local_bbox_size_mm(obj)


def parse_curved_frame_size_from_name(obj_name: str):
    """
    Lightweight curved-frame source detection.

    The detailed curved radius/angle table lives in curved_frames.py. This
    helper only lets names like "B62 90 R992 2418" pass source-frame filtering
    by returning a nominal (radius, height) pair.
    """
    base_name = strip_blender_duplicate_suffix(obj_name)
    asset_match = re.search(
        r"\bB\d{2,3}_(?P<family>\d{4})_CURVE_"
        r"\d+(?:[pP]\d+)?_H(?P<height>\d{3,4})\b",
        base_name,
        re.IGNORECASE,
    )
    if asset_match:
        return int(asset_match.group("family")), int(asset_match.group("height"))

    radius_match = re.search(r"\bR\s*(\d+)(?:\.\d+)?\b", base_name, re.IGNORECASE)
    if not radius_match:
        return None

    radius_mm = int(radius_match.group(1))
    without_radius = re.sub(r"\bR\s*\d+(?:\.\d+)?\b", " ", base_name, flags=re.IGNORECASE)
    numbers = re.findall(r"(?<!\d)(\d+(?:\.\d+)?)(?!\d)", without_radius)
    height_candidates = []
    for number in numbers:
        value = int(round(float(number)))
        if value in BEMATRIX_FRAME_SIZES_MM:
            height_candidates.append(value)

    if not height_candidates:
        return None

    return radius_mm, height_candidates[-1]


def is_marked_panel(obj):
    """
    True only for the generated-panel custom-property marker.

    IMPORTANT: Blender stores a boolean custom property as an integer
    IDProperty, so `obj["is_bematrix_panel"] = True` reads back as `1`, and the
    identity test `obj.get(...) is True` is always False. Use a truthy check so
    duplicate detection and stale-panel deletion actually match our panels.
    """
    return bool(obj.get("is_bematrix_panel"))


def is_generated_panel_object(obj):
    """
    Generated panel objects are never valid source frames.

    Custom properties are the primary detection method. The name prefix is a
    safety fallback for older or partially generated panel objects.
    """
    if obj is None:
        return False

    return (
        is_marked_panel(obj)
        or obj.name.startswith(GENERATED_PANEL_PREFIX)
        or obj.name.startswith(GENERATED_SEG_PREFIX)
    )


def is_valid_frame_object(obj):
    if obj is None:
        return False

    if obj.type != "MESH":
        return False

    if is_generated_panel_object(obj):
        return False

    return get_frame_size_mm(obj) is not None


def generated_panel_name(frame_obj, side_label):
    clean_frame_name = strip_blender_duplicate_suffix(frame_obj.name)
    return f"{GENERATED_PANEL_PREFIX}{side_label}_{clean_frame_name}"


def generated_array_panel_name(frame_obj, side_label, index_1, index_2=None):
    """
    One array  -> ..._A001, ..._A002
    Two arrays -> ..._A001_B001, ..._A001_B002, ..._A002_B001
    """
    base = generated_panel_name(frame_obj, side_label)
    if index_2 is None:
        return f"{base}_A{index_1:03d}"
    return f"{base}_A{index_1:03d}_B{index_2:03d}"


def generated_seg_name(frame_obj, side_label, row_index):
    """
    SEG fabric plane name, one continuous plane per Z row:
    BM_SEG_FRONT_B62 0992 2418_ROW001
    """
    clean_frame_name = strip_blender_duplicate_suffix(frame_obj.name)
    return (
        f"{GENERATED_SEG_PREFIX}{side_label}_{clean_frame_name}_ROW{row_index:03d}"
    )


def get_mesh_local_depth_m(obj):
    """
    Local Y (depth) of the frame in meters, measured from the RAW MESH DATA
    (obj.data.vertices), NOT obj.bound_box / obj.dimensions.

    This matters because obj.bound_box and obj.dimensions are evaluated and can
    include the Array modifier's duplicated copies, which would inflate the
    depth. The raw mesh vertices are the single, un-arrayed frame.

    Returns depth_m or None.
    """
    if obj.type != "MESH" or obj.data is None or len(obj.data.vertices) == 0:
        return None

    ys = [v.co.y for v in obj.data.vertices]
    return (max(ys) - min(ys)) * abs(obj.scale.y)


def get_frame_depth_mm(frame_obj):
    """
    Returns (depth_mm, source_label). Prefers the leading B-number from the name
    (e.g. B62 -> 62 mm). Falls back to the raw-mesh local depth so it never uses
    the evaluated/array-inflated bounding box.
    """
    parsed = parse_frame_depth_mm(frame_obj.name)
    if parsed is not None:
        return parsed, "name B-number"

    mesh_depth_m = get_mesh_local_depth_m(frame_obj)
    if mesh_depth_m is not None:
        return mesh_depth_m * 1000.0, "raw mesh depth (pre-modifier)"

    return 0.0, "unknown"


def get_frame_spacing_dims_m(frame_obj):
    """
    Per-axis source-frame dimensions (meters) used for ARRAY SPACING only.

    These are the real frame dimensions, NOT the trimmed panel size and NOT the
    evaluated bounding box:

        X = parsed frame width  (from the name, e.g. 0992 -> 0.992 m)
        Z = parsed frame height (from the name, e.g. 0992 -> 0.992 m)
        Y = parsed frame depth  (B-number, e.g. B62 -> 0.062 m), else raw mesh

    Using the name for X/Z avoids the ~6 mm error seen when the modeled frame
    mesh is slightly larger than its nominal size (e.g. a 992 mm frame whose
    mesh bounding box is ~998 mm). Trim is never involved here.
    """
    size = get_frame_size_mm(frame_obj)
    if size:
        width_mm, height_mm = size
    else:
        # Name parse failed; fall back to the raw mesh X/Z extents.
        width_mm, height_mm = 0.0, 0.0
        if frame_obj.type == "MESH" and frame_obj.data and len(frame_obj.data.vertices):
            xs = [v.co.x for v in frame_obj.data.vertices]
            zs = [v.co.z for v in frame_obj.data.vertices]
            width_mm = (max(xs) - min(xs)) * abs(frame_obj.scale.x) * 1000.0
            height_mm = (max(zs) - min(zs)) * abs(frame_obj.scale.z) * 1000.0

    depth_mm, _source = get_frame_depth_mm(frame_obj)

    return Vector((mm_to_m(width_mm), mm_to_m(depth_mm), mm_to_m(height_mm)))


def get_target_frames(context):
    scene = context.scene
    props = scene.bematrix_panel_props

    frames = []

    if props.source_mode == "SELECTED":
        frames = [obj for obj in context.selected_objects if is_valid_frame_object(obj)]

    elif props.source_mode == "ACTIVE_COLLECTION":
        active = context.object
        if active and active.users_collection:
            collection = active.users_collection[0]
            frames = [obj for obj in collection.objects if is_valid_frame_object(obj)]

    elif props.source_mode == "CHOSEN_COLLECTION":
        collection = props.target_collection
        if collection:
            frames = [obj for obj in collection.objects if is_valid_frame_object(obj)]

    # Remove duplicates while preserving order.
    unique = []
    seen = set()

    for obj in frames:
        if obj.name not in seen:
            unique.append(obj)
            seen.add(obj.name)

    return unique
