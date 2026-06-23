"""
Hard graphic panel placement.

Creates/updates trimmed flat panels, one per frame and per array position
(including two-array grids), parented to the source frame. Behavior, sizing,
offsets, naming and duplicate prevention are unchanged from the single-file
version.
"""

import bpy
from mathutils import Vector

from .utils import (
    mm_to_m,
    is_marked_panel,
    generated_panel_name,
    generated_array_panel_name,
)
from .materials import get_or_create_unique_panel_material
from .array_helpers import (
    get_panel_array_positions,
    remove_generated_array_modifiers,
)


def find_existing_panel(frame_obj, side_label, index_1=None, index_2=None):
    """
    Checks children first. This prevents duplicate generated hard panels.

    Matches on parent frame (we only look at this frame's children), side, and
    BOTH array indices. The second index is None for no-array and one-array
    panels, so those still match cleanly. SEG planes are skipped so a hard-panel
    run never grabs a SEG plane as its "existing" panel.
    """
    for child in frame_obj.children:
        if child.type == "MESH" and is_marked_panel(child):
            if child.get("bematrix_panel_kind") == "SEG":
                continue

            if child.get("bematrix_panel_side") != side_label:
                continue

            if (
                child.get("bematrix_array_index") == index_1
                and child.get("bematrix_array_index_2") == index_2
            ):
                return child

    return None


def delete_stale_array_panels(frame_obj, side_label, valid_keys):
    """
    Deletes generated panels for this side whose (index_1, index_2) key is no
    longer valid.

    `valid_keys` is the set of (index_1, index_2) tuples currently being
    generated. This handles: array count decreasing, switching between one and
    two arrays, and removing the old unsuffixed panel when a frame starts using
    an Array. Returns the list of deleted panel names.
    """
    valid = set(valid_keys)
    deleted_names = []

    for child in list(frame_obj.children):
        if child.type != "MESH" or not is_marked_panel(child):
            continue

        # Never touch SEG planes from the hard-panel path.
        if child.get("bematrix_panel_kind") == "SEG":
            continue

        if child.get("bematrix_panel_side") != side_label:
            continue

        key = (
            child.get("bematrix_array_index"),
            child.get("bematrix_array_index_2"),
        )

        if key not in valid:
            deleted_names.append(child.name)
            bpy.data.objects.remove(child, do_unlink=True)

    return deleted_names


def create_or_update_panel_for_frame(
    frame_obj,
    side_label: str,
    side_offset_mm: float,
    trim_mm: float,
    frame_width_mm: float,
    frame_height_mm: float,
    array_list,
    replace_existing: bool = True,
):
    # Structured result so the operator can print useful console/report output.
    # created/updated entries are (name, (x, y, z)) so locations can be logged.
    details = {
        "frame_name": frame_obj.name,
        "side": side_label,
        "created": [],
        "updated": [],
        "deleted_names": [],
        "panel_count": 0,
        "error": None,
    }

    panel_width_mm = frame_width_mm - trim_mm
    panel_height_mm = frame_height_mm - trim_mm

    if panel_width_mm <= 0 or panel_height_mm <= 0:
        details["error"] = f"Invalid panel size for {frame_obj.name}"
        return 0, details

    panel_width_m = mm_to_m(panel_width_mm)
    panel_height_m = mm_to_m(panel_height_mm)
    y_offset_m = mm_to_m(side_offset_mm)

    half_w = panel_width_m / 2.0
    half_h = panel_height_m / 2.0

    # Mesh lies in the local X/Z plane and is centered at Y = 0. The front/back
    # Y offset is NOT baked into the vertices: it lives in the object location as
    # the base position so the Array Y step is *added* to it (front/back base Y
    # offset + array step Y * index), never overwritten.
    verts = [
        (-half_w, 0.0, -half_h),
        ( half_w, 0.0, -half_h),
        ( half_w, 0.0,  half_h),
        (-half_w, 0.0,  half_h),
    ]

    faces = [(0, 1, 2, 3)]

    # Base panel location for this side: the front/back Y offset. Array steps are
    # added on top of this for each copy.
    base_location = Vector((0.0, y_offset_m, 0.0))

    # array_list was detected once at the frame level by the operator and passed
    # in, so FRONT and BACK stay perfectly in sync. Each panel gets its own
    # unique material inside the loop below.
    array_positions = get_panel_array_positions(frame_obj, array_list)
    valid_keys = {(index_1, index_2) for index_1, index_2, _loc in array_positions}

    details["deleted_names"] = delete_stale_array_panels(
        frame_obj, side_label, valid_keys
    )

    panel_count = 0

    for index_1, index_2, array_step in array_positions:
        if index_1 is None:
            panel_name = generated_panel_name(frame_obj, side_label)
        else:
            panel_name = generated_array_panel_name(
                frame_obj,
                side_label,
                index_1,
                index_2,
            )

        # Final local location = base front/back offset + combined array step.
        # array_step already encodes step1*(i1-1) + step2*(i2-1), so _A001(_B001)
        # sits at the base position.
        final_location = base_location + array_step

        # Unique material per panel object, reused by name on re-runs.
        panel_mat = get_or_create_unique_panel_material(panel_name)

        existing = find_existing_panel(frame_obj, side_label, index_1, index_2)

        if existing and replace_existing:
            mesh = existing.data
            mesh.clear_geometry()
            mesh.from_pydata(verts, [], faces)
            mesh.update()

            panel_obj = existing
            details["updated"].append((panel_name, tuple(final_location), panel_mat.name))
        else:
            details["created"].append((panel_name, tuple(final_location), panel_mat.name))
            mesh = bpy.data.meshes.new(f"{panel_name}_Mesh")
            mesh.from_pydata(verts, [], faces)
            mesh.update()

            panel_obj = bpy.data.objects.new(panel_name, mesh)

            # Link to same collection as the frame if possible.
            if frame_obj.users_collection:
                frame_obj.users_collection[0].objects.link(panel_obj)
            else:
                bpy.context.collection.objects.link(panel_obj)

        # Vertices are authored in frame-local space. Array copies are real
        # child objects offset along the source frame's local axes.
        panel_obj.parent = frame_obj
        panel_obj.matrix_parent_inverse.identity()
        panel_obj.location = final_location
        panel_obj.rotation_euler = (0, 0, 0)
        panel_obj.scale = (1, 1, 1)

        if len(panel_obj.data.materials) == 0:
            panel_obj.data.materials.append(panel_mat)
        else:
            panel_obj.data.materials[0] = panel_mat

        panel_obj.name = panel_name
        panel_obj.data.name = f"{panel_obj.name}_Mesh"

        panel_obj["is_bematrix_panel"] = True
        panel_obj["bematrix_panel_kind"] = "HARD"
        panel_obj["bematrix_parent_frame"] = frame_obj.name
        panel_obj["bematrix_panel_side"] = side_label
        panel_obj["bematrix_frame_width_mm"] = frame_width_mm
        panel_obj["bematrix_frame_height_mm"] = frame_height_mm
        panel_obj["bematrix_panel_width_mm"] = panel_width_mm
        panel_obj["bematrix_panel_height_mm"] = panel_height_mm
        panel_obj["bematrix_trim_mm"] = trim_mm
        panel_obj["bematrix_y_offset_mm"] = side_offset_mm

        # Store both array indices so re-runs match by parent + side + index_1 +
        # index_2. Absent properties read back as None, which is exactly the key
        # used for no-array (None, None) and one-array (i1, None) panels.
        if index_1 is None:
            for key in ("bematrix_array_index", "bematrix_array_index_2",
                        "bematrix_array_count"):
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

        # Old versions copied Array modifiers onto panels. New panels are real
        # per-position objects, so remove only modifiers generated by this tool.
        remove_generated_array_modifiers(panel_obj)

        panel_count += 1

    details["panel_count"] = panel_count
    details["panel_width_mm"] = panel_width_mm
    details["panel_height_mm"] = panel_height_mm

    return panel_count, details
