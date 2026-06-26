"""
Curved BeMatrix panel helpers.

This module is intentionally limited to Blender mesh generation. SVG/export
support for curved panels is a later phase; the current SVG validator should
reject these non-flat generated meshes rather than trying to flatten them.
"""

import math
import re

import bpy
from mathutils import Vector

from .array_helpers import get_panel_array_positions, remove_generated_array_modifiers
from .materials import get_or_create_unique_panel_material
from .utils import (
    BEMATRIX_FRAME_SIZES_MM,
    GENERATED_PANEL_PREFIX,
    GENERATED_SEG_PREFIX,
    is_marked_panel,
    mm_to_m,
    strip_blender_duplicate_suffix,
)


CURVED_FRAME_TABLE = {
    (90.0, 182): {
        "outside_panel_width_mm": 408.5,
        "inside_panel_width_mm": 317.5,
        "height_trim_mm": 9.0,
    },
    (90.0, 430): {
        "outside_panel_width_mm": 798.0,
        "inside_panel_width_mm": 707.0,
        "height_trim_mm": 7.0,
    },
    (45.0, 992): {
        "outside_panel_width_mm": 771.0,
        "inside_panel_width_mm": 725.0,
        "height_trim_mm": 7.0,
    },
    (90.0, 992): {
        "outside_panel_width_mm": 1549.0,
        "inside_panel_width_mm": 1458.0,
        "height_trim_mm": 7.0,
    },
    (45.0, 1488): {
        "outside_panel_width_mm": 1161.0,
        "inside_panel_width_mm": 1116.0,
        "height_trim_mm": 7.0,
    },
    (30.0, 1984): {
        "outside_panel_width_mm": 1031.5,
        "inside_panel_width_mm": 1001.0,
        "height_trim_mm": 7.0,
    },
    (22.5, 2976): {
        "outside_panel_width_mm": 1162.0,
        "inside_panel_width_mm": 1139.0,
        "height_trim_mm": 7.0,
    },
    (11.25, 5952): {
        "outside_panel_width_mm": 1161.0,
        "inside_panel_width_mm": 1150.0,
        "height_trim_mm": 7.0,
    },
}

CURVED_ASSET_FAMILY_MAP = {
    248: 182,   # B62_0248_CURVE_90_* uses the small 90-degree curved reference.
    496: 430,   # B62_0496_CURVE_90_* maps to the R430 / 0496 curved reference.
    5952: 5952,
    2976: 2976,
}

CURVED_FACE_LABELS = {
    "OUTSIDE": "Outside Curve",
    "INSIDE": "Inside Curve",
}


def curved_face_for_panel_side(side_label):
    """
    Curved frames only support two useful generated faces.

    Reuse the existing Panel Side control so the UI does not expose four
    front/back + inside/outside combinations:
    FRONT (-Y) is the outside curve, BACK (+Y) is the inside curve.
    """
    if side_label == "FRONT":
        return "OUTSIDE"
    if side_label == "BACK":
        return "INSIDE"
    return None


def curved_face_label(curved_face):
    return CURVED_FACE_LABELS.get(curved_face, str(curved_face))


def _format_angle(angle):
    if abs(angle - round(angle)) < 1e-6:
        return str(int(round(angle)))
    return str(angle).replace(".", "p")


def _curved_generated_name(frame_obj, side_label, panel_kind, index_1=None, index_2=None):
    clean_frame_name = strip_blender_duplicate_suffix(frame_obj.name)
    prefix = GENERATED_SEG_PREFIX if panel_kind.startswith("SEG") else GENERATED_PANEL_PREFIX
    base = f"{prefix}{side_label}_{clean_frame_name}"
    if index_1 is None:
        return base
    if index_2 is None:
        return f"{base}_A{index_1:03d}"
    return f"{base}_A{index_1:03d}_B{index_2:03d}"


def _numbers_after_removing_radius(obj_name):
    base_name = strip_blender_duplicate_suffix(obj_name)
    without_radius = re.sub(r"\bR\s*\d+(?:\.\d+)?\b", " ", base_name, flags=re.IGNORECASE)
    return re.findall(r"(?<!\d)(\d+(?:\.\d+)?)(?!\d)", without_radius)


def _parse_angle_token(token):
    try:
        return float(str(token).replace("p", ".").replace("P", "."))
    except (TypeError, ValueError):
        return None


def _parse_curved_asset_name(base_name):
    """
    Parse the updated Blender asset pattern:

        B62_0248_CURVE_90_H0992
        B62_5952_CURVE_11p25_H0992

    Returns a curve spec dict or None.
    """
    # The height group ends the recognised token. Allow an optional trailing
    # suffix such as "_Frame" (e.g. B62_0248_CURVE_90_H0992_Frame) by ending on a
    # "not another digit/p" lookahead instead of a strict word boundary, which
    # would fail before an underscore.
    match = re.search(
        r"\bB(?P<depth>\d{2,3})_(?P<family>\d{4})_CURVE_"
        r"(?P<angle>\d+(?:[pP]\d+)?)_H(?P<height>\d{3,4})(?![0-9pP])",
        base_name,
        re.IGNORECASE,
    )
    if not match:
        return None

    family_mm = int(match.group("family"))
    radius_mm = CURVED_ASSET_FAMILY_MAP.get(family_mm)
    if radius_mm is None:
        return None

    angle = _parse_angle_token(match.group("angle"))
    if angle is None:
        return None

    height_mm = int(match.group("height"))
    key = (angle, radius_mm)
    table = CURVED_FRAME_TABLE.get(key)
    if table is None:
        return None

    return {
        "angle_degrees": angle,
        "radius_mm": radius_mm,
        "family_mm": family_mm,
        "frame_height_mm": height_mm,
        "outside_panel_width_mm": table["outside_panel_width_mm"],
        "inside_panel_width_mm": table["inside_panel_width_mm"],
        "height_trim_mm": table["height_trim_mm"],
        "detection_path": "updated B62 asset-name detection",
    }


def parse_curved_frame_from_name(obj_name, frame_height_mm=None):
    """
    Detect known curved frame references from object names.

    Expected names can be loose, e.g. "B62 90 R992 2418",
    "B62 R992 90 2418", or "R992 45 1984". The table remains the source of
    truth for supported radius/angle combinations.
    """
    base_name = strip_blender_duplicate_suffix(obj_name)
    asset_spec = _parse_curved_asset_name(base_name)
    if asset_spec is not None:
        return asset_spec

    radius_match = re.search(r"\bR\s*(\d+)(?:\.\d+)?\b", base_name, re.IGNORECASE)
    if not radius_match:
        return None

    radius_mm = int(radius_match.group(1))
    possible_angles = sorted(
        angle for angle, radius in CURVED_FRAME_TABLE
        if radius == radius_mm
    )
    if not possible_angles:
        return None

    angle = None
    tokens = _numbers_after_removing_radius(base_name)
    for token in tokens:
        value = float(token)
        for possible in possible_angles:
            if abs(value - possible) < 1e-6:
                angle = possible
                break
        if angle is not None:
            break

    if angle is None and len(possible_angles) == 1:
        angle = possible_angles[0]
    if angle is None:
        return None

    height_mm = frame_height_mm
    if height_mm is None:
        height_candidates = []
        for token in tokens:
            value = int(round(float(token)))
            if value in BEMATRIX_FRAME_SIZES_MM and abs(float(token) - angle) > 1e-6:
                height_candidates.append(value)
        if height_candidates:
            height_mm = height_candidates[-1]

    table = CURVED_FRAME_TABLE[(angle, radius_mm)]
    return {
        "angle_degrees": angle,
        "radius_mm": radius_mm,
        "family_mm": radius_mm,
        "frame_height_mm": height_mm,
        "outside_panel_width_mm": table["outside_panel_width_mm"],
        "inside_panel_width_mm": table["inside_panel_width_mm"],
        "height_trim_mm": table["height_trim_mm"],
        "detection_path": "explicit radius/angle detection",
    }


def is_known_curved_frame_name(obj_name):
    return parse_curved_frame_from_name(obj_name) is not None


def _local_bounds(frame_obj):
    corners = [Vector(corner) for corner in frame_obj.bound_box]
    return {
        "min_x": min(v.x for v in corners),
        "max_x": max(v.x for v in corners),
        "min_y": min(v.y for v in corners),
        "max_y": max(v.y for v in corners),
        "min_z": min(v.z for v in corners),
        "max_z": max(v.z for v in corners),
    }


AXIS_NAMES = {0: "X", 1: "Y", 2: "Z"}


def _bounds_from_points(points):
    return {
        "min_x": min(v[0] for v in points),
        "max_x": max(v[0] for v in points),
        "min_y": min(v[1] for v in points),
        "max_y": max(v[1] for v in points),
        "min_z": min(v[2] for v in points),
        "max_z": max(v[2] for v in points),
    }


def _percentile(sorted_values, pct):
    """Linear-interpolated percentile of an already-sorted list."""
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    k = (len(sorted_values) - 1) * (pct / 100.0)
    lo = int(math.floor(k))
    hi = int(math.ceil(k))
    if lo == hi:
        return sorted_values[lo]
    return sorted_values[lo] * (hi - k) + sorted_values[hi] * (k - lo)


def _footprint_axes(vertical_axis):
    """The two local axis indices that form the curve footprint plane."""
    return [axis for axis in (0, 1, 2) if axis != vertical_axis]


def _detect_vertical_axis(frame_obj, frame_height_m):
    """
    Pick the local bounding-box axis whose extent best matches the parsed frame
    height. Curved BeMatrix assets may be authored with height along Y or Z, and
    'Set Origin to Center of Mass' does not change which axis is vertical, so we
    detect it per-frame instead of assuming a fixed convention.
    """
    bounds = _local_bounds(frame_obj)
    extents = {
        0: bounds["max_x"] - bounds["min_x"],
        1: bounds["max_y"] - bounds["min_y"],
        2: bounds["max_z"] - bounds["min_z"],
    }
    if frame_height_m and frame_height_m > 0.0:
        vertical_axis = min(extents, key=lambda axis: abs(extents[axis] - frame_height_m))
    else:
        vertical_axis = max(extents, key=lambda axis: extents[axis])
    return vertical_axis, extents


def _frame_local_vertices(frame_obj):
    if frame_obj.type != "MESH" or frame_obj.data is None:
        return []
    return [vertex.co.copy() for vertex in frame_obj.data.vertices]


def _fit_circle_2d(points2d):
    """
    Least-squares circle fit for (a, b) footprint points. Returns center, radius
    and the occupied angular arc (complement of the largest circular gap).
    """
    if len(points2d) < 3:
        return None

    # Solve a^2 + b^2 + D*a + E*b + F = 0 with normal equations.
    rows = []
    rhs = []
    for a, b in points2d:
        rows.append((a, b, 1.0))
        rhs.append(-(a * a + b * b))

    matrix = [
        [sum(row[i] * row[j] for row in rows) for j in range(3)]
        for i in range(3)
    ]
    vector = [sum(rows[r][i] * rhs[r] for r in range(len(rows))) for i in range(3)]
    aug = [matrix[i] + [vector[i]] for i in range(3)]

    for col in range(3):
        pivot = max(range(col, 3), key=lambda row: abs(aug[row][col]))
        if abs(aug[pivot][col]) < 1e-12:
            return None
        aug[col], aug[pivot] = aug[pivot], aug[col]
        divisor = aug[col][col]
        for j in range(col, 4):
            aug[col][j] /= divisor
        for row in range(3):
            if row == col:
                continue
            factor = aug[row][col]
            for j in range(col, 4):
                aug[row][j] -= factor * aug[col][j]

    d, e, f = (aug[i][3] for i in range(3))
    center_a = -d / 2.0
    center_b = -e / 2.0
    centerline_radius = math.sqrt(max(0.0, center_a * center_a + center_b * center_b - f))

    raw_angles = [
        math.degrees(math.atan2(b - center_b, a - center_a)) % 360.0
        for a, b in points2d
    ]
    angles = sorted(set(round(angle, 4) for angle in raw_angles))
    if not angles:
        return None

    if len(angles) == 1:
        start_angle = end_angle = angles[0]
    else:
        largest_gap = None
        largest_i = 0
        for i, angle in enumerate(angles):
            next_angle = angles[(i + 1) % len(angles)]
            if i == len(angles) - 1:
                next_angle += 360.0
            gap = next_angle - angle
            if largest_gap is None or gap > largest_gap:
                largest_gap = gap
                largest_i = i
        start_angle = angles[(largest_i + 1) % len(angles)]
        end_angle = angles[largest_i]
        if end_angle < start_angle:
            end_angle += 360.0

        # Reject lone stray verts at the extremes so the occupied sweep tracks
        # the real footprint edges, not a single outlier.
        continuous = sorted(
            (a if a >= start_angle - 1e-6 else a + 360.0) for a in raw_angles
        )
        continuous = [c for c in continuous
                      if start_angle - 1e-6 <= c <= end_angle + 1e-6]
        if len(continuous) >= 20:
            start_angle = _percentile(continuous, 0.5)
            end_angle = _percentile(continuous, 99.5)

    radii = sorted(math.hypot(a - center_a, b - center_b) for a, b in points2d)
    return {
        "center": (center_a, center_b),
        "centerline_radius_m": centerline_radius,
        "inner_radius_m": _percentile(radii, 1.0),
        "outer_radius_m": _percentile(radii, 99.0),
        "occupied_start_degrees": start_angle,
        "occupied_end_degrees": end_angle,
        "occupied_mid_degrees": (start_angle + end_angle) / 2.0,
        "occupied_sweep_degrees": end_angle - start_angle,
    }


def _fit_frame_curve(frame_obj, vertical_axis, bars_only=True):
    """
    Fit the frame's curved footprint. By default only the top and bottom bars
    (vertical extremes) are used: those are clean swept arcs, while the vertical
    side members would bias a full-mesh fit.
    """
    verts = _frame_local_vertices(frame_obj)
    if not verts:
        return None
    ai, bi = _footprint_axes(vertical_axis)
    v_values = [co[vertical_axis] for co in verts]
    v_min = min(v_values)
    v_max = max(v_values)

    selected = verts
    if bars_only and v_max - v_min > 1e-6:
        band = (v_max - v_min) * 0.12
        bars = [co for co in verts if co[vertical_axis] < v_min + band
                or co[vertical_axis] > v_max - band]
        if len(bars) >= 3:
            selected = bars

    footprint = [(co[ai], co[bi]) for co in selected]
    circle = _fit_circle_2d(footprint)
    if circle is None:
        return None
    circle["vertical_axis"] = vertical_axis
    circle["footprint_axes"] = (ai, bi)
    circle["vertical_min"] = v_min
    circle["vertical_max"] = v_max
    circle["vertical_center"] = (v_min + v_max) / 2.0
    return circle


def _mesh_metrics_from_points(points, vertical_axis=1):
    """Bounds + fitted-arc metrics for a generated/reference mesh in local space."""
    if not points:
        return None
    bounds = _bounds_from_points(points)
    ai, bi = _footprint_axes(vertical_axis)
    seen = set()
    footprint = []
    for point in points:
        key = (round(point[ai], 6), round(point[bi], 6))
        if key in seen:
            continue
        seen.add(key)
        footprint.append((point[ai], point[bi]))
    circle = _fit_circle_2d(footprint)
    v_lo = bounds["min_" + AXIS_NAMES[vertical_axis].lower()]
    v_hi = bounds["max_" + AXIS_NAMES[vertical_axis].lower()]
    return {
        "bounds": bounds,
        "vertical_axis": vertical_axis,
        "radius_m": circle["outer_radius_m"] if circle else None,
        "inner_radius_m": circle["inner_radius_m"] if circle else None,
        "outer_radius_m": circle["outer_radius_m"] if circle else None,
        "arc_center": circle["center"] if circle else None,
        "arc_start_angle_degrees": circle["occupied_start_degrees"] if circle else None,
        "arc_end_angle_degrees": circle["occupied_end_degrees"] if circle else None,
        "arc_sweep_degrees": circle["occupied_sweep_degrees"] if circle else None,
        "height_m": v_hi - v_lo,
    }


def _object_points_in_frame_local(obj, frame_obj):
    if obj.type != "MESH" or obj.data is None:
        return []

    if obj.parent == frame_obj:
        matrix = obj.matrix_local
    else:
        matrix = frame_obj.matrix_world.inverted() @ obj.matrix_world

    return [matrix @ vertex.co for vertex in obj.data.vertices]


# ---------------------------------------------------------------------------
# Reference-curve path
#
# A curved frame's true infill surface is the actual interior/exterior curve
# edge of the frame. The most faithful way to reproduce it is to read a manually
# verified reference panel object built from those edges. When a sibling object
# named "<frame-base>_Outside" / "<frame-base>_Inside" exists, we resample its
# footprint path directly instead of fitting a circle to the frame mesh (the
# frame point cloud's best-fit circle is biased off the true curve centre).
#
# This is the validated path proven against B62_0248_CURVE_90_H0992. It already
# generalises to any curved frame that ships matching _Outside/_Inside reference
# objects; when none is present we fall back to the frame-fit arc.
# ---------------------------------------------------------------------------

_REFERENCE_SIDE_SUFFIX = {"OUTSIDE": "Outside", "INSIDE": "Inside"}


def _reference_base_name(frame_obj):
    base = strip_blender_duplicate_suffix(frame_obj.name)
    # B62_0248_CURVE_90_H0992_Frame -> B62_0248_CURVE_90_H0992
    return re.sub(r"_Frame$", "", base, flags=re.IGNORECASE)


def _find_reference_curve_object(frame_obj, curved_face):
    """Locate the manually built reference infill surface for this side."""
    suffix = _REFERENCE_SIDE_SUFFIX.get(curved_face)
    if suffix is None:
        return None
    base = _reference_base_name(frame_obj)
    wanted = {f"{base}_{suffix}".lower()}
    for obj in bpy.data.objects:
        if obj.type != "MESH" or obj is frame_obj or obj.data is None:
            continue
        if is_marked_panel(obj):
            continue  # never treat our own generated panels as a reference
        if strip_blender_duplicate_suffix(obj.name).lower() in wanted:
            return obj
    return None


def _order_open_arc(columns, center_a, center_b):
    """
    Order footprint columns along an open arc path. Sort by angle, then rotate
    so the sequence starts right after the largest angular gap (the empty side of
    the arc), giving a clean end-to-end path even if it crosses the atan2 seam.
    """
    if len(columns) < 3:
        return list(columns)
    items = sorted(columns, key=lambda c: math.atan2(c[1] - center_b, c[0] - center_a))
    angles = [math.degrees(math.atan2(c[1] - center_b, c[0] - center_a)) % 360.0
              for c in items]
    largest_gap = -1.0
    gap_index = 0
    for i in range(len(angles)):
        nxt = angles[(i + 1) % len(angles)] + (360.0 if i == len(angles) - 1 else 0.0)
        gap = nxt - angles[i]
        if gap > largest_gap:
            largest_gap = gap
            gap_index = i
    start = (gap_index + 1) % len(items)
    return items[start:] + items[:start]


def _reference_curve_layout(ref_obj, frame_obj, vertical_axis):
    """
    Extract the reference panel's footprint path in frame-local space:
    an ordered list of (a, b) columns plus the vertical span and a circle fit
    (centre/radius/angles) for reporting.
    """
    pts = _object_points_in_frame_local(ref_obj, frame_obj)
    if len(pts) < 4:
        return None
    ai, bi = _footprint_axes(vertical_axis)
    v_values = [p[vertical_axis] for p in pts]
    z_lo, z_hi = min(v_values), max(v_values)

    seen = set()
    columns = []
    for p in pts:
        key = (round(p[ai], 4), round(p[bi], 4))
        if key in seen:
            continue
        seen.add(key)
        columns.append((p[ai], p[bi]))
    if len(columns) < 3:
        return None

    circle = _fit_circle_2d(columns)
    # Order along the path using the ARC CENTRE (circle fit), not the centroid of
    # the points. The centroid lies on/near the arc, which gives a non-monotonic
    # angular order; the arc centre sits well off the curve so angles increase
    # cleanly from one end to the other.
    if circle is not None:
        center_a, center_b = circle["center"]
    else:
        center_a = sum(c[0] for c in columns) / len(columns)
        center_b = sum(c[1] for c in columns) / len(columns)
    ring = _order_open_arc(columns, center_a, center_b)
    return {
        "ring": ring,
        "z_lo": z_lo,
        "z_hi": z_hi,
        "vertical_axis": vertical_axis,
        "footprint_axes": (ai, bi),
        "reference_name": ref_obj.name,
        "circle": circle,
    }


def _resample_polyline(points2d, segment_count):
    """Uniformly resample an open polyline by arc length into segment_count+1 pts."""
    if len(points2d) < 2:
        return list(points2d)
    cum = [0.0]
    for i in range(1, len(points2d)):
        d = math.hypot(points2d[i][0] - points2d[i - 1][0],
                       points2d[i][1] - points2d[i - 1][1])
        cum.append(cum[-1] + d)
    total = cum[-1]
    if total <= 1e-9:
        return [points2d[0]] * (segment_count + 1)
    out = []
    seg = 0
    for k in range(segment_count + 1):
        target = total * k / segment_count
        while seg < len(cum) - 2 and cum[seg + 1] < target:
            seg += 1
        span = cum[seg + 1] - cum[seg]
        t = (target - cum[seg]) / span if span > 1e-12 else 0.0
        x = points2d[seg][0] + (points2d[seg + 1][0] - points2d[seg][0]) * t
        y = points2d[seg][1] + (points2d[seg + 1][1] - points2d[seg][1]) * t
        out.append((x, y))
    return out


def _curved_mesh_from_ring(ring2d, z_lo, z_hi, vertical_axis, footprint_axes, curved_face):
    """Build a vertical curved strip that follows the reference footprint path."""
    ai, bi = footprint_axes
    n = len(ring2d)
    # Arc-length parameterisation so U = 0..1 tracks physical distance across the
    # curve (not vertex index), giving even artwork spacing over uneven columns.
    cum = [0.0]
    for i in range(1, n):
        cum.append(cum[-1] + math.hypot(ring2d[i][0] - ring2d[i - 1][0],
                                        ring2d[i][1] - ring2d[i - 1][1]))
    total = cum[-1] if cum[-1] > 1e-9 else 1.0
    verts = []
    uvs = []
    for i, (a_val, b_val) in enumerate(ring2d):
        t = cum[i] / total
        for z_val, v in ((z_lo, 0.0), (z_hi, 1.0)):
            co = [0.0, 0.0, 0.0]
            co[ai] = a_val
            co[bi] = b_val
            co[vertical_axis] = z_val
            verts.append(tuple(co))
            uvs.append((t, v))
    faces = []
    for i in range(n - 1):
        a = i * 2
        if curved_face == "OUTSIDE":
            faces.append((a, a + 1, a + 3, a + 2))
        else:
            faces.append((a, a + 2, a + 3, a + 1))
    return verts, faces, uvs


def _find_curved_reference_object(frame_obj, side_label, generated_obj):
    """
    Locate the manually placed reference plane for this side, e.g.
    BM_PANEL_FRONT_B62_0496_CURVE_90_H0992.

    The generated panel uses the SAME name as the reference plane, so creating a
    panel makes Blender swap a ".001" suffix between them. Match on the stripped
    name and skip our own generated panels (marked objects) so the human-placed
    reference is still found after that swap.
    """
    clean_frame_name = strip_blender_duplicate_suffix(frame_obj.name)
    reference_name = f"{GENERATED_PANEL_PREFIX}{side_label}_{clean_frame_name}"
    for obj in bpy.data.objects:
        if obj == generated_obj or obj.type != "MESH":
            continue
        if is_marked_panel(obj):
            continue
        if strip_blender_duplicate_suffix(obj.name) == reference_name:
            return obj
    return None


def compare_curved_panel_to_reference(frame_obj, panel_obj, side_label, vertical_axis=1):
    """
    Compare a generated curved mesh with a manually placed reference plane when
    the reference object exists in the scene.
    """
    reference_obj = _find_curved_reference_object(frame_obj, side_label, panel_obj)
    generated_points = _object_points_in_frame_local(panel_obj, frame_obj)
    generated = _mesh_metrics_from_points(generated_points, vertical_axis)
    if reference_obj is None:
        return {"reference_name": None, "generated": generated, "reference": None}

    reference_points = _object_points_in_frame_local(reference_obj, frame_obj)
    return {
        "reference_name": reference_obj.name,
        "generated": generated,
        "reference": _mesh_metrics_from_points(reference_points, vertical_axis),
    }


def _compute_curved_arc_layout(frame_obj, spec, curved_face, segment_count):
    """
    Build the local-space arc the generated panel follows by FITTING the frame's
    own curved surface, so the panel hugs the frame instead of using a radius
    derived from the official (developed) panel width, which is too wide.

    Both the radius AND the angular sweep come from the frame mesh: the panel is
    concentric with the fitted frame curve and sweeps the frame's MEASURED
    occupied footprint angle (edge to edge), not the nominal name angle. The
    nominal angle understates the real sweep (e.g. B62_0496_CURVE_90 actually
    sweeps ~119 deg of footprint), which is why a nominal-width panel looked too
    narrow and did not reach the frame edges. Vertical axis (Y or Z) is detected
    per-frame; the other two local axes form the footprint plane.

    The mesh is pre-oriented in frame-local space (object rotation stays 0,0,0).
    For reference, the equivalent object rotation that the manual planes use is
    rotation_x = 90 deg, rotation_y = 0, rotation_z = 90 + nominal_angle / 2.
    """
    bounds = _local_bounds(frame_obj)
    frame_height_m = mm_to_m(spec["frame_height_mm"]) if spec.get("frame_height_mm") else None
    vertical_axis, extents = _detect_vertical_axis(frame_obj, frame_height_m)
    ai, bi = _footprint_axes(vertical_axis)

    fit = _fit_frame_curve(frame_obj, vertical_axis, bars_only=True)
    nominal_angle = spec["angle_degrees"]

    if fit is None:
        # Degenerate fallback: keep a sane arc rather than crashing.
        center = ((bounds["min_" + AXIS_NAMES[ai].lower()] + bounds["max_" + AXIS_NAMES[ai].lower()]) / 2.0,
                  (bounds["min_" + AXIS_NAMES[bi].lower()] + bounds["max_" + AXIS_NAMES[bi].lower()]) / 2.0)
        outer_r = inner_r = max(extents.values()) / 2.0
        mid_deg = 270.0
        start_deg = mid_deg - nominal_angle / 2.0
        end_deg = mid_deg + nominal_angle / 2.0
        vertical_center = (bounds["min_" + AXIS_NAMES[vertical_axis].lower()]
                           + bounds["max_" + AXIS_NAMES[vertical_axis].lower()]) / 2.0
        centerline_r = outer_r
        sweep_source = "nominal (no frame fit)"
    else:
        center = fit["center"]
        outer_r = fit["outer_radius_m"]
        inner_r = fit["inner_radius_m"]
        centerline_r = fit["centerline_radius_m"]
        mid_deg = fit["occupied_mid_degrees"]
        vertical_center = fit["vertical_center"]
        start_deg = fit["occupied_start_degrees"]
        end_deg = fit["occupied_end_degrees"]
        sweep_source = "measured frame footprint"
        # Guard against a degenerate fit: fall back to nominal if implausible.
        measured_sweep = end_deg - start_deg
        if not (0.5 <= measured_sweep <= 300.0):
            start_deg = mid_deg - nominal_angle / 2.0
            end_deg = mid_deg + nominal_angle / 2.0
            sweep_source = "nominal (measured sweep implausible)"

    radius_m = outer_r if curved_face == "OUTSIDE" else inner_r

    start_angle = math.radians(start_deg)
    end_angle = math.radians(end_deg)
    expected_rotation_z = 90.0 + nominal_angle / 2.0

    return {
        "bounds": bounds,
        "vertical_axis": vertical_axis,
        "footprint_axes": (ai, bi),
        "center": center,
        "radius_m": radius_m,
        "inner_radius_m": inner_r,
        "outer_radius_m": outer_r,
        "centerline_radius_m": centerline_r,
        "vertical_center": vertical_center,
        "mid_angle_degrees": mid_deg,
        "nominal_angle_degrees": nominal_angle,
        "measured_sweep_degrees": end_deg - start_deg,
        "sweep_source": sweep_source,
        "start_angle": start_angle,
        "end_angle": end_angle,
        "direction": "counterclockwise",
        "expected_rotation": (90.0, 0.0, expected_rotation_z),
        "fit_score": 0.0,
    }


def _curved_mesh_data(panel_height_mm, arc_layout, curved_face, segment_count):
    """
    Build a vertical curved strip in curved-frame local space.

    Vertical axis is detected per-frame (Y or Z); the other two local axes hold
    the curve footprint. The arc is concentric with the fitted frame curve, so
    the strip follows the frame. The mesh is pre-oriented (no object rotation).
    """
    panel_height_m = mm_to_m(panel_height_mm)
    half_h = panel_height_m / 2.0
    vertical_axis = arc_layout["vertical_axis"]
    ai, bi = arc_layout["footprint_axes"]
    center_a, center_b = arc_layout["center"]
    radius_m = arc_layout["radius_m"]
    v_center = arc_layout["vertical_center"]
    start_angle = arc_layout["start_angle"]
    end_angle = arc_layout["end_angle"]

    def _vertex(a_val, b_val, v_val):
        co = [0.0, 0.0, 0.0]
        co[ai] = a_val
        co[bi] = b_val
        co[vertical_axis] = v_val
        return tuple(co)

    verts = []
    uvs = []
    for i in range(segment_count + 1):
        t = i / segment_count
        theta = start_angle + (end_angle - start_angle) * t
        a_val = center_a + radius_m * math.cos(theta)
        b_val = center_b + radius_m * math.sin(theta)
        verts.append(_vertex(a_val, b_val, v_center - half_h))
        verts.append(_vertex(a_val, b_val, v_center + half_h))
        uvs.append((t, 0.0))
        uvs.append((t, 1.0))

    faces = []
    sweep_is_ccw = end_angle >= start_angle
    for i in range(segment_count):
        a = i * 2
        outside_winding = curved_face == "OUTSIDE"
        if not sweep_is_ccw:
            outside_winding = not outside_winding
        if outside_winding:
            faces.append((a, a + 1, a + 3, a + 2))
        else:
            faces.append((a, a + 2, a + 3, a + 1))

    return verts, faces, uvs


def _find_existing_curved_panel(frame_obj, side_label, panel_kind,
                                curved_face, index_1=None, index_2=None):
    for child in frame_obj.children:
        if child.type != "MESH" or not is_marked_panel(child):
            continue
        if child.get("bematrix_panel_kind") != panel_kind:
            continue
        if child.get("bematrix_panel_side") != side_label:
            continue
        if child.get("bematrix_curved_face") != curved_face:
            continue
        if (
            child.get("bematrix_array_index") == index_1
            and child.get("bematrix_array_index_2") == index_2
        ):
            return child
    return None


def _delete_stale_curved_panels(frame_obj, side_label, panel_kind,
                                curved_face, valid_keys):
    valid = set(valid_keys)
    deleted_names = []
    for child in list(frame_obj.children):
        if child.type != "MESH" or not is_marked_panel(child):
            continue
        if child.get("bematrix_panel_kind") != panel_kind:
            continue
        if child.get("bematrix_panel_side") != side_label:
            continue
        if child.get("bematrix_curved_face") != curved_face:
            continue
        key = (child.get("bematrix_array_index"), child.get("bematrix_array_index_2"))
        if key not in valid:
            deleted_names.append(child.name)
            bpy.data.objects.remove(child, do_unlink=True)
    return deleted_names


def create_or_update_curved_panel_for_frame(
    frame_obj,
    side_label,
    side_offset_mm,
    frame_height_mm,
    array_list,
    curved_face="OUTSIDE",
    panel_kind="HARD_CURVED",
    replace_existing=True,
):
    details = {
        "frame_name": frame_obj.name,
        "side": side_label,
        "created": [],
        "updated": [],
        "deleted_names": [],
        "reference_checks": [],
        "panel_count": 0,
        "error": None,
        "is_curved": True,
    }
    curved_face = curved_face if curved_face in {"OUTSIDE", "INSIDE"} else "OUTSIDE"
    resolved_label = curved_face_label(curved_face)
    spec = parse_curved_frame_from_name(frame_obj.name, frame_height_mm=frame_height_mm)
    if spec is None:
        details["error"] = "No supported curved frame size detected."
        return 0, details
    if spec["frame_height_mm"] is None:
        details["error"] = "Could not detect curved frame height."
        return 0, details

    width_key = "outside_panel_width_mm" if curved_face == "OUTSIDE" else "inside_panel_width_mm"
    panel_width_mm = spec[width_key]
    panel_height_mm = spec["frame_height_mm"] - spec["height_trim_mm"]
    if panel_width_mm <= 0 or panel_height_mm <= 0:
        details["error"] = "Invalid curved panel dimensions."
        return 0, details

    segment_count = max(8, int(math.ceil(spec["angle_degrees"] / 5.0)))
    arc_layout = _compute_curved_arc_layout(
        frame_obj,
        spec,
        curved_face,
        segment_count,
    )
    vertical_axis = arc_layout["vertical_axis"]

    # Preferred path: if a manually verified reference infill object exists for
    # this side (e.g. B62_0248_CURVE_90_H0992_Outside), reproduce its exact curve
    # rather than fitting the frame point cloud. See the reference-curve helpers.
    ref_obj = _find_reference_curve_object(frame_obj, curved_face)
    ref_layout = _reference_curve_layout(ref_obj, frame_obj, vertical_axis) if ref_obj else None
    if ref_layout and len(ref_layout["ring"]) >= 3:
        # Use the reference's own ordered footprint columns directly so generated
        # vertices land exactly on the reference path (no resampling onto the long
        # end-tab edges). UVs are still arc-length proportional via _curved_mesh.
        ring = ref_layout["ring"]
        verts, faces, uvs = _curved_mesh_from_ring(
            ring, ref_layout["z_lo"], ref_layout["z_hi"],
            vertical_axis, arc_layout["footprint_axes"], curved_face,
        )
        segment_count = len(ring) - 1
        panel_height_mm = (ref_layout["z_hi"] - ref_layout["z_lo"]) * 1000.0
        circle = ref_layout["circle"]
        if circle:
            arc_layout["center"] = circle["center"]
            arc_layout["radius_m"] = circle["outer_radius_m"] if curved_face == "OUTSIDE" else circle["inner_radius_m"]
            arc_layout["outer_radius_m"] = circle["outer_radius_m"]
            arc_layout["inner_radius_m"] = circle["inner_radius_m"]
            arc_layout["centerline_radius_m"] = circle["centerline_radius_m"]
            arc_layout["mid_angle_degrees"] = circle["occupied_mid_degrees"]
            arc_layout["start_angle"] = math.radians(circle["occupied_start_degrees"])
            arc_layout["end_angle"] = math.radians(circle["occupied_end_degrees"])
            arc_layout["measured_sweep_degrees"] = circle["occupied_sweep_degrees"]
        arc_layout["sweep_source"] = "reference object"
        details["reference_curve_object"] = ref_layout["reference_name"]
    else:
        verts, faces, uvs = _curved_mesh_data(
            panel_height_mm,
            arc_layout,
            curved_face,
            segment_count,
        )
        details["reference_curve_object"] = None
    first_vertex = verts[0] if verts else None
    last_vertex = verts[-2] if len(verts) >= 2 else None
    generated_mesh_metrics = _mesh_metrics_from_points(
        [Vector(v) for v in verts], vertical_axis
    )

    array_positions = get_panel_array_positions(frame_obj, array_list)
    valid_keys = {(index_1, index_2) for index_1, index_2, _loc in array_positions}
    details["deleted_names"] = _delete_stale_curved_panels(
        frame_obj, side_label, panel_kind, curved_face, valid_keys
    )

    count = 0
    for index_1, index_2, array_step in array_positions:
        panel_name = _curved_generated_name(frame_obj, side_label, panel_kind, index_1, index_2)
        panel_mat = get_or_create_unique_panel_material(panel_name)
        existing = _find_existing_curved_panel(
            frame_obj, side_label, panel_kind, curved_face, index_1, index_2
        )

        if existing and replace_existing:
            mesh = existing.data
            mesh.clear_geometry()
            mesh.from_pydata(verts, [], faces)
            mesh.update()
            panel_obj = existing
            action_bucket = details["updated"]
        else:
            mesh = bpy.data.meshes.new(f"{panel_name}_Mesh")
            mesh.from_pydata(verts, [], faces)
            mesh.update()
            panel_obj = bpy.data.objects.new(panel_name, mesh)
            if frame_obj.users_collection:
                frame_obj.users_collection[0].objects.link(panel_obj)
            else:
                bpy.context.collection.objects.link(panel_obj)
            action_bucket = details["created"]

        uv_layer = panel_obj.data.uv_layers.get("UVMap")
        if uv_layer is None:
            uv_layer = panel_obj.data.uv_layers.new(name="UVMap")
        for poly in panel_obj.data.polygons:
            for loop_i in poly.loop_indices:
                vi = panel_obj.data.loops[loop_i].vertex_index
                uv_layer.data[loop_i].uv = uvs[vi]

        panel_obj.parent = frame_obj
        panel_obj.matrix_parent_inverse.identity()
        panel_obj.location = Vector(array_step)
        panel_obj.rotation_euler = (0.0, 0.0, 0.0)
        panel_obj.scale = (1.0, 1.0, 1.0)

        if panel_obj.data.materials:
            panel_obj.data.materials[0] = panel_mat
        else:
            panel_obj.data.materials.append(panel_mat)

        panel_obj.name = panel_name
        panel_obj.data.name = f"{panel_obj.name}_Mesh"
        panel_obj["is_bematrix_panel"] = True
        panel_obj["bematrix_panel_kind"] = panel_kind
        panel_obj["bematrix_parent_frame"] = frame_obj.name
        panel_obj["bematrix_panel_side"] = side_label
        panel_obj["bematrix_curved_face"] = curved_face
        panel_obj["bematrix_resolved_curved_side"] = resolved_label
        panel_obj["bematrix_curved_detection_path"] = spec["detection_path"]
        panel_obj["bematrix_curved_family_mm"] = spec["family_mm"]
        panel_obj["bematrix_curved_radius_mm"] = spec["radius_mm"]
        panel_obj["bematrix_curved_angle_degrees"] = spec["angle_degrees"]
        panel_obj["bematrix_panel_width_mm"] = panel_width_mm
        panel_obj["bematrix_panel_height_mm"] = panel_height_mm
        panel_obj["bematrix_frame_height_mm"] = spec["frame_height_mm"]
        panel_obj["bematrix_y_offset_mm"] = side_offset_mm
        panel_obj["bematrix_curved_mesh_segments"] = segment_count

        if index_1 is None:
            for key in ("bematrix_array_index", "bematrix_array_index_2", "bematrix_array_count"):
                if key in panel_obj:
                    del panel_obj[key]
        else:
            panel_obj["bematrix_array_index"] = index_1
            if index_2 is None:
                if "bematrix_array_index_2" in panel_obj:
                    del panel_obj["bematrix_array_index_2"]
            else:
                panel_obj["bematrix_array_index_2"] = index_2
            panel_obj["bematrix_array_count"] = len(array_positions)

        remove_generated_array_modifiers(panel_obj)
        action_bucket.append((
            panel_obj.name,
            tuple(panel_obj.location),
            tuple(panel_obj.rotation_euler),
            panel_mat.name,
        ))

        reference_check = compare_curved_panel_to_reference(
            frame_obj,
            panel_obj,
            side_label,
            vertical_axis,
        )
        details["reference_checks"].append((panel_obj.name, reference_check))

        # The panel is always built in frame-local space and parented at the
        # frame origin, so the mesh verts ARE the frame-local points. Use them
        # directly (object.matrix_local can be stale before a depsgraph update).
        local_points = [Vector(v) for v in verts]
        local_metrics = _mesh_metrics_from_points(local_points, vertical_axis)
        local_bounds = local_metrics["bounds"] if local_metrics else generated_mesh_metrics["bounds"]
        print(f"\n  --- CURVED PANEL DEBUG [{side_label}] ---")
        print(f"  selected frame name: {frame_obj.name}")
        print(
            f"  detected curve: family={spec['family_mm']} radius={spec['radius_mm']} mm "
            f"angle={spec['angle_degrees']} deg height={spec['frame_height_mm']} mm"
        )
        print(f"  selected panel side: {side_label}")
        print(f"  resolved curve side: {resolved_label}")
        v_ax = AXIS_NAMES[arc_layout["vertical_axis"]]
        f_ax = "/".join(AXIS_NAMES[a] for a in arc_layout["footprint_axes"])
        print(f"  local axis convention used: {v_ax} vertical, {f_ax} curve footprint")
        exp_rot = arc_layout["expected_rotation"]
        print(
            f"  expected object rotation (manual-plane rule, mesh is pre-oriented): "
            f"X={exp_rot[0]:.3f} Y={exp_rot[1]:.3f} Z={exp_rot[2]:.3f} deg"
        )
        print(f"  generated object rotation: (0.000, 0.000, 0.000) deg (mesh baked in frame space)")
        print(f"  panel width (official, reference only): {panel_width_mm:g} mm")
        print(
            f"  frame-fitted radii: outer={arc_layout['outer_radius_m']:.6f} m "
            f"inner={arc_layout['inner_radius_m']:.6f} m "
            f"centerline={arc_layout['centerline_radius_m']:.6f} m"
        )
        print(f"  calculated radius ({resolved_label}): {arc_layout['radius_m']:.6f} m")
        print(f"  panel height: {panel_height_mm:g} mm")
        print(f"  arc center (footprint {f_ax}): {tuple(round(v, 6) for v in arc_layout['center'])}")
        print(f"  arc symmetry mid-angle: {arc_layout['mid_angle_degrees']:.4f} deg")
        print(f"  start angle: {math.degrees(arc_layout['start_angle']):.6f} deg")
        print(f"  end angle: {math.degrees(arc_layout['end_angle']):.6f} deg")
        print(
            f"  sweep: {arc_layout['measured_sweep_degrees']:.4f} deg "
            f"(source: {arc_layout['sweep_source']}; nominal name angle "
            f"{arc_layout['nominal_angle_degrees']:g} deg)"
        )
        print(f"  sweep direction: {arc_layout['direction']}")
        a_i, b_i = arc_layout["footprint_axes"]
        follow_errs = [
            abs(math.hypot(p[a_i] - arc_layout["center"][0],
                           p[b_i] - arc_layout["center"][1]) - arc_layout["radius_m"])
            for p in local_points
        ]
        if follow_errs:
            print(
                f"  max frame-follow error (vertex footprint vs fitted face radius): "
                f"{max(follow_errs) * 1000.0:.3f} mm"
            )
        print(f"  mesh segment count: {segment_count}")
        print(
            "  generated local bounds: "
            f"x=({local_bounds['min_x']:.6f}, {local_bounds['max_x']:.6f}), "
            f"y=({local_bounds['min_y']:.6f}, {local_bounds['max_y']:.6f}), "
            f"z=({local_bounds['min_z']:.6f}, {local_bounds['max_z']:.6f})"
        )
        print(f"  created object name: {panel_obj.name}")
        if ref_layout is not None:
            ref_pts = _object_points_in_frame_local(ref_obj, frame_obj)
            rxs = [p[a_i] for p in ref_pts]; rys = [p[b_i] for p in ref_pts]
            rzs = [p[arc_layout["vertical_axis"]] for p in ref_pts]
            rc = ref_layout["circle"]
            print(f"  REFERENCE OBJECT USED: {ref_layout['reference_name']} (verts={len(ref_pts)})")
            print(
                f"    reference footprint bounds: {AXIS_NAMES[a_i]}=({min(rxs):.4f},{max(rxs):.4f}) "
                f"{AXIS_NAMES[b_i]}=({min(rys):.4f},{max(rys):.4f}) "
                f"{v_ax}=({min(rzs):.4f},{max(rzs):.4f})"
            )
            if rc:
                print(
                    f"    reference fit: center=({rc['center'][0]:.5f},{rc['center'][1]:.5f}) "
                    f"R(out/in)={rc['outer_radius_m']:.5f}/{rc['inner_radius_m']:.5f} "
                    f"angles {rc['occupied_start_degrees']:.2f}..{rc['occupied_end_degrees']:.2f} "
                    f"sweep {rc['occupied_sweep_degrees']:.2f} deg"
                )
            # max distance from each generated vertex to nearest reference vertex
            if ref_pts:
                max_err = 0.0
                for g in local_points:
                    best = min((g - r).length for r in ref_pts)
                    if best > max_err:
                        max_err = best
                print(f"    MAX generated->reference vertex distance: {max_err * 1000.0:.3f} mm")
        reference = reference_check.get("reference")
        generated = reference_check.get("generated")
        if reference and generated:
            print(f"  reference comparison: {reference_check['reference_name']}")
            print(
                "    generated local bounds: "
                f"x=({generated['bounds']['min_x']:.6f}, {generated['bounds']['max_x']:.6f}), "
                f"y=({generated['bounds']['min_y']:.6f}, {generated['bounds']['max_y']:.6f}), "
                f"z=({generated['bounds']['min_z']:.6f}, {generated['bounds']['max_z']:.6f})"
            )
            print(
                "    reference local bounds: "
                f"x=({reference['bounds']['min_x']:.6f}, {reference['bounds']['max_x']:.6f}), "
                f"y=({reference['bounds']['min_y']:.6f}, {reference['bounds']['max_y']:.6f}), "
                f"z=({reference['bounds']['min_z']:.6f}, {reference['bounds']['max_z']:.6f})"
            )
            print(
                f"    generated radius: {generated['radius_m']:.6f} m, "
                f"reference radius: {reference['radius_m']:.6f} m"
            )
            print(
                f"    generated arc angle range: "
                f"{generated['arc_start_angle_degrees']:.6f} -> "
                f"{generated['arc_end_angle_degrees']:.6f} deg, "
                f"reference arc angle range: "
                f"{reference['arc_start_angle_degrees']:.6f} -> "
                f"{reference['arc_end_angle_degrees']:.6f} deg"
            )
            print(
                f"    generated height: {generated['height_m']:.6f} m, "
                f"reference height: {reference['height_m']:.6f} m"
            )
        count += 1

    generated_bounds = generated_mesh_metrics["bounds"] if generated_mesh_metrics else arc_layout["bounds"]
    details.update({
        "panel_count": count,
        "panel_width_mm": panel_width_mm,
        "panel_height_mm": panel_height_mm,
        "radius_mm": spec["radius_mm"],
        "angle_degrees": spec["angle_degrees"],
        "family_mm": spec["family_mm"],
        "detection_path": spec["detection_path"],
        "curved_face": curved_face,
        "curved_face_label": resolved_label,
        "local_axis_convention": (
            f"{AXIS_NAMES[arc_layout['vertical_axis']]} vertical, "
            f"{'/'.join(AXIS_NAMES[a] for a in arc_layout['footprint_axes'])} curve footprint"
        ),
        "vertical_axis": AXIS_NAMES[arc_layout["vertical_axis"]],
        "frame_local_bounds": arc_layout["bounds"],
        "local_bounds": generated_bounds,
        "generated_local_bounds": generated_bounds,
        "arc_center": arc_layout["center"],
        "arc_radius_m": arc_layout["radius_m"],
        "arc_inner_radius_m": arc_layout["inner_radius_m"],
        "arc_outer_radius_m": arc_layout["outer_radius_m"],
        "arc_centerline_radius_m": arc_layout["centerline_radius_m"],
        "arc_mid_angle_degrees": arc_layout["mid_angle_degrees"],
        "expected_rotation": arc_layout["expected_rotation"],
        "arc_start_angle_degrees": math.degrees(arc_layout["start_angle"]),
        "arc_end_angle_degrees": math.degrees(arc_layout["end_angle"]),
        "arc_sweep_degrees": arc_layout["measured_sweep_degrees"],
        "arc_sweep_source": arc_layout["sweep_source"],
        "arc_nominal_angle_degrees": arc_layout["nominal_angle_degrees"],
        "arc_direction": arc_layout["direction"],
        "arc_fit_score": arc_layout["fit_score"],
        "first_vertex": first_vertex,
        "last_vertex": last_vertex,
        "mesh_segment_count": segment_count,
        "panel_kind": panel_kind,
    })
    # TODO(curved SVG): Export requires arc flattening/unwrapping rules. Do not
    # include these curved meshes in production SVG workflows until that phase is
    # designed and validated.
    return count, details
