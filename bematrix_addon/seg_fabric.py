"""
SEG fabric plane placement.

SEG planes differ from hard panels: they use the full frame size (no trim),
combine an X array into one continuous plane across the whole run, make one
plane per Z row for an X/Z grid, and sit 1 mm outside the hard-panel offsets.

NOTE: SEG is intentionally left as-is by this refactor (it is not yet fully
working). This module is a straight extraction of the existing SEG logic.
"""

import bpy
from mathutils import Vector

from .utils import (
    mm_to_m,
    is_marked_panel,
    generated_seg_name,
)
from .materials import get_or_create_unique_panel_material
from .array_helpers import (
    get_array_step_m,
    remove_generated_array_modifiers,
)


def find_existing_seg(frame_obj, side_label, row_index):
    """Find an existing SEG plane by parent frame, side, and row index."""
    for child in frame_obj.children:
        if child.type != "MESH" or not is_marked_panel(child):
            continue
        if child.get("bematrix_panel_kind") != "SEG":
            continue
        if child.get("bematrix_panel_side") != side_label:
            continue
        if child.get("bematrix_seg_row") == row_index:
            return child

    return None


def delete_stale_seg_panels(frame_obj, side_label, valid_rows):
    """
    Deletes SEG planes for this side whose row index is no longer valid (e.g.
    the Z array row count decreased). Only touches SEG planes. Returns the list
    of deleted names.
    """
    valid = set(valid_rows)
    deleted_names = []

    for child in list(frame_obj.children):
        if child.type != "MESH" or not is_marked_panel(child):
            continue

        if child.get("bematrix_panel_kind") != "SEG":
            continue

        if child.get("bematrix_panel_side") != side_label:
            continue

        if child.get("bematrix_seg_row") not in valid:
            deleted_names.append(child.name)
            bpy.data.objects.remove(child, do_unlink=True)

    return deleted_names


def classify_seg_arrays(frame_obj, array_list):
    """
    For SEG fabric, classify the (up to two) arrays into an X "column" run and a
    Z "row" stack by their dominant step axis.

    Returns (x_count, x_step, z_count, z_step) where the steps are full Vectors
    in meters. Defaults are count 1 / zero step when an axis has no array. Arrays
    that are dominantly along Y, or that have no real offset, are ignored for
    SEG (a fabric graphic does not tile in depth).
    """
    x_count, x_step = 1, Vector((0.0, 0.0, 0.0))
    z_count, z_step = 1, Vector((0.0, 0.0, 0.0))

    for settings in array_list:
        step = get_array_step_m(frame_obj, settings)

        axis = max(range(3), key=lambda i: abs(step[i]))
        if abs(step[axis]) < 1e-6:
            continue  # No real offset; nothing to combine.

        if axis == 0 and x_count == 1:
            x_count, x_step = settings.count, step
        elif axis == 2 and z_count == 1:
            z_count, z_step = settings.count, step
        # axis == 1 (Y) is intentionally ignored for SEG.

    return x_count, x_step, z_count, z_step


def create_or_update_seg_for_frame(
    frame_obj,
    side_label: str,
    side_offset_mm: float,
    frame_width_mm: float,
    frame_height_mm: float,
    array_list,
    replace_existing: bool = True,
):
    """
    Create/update SEG fabric planes for one frame and side.

    SEG differs from hard panels:
      * size uses the FULL frame size (no trim),
      * an X array is combined into ONE continuous plane across the whole run,
      * a two-array X/Z grid makes one plane PER Z ROW (full X span x one frame
        tall),
      * default offsets sit 1 mm outside the hard panel (-32 / +32 mm).
    """
    details = {
        "frame_name": frame_obj.name,
        "side": side_label,
        "created": [],
        "updated": [],
        "deleted_names": [],
        "panel_count": 0,
        "error": None,
    }

    # SEG uses the full frame size, NOT frame size minus trim.
    if frame_width_mm <= 0 or frame_height_mm <= 0:
        details["error"] = f"Invalid SEG size for {frame_obj.name}"
        return 0, details

    x_count, x_step, z_count, z_step = classify_seg_arrays(frame_obj, array_list)

    frame_width_m = mm_to_m(frame_width_mm)
    frame_height_m = mm_to_m(frame_height_mm)
    y_offset_m = mm_to_m(side_offset_mm)

    # One continuous plane across the X run: edge-to-edge width.
    seg_width_m = (x_count - 1) * abs(x_step.x) + frame_width_m
    seg_height_m = frame_height_m  # one frame tall per row

    half_w = seg_width_m / 2.0
    half_h = seg_height_m / 2.0

    verts = [
        (-half_w, 0.0, -half_h),
        ( half_w, 0.0, -half_h),
        ( half_w, 0.0,  half_h),
        (-half_w, 0.0,  half_h),
    ]
    faces = [(0, 1, 2, 3)]

    base_location = Vector((0.0, y_offset_m, 0.0))
    # The plane is centered on the X run midpoint: frame centers run from 0 to
    # (x_count - 1) * x_step, so the midpoint is half of that.
    x_run_center = x_step * ((x_count - 1) / 2.0)

    valid_rows = set(range(1, z_count + 1))
    details["deleted_names"] = delete_stale_seg_panels(
        frame_obj, side_label, valid_rows
    )

    seg_width_mm = seg_width_m * 1000.0
    seg_height_mm = seg_height_m * 1000.0

    panel_count = 0

    for row in range(z_count):
        row_index = row + 1
        seg_name = generated_seg_name(frame_obj, side_label, row_index)

        # Center of this row's plane: base + X run midpoint + this row's Z step.
        final_location = base_location + x_run_center + z_step * row

        seg_mat = get_or_create_unique_panel_material(seg_name)

        existing = find_existing_seg(frame_obj, side_label, row_index)

        if existing and replace_existing:
            mesh = existing.data
            mesh.clear_geometry()
            mesh.from_pydata(verts, [], faces)
            mesh.update()

            seg_obj = existing
            details["updated"].append((seg_name, tuple(final_location), seg_mat.name))
        else:
            details["created"].append((seg_name, tuple(final_location), seg_mat.name))
            mesh = bpy.data.meshes.new(f"{seg_name}_Mesh")
            mesh.from_pydata(verts, [], faces)
            mesh.update()

            seg_obj = bpy.data.objects.new(seg_name, mesh)

            if frame_obj.users_collection:
                frame_obj.users_collection[0].objects.link(seg_obj)
            else:
                bpy.context.collection.objects.link(seg_obj)

        seg_obj.parent = frame_obj
        seg_obj.matrix_parent_inverse.identity()
        seg_obj.location = final_location
        seg_obj.rotation_euler = (0, 0, 0)
        seg_obj.scale = (1, 1, 1)

        if len(seg_obj.data.materials) == 0:
            seg_obj.data.materials.append(seg_mat)
        else:
            seg_obj.data.materials[0] = seg_mat

        seg_obj.name = seg_name
        seg_obj.data.name = f"{seg_obj.name}_Mesh"

        seg_obj["is_bematrix_panel"] = True
        seg_obj["bematrix_panel_kind"] = "SEG"
        seg_obj["bematrix_parent_frame"] = frame_obj.name
        seg_obj["bematrix_panel_side"] = side_label
        seg_obj["bematrix_seg_row"] = row_index
        seg_obj["bematrix_seg_row_count"] = z_count
        seg_obj["bematrix_seg_x_count"] = x_count
        seg_obj["bematrix_frame_width_mm"] = frame_width_mm
        seg_obj["bematrix_frame_height_mm"] = frame_height_mm
        seg_obj["bematrix_seg_width_mm"] = seg_width_mm
        seg_obj["bematrix_seg_height_mm"] = seg_height_mm
        seg_obj["bematrix_y_offset_mm"] = side_offset_mm

        remove_generated_array_modifiers(seg_obj)

        panel_count += 1

    details["panel_count"] = panel_count
    details["seg_width_mm"] = seg_width_mm
    details["seg_height_mm"] = seg_height_mm

    return panel_count, details
