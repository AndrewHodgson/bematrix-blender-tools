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
    match = re.search(
        r"\bB(?P<depth>\d{2,3})_(?P<family>\d{4})_CURVE_"
        r"(?P<angle>\d+(?:[pP]\d+)?)_H(?P<height>\d{3,4})\b",
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


def _sample_arc_offsets(radius_m, start_angle, end_angle, segment_count):
    offsets = []
    for i in range(segment_count + 1):
        t = i / segment_count
        theta = start_angle + (end_angle - start_angle) * t
        offsets.append((radius_m * math.cos(theta), radius_m * math.sin(theta)))
    return offsets


def _fit_arc_to_bounds(bounds, radius_m, angle_degrees, segment_count):
    """
    Find the circular arc orientation whose sampled footprint best matches the
    selected frame object's local X/Y bounding box.

    This keeps curved generation tied to the actual asset footprint instead of
    assuming the arc center is at local origin or applying arbitrary offsets.
    """
    angle_rad = math.radians(angle_degrees)
    candidates = []
    for base_degrees in (0.0, 90.0, 180.0, 270.0):
        base_angle = math.radians(base_degrees)
        for direction in (1.0, -1.0):
            start_angle = base_angle
            end_angle = base_angle + direction * angle_rad
            offsets = _sample_arc_offsets(radius_m, start_angle, end_angle, segment_count)
            min_off_x = min(x for x, _y in offsets)
            max_off_x = max(x for x, _y in offsets)
            min_off_y = min(y for _x, y in offsets)
            max_off_y = max(y for _x, y in offsets)

            center_x_from_min = bounds["min_x"] - min_off_x
            center_x_from_max = bounds["max_x"] - max_off_x
            center_y_from_min = bounds["min_y"] - min_off_y
            center_y_from_max = bounds["max_y"] - max_off_y
            center_x = (center_x_from_min + center_x_from_max) / 2.0
            center_y = (center_y_from_min + center_y_from_max) / 2.0

            pred_min_x = center_x + min_off_x
            pred_max_x = center_x + max_off_x
            pred_min_y = center_y + min_off_y
            pred_max_y = center_y + max_off_y
            score = (
                abs(pred_min_x - bounds["min_x"])
                + abs(pred_max_x - bounds["max_x"])
                + abs(pred_min_y - bounds["min_y"])
                + abs(pred_max_y - bounds["max_y"])
                + abs(center_x_from_min - center_x_from_max)
                + abs(center_y_from_min - center_y_from_max)
            )
            candidates.append({
                "score": score,
                "center": (center_x, center_y),
                "start_angle": start_angle,
                "end_angle": end_angle,
                "direction": "counterclockwise" if direction > 0.0 else "clockwise",
            })

    return min(candidates, key=lambda item: item["score"])


def _compute_curved_arc_layout(frame_obj, spec, curved_face, panel_width_mm, segment_count):
    """
    Return the local-space arc used by the generated curved panel.

    The side-specific panel radius comes from the BeMatrix infill width table.
    The arc center and sweep are fitted from the frame's local bounding box using
    the outside radius, then reused for inside/outside so both faces share the
    same real curved-frame footprint.
    """
    bounds = _local_bounds(frame_obj)
    angle_rad = math.radians(spec["angle_degrees"])
    radius_m = mm_to_m(panel_width_mm) / angle_rad if angle_rad > 1e-9 else mm_to_m(panel_width_mm)
    outside_radius_m = (
        mm_to_m(spec["outside_panel_width_mm"]) / angle_rad
        if angle_rad > 1e-9 else mm_to_m(spec["outside_panel_width_mm"])
    )
    fit = _fit_arc_to_bounds(bounds, outside_radius_m, spec["angle_degrees"], segment_count)
    return {
        "bounds": bounds,
        "center": fit["center"],
        "radius_m": radius_m,
        "orientation_radius_m": outside_radius_m,
        "start_angle": fit["start_angle"],
        "end_angle": fit["end_angle"],
        "direction": fit["direction"],
        "fit_score": fit["score"],
        "z_center": (bounds["min_z"] + bounds["max_z"]) / 2.0,
    }


def _curved_mesh_data(panel_height_mm, arc_layout, curved_face, segment_count):
    """
    Build a vertical curved strip in frame-local space from a fitted arc.

    X/Y follow the selected curved frame footprint. Z is centered on the frame's
    local bounding box so assets with a bottom-origin do not place panels below
    the frame.
    """
    panel_height_m = mm_to_m(panel_height_mm)
    half_h = panel_height_m / 2.0
    center_x, center_y = arc_layout["center"]
    radius_m = arc_layout["radius_m"]
    start_angle = arc_layout["start_angle"]
    end_angle = arc_layout["end_angle"]
    z_center = arc_layout["z_center"]

    verts = []
    uvs = []
    for i in range(segment_count + 1):
        t = i / segment_count
        theta = start_angle + (end_angle - start_angle) * t
        x = center_x + radius_m * math.cos(theta)
        y = center_y + radius_m * math.sin(theta)
        verts.append((x, y, z_center - half_h))
        verts.append((x, y, z_center + half_h))
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
            faces.append((a, a + 2, a + 3, a + 1))
        else:
            faces.append((a, a + 1, a + 3, a + 2))

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
        panel_width_mm,
        segment_count,
    )
    verts, faces, uvs = _curved_mesh_data(
        panel_height_mm,
        arc_layout,
        curved_face,
        segment_count,
    )
    first_vertex = verts[0] if verts else None
    last_vertex = verts[-2] if len(verts) >= 2 else None

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
        count += 1

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
        "local_bounds": arc_layout["bounds"],
        "arc_center": arc_layout["center"],
        "arc_radius_m": arc_layout["radius_m"],
        "arc_orientation_radius_m": arc_layout["orientation_radius_m"],
        "arc_start_angle_degrees": math.degrees(arc_layout["start_angle"]),
        "arc_end_angle_degrees": math.degrees(arc_layout["end_angle"]),
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
