"""
SEG fabric placement.

This module has two SEG strategies:

* `create_smart_seg_panel` (current SEG behavior) — builds ONE SEG fabric mesh
  object per side across the selected frames. Each frame (and each of its array
  instances) becomes one rectangular SEG cell on the frame's OUTSIDE face at
  +-32 mm local Y. Cells are grouped by plane (coplanar): a straight wall or
  in-plane array/grid becomes one connected planar section, while a rotated
  frame / 90-degree corner becomes a SEPARATE planar section in the SAME object,
  so the fabric bends at the corner instead of stretching across it. UVs are
  computed per section in that section's own plane, so rotated sections unwrap
  cleanly.

* `create_or_update_seg_for_frame` (legacy, kept for reference) — the older
  per-frame plane approach that combined X arrays into rows. The operator no
  longer calls this; it is superseded by the smart builder.
"""

import math

import bpy
from mathutils import Vector, Matrix

from .utils import (
    mm_to_m,
    is_marked_panel,
    generated_seg_name,
    get_frame_size_mm,
    strip_blender_duplicate_suffix,
)
from .materials import get_or_create_unique_panel_material
from .array_helpers import (
    get_array_step_m,
    get_panel_array_positions,
    detect_all_array_settings,
    remove_generated_array_modifiers,
)


# Smart SEG (one mesh object per side across selected frames).
SMART_SEG_NAME = "SEG_Fabric_Panel"
SMART_SEG_KIND = "SEG_SMART"


def _seg_cells_for_frame(frame_obj, side_label, side_offset_mm):
    """
    Build the SEG cell(s) for one frame, EXPANDING any supported Array modifiers
    into instances (same array-position math as the graphic panels).

    Returns (cells, (width_mm, height_mm)) where each cell is a dict with:
        frame        source frame name
        index_1/2    array indices (or None)
        corners      4 world-space corners (BL, BR, TR, TL) of the outside face
        normal       unit world-space outward face normal

    The SEG face uses the FULL frame size (no trim) and sits at `side_offset_mm`
    along the frame's LOCAL Y, transformed by each instance's world matrix so
    rotation, position and depth are respected per frame.
    """
    size = get_frame_size_mm(frame_obj)
    if not size:
        return [], None

    width_mm, height_mm = size
    half_w = mm_to_m(width_mm) / 2.0
    half_h = mm_to_m(height_mm) / 2.0
    y = mm_to_m(side_offset_mm)

    local_corners = (
        Vector((-half_w, y, -half_h)),  # bottom-left
        Vector(( half_w, y, -half_h)),  # bottom-right
        Vector(( half_w, y,  half_h)),  # top-right
        Vector((-half_w, y,  half_h)),  # top-left
    )
    # Outward normal: FRONT face -> local -Y, BACK face -> local +Y.
    normal_local = (
        Vector((0.0, -1.0, 0.0)) if side_label == "FRONT"
        else Vector((0.0, 1.0, 0.0))
    )

    # Expand arrays into instance offsets (local). No array -> a single cell.
    array_list = detect_all_array_settings(frame_obj, limit=2)
    positions = get_panel_array_positions(frame_obj, array_list)

    cells = []
    for index_1, index_2, offset in positions:
        cell_matrix = frame_obj.matrix_world @ Matrix.Translation(offset)
        rotation = cell_matrix.to_3x3()
        corners = [cell_matrix @ corner for corner in local_corners]
        normal = rotation @ normal_local
        if normal.length > 1e-9:
            normal = normal.normalized()
        cells.append({
            "frame": frame_obj.name,
            "index_1": index_1,
            "index_2": index_2,
            "corners": corners,
            "normal": normal,
        })

    return cells, (width_mm, height_mm)


def _plane_key(normal, point, normal_round=3, dist_round=3):
    """
    Key that is equal for coplanar cells: rounded unit normal plus the rounded
    signed plane distance (normal . point). Cells on the same outside plane share
    this key; a rotated/corner frame gets a different key and becomes its own
    planar section.
    """
    nkey = (round(normal.x, normal_round),
            round(normal.y, normal_round),
            round(normal.z, normal_round))
    dist = round(normal.dot(point), dist_round)
    return (nkey, dist)


def create_smart_seg_panel(context, frames, side_label, side_offset_mm,
                           replace_existing=True):
    """
    Build ONE SEG fabric mesh object per side across the given frames.

    * Each frame (and each array instance) is a rectangular SEG cell on the
      frame's outside face at +-32 mm local Y, using the full frame size.
    * Cells are grouped by PLANE: coplanar, touching cells weld into one
      connected planar section (a straight wall or in-plane array/grid becomes a
      large flat section). A rotated frame / 90-degree corner has a different
      face normal, so it becomes a SEPARATE planar section in the SAME object —
      the fabric bends at the corner instead of stretching across it.
    * Empty grid spaces stay empty (only real cells get a quad).
    * The mesh is built in the MAIN frame's local space and PARENTED to it, so it
      follows the frames and works when the whole group is rotated. The main
      frame is the active selected frame (else the first).
    * UVs are real-world planar coordinates (meters) computed PER SECTION in that
      section's own plane, so rotated sections unwrap cleanly; sections are
      packed side-by-side in U so they do not overlap.

    Re-running with the same main frame updates that frame's SEG mesh; a
    different selection (different main frame) makes a separate object.

    Returns (object_or_None, info_dict).
    """
    info = {"quad_count": 0, "vert_count": 0, "skipped": 0,
            "section_count": 0, "error": None}

    if not frames:
        info["error"] = "no frames"
        return None, info

    active = context.view_layer.objects.active
    main_frame = active if (active is not None and active in frames) else frames[0]
    main_inv = main_frame.matrix_world.inverted()

    print(f"\n  --- SMART SEG [{side_label}] (offset {side_offset_mm} mm) ---")
    print(f"  Main frame: {main_frame.name}")

    # Collect cells (array-expanded) for all frames + their world face data.
    all_cells = []
    frame_dims_m = []
    for frame_obj in frames:
        cells, dims_mm = _seg_cells_for_frame(frame_obj, side_label, side_offset_mm)
        if not cells:
            info["skipped"] += 1
            print(f"  Frame '{frame_obj.name}': no detectable size - skipped.")
            continue
        frame_dims_m += [mm_to_m(dims_mm[0]), mm_to_m(dims_mm[1])]
        mw = frame_obj.matrix_world
        loc = mw.to_translation()
        rot = mw.to_euler()
        print(
            f"  Frame '{frame_obj.name}': loc="
            f"{tuple(round(v, 3) for v in loc)} rotXYZ_deg="
            f"{tuple(round(math.degrees(a), 1) for a in rot)} "
            f"cells(array-expanded)={len(cells)}"
        )
        for cell in cells:
            print(
                f"      cell A{cell['index_1']}/B{cell['index_2']} "
                f"normal={tuple(round(v, 3) for v in cell['normal'])} "
                f"corners={[tuple(round(v, 3) for v in c) for c in cell['corners']]}"
            )
        all_cells.extend(cells)

    if not all_cells:
        info["error"] = "no valid frame cells"
        return None, info

    weld_tol = max(1e-4, 0.1 * min(frame_dims_m))

    # Group cells into coplanar sections.
    groups = {}
    for cell in all_cells:
        key = _plane_key(cell["normal"], cell["corners"][0])
        groups.setdefault(key, []).append(cell)
    print(f"  Coplanar sections: {len(groups)}")

    verts = []        # main-frame-local positions
    vert_uv = []      # one UV per vertex (no cross-section sharing)
    faces = []
    u_cursor = 0.0
    uv_gap = max(0.02, 0.05 * min(frame_dims_m))

    for section_i, (key, cells) in enumerate(groups.items(), start=1):
        # 2D basis for this section's plane, recovered from the first cell's
        # corners: edge BL->BR is U (frame width), BL->TL is V (frame height).
        sample_normal, sample_dist = key
        c = cells[0]["corners"]
        u_axis = (c[1] - c[0])
        v_axis = (c[3] - c[0])
        u_axis = u_axis.normalized() if u_axis.length > 1e-9 else Vector((1.0, 0.0, 0.0))
        v_axis = v_axis.normalized() if v_axis.length > 1e-9 else Vector((0.0, 0.0, 1.0))

        # Section UV origin = min projection over its corners.
        proj_u = [corner.dot(u_axis) for cell in cells for corner in cell["corners"]]
        proj_v = [corner.dot(v_axis) for cell in cells for corner in cell["corners"]]
        min_u, max_u = min(proj_u), max(proj_u)
        min_v = min(proj_v)
        section_width_u = max_u - min_u

        # Weld within this section only (clean bends between sections).
        sec_positions = []   # local positions for tolerance search
        sec_indices = []     # parallel global vertex indices

        def section_weld(local_point, world_corner):
            for j, existing in enumerate(sec_positions):
                if (local_point - existing).length <= weld_tol:
                    return sec_indices[j]
            gi = len(verts)
            verts.append(local_point)
            vert_uv.append((
                world_corner.dot(u_axis) - min_u + u_cursor,
                world_corner.dot(v_axis) - min_v,
            ))
            sec_positions.append(local_point)
            sec_indices.append(gi)
            return gi

        for cell in cells:
            idx = [
                section_weld(main_inv @ corner, corner)
                for corner in cell["corners"]
            ]
            # Winding for outward normal: FRONT -> local -Y, BACK reversed.
            if side_label == "BACK":
                faces.append((idx[0], idx[3], idx[2], idx[1]))
            else:
                faces.append((idx[0], idx[1], idx[2], idx[3]))

        print(
            f"    Section {section_i}: normal={sample_normal} dist={sample_dist} "
            f"cells={len(cells)} frames="
            f"{sorted({cell['frame'] for cell in cells})}"
        )
        u_cursor += section_width_u + uv_gap

    if not faces:
        info["error"] = "no valid frame cells"
        return None, info

    clean_main = strip_blender_duplicate_suffix(main_frame.name)
    obj_name = f"{SMART_SEG_NAME}_{side_label}_{clean_main}"
    mesh = bpy.data.meshes.new(f"{obj_name}_Mesh")
    mesh.from_pydata([tuple(v) for v in verts], [], [list(f) for f in faces])
    mesh.update(calc_edges=True)

    uv_layer = mesh.uv_layers.new(name="UVMap")
    for poly in mesh.polygons:
        for loop_i in poly.loop_indices:
            vi = mesh.loops[loop_i].vertex_index
            uv_layer.data[loop_i].uv = vert_uv[vi]

    # Find this main frame's existing SEG mesh for this side (update, no dup).
    existing = None
    for child in main_frame.children:
        if (
            child.type == "MESH"
            and is_marked_panel(child)
            and child.get("bematrix_panel_kind") == SMART_SEG_KIND
            and child.get("bematrix_panel_side") == side_label
        ):
            existing = child
            break

    if existing is not None and replace_existing:
        obj = existing
        old_mesh = obj.data
        obj.data = mesh
        if old_mesh is not None and old_mesh.users == 0:
            bpy.data.meshes.remove(old_mesh)
        info["created"] = False
    else:
        obj = bpy.data.objects.new(obj_name, mesh)
        target_coll = None
        if main_frame.users_collection:
            target_coll = main_frame.users_collection[0]
        (target_coll or context.collection).objects.link(obj)
        info["created"] = True

    # Parent to the main frame; identity local transform places the local-space
    # mesh exactly and makes it follow the frame.
    obj.parent = main_frame
    obj.matrix_parent_inverse = Matrix.Identity(4)
    obj.location = (0.0, 0.0, 0.0)
    obj.rotation_euler = (0.0, 0.0, 0.0)
    obj.scale = (1.0, 1.0, 1.0)

    seg_mat = get_or_create_unique_panel_material(obj_name)
    if len(obj.data.materials) == 0:
        obj.data.materials.append(seg_mat)
    else:
        obj.data.materials[0] = seg_mat

    obj["is_bematrix_panel"] = True
    obj["bematrix_panel_kind"] = SMART_SEG_KIND
    obj["bematrix_panel_side"] = side_label
    obj["bematrix_smart_seg"] = True
    obj["bematrix_seg_cell_count"] = len(faces)
    obj["bematrix_seg_section_count"] = len(groups)
    obj["bematrix_y_offset_mm"] = side_offset_mm
    obj["bematrix_parent_frame"] = main_frame.name

    dims = tuple(round(v, 4) for v in obj.dimensions)
    print(
        f"  -> object '{obj.name}': cells={len(faces)} sections={len(groups)} "
        f"verts={len(verts)} dims(local m)={dims}"
    )

    info["quad_count"] = len(faces)
    info["vert_count"] = len(verts)
    info["section_count"] = len(groups)
    info["object"] = obj.name
    info["material"] = seg_mat.name
    info["main_frame"] = main_frame.name
    return obj, info


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
