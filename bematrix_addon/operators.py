"""
Operators for the BeMatrix Graphic Panels add-on.

Dispatches each source frame to either the hard-panel or SEG-fabric generator
based on the Panel Type, and prints diagnostics to the system console. bl_idname
values are unchanged so existing UI/keymaps keep working.
"""

import bmesh
import math
import os
import re
import bpy
from bpy_extras.io_utils import ExportHelper, ImportHelper
from mathutils import Matrix, Vector
from xml.sax.saxutils import escape

from .utils import (
    ADDON_VERSION,
    get_target_frames,
    get_frame_size_mm,
    get_frame_depth_mm,
    get_frame_spacing_dims_m,
    is_generated_panel_object,
    is_marked_panel,
    is_valid_frame_object,
    strip_blender_duplicate_suffix,
)
from .array_helpers import (
    detect_all_array_settings,
    get_array_step_m,
    get_panel_array_positions,
    is_supported_array_modifier,
    dump_source_frame_modifiers,
)
from .hard_panels import create_or_update_panel_for_frame
from .seg_fabric import create_smart_seg_panel


class BEMATRIX_OT_UpdateAddonFromZip(bpy.types.Operator, ImportHelper):
    bl_idname = "bematrix.update_addon_from_zip"
    bl_label = "Update Add-on from ZIP"
    bl_description = "Install a BeMatrix add-on ZIP over the current add-on"
    bl_options = {"REGISTER"}

    filename_ext = ".zip"
    filter_glob: bpy.props.StringProperty(
        default="*.zip",
        options={"HIDDEN"},
    )

    def execute(self, context):
        filepath = os.path.abspath(bpy.path.abspath(self.filepath))

        if not filepath.lower().endswith(".zip"):
            self.report({"ERROR"}, "Choose a .zip file.")
            return {"CANCELLED"}

        if not os.path.isfile(filepath):
            self.report({"ERROR"}, f"ZIP file not found: {filepath}")
            return {"CANCELLED"}

        self.report({"INFO"}, "Installing add-on ZIP. Restart Blender after the update completes.")

        try:
            result = bpy.ops.preferences.addon_install(
                filepath=filepath,
                overwrite=True,
            )
        except Exception as exc:
            self.report({"ERROR"}, f"Add-on update failed: {exc}")
            return {"CANCELLED"}

        if "FINISHED" not in result:
            self.report({"ERROR"}, "Blender did not finish installing the ZIP. Check that it contains bematrix_addon/__init__.py.")
            return {"CANCELLED"}

        # Do not call self.report(), reload modules, or re-enable the add-on
        # after installing over the currently running package. Blender can
        # invalidate this operator's RNA class during addon_install, and touching
        # `self` after that has caused access-violation crashes in Blender 5.1.
        print(f"BeMatrix add-on ZIP installed from: {filepath}")
        print("Restart Blender if new panels, operators, or UI changes do not appear.")
        return {"FINISHED"}


class BEMATRIX_OT_AddGraphicPanels(bpy.types.Operator):
    bl_idname = "bematrix.add_graphic_panels"
    bl_label = "Add / Update Graphic Panels"
    bl_description = "Add or update BeMatrix graphic panel planes"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        props = context.scene.bematrix_panel_props
        frames = get_target_frames(context)

        # Diagnostic header. Printing the version + file path proves which file
        # Blender actually loaded. Generated BM_PANEL_ objects are excluded from
        # frame detection, so this count reflects real source frames only.
        print("\n=== BeMatrix Graphic Panels ===")
        print(f"Add-on version: {ADDON_VERSION}")
        print(f"Loaded file:    {__file__}")
        print(f"Panel type:     {props.panel_type}")
        print(f"Detected {len(frames)} valid source frame(s).")

        if not frames:
            self.report({"WARNING"}, "No valid BeMatrix frames found.")
            return {"CANCELLED"}

        # SEG fabric uses the smart, connected-mesh builder across all the
        # selected frames (one quad per frame). Hard panels keep their original
        # per-frame behavior below.
        if props.panel_type == "SEG":
            return self._execute_smart_seg(context, props, frames)

        success_count = 0
        deleted_count = 0

        front_off, back_off = props.front_offset_mm, props.back_offset_mm

        side_jobs = []

        if props.panel_side in {"FRONT", "BOTH"}:
            side_jobs.append(("FRONT", front_off))

        if props.panel_side in {"BACK", "BOTH"}:
            side_jobs.append(("BACK", back_off))

        for frame_obj in frames:
            print(f"\nSource frame: {frame_obj.name}")

            # Detect size + array ONCE per frame so FRONT/BACK match and so the
            # diagnostics are printed a single time per frame.
            frame_size = get_frame_size_mm(frame_obj)
            if not frame_size:
                print("  SKIPPED: could not detect frame size.")
                continue

            frame_width_mm, frame_height_mm = frame_size

            # Full modifier dump so we can see exactly what Blender 5.1 exposes.
            dump_source_frame_modifiers(frame_obj)

            # PANEL SIZE = name dimension minus trim.
            # ARRAY SPACING = source frame dimensions (name W/H, parsed depth),
            # NOT the trimmed panel size and NOT the evaluated bounding box.
            depth_mm, depth_source = get_frame_depth_mm(frame_obj)
            spacing_dims_m = get_frame_spacing_dims_m(frame_obj)

            panel_w_mm = frame_width_mm - props.trim_mm
            panel_h_mm = frame_height_mm - props.trim_mm
            print(
                f"  Name dimensions (W x H): {frame_width_mm} x {frame_height_mm} mm"
            )
            print(f"  Panel size (W x H): {panel_w_mm} x {panel_h_mm} mm")

            print(
                f"  Frame depth: {round(depth_mm, 1)} mm (source: {depth_source})"
            )
            print(
                f"  Spacing dims used for array step (W x D x H, m): "
                f"{tuple(round(v, 4) for v in spacing_dims_m)}"
            )

            # Up to two stacked Arrays (e.g. columns x rows) are supported.
            array_list = detect_all_array_settings(frame_obj, limit=2)

            if not array_list:
                # List modifier types so it is obvious when an "array" is really
                # an unsupported modifier (e.g. a non-array Geometry Nodes group).
                mod_types = [
                    f"{m.name}({m.type})" for m in frame_obj.modifiers
                ]
                print(f"  Array modifiers: none detected. Modifiers: {mod_types or 'none'}")
            else:
                print(f"  Array modifiers detected: {len(array_list)}")
                total = 1
                for slot, settings in enumerate(array_list, start=1):
                    step = get_array_step_m(frame_obj, settings)
                    total *= settings.count
                    print(
                        f"  Array {slot}: '{settings.modifier_name}' "
                        f"(type {settings.source_type}) count={settings.count}"
                    )
                    print(
                        f"    Relative offset: enabled={settings.use_relative_offset} "
                        f"vector={tuple(round(v, 4) for v in settings.relative_offset)}"
                    )
                    print(
                        f"    Constant offset: enabled={settings.use_constant_offset} "
                        f"vector={tuple(round(v, 4) for v in settings.constant_offset)}"
                    )
                    print(f"    Computed step (m): {tuple(round(v, 4) for v in step)}")
                    for note in settings.notes:
                        print(f"      note: {note}")
                if len(array_list) > 1:
                    print(f"  Total panels per side = {total}")

            for side_label, offset_mm in side_jobs:
                panel_count, details = create_or_update_panel_for_frame(
                    frame_obj=frame_obj,
                    side_label=side_label,
                    side_offset_mm=offset_mm,
                    trim_mm=props.trim_mm,
                    frame_width_mm=frame_width_mm,
                    frame_height_mm=frame_height_mm,
                    array_list=array_list,
                    replace_existing=props.replace_existing,
                )

                if details.get("error"):
                    print(f"  [{side_label}] SKIPPED: {details['error']}")
                    continue

                for name, location, mat_name in details["created"]:
                    print(
                        f"  [{side_label}] created: {name} at "
                        f"{tuple(round(v, 4) for v in location)}  material={mat_name}"
                    )
                for name, location, mat_name in details["updated"]:
                    print(
                        f"  [{side_label}] updated: {name} at "
                        f"{tuple(round(v, 4) for v in location)}  material={mat_name}"
                    )
                for name in details["deleted_names"]:
                    print(f"  [{side_label}] deleted stale: {name}")

                success_count += panel_count
                deleted_count += len(details["deleted_names"])

        self.report(
            {"INFO"},
            f"v{ADDON_VERSION}: {len(frames)} frame(s), "
            f"{success_count} panel(s) added/updated, "
            f"{deleted_count} stale deleted. See console.",
        )

        return {"FINISHED"}

    def _execute_smart_seg(self, context, props, frames):
        """
        Smart SEG: build ONE connected fabric mesh per side across the selected
        frames (one quad per frame, shared vertices, empty cells left empty).
        Hard-panel behavior is untouched; this path only runs for Panel Type SEG.
        """
        print("Smart SEG: one connected fabric mesh per side across selected frames.")

        sides = []
        if props.panel_side in {"FRONT", "BOTH"}:
            sides.append(("FRONT", props.seg_front_offset_mm))
        if props.panel_side in {"BACK", "BOTH"}:
            sides.append(("BACK", props.seg_back_offset_mm))

        made = 0
        cells_total = 0

        for side_label, offset_mm in sides:
            obj, seg_info = create_smart_seg_panel(
                context,
                frames,
                side_label,
                offset_mm,
                replace_existing=props.replace_existing,
            )

            if obj is None:
                print(f"  [{side_label}] SKIPPED: {seg_info.get('error')}")
                continue

            made += 1
            cells_total += seg_info["quad_count"]
            verb = "created" if seg_info.get("created") else "updated"
            print(
                f"  [{side_label}] {verb}: {obj.name} "
                f"({seg_info['quad_count']} face(s), "
                f"{seg_info.get('section_count', 1)} section(s), "
                f"{seg_info.get('mitre_count', seg_info.get('bridge_count', 0))} "
                f"corner mitre(s), "
                f"{seg_info['vert_count']} verts, "
                f"material={seg_info.get('material')})"
            )
            if seg_info.get("skipped"):
                print(
                    f"  [{side_label}] skipped {seg_info['skipped']} frame(s) "
                    f"with no detectable size"
                )

        self.report(
            {"INFO"},
            f"v{ADDON_VERSION}: SEG fabric {made} mesh(es) from {len(frames)} "
            f"selected frame(s), {cells_total} cell(s). See console.",
        )
        return {"FINISHED"}


class BEMATRIX_OT_DeleteGeneratedPanels(bpy.types.Operator):
    bl_idname = "bematrix.delete_generated_panels"
    bl_label = "Delete Generated Panels"
    bl_description = "Delete generated BeMatrix panel children from target frames"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        frames = get_target_frames(context)

        if not frames:
            self.report({"WARNING"}, "No valid BeMatrix frames found.")
            return {"CANCELLED"}

        deleted_count = 0

        for frame_obj in frames:
            for child in list(frame_obj.children):
                if is_marked_panel(child):
                    bpy.data.objects.remove(child, do_unlink=True)
                    deleted_count += 1

        self.report({"INFO"}, f"Deleted {deleted_count} generated panel(s).")
        return {"FINISHED"}


METERS_TO_INCHES = 39.37007874015748
SVG_MARGIN_IN = 0.25
SVG_TITLE_BAND_IN = 0.65
SVG_TITLE_FONT_SIZE_IN = 0.32
PLANAR_TOLERANCE_M = 0.005
COPLANAR_TOLERANCE_M = 0.01
NORMAL_DOT_MIN = math.cos(math.radians(2.0))
EXPORT_DIRECTION_LABELS = {
    "AUTO": "Auto Detect",
    "WORLD_X": "World X",
    "WORLD_Y": "World Y",
}


def meters_to_inches(value_m):
    """Convert Blender meters to true-size print inches."""
    return value_m * METERS_TO_INCHES


def sanitize_svg_filename(name):
    """Create a readable Windows/macOS-safe SVG filename from a Print Group name."""
    safe = re.sub(r"\s+", "_", (name or "").strip())
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", safe)
    safe = re.sub(r"_+", "_", safe).strip("._ ")
    if not safe:
        safe = "Print_Group"

    reserved_windows_names = {
        "CON", "PRN", "AUX", "NUL",
        "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
        "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
    }
    if safe.upper() in reserved_windows_names:
        safe = f"{safe}_Group"

    return f"{safe}.svg"


def _world_vertices_for_object(obj):
    """Return mesh vertices transformed into world space."""
    return [obj.matrix_world @ vert.co for vert in obj.data.vertices]


def _first_world_polygon_normal(obj, world_verts):
    """Find a non-degenerate polygon normal from world-space mesh vertices."""
    for poly in obj.data.polygons:
        indices = list(poly.vertices)
        if len(indices) < 3:
            continue

        p0 = world_verts[indices[0]]
        for idx in range(1, len(indices) - 1):
            edge_a = world_verts[indices[idx]] - p0
            edge_b = world_verts[indices[idx + 1]] - p0
            normal = edge_a.cross(edge_b)
            if normal.length > 1e-9:
                return normal.normalized()

    return None


def _projected_polygon_area(points_2d):
    """Shoelace area for one projected mesh polygon."""
    if len(points_2d) < 3:
        return 0.0

    total = 0.0
    for idx, (x0, y0) in enumerate(points_2d):
        x1, y1 = points_2d[(idx + 1) % len(points_2d)]
        total += x0 * y1 - x1 * y0
    return abs(total) * 0.5


def _orient_axis_positive(axis):
    """Flip an axis so its dominant world component points positive."""
    values = [abs(axis.x), abs(axis.y), abs(axis.z)]
    dominant = values.index(max(values))
    if axis[dominant] < 0:
        axis = -axis
    return axis


def _direction_label(direction):
    return EXPORT_DIRECTION_LABELS.get(direction, str(direction))


def _resolve_straight_wall_direction_from_points(world_points, user_setting):
    """
    Resolve the horizontal export axis from the user's setting.

    Auto Detect looks at the full world-space bounds so parented panels and
    rotated frame objects are handled from their evaluated world coordinates.
    """
    setting = user_setting or "AUTO"
    if setting in {"WORLD_X", "WORLD_Y"}:
        return {
            "setting": setting,
            "resolved": setting,
            "warning": None,
        }

    min_x = min(point.x for point in world_points)
    max_x = max(point.x for point in world_points)
    min_y = min(point.y for point in world_points)
    max_y = max(point.y for point in world_points)
    spread_x = max_x - min_x
    spread_y = max_y - min_y

    warning = None
    if abs(spread_x - spread_y) <= max(0.01, max(spread_x, spread_y) * 0.10):
        warning = "Export direction ambiguous; Auto Detect used World X."
        resolved = "WORLD_X"
    elif spread_y > spread_x:
        resolved = "WORLD_Y"
    else:
        resolved = "WORLD_X"

    return {
        "setting": "AUTO",
        "resolved": resolved,
        "warning": warning,
    }


def _layout_axes_for_plane(normal, resolved_direction):
    """
    Build a stable 2D basis for a straight wall plane.

    Z projected onto the plane is the print height axis. The horizontal axis is
    perpendicular to both the wall normal and height axis, then flipped so output
    ordering is stable for Illustrator.
    """
    vertical = Vector((0.0, 0.0, 1.0))
    vertical = vertical - normal * vertical.dot(normal)
    if vertical.length < 1e-9:
        vertical = Vector((0.0, 1.0, 0.0))
        vertical = vertical - normal * vertical.dot(normal)
    vertical = vertical.normalized()

    requested_horizontal = (
        Vector((0.0, 1.0, 0.0))
        if resolved_direction == "WORLD_Y"
        else Vector((1.0, 0.0, 0.0))
    )
    horizontal = requested_horizontal - normal * requested_horizontal.dot(normal)
    if horizontal.length < 1e-9:
        return None, None, (
            f"{_direction_label(resolved_direction)} is nearly perpendicular to "
            "the wall plane and cannot be used as the export direction."
        )
    horizontal = horizontal.normalized()

    return _orient_axis_positive(horizontal), _orient_axis_positive(vertical), None


def _collect_export_plane_data(selected_objects, direction_setting="AUTO"):
    """
    Validate selected generated mesh planes and return projected SVG bounds.

    Phase 1 intentionally supports straight, coplanar wall layouts only. Bounds
    are calculated from world-space vertices (`matrix_world @ vertex.co`) so
    parented panels and rotated frames export at their true scene positions.
    """
    candidates = [
        obj
        for obj in selected_objects
        if obj.type == "MESH" and is_generated_panel_object(obj)
    ]

    if not candidates:
        return None, "No selected generated mesh planes found.", None

    plane_data = []
    all_world_points = []
    for obj in candidates:
        if obj.data is None or not obj.data.vertices or not obj.data.polygons:
            return None, f"'{obj.name}' has no mesh plane geometry.", None

        world_verts = _world_vertices_for_object(obj)
        all_world_points.extend(world_verts)
        normal = _first_world_polygon_normal(obj, world_verts)
        if normal is None:
            return None, f"'{obj.name}' has no valid polygon normal.", None

        plane_distance = normal.dot(world_verts[0])
        max_local_distance = max(
            abs(normal.dot(point) - plane_distance) for point in world_verts
        )
        if max_local_distance > PLANAR_TOLERANCE_M:
            return None, (
                f"'{obj.name}' is not a flat plane. "
                "Phase 1 supports straight planar exports only."
            ), None

        center = Vector((0.0, 0.0, 0.0))
        for point in world_verts:
            center += point
        center /= len(world_verts)

        plane_data.append({
            "object": obj,
            "verts": world_verts,
            "normal": normal,
            "center": center,
        })

    reference_normal = plane_data[0]["normal"]
    reference_distance = reference_normal.dot(plane_data[0]["verts"][0])
    direction_info = _resolve_straight_wall_direction_from_points(
        all_world_points,
        direction_setting,
    )

    for item in plane_data:
        if abs(reference_normal.dot(item["normal"])) < NORMAL_DOT_MIN:
            return None, (
                "Selected planes are not approximately parallel. "
                "Phase 1 supports straight-wall exports only."
            ), direction_info

        for point in item["verts"]:
            if abs(reference_normal.dot(point) - reference_distance) > COPLANAR_TOLERANCE_M:
                return None, (
                    "Selected planes are not approximately coplanar. "
                    "Phase 1 supports one straight wall plane only."
                ), direction_info

    horizontal_axis, vertical_axis, axis_error = _layout_axes_for_plane(
        reference_normal,
        direction_info["resolved"],
    )
    if axis_error:
        return None, axis_error, direction_info

    export_items = []
    for item in plane_data:
        obj = item["object"]
        projected = [
            (point.dot(horizontal_axis), point.dot(vertical_axis))
            for point in item["verts"]
        ]
        min_u = min(point[0] for point in projected)
        max_u = max(point[0] for point in projected)
        min_v = min(point[1] for point in projected)
        max_v = max(point[1] for point in projected)

        width_m = max_u - min_u
        height_m = max_v - min_v
        if width_m <= 1e-6 or height_m <= 1e-6:
            return None, f"'{obj.name}' has zero-width or zero-height bounds.", direction_info

        polygon_area_m2 = 0.0
        for poly in obj.data.polygons:
            poly_points = [
                (
                    item["verts"][vertex_index].dot(horizontal_axis),
                    item["verts"][vertex_index].dot(vertical_axis),
                )
                for vertex_index in poly.vertices
            ]
            polygon_area_m2 += _projected_polygon_area(poly_points)

        bounds_area_m2 = width_m * height_m
        area_ratio = polygon_area_m2 / bounds_area_m2 if bounds_area_m2 > 0 else 0.0
        if area_ratio < 0.98 or area_ratio > 1.02:
            return None, (
                f"'{obj.name}' is not a rectangular straight-wall plane. "
                "Phase 1 does not support L-shapes, holes, or angled unfolds."
            ), direction_info

        export_items.append({
            "object": obj,
            "center_x": item["center"].x,
            "center_u": item["center"].dot(horizontal_axis),
            "min_u": min_u,
            "max_u": max_u,
            "min_v": min_v,
            "max_v": max_v,
            "width_in": meters_to_inches(width_m),
            "height_in": meters_to_inches(height_m),
        })

    export_items.sort(key=lambda item: (item["center_u"], item["object"].name))
    return export_items, None, direction_info


def _svg_for_export_items(export_items, print_group_name=None):
    min_u = min(item["min_u"] for item in export_items)
    max_u = max(item["max_u"] for item in export_items)
    min_v = min(item["min_v"] for item in export_items)
    max_v = max(item["max_v"] for item in export_items)

    title_band_in = SVG_TITLE_BAND_IN if print_group_name else 0.0
    document_width_in = meters_to_inches(max_u - min_u) + SVG_MARGIN_IN * 2.0
    document_height_in = (
        meters_to_inches(max_v - min_v) + SVG_MARGIN_IN * 2.0 + title_band_in
    )
    document_title = print_group_name or "BeMatrix Print Layout Export"

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'width="{document_width_in:.6f}in" '
            f'height="{document_height_in:.6f}in" '
            f'viewBox="0 0 {document_width_in:.6f} {document_height_in:.6f}">'
        ),
        f'  <title>{escape(document_title)}</title>',
    ]

    if print_group_name:
        lines.extend([
            (
                f'  <text id="bematrix-print-group-title" '
                f'x="{SVG_MARGIN_IN:.6f}" y="0.420000" '
                f'fill="#000000" font-family="Arial" '
                f'font-size="{SVG_TITLE_FONT_SIZE_IN:.6f}">'
                f'{escape(print_group_name)}</text>'
            ),
        ])

    lines.extend([
        '  <g id="bematrix-print-layout" fill="none" stroke="#000000" stroke-width="0.01">',
    ])

    for item_index, item in enumerate(export_items, start=1):
        obj = item["object"]
        x = meters_to_inches(item["min_u"] - min_u) + SVG_MARGIN_IN
        y = meters_to_inches(item["min_v"] - min_v) + SVG_MARGIN_IN + title_band_in
        width = item["width_in"]
        height = item["height_in"]
        name_attr = escape(obj.name, {'"': "&quot;"})
        lines.append(
            f'    <rect id="bematrix-plane-{item_index:03d}" '
            f'data-name="{name_attr}" '
            f'x="{x:.6f}" y="{y:.6f}" '
            f'width="{width:.6f}" height="{height:.6f}" />'
        )

    lines.append("  </g>")
    lines.append('  <g id="bematrix-print-labels" fill="#000000" font-family="Arial" font-size="0.18">')

    for item in export_items:
        obj = item["object"]
        x = meters_to_inches(item["min_u"] - min_u) + SVG_MARGIN_IN + 0.12
        y = meters_to_inches(item["min_v"] - min_v) + SVG_MARGIN_IN + title_band_in + 0.28
        label = (
            f"{obj.name} - {item['width_in']:.2f} in x "
            f"{item['height_in']:.2f} in"
        )
        lines.append(f'    <text x="{x:.6f}" y="{y:.6f}">{escape(label)}</text>')

    lines.extend([
        "  </g>",
        "</svg>",
        "",
    ])
    return "\n".join(lines)


def export_planes_to_svg(context, objects, filepath, print_group_name=None, direction_setting="AUTO"):
    """
    Export generated plane objects to SVG using the Phase 1 straight-wall rules.

    Returns (count, error_message). The caller is responsible for Blender
    reports so selected-export and group-export can add context-specific warnings.
    """
    export_items, error, direction_info = _collect_export_plane_data(
        objects,
        direction_setting=direction_setting,
    )
    if error:
        return 0, error, direction_info

    if not filepath.lower().endswith(".svg"):
        filepath += ".svg"

    svg_text = _svg_for_export_items(export_items, print_group_name=print_group_name)

    try:
        with open(filepath, "w", encoding="utf-8") as svg_file:
            svg_file.write(svg_text)
    except OSError as exc:
        return 0, f"Unable to write SVG: {exc}", direction_info

    return len(export_items), None, direction_info


def _selected_valid_export_planes(context):
    """Selected generated mesh panels/SEG planes, deduplicated in selection order."""
    planes = []
    seen = set()
    for obj in context.selected_objects:
        if obj.name in seen:
            continue
        if obj.type == "MESH" and is_generated_panel_object(obj):
            planes.append(obj)
            seen.add(obj.name)
    return planes


def _active_print_group(props):
    if props.active_print_group == "NONE":
        return None

    try:
        index = int(props.active_print_group)
    except (TypeError, ValueError):
        return None

    if index < 0 or index >= len(props.print_groups):
        return None

    return props.print_groups[index]


def _collection_name_for_print_group(group_name):
    safe = re.sub(r"[^A-Za-z0-9_. -]+", "_", group_name).strip()
    safe = safe.replace(" ", "_")
    return f"BM_PRINT_{safe or 'Group'}"


def _ensure_print_group_collection(context, group_name, objects):
    """
    Optional Outliner helper: link stored objects into BM_PRINT_<Group Name>
    without unlinking them from their existing collections.
    """
    collection_name = _collection_name_for_print_group(group_name)
    collection = bpy.data.collections.get(collection_name)
    if collection is None:
        collection = bpy.data.collections.new(collection_name)

    if context.scene.collection.children.get(collection.name) is None:
        context.scene.collection.children.link(collection)

    for obj in objects:
        if collection.objects.get(obj.name) is None:
            collection.objects.link(obj)

    return collection


def _resolve_print_group_objects(group):
    objects = []
    missing = []
    invalid = []
    seen = set()

    for item in group.objects:
        object_name = item.object_name
        if not object_name or object_name in seen:
            continue
        seen.add(object_name)

        obj = bpy.data.objects.get(object_name)
        if obj is None:
            missing.append(object_name)
            continue
        if obj.type != "MESH" or not is_generated_panel_object(obj):
            invalid.append(object_name)
            continue
        objects.append(obj)

    return objects, missing, invalid


def _summarize_export_items(export_items):
    min_u = min(item["min_u"] for item in export_items)
    max_u = max(item["max_u"] for item in export_items)
    min_v = min(item["min_v"] for item in export_items)
    max_v = max(item["max_v"] for item in export_items)
    return meters_to_inches(max_u - min_u), meters_to_inches(max_v - min_v)


def _direction_summary(direction_info):
    if not direction_info:
        return "direction unknown"
    setting = direction_info.get("setting")
    resolved = direction_info.get("resolved")
    if setting == "AUTO":
        return f"direction Auto Detect -> {_direction_label(resolved)}"
    return f"direction {_direction_label(resolved)}"


def _validate_print_group(group, direction_setting="AUTO"):
    group_name = group.group_name.strip() or "Print Group"
    object_names = [
        item.object_name
        for item in group.objects
        if item.object_name
    ]

    if not object_names:
        return {
            "severity": "ERROR",
            "group_name": group_name,
            "line": f"{group_name}: ERROR - No objects stored in Print Group.",
            "details": [],
        }

    objects = []
    details = []
    seen = set()
    for object_name in object_names:
        if object_name in seen:
            details.append(f"Duplicate stored object ignored: {object_name}")
            continue
        seen.add(object_name)

        obj = bpy.data.objects.get(object_name)
        if obj is None:
            return {
                "severity": "ERROR",
                "group_name": group_name,
                "line": f"{group_name}: ERROR - Missing object: {object_name}",
                "details": details,
            }

        if obj.type != "MESH":
            return {
                "severity": "ERROR",
                "group_name": group_name,
                "line": f"{group_name}: ERROR - Object is not a mesh: {object_name}",
                "details": details,
            }

        if not is_generated_panel_object(obj):
            return {
                "severity": "ERROR",
                "group_name": group_name,
                "line": f"{group_name}: ERROR - Object is not a generated BeMatrix panel/SEG plane: {object_name}",
                "details": details,
            }

        if obj.data is None or not obj.data.vertices or not obj.data.polygons:
            return {
                "severity": "ERROR",
                "group_name": group_name,
                "line": f"{group_name}: ERROR - Object has no usable mesh geometry: {object_name}",
                "details": details,
            }

        objects.append(obj)

    export_items, error, direction_info = _collect_export_plane_data(
        objects,
        direction_setting=direction_setting,
    )
    if error:
        return {
            "severity": "ERROR",
            "group_name": group_name,
            "line": f"{group_name}: ERROR - {error}; {_direction_summary(direction_info)}",
            "details": details,
            "direction_info": direction_info,
        }

    total_width_in, total_height_in = _summarize_export_items(export_items)
    panel_heights = [item["height_in"] for item in export_items]
    warnings = []
    if direction_info and direction_info.get("warning"):
        warnings.append(direction_info["warning"])
    if panel_heights and (max(panel_heights) - min(panel_heights)) > 0.125:
        warnings.append("Plane heights differ.")

    if warnings:
        line = (
            f"{group_name}: WARNING - {len(export_items)} planes, approx "
            f"{total_width_in:.2f} in wide x {total_height_in:.2f} in high, "
            f"{_direction_summary(direction_info)}; "
            f"{' '.join(warnings)}"
        )
        severity = "WARNING"
    else:
        line = (
            f"{group_name}: OK - {len(export_items)} planes, approx "
            f"{total_width_in:.2f} in wide x {total_height_in:.2f} in high, "
            f"{_direction_summary(direction_info)}"
        )
        severity = "OK"

    return {
        "severity": severity,
        "group_name": group_name,
        "line": line,
        "details": details + warnings,
        "direction_info": direction_info,
    }


def _set_validation_status(props, lines):
    props.print_group_validation_status = "\n".join(lines) if lines else "No validation result."


class BEMATRIX_OT_ExportSelectedPlanesToSVG(bpy.types.Operator, ExportHelper):
    bl_idname = "bematrix.export_selected_planes_svg"
    bl_label = "Export Selected Planes to SVG"
    bl_description = (
        "Export selected generated hard-panel or SEG plane objects as a "
        "true-size straight-wall SVG layout"
    )
    bl_options = {"REGISTER"}

    filename_ext = ".svg"
    filter_glob: bpy.props.StringProperty(
        default="*.svg",
        options={"HIDDEN"},
    )

    def execute(self, context):
        props = context.scene.bematrix_panel_props
        count, error, direction_info = export_planes_to_svg(
            context,
            context.selected_objects,
            self.filepath,
            direction_setting=props.straight_wall_direction,
        )
        if error is not None:
            self.report({"ERROR"}, error)
            return {"CANCELLED"}

        if direction_info.get("warning"):
            self.report(
                {"WARNING"},
                f"Exported {count} selected plane(s) using "
                f"{_direction_label(direction_info['resolved'])}; "
                f"{direction_info['warning']}",
            )
            return {"FINISHED"}

        self.report(
            {"INFO"},
            f"Exported {count} selected plane(s) to SVG using "
            f"{_direction_label(direction_info['resolved'])}.",
        )
        return {"FINISHED"}


class BEMATRIX_OT_CreatePrintGroupFromSelected(bpy.types.Operator):
    bl_idname = "bematrix.create_print_group_from_selected"
    bl_label = "Create Print Group From Selected"
    bl_description = "Save the selected generated panel/SEG planes as a named Print Group"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        props = context.scene.bematrix_panel_props
        group_name = props.print_group_name.strip()
        if not group_name:
            self.report({"ERROR"}, "Enter a Print Group name.")
            return {"CANCELLED"}

        for group in props.print_groups:
            if group.group_name.strip().lower() == group_name.lower():
                self.report({"ERROR"}, f"Print Group '{group_name}' already exists.")
                return {"CANCELLED"}

        planes = _selected_valid_export_planes(context)
        if not planes:
            self.report({"ERROR"}, "Select one or more generated hard-panel or SEG plane objects.")
            return {"CANCELLED"}

        group = props.print_groups.add()
        group.group_name = group_name
        for obj in planes:
            item = group.objects.add()
            item.object_name = obj.name

        collection = _ensure_print_group_collection(context, group_name, planes)
        props.active_print_group = str(len(props.print_groups) - 1)

        self.report(
            {"INFO"},
            f"Created Print Group '{group_name}' with {len(planes)} plane(s). "
            f"Linked to collection '{collection.name}'.",
        )
        return {"FINISHED"}


class BEMATRIX_OT_SelectPrintGroupObjects(bpy.types.Operator):
    bl_idname = "bematrix.select_print_group_objects"
    bl_label = "Select Group Objects"
    bl_description = "Select the generated plane objects stored in the active Print Group"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        props = context.scene.bematrix_panel_props
        group = _active_print_group(props)
        if group is None:
            self.report({"ERROR"}, "Choose a Print Group first.")
            return {"CANCELLED"}

        objects, missing, invalid = _resolve_print_group_objects(group)
        if not objects:
            self.report({"ERROR"}, f"Print Group '{group.group_name}' has no valid objects.")
            return {"CANCELLED"}

        try:
            for obj in list(context.selected_objects):
                obj.select_set(False)
            for obj in objects:
                obj.select_set(True)
            context.view_layer.objects.active = objects[0]
        except RuntimeError as exc:
            self.report({"ERROR"}, f"Could not select Print Group objects: {exc}")
            return {"CANCELLED"}

        if missing or invalid:
            self.report(
                {"WARNING"},
                f"Selected {len(objects)} object(s); skipped "
                f"{len(missing)} missing and {len(invalid)} invalid.",
            )
        else:
            self.report({"INFO"}, f"Selected {len(objects)} Print Group object(s).")

        return {"FINISHED"}


class BEMATRIX_OT_ValidateActivePrintGroup(bpy.types.Operator):
    bl_idname = "bematrix.validate_active_print_group"
    bl_label = "Validate Active Group"
    bl_description = "Check whether the active Print Group is safe for straight-wall SVG export"
    bl_options = {"REGISTER"}

    def execute(self, context):
        props = context.scene.bematrix_panel_props
        group = _active_print_group(props)
        if group is None:
            message = "No active Print Group selected."
            _set_validation_status(props, [f"ERROR - {message}"])
            self.report({"ERROR"}, message)
            return {"CANCELLED"}

        result = _validate_print_group(
            group,
            direction_setting=props.straight_wall_direction,
        )
        _set_validation_status(props, [result["line"]])
        print("\n=== BeMatrix Print Group Validation ===")
        print(f"Direction setting: {_direction_label(props.straight_wall_direction)}")
        print(result["line"])
        for detail in result["details"]:
            print(f"  {detail}")

        if result["severity"] == "ERROR":
            self.report({"ERROR"}, result["line"])
            return {"CANCELLED"}
        if result["severity"] == "WARNING":
            self.report({"WARNING"}, result["line"])
            return {"FINISHED"}

        self.report({"INFO"}, result["line"])
        return {"FINISHED"}


class BEMATRIX_OT_ValidateAllPrintGroups(bpy.types.Operator):
    bl_idname = "bematrix.validate_all_print_groups"
    bl_label = "Validate All Groups"
    bl_description = "Check every saved Print Group for straight-wall SVG export compatibility"
    bl_options = {"REGISTER"}

    def execute(self, context):
        props = context.scene.bematrix_panel_props
        if not props.print_groups:
            message = "No Print Groups have been created."
            _set_validation_status(props, [f"ERROR - {message}"])
            self.report({"ERROR"}, message)
            return {"CANCELLED"}

        ok_count = 0
        warning_count = 0
        error_count = 0
        lines = []

        print("\n=== BeMatrix Print Group Validation ===")
        print(f"Direction setting: {_direction_label(props.straight_wall_direction)}")
        for group in props.print_groups:
            result = _validate_print_group(
                group,
                direction_setting=props.straight_wall_direction,
            )
            lines.append(result["line"])
            print(result["line"])
            for detail in result["details"]:
                print(f"  {detail}")

            if result["severity"] == "OK":
                ok_count += 1
            elif result["severity"] == "WARNING":
                warning_count += 1
            else:
                error_count += 1

        summary = (
            f"Validation complete: {ok_count} OK, {warning_count} warning, "
            f"{error_count} error."
        )
        _set_validation_status(props, [summary] + lines[:4])

        if error_count:
            self.report({"ERROR"}, f"{summary} See console and sidebar status.")
            return {"CANCELLED"}
        if warning_count:
            self.report({"WARNING"}, f"{summary} See console and sidebar status.")
            return {"FINISHED"}

        self.report({"INFO"}, summary)
        return {"FINISHED"}


def _directory_path_from_operator(operator):
    directory = bpy.path.abspath(operator.directory)
    if not directory:
        return None
    return os.path.abspath(directory)


def _export_print_group_to_folder(group, folder_path, direction_setting="AUTO"):
    group_name = group.group_name.strip() or "Print Group"
    filepath = os.path.join(folder_path, sanitize_svg_filename(group_name))
    objects, missing, invalid = _resolve_print_group_objects(group)
    if not objects:
        return {
            "ok": False,
            "group_name": group_name,
            "filepath": filepath,
            "count": 0,
            "missing": missing,
            "invalid": invalid,
            "error": "No valid exportable planes.",
            "direction_info": None,
        }

    count, error, direction_info = export_planes_to_svg(
        None,
        objects,
        filepath,
        print_group_name=group_name,
        direction_setting=direction_setting,
    )
    if error is not None:
        return {
            "ok": False,
            "group_name": group_name,
            "filepath": filepath,
            "count": 0,
            "missing": missing,
            "invalid": invalid,
            "error": error,
            "direction_info": direction_info,
        }

    return {
        "ok": True,
        "group_name": group_name,
        "filepath": filepath,
        "count": count,
        "missing": missing,
        "invalid": invalid,
        "error": None,
        "direction_info": direction_info,
    }


class BEMATRIX_OT_ExportActivePrintGroupToFolder(bpy.types.Operator):
    bl_idname = "bematrix.export_active_print_group_folder"
    bl_label = "Export Active Group to Folder"
    bl_description = "Export the active Print Group to a folder using the group name as the SVG filename"
    bl_options = {"REGISTER"}

    directory: bpy.props.StringProperty(
        name="Output Folder",
        description="Folder where the active Print Group SVG will be written",
        subtype="DIR_PATH",
    )
    filter_folder: bpy.props.BoolProperty(
        default=True,
        options={"HIDDEN"},
    )

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        props = context.scene.bematrix_panel_props
        group = _active_print_group(props)
        if group is None:
            self.report({"ERROR"}, "Choose a Print Group first.")
            return {"CANCELLED"}

        folder_path = _directory_path_from_operator(self)
        if not folder_path or not os.path.isdir(folder_path):
            self.report({"ERROR"}, "Choose a valid output folder.")
            return {"CANCELLED"}

        result = _export_print_group_to_folder(
            group,
            folder_path,
            direction_setting=props.straight_wall_direction,
        )
        if not result["ok"]:
            self.report(
                {"ERROR"},
                f"Print Group '{result['group_name']}' export failed: {result['error']}",
            )
            return {"CANCELLED"}

        direction_label = _direction_label(result["direction_info"]["resolved"])
        direction_warning = result["direction_info"].get("warning")
        if result["missing"] or result["invalid"] or direction_warning:
            extra_warning = f" {direction_warning}" if direction_warning else ""
            self.report(
                {"WARNING"},
                f"Exported '{result['group_name']}' with {result['count']} plane(s); "
                f"used {direction_label}; "
                f"skipped {len(result['missing'])} missing and "
                f"{len(result['invalid'])} invalid.{extra_warning}",
            )
        else:
            self.report(
                {"INFO"},
                f"Exported '{result['group_name']}' to {result['filepath']} using {direction_label}.",
            )

        return {"FINISHED"}


class BEMATRIX_OT_ExportAllPrintGroupsToFolder(bpy.types.Operator):
    bl_idname = "bematrix.export_all_print_groups_folder"
    bl_label = "Export All Groups to Folder"
    bl_description = "Export every saved Print Group to one SVG per group in the chosen folder"
    bl_options = {"REGISTER"}

    directory: bpy.props.StringProperty(
        name="Output Folder",
        description="Folder where Print Group SVG files will be written",
        subtype="DIR_PATH",
    )
    filter_folder: bpy.props.BoolProperty(
        default=True,
        options={"HIDDEN"},
    )

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        props = context.scene.bematrix_panel_props
        if not props.print_groups:
            self.report({"ERROR"}, "No Print Groups have been created.")
            return {"CANCELLED"}

        folder_path = _directory_path_from_operator(self)
        if not folder_path or not os.path.isdir(folder_path):
            self.report({"ERROR"}, "Choose a valid output folder.")
            return {"CANCELLED"}

        exported = 0
        failed = 0
        warning_groups = 0

        print("\n=== BeMatrix Print Group Batch SVG Export ===")
        print(f"Output folder: {folder_path}")
        print(f"Direction setting: {_direction_label(props.straight_wall_direction)}")

        for group in props.print_groups:
            result = _export_print_group_to_folder(
                group,
                folder_path,
                direction_setting=props.straight_wall_direction,
            )
            if result["ok"]:
                exported += 1
                if (
                    result["missing"]
                    or result["invalid"]
                    or result["direction_info"].get("warning")
                ):
                    warning_groups += 1
                direction_label = _direction_label(result["direction_info"]["resolved"])
                warning_text = ""
                if result["direction_info"].get("warning"):
                    warning_text = f", {result['direction_info']['warning']}"
                print(
                    f"  OK: {result['group_name']} -> {result['filepath']} "
                    f"using {direction_label} ({result['count']} plane(s), "
                    f"{len(result['missing'])} missing, {len(result['invalid'])} invalid"
                    f"{warning_text})"
                )
            else:
                failed += 1
                print(f"  SKIPPED: {result['group_name']} - {result['error']}")

        if exported == 0:
            self.report(
                {"ERROR"},
                f"No Print Groups exported. {failed} failed/skipped. See console.",
            )
            return {"CANCELLED"}

        if failed or warning_groups:
            self.report(
                {"WARNING"},
                f"Exported {exported} Print Group(s); {failed} failed/skipped, "
                f"{warning_groups} had missing/invalid objects. See console.",
            )
        else:
            self.report(
                {"INFO"},
                f"Exported {exported} Print Group SVG file(s) to {folder_path}",
            )

        return {"FINISHED"}


class BEMATRIX_OT_DeletePrintGroup(bpy.types.Operator):
    bl_idname = "bematrix.delete_print_group"
    bl_label = "Delete Print Group"
    bl_description = "Delete the active Print Group data. Objects are not deleted"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        props = context.scene.bematrix_panel_props
        if props.active_print_group == "NONE":
            self.report({"ERROR"}, "Choose a Print Group first.")
            return {"CANCELLED"}

        try:
            index = int(props.active_print_group)
        except (TypeError, ValueError):
            self.report({"ERROR"}, "Choose a valid Print Group.")
            return {"CANCELLED"}

        if index < 0 or index >= len(props.print_groups):
            self.report({"ERROR"}, "Choose a valid Print Group.")
            return {"CANCELLED"}

        group_name = props.print_groups[index].group_name
        props.print_groups.remove(index)
        if props.print_groups:
            props.active_print_group = str(min(index, len(props.print_groups) - 1))
        else:
            props.active_print_group = "NONE"

        self.report({"INFO"}, f"Deleted Print Group '{group_name}'. Objects were not deleted.")
        return {"FINISHED"}


class BEMATRIX_OT_ConvertArrayToFrames(bpy.types.Operator):
    bl_idname = "bematrix.convert_array_to_frames"
    bl_label = "Convert Array to Individual Frames"
    bl_description = (
        "For each selected BeMatrix frame with one or two simple Array modifiers, "
        "create a separate real frame object per array position, then hide the "
        "original array source (it is not deleted)"
    )
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        # Selected frames only. Ignore generated BM_PANEL_ / BM_SEG_ objects
        # (is_valid_frame_object already excludes them) and skip objects already
        # marked as a hidden array source.
        selected = [
            obj
            for obj in context.selected_objects
            if is_valid_frame_object(obj) and not obj.get("bematrix_array_source")
        ]

        print("\n=== BeMatrix: Convert Array to Individual Frames ===")
        print(f"Add-on version: {ADDON_VERSION}")
        print(f"Selected valid frame(s): {len(selected)}")

        if not selected:
            self.report({"WARNING"}, "No valid BeMatrix frames selected.")
            return {"CANCELLED"}

        total_created = 0
        converted_frames = 0
        skipped_no_array = 0
        new_objects = []

        for source in selected:
            # Same detection used by the graphic-panel generator: up to two
            # simple count-based Array modifiers.
            array_list = detect_all_array_settings(source, limit=2)

            if not array_list:
                skipped_no_array += 1
                print(f"  '{source.name}': no supported Array modifier - skipped.")
                self.report({"INFO"}, f"No Array found on '{source.name}'.")
                continue

            # Same array-position math as generated graphic panels.
            positions = get_panel_array_positions(source, array_list)
            base_name = strip_blender_duplicate_suffix(source.name)
            counts = " x ".join(str(s.count) for s in array_list)
            print(
                f"  '{source.name}': {len(array_list)} array(s) (counts {counts}) "
                f"-> {len(positions)} frame(s)"
            )

            for index_1, index_2, offset in positions:
                new_obj = self._make_frame_copy(
                    context, source, base_name, index_1, index_2, offset
                )
                new_objects.append(new_obj)
                total_created += 1
                loc = tuple(round(v, 4) for v in new_obj.matrix_world.translation)
                print(f"    created: {new_obj.name} at world {loc}")

            # Hide and mark the original array source instead of deleting it.
            source["bematrix_array_source"] = True
            source.hide_render = True
            try:
                source.hide_set(True)
            except RuntimeError:
                source.hide_viewport = True

            converted_frames += 1

        # Select the generated frames for convenience (best effort).
        try:
            for obj in list(context.selected_objects):
                obj.select_set(False)
            for obj in new_objects:
                obj.select_set(True)
            if new_objects:
                context.view_layer.objects.active = new_objects[0]
        except RuntimeError:
            pass

        self.report(
            {"INFO"},
            f"v{ADDON_VERSION}: converted {converted_frames} frame(s) -> "
            f"{total_created} real frame(s); {skipped_no_array} skipped (no Array). "
            f"See console.",
        )
        return {"FINISHED"}

    @staticmethod
    def _make_frame_copy(context, source, base_name, index_1, index_2, offset):
        """
        Duplicate the source frame object + mesh, strip its Array modifiers, place
        it at one array position, and tag it as a broken-out array frame.
        """
        if index_2 is None:
            suffix = f"_A{index_1:03d}"
        else:
            suffix = f"_A{index_1:03d}_B{index_2:03d}"
        new_name = f"{base_name}{suffix}"

        # Duplicate the object AND its mesh so each frame is a separate, real,
        # selectable object (not instances, not one joined mesh). Object/mesh
        # material slots are preserved by the copy.
        new_obj = source.copy()
        new_obj.data = source.data.copy()

        # Generated frames must have NO Array modifiers (do not apply
        # destructively, do not join). Only remove array modifiers; keep any
        # other modifiers the frame may have.
        for mod in list(new_obj.modifiers):
            if is_supported_array_modifier(mod):
                new_obj.modifiers.remove(mod)

        new_obj.name = new_name
        new_obj.data.name = f"{new_name}_Mesh"

        # Keep the same collection(s) as the source.
        linked = False
        for coll in source.users_collection:
            coll.objects.link(new_obj)
            linked = True
        if not linked:
            context.collection.objects.link(new_obj)

        # Place at the array position. `offset` is a local-space vector in meters
        # (identical to the value used to place generated graphic panels). Post-
        # multiplying by a local translation keeps the original rotation/scale.
        new_obj.matrix_world = source.matrix_world @ Matrix.Translation(offset)

        new_obj["bematrix_array_broken_object"] = True
        new_obj["bematrix_source_frame_name"] = source.name
        new_obj["bematrix_array_index_1"] = index_1
        new_obj["bematrix_array_index_2"] = index_2 if index_2 is not None else 0

        return new_obj


def _single_selected_edit_vertex(obj):
    """
    Return the single selected vertex's local coordinate for a mesh in Edit Mode,
    or (None, message) if the selection is not exactly one vertex.
    """
    bm = bmesh.from_edit_mesh(obj.data)
    selected = [v for v in bm.verts if v.select]
    if len(selected) != 1:
        return None, "Select exactly one vertex in Edit Mode."
    return selected[0].co.copy(), None


class BEMATRIX_OT_SetSnapTarget(bpy.types.Operator):
    bl_idname = "bematrix.set_snap_target"
    bl_label = "Set Snap Target"
    bl_description = (
        "In Edit Mode with one vertex selected: store that vertex's world "
        "location as the snap target and move the 3D cursor there. The object "
        "is not moved"
    )
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.edit_object
        return obj is not None and obj.type == "MESH"

    def execute(self, context):
        obj = context.edit_object

        local_co, message = _single_selected_edit_vertex(obj)
        if local_co is None:
            self.report({"WARNING"}, message)
            return {"CANCELLED"}

        # World-space location of the selected vertex.
        target = obj.matrix_world @ local_co

        props = context.scene.bematrix_panel_props
        props.snap_target = target
        props.snap_target_set = True

        # Move the 3D cursor to the target; do NOT move the object.
        context.scene.cursor.location = target

        self.report(
            {"INFO"},
            f"Snap target set at {tuple(round(v, 4) for v in target)}.",
        )
        return {"FINISHED"}


class BEMATRIX_OT_SnapFrameToTarget(bpy.types.Operator):
    bl_idname = "bematrix.snap_frame_to_target"
    bl_label = "Snap Frame to Target"
    bl_description = (
        "In Edit Mode with one vertex selected: move the whole object so that "
        "vertex lands exactly on the stored snap target. Rotation and scale are "
        "preserved"
    )
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.edit_object
        return obj is not None and obj.type == "MESH"

    def execute(self, context):
        props = context.scene.bematrix_panel_props
        if not props.snap_target_set:
            self.report({"WARNING"}, "No snap target set. Use Set Snap Target first.")
            return {"CANCELLED"}

        obj = context.edit_object

        local_co, message = _single_selected_edit_vertex(obj)
        if local_co is None:
            self.report({"WARNING"}, message)
            return {"CANCELLED"}

        # World-space location of the source vertex on the object to move.
        source_world = obj.matrix_world @ local_co
        target = Vector(props.snap_target)
        delta = target - source_world

        # Translate the WHOLE object in world space so the source vertex lands on
        # the target. Pre-multiplying by a world translation leaves the object's
        # rotation and scale untouched, and works whether or not it is parented.
        obj.matrix_world = Matrix.Translation(delta) @ obj.matrix_world

        # Keep the 3D cursor at the target.
        context.scene.cursor.location = target

        self.report(
            {"INFO"},
            f"Snapped '{obj.name}' onto target "
            f"{tuple(round(v, 4) for v in target)}.",
        )
        return {"FINISHED"}


class BEMATRIX_OT_MakeSelectedLocal(bpy.types.Operator):
    bl_idname = "bematrix.make_selected_local"
    bl_label = "Make Selected Local"
    bl_description = (
        "Make the selected objects and their mesh data local/editable "
        "(Object > Relations > Make Local > Selected Objects and Data)"
    )
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        # Make Local runs in Object Mode on the current selection.
        return context.mode == "OBJECT" and len(context.selected_objects) > 0

    def execute(self, context):
        count = len(context.selected_objects)

        # Equivalent of Object > Relations > Make Local > Selected Objects and
        # Data. 'SELECT_OBDATA' makes both the objects and their data local.
        try:
            result = bpy.ops.object.make_local(type="SELECT_OBDATA")
        except RuntimeError as exc:
            self.report({"WARNING"}, f"Make Local failed: {exc}")
            return {"CANCELLED"}

        if "FINISHED" not in result:
            self.report({"WARNING"}, "Make Local did not run (nothing linked?).")
            return {"CANCELLED"}

        self.report({"INFO"}, f"Made {count} selected object(s) and data local.")
        return {"FINISHED"}
