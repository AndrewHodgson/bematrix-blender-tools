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
    get_frame_depth_mm,
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


def _seg_cell_corners(half_w, half_h, y):
    """Four local corners (BL, BR, TR, TL) of a SEG cell at depth offset y."""
    return (
        Vector((-half_w, y, -half_h)),  # bottom-left
        Vector(( half_w, y, -half_h)),  # bottom-right
        Vector(( half_w, y,  half_h)),  # top-right
        Vector((-half_w, y,  half_h)),  # top-left
    )


def _section_boundary_edges(section_faces):
    """
    Outline edges of a section: edges used by exactly one face. Returned as
    (vert_index_a, vert_index_b) tuples.
    """
    counts = {}
    for face in section_faces:
        n = len(face)
        for k in range(n):
            edge = frozenset((face[k], face[(k + 1) % n]))
            counts[edge] = counts.get(edge, 0) + 1
    return [tuple(edge) for edge, c in counts.items() if c == 1]


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
            "section_count": 0, "bridge_count": 0, "mitre_count": 0,
            "error": None}

    if not frames:
        info["error"] = "no frames"
        return None, info

    active = context.view_layer.objects.active
    main_frame = active if (active is not None and active in frames) else frames[0]
    main_inv = main_frame.matrix_world.inverted()
    offset_m = mm_to_m(abs(side_offset_mm))

    print(f"\n  --- SMART SEG [{side_label}] (offset +-{abs(side_offset_mm)} mm) ---")
    print(f"  Main frame: {main_frame.name}")

    # Pass 1: per-frame data + all cell centres for the group centroid.
    frame_data = []      # (frame, (w_mm, h_mm), [(i1, i2, offset), ...])
    centers = []
    frame_dims_m = []
    depth_m_vals = []
    for frame_obj in frames:
        size = get_frame_size_mm(frame_obj)
        if not size:
            info["skipped"] += 1
            print(f"  Frame '{frame_obj.name}': no detectable size - skipped.")
            continue
        array_list = detect_all_array_settings(frame_obj, limit=2)
        positions = get_panel_array_positions(frame_obj, array_list)
        frame_data.append((frame_obj, size, positions))
        frame_dims_m += [mm_to_m(size[0]), mm_to_m(size[1])]
        depth_mm, _src = get_frame_depth_mm(frame_obj)
        depth_m_vals.append(mm_to_m(depth_mm))
        for _i1, _i2, offset in positions:
            centers.append(frame_obj.matrix_world @ offset)

    if not frame_data or not centers:
        info["error"] = "no valid frame cells"
        return None, info

    centroid = Vector((0.0, 0.0, 0.0))
    for c in centers:
        centroid += c
    centroid /= len(centers)
    eps = 0.02 * min(frame_dims_m)
    print(f"  Group centroid (world): {tuple(round(v, 3) for v in centroid)}")

    # Pass 2: build cells, choosing the OUTSIDE face per frame from the centroid.
    all_cells = []
    for frame_obj, size, positions in frame_data:
        width_mm, height_mm = size
        half_w = mm_to_m(width_mm) / 2.0
        half_h = mm_to_m(height_mm) / 2.0
        rot = frame_obj.matrix_world.to_3x3()
        y_world = rot @ Vector((0.0, 1.0, 0.0))
        y_world = y_world.normalized() if y_world.length > 1e-9 else Vector((0.0, 1.0, 0.0))
        eul = frame_obj.matrix_world.to_euler()
        print(
            f"  Frame '{frame_obj.name}': loc="
            f"{tuple(round(v, 3) for v in frame_obj.matrix_world.to_translation())} "
            f"rotXYZ_deg={tuple(round(math.degrees(a), 1) for a in eul)} "
            f"cells={len(positions)}"
        )
        for index_1, index_2, offset in positions:
            cell_matrix = frame_obj.matrix_world @ Matrix.Translation(offset)
            center = cell_matrix.to_translation()
            # Which local-Y direction points AWAY from the group centroid?
            d = y_world.dot(centroid - center)
            if d > eps:
                outside_sign = -1.0   # +Y points toward centre -> outside is -Y
            elif d < -eps:
                outside_sign = 1.0
            else:
                outside_sign = -1.0   # coplanar / ambiguous -> default front = -Y
            # Front = outside face, Back = inside face.
            y_sign = -outside_sign if side_label == "BACK" else outside_sign
            y = y_sign * offset_m

            corners = [cell_matrix @ c for c in _seg_cell_corners(half_w, half_h, y)]
            normal = rot @ Vector((0.0, y_sign, 0.0))
            normal = normal.normalized() if normal.length > 1e-9 else normal
            all_cells.append({
                "frame": frame_obj.name,
                "index_1": index_1,
                "index_2": index_2,
                "corners": corners,
                "normal": normal,
                "y_sign": y_sign,
            })
            print(
                f"      cell A{index_1}/B{index_2} y_sign={int(y_sign)} "
                f"normal={tuple(round(v, 3) for v in normal)}"
            )

    weld_tol = max(1e-4, 0.1 * min(frame_dims_m))

    # Group cells into coplanar sections.
    groups = {}
    for cell in all_cells:
        key = _plane_key(cell["normal"], cell["corners"][0])
        groups.setdefault(key, []).append(cell)
    print(f"  Coplanar sections: {len(groups)}")

    verts = []             # main-frame-local positions
    vert_uv = []           # one UV per vertex
    faces = []
    section_faces = []     # face tuples per section (for boundary edges)
    section_normals = []   # world normal per section
    section_uv_axes = []    # world-space planar UV basis per section
    u_cursor = 0.0
    uv_gap = max(0.02, 0.05 * min(frame_dims_m))

    for section_i, (key, cells) in enumerate(groups.items(), start=1):
        c0 = cells[0]["corners"]
        u_axis = c0[1] - c0[0]
        v_axis = c0[3] - c0[0]
        u_axis = u_axis.normalized() if u_axis.length > 1e-9 else Vector((1.0, 0.0, 0.0))
        v_axis = v_axis.normalized() if v_axis.length > 1e-9 else Vector((0.0, 0.0, 1.0))

        proj_u = [corner.dot(u_axis) for cell in cells for corner in cell["corners"]]
        proj_v = [corner.dot(v_axis) for cell in cells for corner in cell["corners"]]
        min_u, max_u = min(proj_u), max(proj_u)
        min_v = min(proj_v)
        section_width_u = max_u - min_u

        sec_positions = []
        sec_indices = []

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

        this_section_faces = []
        for cell in cells:
            idx = [section_weld(main_inv @ corner, corner) for corner in cell["corners"]]
            # Winding so the face normal follows the cell's outward y_sign.
            if cell["y_sign"] > 0:
                face = (idx[0], idx[3], idx[2], idx[1])
            else:
                face = (idx[0], idx[1], idx[2], idx[3])
            faces.append(face)
            this_section_faces.append(face)

        section_faces.append(this_section_faces)
        section_normals.append(cells[0]["normal"])
        section_uv_axes.append((u_axis, v_axis))
        print(
            f"    Section {section_i}: normal={key[0]} dist={key[1]} "
            f"cells={len(cells)} frames={sorted({cell['frame'] for cell in cells})}"
        )
        u_cursor += section_width_u + uv_gap

    if not faces:
        info["error"] = "no valid frame cells"
        return None, info

    # --- Corner mitres: extend perpendicular sections to their shared corner
    # line so the fabric meets cleanly at the outer corner. This wraps the frame
    # depth at 90 degrees instead of cutting a diagonal end-cap that clips the
    # metal.
    avg_depth = (sum(depth_m_vals) / len(depth_m_vals)) if depth_m_vals else mm_to_m(62.0)
    corner_reach = avg_depth + 2.0 * offset_m + 0.05  # max corner gap to close
    main_rot_inv = main_inv.to_3x3()

    # Section normals + plane offsets in the mesh's local space.
    sec_n_local = []
    sec_d_local = []
    for idx in range(len(section_faces)):
        n_local = main_rot_inv @ section_normals[idx]
        n_local = n_local.normalized() if n_local.length > 1e-9 else n_local
        rep = verts[section_faces[idx][0][0]]
        sec_n_local.append(n_local)
        sec_d_local.append(n_local.dot(rep))

    def _extend_section_to_plane(sec_idx, n_self, n_other, d_other, corner_dir):
        """Slide the near boundary edges of a section onto another section's
        plane (within its own plane), so the two faces reach the corner line."""
        moved = 0
        for e0, e1 in _section_boundary_edges(section_faces[sec_idx]):
            p0, p1 = verts[e0], verts[e1]
            edge = p1 - p0
            if edge.length < 1e-9:
                continue
            edge_n = edge.normalized()
            if abs(edge_n.dot(corner_dir)) < 0.9:
                continue  # only edges running along the corner line
            mid = (p0 + p1) / 2.0
            if abs(n_other.dot(mid) - d_other) > corner_reach:
                continue  # only the near side (close to the other plane)
            perp = edge_n.cross(n_self)
            if perp.length < 1e-9:
                continue
            perp = perp.normalized()
            denom = n_other.dot(perp)
            if abs(denom) < 1e-6:
                continue  # cannot reach the other plane in-plane
            for vi in (e0, e1):
                s = (d_other - n_other.dot(verts[vi])) / denom
                verts[vi] = verts[vi] + perp * s
            moved += 1
        return moved

    corner_count = 0
    for i in range(len(section_faces)):
        for j in range(i + 1, len(section_faces)):
            ni, nj = sec_n_local[i], sec_n_local[j]
            if ni.length < 1e-9 or nj.length < 1e-9:
                continue
            if abs(ni.dot(nj)) > 0.866:
                continue  # parallel / opposite walls: not a corner

            corner_dir = ni.cross(nj)
            if corner_dir.length < 1e-9:
                continue
            corner_dir = corner_dir.normalized()

            # Confirm the two sections actually meet at a corner (their nearest
            # boundary edges are within reach), not just share infinite planes.
            best_gap = None
            for a0, a1 in _section_boundary_edges(section_faces[i]):
                ma = (verts[a0] + verts[a1]) / 2.0
                for b0, b1 in _section_boundary_edges(section_faces[j]):
                    mb = (verts[b0] + verts[b1]) / 2.0
                    g = (ma - mb).length
                    if best_gap is None or g < best_gap:
                        best_gap = g
            if best_gap is None or best_gap > corner_reach:
                continue

            m1 = _extend_section_to_plane(i, ni, nj, sec_d_local[j], corner_dir)
            m2 = _extend_section_to_plane(j, nj, ni, sec_d_local[i], corner_dir)
            corner_count += 1
            print(
                f"    Corner mitre: section {i + 1} <-> {j + 1} "
                f"gap={round(best_gap, 4)} m edges_extended={m1 + m2}"
            )

    if corner_count:
        print(f"  Corner mitres applied: {corner_count}")

    # Vertices may have been moved by corner mitres. Recompute per-section UVs
    # from the final geometry so the extended edge keeps real-world scale and
    # does not inherit stale coordinates from the original exact-size cell.
    u_cursor = 0.0
    for sec_idx, faces_in_section in enumerate(section_faces):
        section_vertex_indices = sorted({vi for face in faces_in_section for vi in face})
        u_axis, v_axis = section_uv_axes[sec_idx]
        world_points = {
            vi: main_frame.matrix_world @ verts[vi]
            for vi in section_vertex_indices
        }
        proj_u = [p.dot(u_axis) for p in world_points.values()]
        proj_v = [p.dot(v_axis) for p in world_points.values()]
        min_u, max_u = min(proj_u), max(proj_u)
        min_v = min(proj_v)
        for vi, world_point in world_points.items():
            vert_uv[vi] = (
                world_point.dot(u_axis) - min_u + u_cursor,
                world_point.dot(v_axis) - min_v,
            )
        u_cursor += (max_u - min_u) + uv_gap

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
    obj["bematrix_seg_bridge_count"] = corner_count
    obj["bematrix_seg_mitre_count"] = corner_count
    obj["bematrix_y_offset_mm"] = side_offset_mm
    obj["bematrix_parent_frame"] = main_frame.name

    dims = tuple(round(v, 4) for v in obj.dimensions)
    print(
        f"  -> object '{obj.name}': faces={len(faces)} sections={len(groups)} "
        f"mitres={corner_count} verts={len(verts)} dims(local m)={dims}"
    )

    info["quad_count"] = len(faces)
    info["vert_count"] = len(verts)
    info["section_count"] = len(groups)
    info["bridge_count"] = corner_count
    info["mitre_count"] = corner_count
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
