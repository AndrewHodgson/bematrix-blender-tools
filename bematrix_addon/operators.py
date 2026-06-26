"""
Operators for the BeMatrix Graphic Panels add-on.

Dispatches each source frame to either the hard-panel or SEG-fabric generator
based on the Panel Type, and prints diagnostics to the system console. bl_idname
values are unchanged so existing UI/keymaps keep working.
"""

import bmesh
import csv
import json
import math
import os
import re
from datetime import datetime, timezone
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
    get_hard_panel_size_mm,
    get_frame_dimension_mm,
    format_dimension_validation,
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
from .curved_frames import (
    create_or_update_curved_panel_for_frame,
    curved_face_for_panel_side,
    parse_curved_frame_from_name,
)


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

            # PANEL SIZE = official BeMatrix F -> P lookup when available.
            # ARRAY SPACING = source frame dimensions (name W/H, parsed depth),
            # NOT the trimmed panel size and NOT the evaluated bounding box.
            depth_mm, depth_source = get_frame_depth_mm(frame_obj)
            spacing_dims_m = get_frame_spacing_dims_m(frame_obj)

            panel_w_mm, panel_h_mm = get_hard_panel_size_mm(
                frame_width_mm,
                frame_height_mm,
                fallback_trim_mm=props.trim_mm,
            )
            print(
                f"  Name dimensions (W x H): {frame_width_mm} x {frame_height_mm} mm"
            )
            panel_size_source = (
                "official BeMatrix F->P table"
                if (
                    get_frame_dimension_mm(frame_width_mm) is not None
                    and get_frame_dimension_mm(frame_height_mm) is not None
                )
                else f"legacy trim fallback ({props.trim_mm:g} mm)"
            )
            print(
                f"  Panel size (W x H): {panel_w_mm} x {panel_h_mm} mm "
                f"({panel_size_source})"
            )

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

                for entry in details["created"]:
                    name, location, mat_name = entry[0], entry[1], entry[-1]
                    print(
                        f"  [{side_label}] created: {name} at "
                        f"{tuple(round(v, 4) for v in location)}  material={mat_name}"
                    )
                for entry in details["updated"]:
                    name, location, mat_name = entry[0], entry[1], entry[-1]
                    print(
                        f"  [{side_label}] updated: {name} at "
                        f"{tuple(round(v, 4) for v in location)}  material={mat_name}"
                    )
                for name in details["deleted_names"]:
                    print(f"  [{side_label}] deleted stale: {name}")
                if details.get("is_curved"):
                    bounds = details["local_bounds"]
                    print(
                        f"  [{side_label}] curved frame: selected frame={frame_obj.name}, "
                        f"path={details['detection_path']}, "
                        f"family={details['family_mm']}, "
                        f"R{details['radius_mm']} angle={details['angle_degrees']} deg, "
                        f"selected Panel Side={side_label}, "
                        f"resolved curved side={details['curved_face_label']}, "
                        f"mesh={details['panel_width_mm']} x {details['panel_height_mm']} mm, "
                        f"segments={details['mesh_segment_count']}"
                    )
                    print(
                        f"      local bounds: "
                        f"x=({bounds['min_x']:.4f}, {bounds['max_x']:.4f}), "
                        f"y=({bounds['min_y']:.4f}, {bounds['max_y']:.4f}), "
                        f"z=({bounds['min_z']:.4f}, {bounds['max_z']:.4f})"
                    )
                    print(
                        f"      arc: center={tuple(round(v, 4) for v in details['arc_center'])}, "
                        f"radius={details['arc_radius_m']:.4f} m, "
                        f"start={details['arc_start_angle_degrees']:.2f} deg, "
                        f"end={details['arc_end_angle_degrees']:.2f} deg, "
                        f"direction={details['arc_direction']}, "
                        f"fit_score={details['arc_fit_score']:.6f}"
                    )
                    exp_rot = details["expected_rotation"]
                    print(
                        f"      axis: {details['vertical_axis']} vertical | "
                        f"radii outer={details['arc_outer_radius_m']:.4f} "
                        f"inner={details['arc_inner_radius_m']:.4f} m | "
                        f"sweep={details['arc_sweep_degrees']:.2f} deg "
                        f"({details['arc_sweep_source']}, nominal "
                        f"{details['arc_nominal_angle_degrees']:g}) | "
                        f"expected rotation (manual-plane rule)="
                        f"({exp_rot[0]:.3f}, {exp_rot[1]:.3f}, {exp_rot[2]:.3f}) "
                        f"deg, generated rotation=(0, 0, 0) baked"
                    )
                    print(
                        f"      reference object used: {details.get('reference_curve_object') or 'none (frame-fit fallback)'}"
                    )
                    print(
                        f"      first vertex={tuple(round(v, 4) for v in details['first_vertex'])}, "
                        f"last vertex={tuple(round(v, 4) for v in details['last_vertex'])}"
                    )
                    for entry in details["created"] + details["updated"]:
                        name, location, rotation, _mat_name = entry
                        print(
                            f"      curved object: {name}, "
                            f"location={tuple(round(v, 4) for v in location)}, "
                            f"rotation={tuple(round(v, 4) for v in rotation)}"
                        )
                print(
                    "  "
                    + format_dimension_validation(
                        f"{frame_obj.name} {side_label} hard panel",
                        details["panel_width_mm"] if details.get("is_curved") else panel_w_mm,
                        details["panel_height_mm"] if details.get("is_curved") else panel_h_mm,
                        details["panel_width_mm"],
                        details["panel_height_mm"],
                    )
                )

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

        curved_frames = [
            frame for frame in frames
            if parse_curved_frame_from_name(frame.name, frame_height_mm=(get_frame_size_mm(frame) or (None, None))[1])
        ]
        straight_frames = [frame for frame in frames if frame not in curved_frames]

        for side_label, offset_mm in sides:
            if straight_frames:
                obj, seg_info = create_smart_seg_panel(
                    context,
                    straight_frames,
                    side_label,
                    offset_mm,
                    replace_existing=props.replace_existing,
                )

                if obj is None:
                    print(f"  [{side_label}] SKIPPED: {seg_info.get('error')}")
                else:
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

            for frame_obj in curved_frames:
                frame_size = get_frame_size_mm(frame_obj)
                frame_height_mm = frame_size[1] if frame_size else None
                array_list = detect_all_array_settings(frame_obj, limit=2)
                curved_face = curved_face_for_panel_side(side_label)
                if curved_face is None:
                    print(
                        f"  [{side_label}] curved SEG SKIPPED {frame_obj.name}: "
                        "curved frames support Front -Y (Outside Curve) and Back +Y (Inside Curve) only."
                    )
                    continue
                panel_count, details = create_or_update_curved_panel_for_frame(
                    frame_obj=frame_obj,
                    side_label=side_label,
                    side_offset_mm=offset_mm,
                    frame_height_mm=frame_height_mm,
                    array_list=array_list,
                    curved_face=curved_face,
                    panel_kind="SEG_CURVED",
                    replace_existing=props.replace_existing,
                )
                if details.get("error"):
                    print(f"  [{side_label}] curved SEG SKIPPED {frame_obj.name}: {details['error']}")
                    continue
                made += panel_count
                cells_total += panel_count
                for entry in details["created"]:
                    name, location, rotation, mat_name = entry
                    print(f"  [{side_label}] curved SEG created: {name} material={mat_name}")
                    print(
                        f"      location={tuple(round(v, 4) for v in location)}, "
                        f"rotation={tuple(round(v, 4) for v in rotation)}"
                    )
                for entry in details["updated"]:
                    name, location, rotation, mat_name = entry
                    print(f"  [{side_label}] curved SEG updated: {name} material={mat_name}")
                    print(
                        f"      location={tuple(round(v, 4) for v in location)}, "
                        f"rotation={tuple(round(v, 4) for v in rotation)}"
                    )
                for name in details["deleted_names"]:
                    print(f"  [{side_label}] curved SEG deleted stale: {name}")
                bounds = details["local_bounds"]
                print(
                    f"  [{side_label}] curved SEG frame: {frame_obj.name}, "
                    f"path={details['detection_path']}, "
                    f"family={details['family_mm']}, "
                    f"R{details['radius_mm']} angle={details['angle_degrees']} deg, "
                    f"selected Panel Side={side_label}, "
                    f"resolved curved side={details['curved_face_label']}, "
                    f"mesh={details['panel_width_mm']} x {details['panel_height_mm']} mm, "
                    f"segments={details['mesh_segment_count']}"
                )
                print(
                    f"      local bounds: "
                    f"x=({bounds['min_x']:.4f}, {bounds['max_x']:.4f}), "
                    f"y=({bounds['min_y']:.4f}, {bounds['max_y']:.4f}), "
                    f"z=({bounds['min_z']:.4f}, {bounds['max_z']:.4f})"
                )
                print(
                    f"      arc: center={tuple(round(v, 4) for v in details['arc_center'])}, "
                    f"radius={details['arc_radius_m']:.4f} m, "
                    f"start={details['arc_start_angle_degrees']:.2f} deg, "
                    f"end={details['arc_end_angle_degrees']:.2f} deg, "
                    f"direction={details['arc_direction']}, "
                    f"fit_score={details['arc_fit_score']:.6f}"
                )
                exp_rot = details["expected_rotation"]
                print(
                    f"      axis: {details['vertical_axis']} vertical | "
                    f"radii outer={details['arc_outer_radius_m']:.4f} "
                    f"inner={details['arc_inner_radius_m']:.4f} m | "
                    f"sweep={details['arc_sweep_degrees']:.2f} deg "
                    f"({details['arc_sweep_source']}, nominal "
                    f"{details['arc_nominal_angle_degrees']:g}) | "
                    f"expected rotation (manual-plane rule)="
                    f"({exp_rot[0]:.3f}, {exp_rot[1]:.3f}, {exp_rot[2]:.3f}) "
                    f"deg, generated rotation=(0, 0, 0) baked"
                )
                print(
                    f"      reference object used: {details.get('reference_curve_object') or 'none (frame-fit fallback)'}"
                )
                print(
                    f"      first vertex={tuple(round(v, 4) for v in details['first_vertex'])}, "
                    f"last vertex={tuple(round(v, 4) for v in details['last_vertex'])}"
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
MM_TO_INCHES = 1.0 / 25.4
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
PRINT_EXPORT_MODE_LABELS = {
    "AUTO": "Auto Detect",
    "STRAIGHT": "Straight Wall",
    "UNFOLD": "Unfold Connected Walls",
    "CURVED_FLAT": "Curved Flat Rectangle",
}
UNFOLD_AXIS_TOLERANCE_DOT = math.cos(math.radians(10.0))
UNFOLD_CORNER_WARNING_M = 0.025
UNFOLD_CORNER_MAX_GAP_M = 0.25
CURVED_0248_ASSET_TOKEN = "B62_0248_CURVE_90_H0992"
CURVED_0248_EXPECTED_IN = {
    "INSIDE": {"width": 12.50, "height": 38.74},
    "OUTSIDE": {"width": 16.08, "height": 38.74},
}
CURVED_EXPORT_WARNING_TOLERANCE_IN = 0.05


def meters_to_inches(value_m):
    """Convert Blender meters to true-size print inches."""
    return value_m * METERS_TO_INCHES


def mm_to_inches(value_mm):
    """Convert official BeMatrix millimeters to true-size print inches."""
    return value_mm * MM_TO_INCHES


def _calibrated_export_dimensions_in(obj, measured_width_m, measured_height_m):
    """
    Return export dimensions from BeMatrix metadata when available.

    Geometry is still used for positions and validation. Width/height labels,
    SVG data attributes, manifest rows, and JSX artboards use the stored
    official dimensions so small Blender transform/bounds drift does not change
    production sizes.
    """
    kind = obj.get("bematrix_panel_kind")
    width_mm = None
    height_mm = None

    if kind == "HARD":
        width_mm = obj.get("bematrix_panel_width_mm")
        height_mm = obj.get("bematrix_panel_height_mm")
    elif kind in {"SEG", "SEG_SMART"}:
        width_mm = obj.get("bematrix_seg_width_mm")
        height_mm = obj.get("bematrix_seg_height_mm")

    try:
        if width_mm is not None and height_mm is not None:
            width_mm = float(width_mm)
            height_mm = float(height_mm)
            if width_mm > 0.0 and height_mm > 0.0:
                return {
                    "width_in": mm_to_inches(width_mm),
                    "height_in": mm_to_inches(height_mm),
                    "width_m": width_mm / 1000.0,
                    "height_m": height_mm / 1000.0,
                    "width_source": "bematrix_metadata",
                    "expected_width_mm": width_mm,
                    "expected_height_mm": height_mm,
                    "measured_width_in": meters_to_inches(measured_width_m),
                    "measured_height_in": meters_to_inches(measured_height_m),
                }
    except (TypeError, ValueError):
        pass

    return {
        "width_in": meters_to_inches(measured_width_m),
        "height_in": meters_to_inches(measured_height_m),
        "width_m": measured_width_m,
        "height_m": measured_height_m,
        "width_source": "geometry",
        "expected_width_mm": None,
        "expected_height_mm": None,
        "measured_width_in": meters_to_inches(measured_width_m),
        "measured_height_in": meters_to_inches(measured_height_m),
    }


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


def _clean_group_abbreviation(value):
    """Normalize a user-facing Print Group abbreviation for IDs and filenames."""
    return re.sub(r"[^A-Z0-9]+", "", (value or "").strip().upper())


def _is_valid_group_abbreviation(value):
    return bool(value) and re.fullmatch(r"[A-Z0-9]+", value) is not None


def _suggest_group_abbreviation(group_name):
    """Suggest a short stable code from a display name, e.g. Back Wall -> BW."""
    words = re.findall(r"[A-Za-z0-9]+", group_name or "")
    if not words:
        return ""
    if len(words) == 1:
        word = words[0].upper()
        return word[:3] if len(word) > 2 else word
    return "".join(word[0].upper() for word in words[:4])


def _unique_group_abbreviation(base_abbr, existing_abbrs):
    """Return a unique abbreviation, keeping the user's suggested base where possible."""
    base = _clean_group_abbreviation(base_abbr)
    if not base:
        return ""
    if base not in existing_abbrs:
        return base
    for index in range(2, 100):
        candidate = f"{base}{index}"
        if candidate not in existing_abbrs:
            return candidate
    return ""


def _group_display_name(group):
    group_name = group.group_name.strip() or "Print Group"
    group_abbr = _clean_group_abbreviation(getattr(group, "group_abbreviation", ""))
    return f"{group_abbr} - {group_name}" if group_abbr else group_name


def _print_group_svg_filename(group):
    """Use the stable abbreviation in filenames when an older group has one."""
    group_name = group.group_name.strip() or "Print Group"
    group_abbr = _clean_group_abbreviation(getattr(group, "group_abbreviation", ""))
    if group_abbr:
        return sanitize_svg_filename(f"{group_abbr}_{group_name}")
    return sanitize_svg_filename(group_name)


def _sanitize_svg_id(value, fallback="item"):
    """Create a stable SVG id fragment that Illustrator can display cleanly."""
    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", (value or "").strip())
    safe = re.sub(r"_+", "_", safe).strip("_")
    if not safe:
        safe = fallback
    if safe[0].isdigit():
        safe = f"{fallback}_{safe}"
    return safe


def _svg_export_options(
    include_print_group_title=True,
    include_panel_labels=True,
    include_artboard_guides=True,
    include_illustrator_artboard_script=True,
    illustrator_template_scale=0.1,
    illustrator_artboard_naming="ABBR_GROUP_NAME_NUMBER",
):
    """Normalize SVG writer options from scene properties or call defaults."""
    try:
        template_scale = float(illustrator_template_scale)
    except (TypeError, ValueError):
        template_scale = 0.1
    if template_scale <= 0:
        template_scale = 0.1
    return {
        "include_print_group_title": bool(include_print_group_title),
        "include_panel_labels": bool(include_panel_labels),
        "include_artboard_guides": bool(include_artboard_guides),
        "include_illustrator_artboard_script": bool(include_illustrator_artboard_script),
        "illustrator_template_scale": template_scale,
        "illustrator_artboard_naming": illustrator_artboard_naming or "ABBR_GROUP_NAME_NUMBER",
    }


def _template_scale_label(scale):
    percent = scale * 100.0
    if abs(percent - round(percent)) < 1e-6:
        return f"{int(round(percent))}%"
    return f"{percent:.2f}%"


def _export_item_top_v(item):
    """
    Top edge in projected Blender/export coordinates.

    Blender/world vertical coordinates increase upward. SVG y coordinates
    increase downward, so SVG top-left placement must measure down from the
    group's highest projected v value.
    """
    return item.get("max_v", item["min_v"] + item.get("height_m", 0.0))


def _artboard_name_for_record(group_abbr, group_name, graphic_id, panel_index, naming_mode):
    safe_group_name = _sanitize_svg_id(group_name or "Print_Group", fallback="Print_Group")
    safe_abbr = _sanitize_svg_id(group_abbr or "", fallback="Group")
    panel_suffix = f"{panel_index:02d}"

    if naming_mode == "GRAPHIC_ID":
        return graphic_id or f"{safe_abbr}{panel_suffix}"
    if naming_mode == "GROUP_NAME_NUMBER":
        return f"{safe_group_name}_{panel_suffix}"
    return f"{safe_abbr}_{safe_group_name}_{panel_suffix}" if group_abbr else f"{safe_group_name}_{panel_suffix}"


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


def _print_export_mode_label(export_mode):
    return PRINT_EXPORT_MODE_LABELS.get(export_mode, str(export_mode))


def _axis_vector_for_direction(direction):
    if direction == "WORLD_Y":
        return Vector((0.0, 1.0, 0.0))
    return Vector((1.0, 0.0, 0.0))


def _classify_world_wall_direction(normal):
    """
    Return the horizontal wall run direction for simple axis-aligned exports.

    A panel whose face normal points mostly along World Y belongs to a wall run
    along World X. A panel whose normal points mostly along World X belongs to a
    wall run along World Y. Phase 5 intentionally supports only this simple
    World X / World Y corner case.
    """
    normal = normal.normalized()
    abs_x = abs(normal.dot(Vector((1.0, 0.0, 0.0))))
    abs_y = abs(normal.dot(Vector((0.0, 1.0, 0.0))))
    abs_z = abs(normal.dot(Vector((0.0, 0.0, 1.0))))

    if abs_z > max(abs_x, abs_y):
        return None
    if abs_y >= UNFOLD_AXIS_TOLERANCE_DOT and abs_y >= abs_x:
        return "WORLD_X"
    if abs_x >= UNFOLD_AXIS_TOLERANCE_DOT and abs_x > abs_y:
        return "WORLD_Y"
    return None


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


def _is_supported_curved_0248_export_panel(obj):
    """Only the first verified curved infill family is enabled for SVG export."""
    if obj is None or obj.type != "MESH":
        return False
    if obj.get("bematrix_panel_kind") != "HARD_CURVED":
        return False
    if int(obj.get("bematrix_curved_family_mm", 0) or 0) == 248:
        return True

    names = [obj.name]
    parent_name = str(obj.get("bematrix_parent_frame", "") or "")
    if parent_name:
        names.append(parent_name)
    if obj.parent is not None:
        names.append(obj.parent.name)
    return any(CURVED_0248_ASSET_TOKEN in name for name in names)


def _curved_export_face(obj):
    face = str(obj.get("bematrix_curved_face", "") or "").upper()
    if face in {"INSIDE", "OUTSIDE"}:
        return face
    side = str(obj.get("bematrix_panel_side", "") or "").upper()
    if side == "BACK":
        return "INSIDE"
    return "OUTSIDE"


def _measure_curved_developed_mesh(obj):
    """
    Measure a generated curved infill as a developed rectangle.

    The generated curved mesh owns the production UV orientation: U follows the
    curve left-to-right and V runs bottom-to-top. Use that UV order to measure
    the actual 3D bottom/top polylines in world space.
    """
    mesh = obj.data
    uv_layer = mesh.uv_layers.active if mesh else None
    if uv_layer is None or not mesh.polygons:
        return None, f"'{obj.name}' has no usable UV map for curved export."

    samples = []
    for poly in mesh.polygons:
        for loop_index in poly.loop_indices:
            vertex_index = mesh.loops[loop_index].vertex_index
            uv = uv_layer.data[loop_index].uv
            point = obj.matrix_world @ mesh.vertices[vertex_index].co
            samples.append((float(uv.x), float(uv.y), point))

    if not samples:
        return None, f"'{obj.name}' has no UV samples for curved export."

    min_v = min(sample[1] for sample in samples)
    max_v = max(sample[1] for sample in samples)
    span_v = max_v - min_v
    if span_v <= 1e-6:
        return None, f"'{obj.name}' has collapsed V coordinates; cannot measure height."

    v_tol = max(1e-5, span_v * 0.10)
    bottom = [(u, p) for u, v, p in samples if abs(v - min_v) <= v_tol]
    top = [(u, p) for u, v, p in samples if abs(v - max_v) <= v_tol]
    if len(bottom) < 2 or len(top) < 2:
        return None, f"'{obj.name}' UV map does not expose bottom/top curve edges."

    def ordered_average_points(edge_samples):
        buckets = {}
        for u, point in edge_samples:
            key = round(u, 6)
            bucket = buckets.setdefault(key, [])
            bucket.append(point)

        ordered = []
        for key in sorted(buckets):
            points = buckets[key]
            avg = Vector((0.0, 0.0, 0.0))
            for point in points:
                avg += point
            avg /= len(points)
            ordered.append((key, avg))
        return ordered

    def polyline_length(ordered_points):
        total = 0.0
        for index in range(len(ordered_points) - 1):
            total += (ordered_points[index + 1][1] - ordered_points[index][1]).length
        return total

    bottom_ordered = ordered_average_points(bottom)
    top_ordered = ordered_average_points(top)
    if len(bottom_ordered) < 2 or len(top_ordered) < 2:
        return None, f"'{obj.name}' has too few curve stations for developed measurement."

    bottom_width_m = polyline_length(bottom_ordered)
    top_width_m = polyline_length(top_ordered)
    width_m = (bottom_width_m + top_width_m) / 2.0

    top_by_u = {u: point for u, point in top_ordered}
    heights = []
    for u, bottom_point in bottom_ordered:
        top_point = top_by_u.get(u)
        if top_point is not None:
            heights.append((top_point - bottom_point).length)
    if not heights:
        height_m = max(
            (top_point - bottom_point).length
            for _bu, bottom_point in bottom_ordered
            for _tu, top_point in top_ordered
        )
    else:
        height_m = sum(heights) / len(heights)

    if width_m <= 1e-6 or height_m <= 1e-6:
        return None, f"'{obj.name}' measured as zero-width or zero-height."

    face = _curved_export_face(obj)
    expected = CURVED_0248_EXPECTED_IN.get(face, CURVED_0248_EXPECTED_IN["OUTSIDE"])
    width_in = meters_to_inches(width_m)
    height_in = meters_to_inches(height_m)
    width_diff_in = width_in - expected["width"]
    height_diff_in = height_in - expected["height"]

    return {
        "width_m": width_m,
        "height_m": height_m,
        "width_in": width_in,
        "height_in": height_in,
        "bottom_width_m": bottom_width_m,
        "top_width_m": top_width_m,
        "face": face,
        "expected_width_in": expected["width"],
        "expected_height_in": expected["height"],
        "width_diff_in": width_diff_in,
        "height_diff_in": height_diff_in,
        "station_count": min(len(bottom_ordered), len(top_ordered)),
    }, None


def _collect_curved_0248_export_data(candidates):
    export_items = []
    warnings = []
    offset_u = 0.0
    gap_m = 0.02

    for obj in sorted(candidates, key=lambda item: item.name):
        measured, error = _measure_curved_developed_mesh(obj)
        if error:
            return None, error, None

        warning = None
        if (
            abs(measured["width_diff_in"]) > CURVED_EXPORT_WARNING_TOLERANCE_IN
            or abs(measured["height_diff_in"]) > CURVED_EXPORT_WARNING_TOLERANCE_IN
        ):
            warning = (
                f"{obj.name}: measured {measured['width_in']:.3f} x "
                f"{measured['height_in']:.3f} in, expected "
                f"{measured['expected_width_in']:.3f} x "
                f"{measured['expected_height_in']:.3f} in "
                f"(diff {measured['width_diff_in']:+.3f}, "
                f"{measured['height_diff_in']:+.3f} in)"
            )
            warnings.append(warning)

        obj["bematrix_curved_developed_width_in"] = measured["width_in"]
        obj["bematrix_curved_developed_height_in"] = measured["height_in"]
        obj["bematrix_curved_svg_expected_width_in"] = measured["expected_width_in"]
        obj["bematrix_curved_svg_expected_height_in"] = measured["expected_height_in"]

        export_items.append({
            "object": obj,
            "center_x": offset_u + measured["width_m"] / 2.0,
            "center_u": offset_u + measured["width_m"] / 2.0,
            "min_u": offset_u,
            "max_u": offset_u + measured["width_m"],
            "min_v": 0.0,
            "max_v": measured["height_m"],
            "width_in": measured["width_in"],
            "height_in": measured["height_in"],
            "width_m": measured["width_m"],
            "height_m": measured["height_m"],
            "width_source": "curved_mesh_developed_uv",
            "expected_width_mm": None,
            "expected_height_mm": None,
            "measured_width_in": measured["width_in"],
            "measured_height_in": measured["height_in"],
            "curved_export": measured,
        })
        offset_u += measured["width_m"] + gap_m

    direction_info = {
        "mode": "CURVED_FLAT",
        "setting": "CURVED_FLAT",
        "resolved": "CURVED_FLAT",
        "warning": " ".join(warnings) if warnings else None,
        "warnings": warnings,
        "details": [
            f"Curved flat rectangle export: {len(export_items)} B62_0248 panel(s)"
        ],
    }
    return export_items, None, direction_info


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

    curved_candidates = [
        obj for obj in candidates if _is_supported_curved_0248_export_panel(obj)
    ]
    if curved_candidates:
        if len(curved_candidates) != len(candidates):
            return None, (
                "B62_0248 curved SVG export currently supports curved panels "
                "by themselves, not mixed with straight panels."
            ), None
        return _collect_curved_0248_export_data(curved_candidates)

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

        calibrated = _calibrated_export_dimensions_in(obj, width_m, height_m)
        export_items.append({
            "object": obj,
            "center_x": item["center"].x,
            "center_u": item["center"].dot(horizontal_axis),
            "min_u": min_u,
            "max_u": max_u,
            "min_v": min_v,
            "max_v": max_v,
            **calibrated,
        })

    export_items.sort(key=lambda item: (item["center_u"], item["object"].name))
    return export_items, None, direction_info


def _segment_bounds_2d(segment):
    direction = segment["direction"]
    along_index = 0 if direction == "WORLD_X" else 1
    cross_index = 1 if direction == "WORLD_X" else 0
    all_points = []
    for item in segment["items"]:
        all_points.extend(item["verts"])

    min_along = min(point[along_index] for point in all_points)
    max_along = max(point[along_index] for point in all_points)
    cross_center = sum(point[cross_index] for point in all_points) / len(all_points)
    return min_along, max_along, cross_center


def _corner_gap_between_segments(segment_a, segment_b):
    """
    Find the nearest pair of World XY endpoints between the two detected runs.

    The unfold order is deterministic (World X then World Y), but the endpoint
    proximity check catches disconnected or ambiguous corner groups before SVG
    export makes a misleading flat layout.
    """
    min_a, max_a, cross_a = _segment_bounds_2d(segment_a)
    min_b, max_b, cross_b = _segment_bounds_2d(segment_b)

    if segment_a["direction"] == "WORLD_X":
        endpoints_a = [
            Vector((min_a, cross_a, 0.0)),
            Vector((max_a, cross_a, 0.0)),
        ]
    else:
        endpoints_a = [
            Vector((cross_a, min_a, 0.0)),
            Vector((cross_a, max_a, 0.0)),
        ]

    if segment_b["direction"] == "WORLD_X":
        endpoints_b = [
            Vector((min_b, cross_b, 0.0)),
            Vector((max_b, cross_b, 0.0)),
        ]
    else:
        endpoints_b = [
            Vector((cross_b, min_b, 0.0)),
            Vector((cross_b, max_b, 0.0)),
        ]

    distances = [
        (endpoint_a - endpoint_b).length
        for endpoint_a in endpoints_a
        for endpoint_b in endpoints_b
    ]
    return min(distances) if distances else None


def _collect_unfold_connected_plane_data(selected_objects):
    """
    Validate and flatten a simple two-segment World X / World Y corner group.

    Segment order is intentionally deterministic for this phase: World X first,
    then World Y. Within each segment, panels sort by their world position along
    that segment direction, preserving real gaps. The measured corner/endcap gap
    between the two detected segments is also preserved in the unfolded SVG.
    """
    candidates = [
        obj
        for obj in selected_objects
        if obj.type == "MESH" and is_generated_panel_object(obj)
    ]

    mode_info = {
        "mode": "UNFOLD",
        "segment_directions": [],
        "warning": None,
        "warnings": [],
        "details": [],
    }

    if not candidates:
        return None, "No selected generated mesh planes found.", mode_info

    unsupported = []
    segments_by_direction = {}

    for obj in candidates:
        if obj.data is None or not obj.data.vertices or not obj.data.polygons:
            return None, f"'{obj.name}' has no mesh plane geometry.", mode_info

        world_verts = _world_vertices_for_object(obj)
        normal = _first_world_polygon_normal(obj, world_verts)
        if normal is None:
            return None, f"'{obj.name}' has no valid polygon normal.", mode_info

        plane_distance = normal.dot(world_verts[0])
        max_local_distance = max(
            abs(normal.dot(point) - plane_distance) for point in world_verts
        )
        if max_local_distance > PLANAR_TOLERANCE_M:
            return None, f"'{obj.name}' is not a flat plane.", mode_info

        center = Vector((0.0, 0.0, 0.0))
        for point in world_verts:
            center += point
        center /= len(world_verts)

        direction = _classify_world_wall_direction(normal)
        if direction is None:
            unsupported.append(obj.name)
            continue

        segment = segments_by_direction.setdefault(direction, {
            "direction": direction,
            "items": [],
        })
        segment["items"].append({
            "object": obj,
            "verts": world_verts,
            "normal": normal,
            "center": center,
        })

    detected_direction_count = len(segments_by_direction) + len(unsupported)
    if unsupported:
        if detected_direction_count > 2:
            return None, "more than two wall directions detected", mode_info
        return None, (
            "could not determine World X / World Y wall direction for: "
            f"{', '.join(unsupported)}"
        ), mode_info

    directions = [direction for direction in ("WORLD_X", "WORLD_Y") if direction in segments_by_direction]
    mode_info["segment_directions"] = directions
    if len(directions) > 2:
        return None, "more than two wall directions detected", mode_info
    if len(directions) != 2:
        detected = ", ".join(_direction_label(direction) for direction in directions) or "none"
        return None, (
            "Unfold Connected Walls requires two perpendicular wall directions; "
            f"detected {detected}."
        ), mode_info

    for direction in directions:
        segment = segments_by_direction[direction]
        reference = segment["items"][0]
        reference_normal = reference["normal"]
        reference_distance = reference_normal.dot(reference["verts"][0])

        for item in segment["items"]:
            if abs(reference_normal.dot(item["normal"])) < NORMAL_DOT_MIN:
                return None, (
                    f"{_direction_label(direction)} segment has bad geometry: "
                    "planes are not approximately parallel."
                ), mode_info
            for point in item["verts"]:
                if abs(reference_normal.dot(point) - reference_distance) > COPLANAR_TOLERANCE_M:
                    return None, (
                        f"{_direction_label(direction)} segment has bad geometry: "
                        "planes are not approximately coplanar."
                    ), mode_info

    gap_m = _corner_gap_between_segments(
        segments_by_direction["WORLD_X"],
        segments_by_direction["WORLD_Y"],
    )
    mode_info["corner_gap_m"] = gap_m
    if gap_m is None or gap_m > UNFOLD_CORNER_MAX_GAP_M:
        return None, "could not determine connected wall order", mode_info
    if gap_m > UNFOLD_CORNER_WARNING_M:
        warning = f"corner gap detected between segments ({meters_to_inches(gap_m):.2f} in)"
        mode_info["warning"] = warning
        mode_info["warnings"].append(warning)

    export_items = []
    offset_u = 0.0
    vertical_axis = Vector((0.0, 0.0, 1.0))

    for direction_index, direction in enumerate(directions):
        segment = segments_by_direction[direction]
        horizontal_axis = _axis_vector_for_direction(direction)
        segment_min_u = None
        segment_max_u = None

        projected_items = []
        for item in segment["items"]:
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
                return None, f"'{obj.name}' has zero-width or zero-height bounds.", mode_info

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
                    "Unfold Connected Walls does not support L-shapes, holes, or curved panels."
                ), mode_info

            segment_min_u = min(min_u, segment_min_u) if segment_min_u is not None else min_u
            segment_max_u = max(max_u, segment_max_u) if segment_max_u is not None else max_u
            calibrated = _calibrated_export_dimensions_in(obj, width_m, height_m)
            projected_items.append({
                "object": obj,
                "center_u": item["center"].dot(horizontal_axis),
                "min_u": min_u,
                "max_u": max_u,
                "min_v": min_v,
                "max_v": max_v,
                "segment_direction": direction,
                **calibrated,
            })

        projected_items.sort(key=lambda item: (item["center_u"], item["object"].name))
        for item in projected_items:
            local_min_u = item["min_u"] - segment_min_u
            local_max_u = item["max_u"] - segment_min_u
            item["min_u"] = offset_u + local_min_u
            item["max_u"] = offset_u + local_max_u
            item["center_u"] = offset_u + (item["center_u"] - segment_min_u)
            export_items.append(item)

        offset_u += segment_max_u - segment_min_u
        if direction_index < len(directions) - 1:
            # Preserve the real world gap between the two unfolded wall runs.
            # This is the same geometry-derived gap that validation reports.
            offset_u += gap_m
        mode_info["details"].append(
            f"{_direction_label(direction)} segment: {len(projected_items)} plane(s)"
        )

    return export_items, None, mode_info


def _svg_for_export_items(export_items, print_group_name=None, export_options=None):
    export_options = export_options or _svg_export_options()
    include_title = bool(print_group_name) and export_options["include_print_group_title"]
    include_labels = export_options["include_panel_labels"]
    include_guides = export_options["include_artboard_guides"]
    template_scale = export_options["illustrator_template_scale"]
    scale_label = _template_scale_label(template_scale)

    min_u = min(item["min_u"] for item in export_items)
    max_u = max(
        item["min_u"] + item.get("width_m", item["max_u"] - item["min_u"])
        for item in export_items
    )
    min_v = min(item["min_v"] for item in export_items)
    max_v = max(_export_item_top_v(item) for item in export_items)

    title_band_in = SVG_TITLE_BAND_IN if include_title else 0.0
    document_width_in = meters_to_inches(max_u - min_u) * template_scale + SVG_MARGIN_IN * 2.0
    document_height_in = (
        meters_to_inches(max_v - min_v) * template_scale + SVG_MARGIN_IN * 2.0 + title_band_in
    )
    document_title = print_group_name or "BeMatrix Print Layout Export"
    panel_label_prefix = print_group_name or "Selected Planes"
    id_prefix = _sanitize_svg_id(panel_label_prefix, fallback="panel")

    def item_svg_rect(item):
        x = meters_to_inches(item["min_u"] - min_u) * template_scale + SVG_MARGIN_IN
        y = meters_to_inches(max_v - _export_item_top_v(item)) * template_scale + SVG_MARGIN_IN + title_band_in
        return x, y, item["width_in"] * template_scale, item["height_in"] * template_scale

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

    if include_title:
        lines.extend([
            '  <g id="print_group_title" fill="#000000" font-family="Arial">',
            (
                f'    <text id="print_group_title_text" '
                f'x="{SVG_MARGIN_IN:.6f}" y="0.420000" '
                f'font-size="{SVG_TITLE_FONT_SIZE_IN:.6f}">'
                f'{escape(print_group_name)}</text>'
            ),
            "  </g>",
        ])

    lines.extend([
        '  <g id="panel_rectangles" fill="none" stroke="#000000" stroke-width="0.01">',
    ])

    for item_index, item in enumerate(export_items, start=1):
        obj = item["object"]
        x, y, width, height = item_svg_rect(item)
        name_attr = escape(obj.name, {'"': "&quot;"})
        lines.append(
            f'    <rect id="panel_{item_index:03d}" '
            f'data-name="{name_attr}" '
            f'data-real-width-in="{item["width_in"]:.6f}" '
            f'data-real-height-in="{item["height_in"]:.6f}" '
            f'data-template-scale="{template_scale:.6f}" '
            f'x="{x:.6f}" y="{y:.6f}" '
            f'width="{width:.6f}" height="{height:.6f}" />'
        )

    lines.append("  </g>")

    if include_guides:
        lines.append(
            '  <g id="artboard_guides" fill="none" stroke="#0070C0" '
            'stroke-width="0.02" stroke-dasharray="0.12 0.08" opacity="0.75">'
        )
        for item_index, item in enumerate(export_items, start=1):
            obj = item["object"]
            x, y, width, height = item_svg_rect(item)
            graphic_id = str(obj.get("bm_graphic_id", "")).strip()
            guide_suffix = _sanitize_svg_id(graphic_id, fallback="panel") if graphic_id else f"{id_prefix}_{item_index:02d}"
            guide_id = f"artboard_{guide_suffix}"
            lines.append(
                f'    <rect id="{guide_id}" '
                f'data-panel-index="{item_index:02d}" '
                f'data-real-width-in="{item["width_in"]:.6f}" '
                f'data-real-height-in="{item["height_in"]:.6f}" '
                f'data-template-scale="{template_scale:.6f}" '
                f'x="{x:.6f}" y="{y:.6f}" '
                f'width="{width:.6f}" height="{height:.6f}" />'
            )
        lines.append("  </g>")

    if include_labels:
        lines.append(
            '  <g id="panel_labels" fill="#000000" font-family="Arial" font-size="0.18">'
        )

        for item_index, item in enumerate(export_items, start=1):
            obj = item["object"]
            x, y, _width, _height = item_svg_rect(item)
            x += 0.12
            y += 0.28
            graphic_id = str(obj.get("bm_graphic_id", "")).strip()
            object_group_name = str(obj.get("bm_print_group_name", "")).strip()
            display_group_name = object_group_name or panel_label_prefix
            production_label = graphic_id or f"{panel_label_prefix} {item_index:02d}"
            object_label = f"Object: {obj.name}"
            size_label = f"Real: {item['width_in']:.2f} in x {item['height_in']:.2f} in"
            scale_text = f"Scale: {scale_label}"
            lines.extend([
                f'    <text id="label_{item_index:03d}" x="{x:.6f}" y="{y:.6f}">',
                f'      <tspan x="{x:.6f}" dy="0">{escape(production_label)}</tspan>',
                f'      <tspan x="{x:.6f}" dy="0.22">{escape(display_group_name)}</tspan>',
                f'      <tspan x="{x:.6f}" dy="0.22">{escape(object_label)}</tspan>',
                f'      <tspan x="{x:.6f}" dy="0.22">{escape(size_label)}</tspan>',
                f'      <tspan x="{x:.6f}" dy="0.22">{escape(scale_text)}</tspan>',
                "    </text>",
            ])
        lines.append("  </g>")

    lines.extend([
        "</svg>",
        "",
    ])
    return "\n".join(lines)


def _collect_export_items_for_mode(objects, direction_setting="AUTO", export_mode="STRAIGHT"):
    """Collect the same ordered export items used by SVG, validation, CSV, and JSX."""
    if export_mode == "UNFOLD":
        return _collect_unfold_connected_plane_data(objects)
    return _collect_export_plane_data(
        objects,
        direction_setting=direction_setting,
    )


def _resolve_export_items_for_mode(objects, direction_setting="AUTO", export_mode="STRAIGHT"):
    """
    Resolve Auto Detect to a concrete export mode and return export items.

    Auto tries the conservative straight-wall path first, then the simple
    two-segment unfold path. It never silently exports with unsupported geometry.
    """
    if export_mode != "AUTO":
        export_items, error, direction_info = _collect_export_items_for_mode(
            objects,
            direction_setting=direction_setting,
            export_mode=export_mode,
        )
        return export_mode, export_items, error, direction_info

    straight_items, straight_error, straight_info = _collect_export_plane_data(
        objects,
        direction_setting=direction_setting,
    )
    if not straight_error:
        if straight_info is None:
            straight_info = {}
        resolved = "CURVED_FLAT" if straight_info.get("mode") == "CURVED_FLAT" else "STRAIGHT"
        straight_info["auto_resolved_mode"] = resolved
        return resolved, straight_items, None, straight_info

    unfold_items, unfold_error, unfold_info = _collect_unfold_connected_plane_data(objects)
    if not unfold_error:
        if unfold_info is None:
            unfold_info = {}
        unfold_info["auto_resolved_mode"] = "UNFOLD"
        return "UNFOLD", unfold_items, None, unfold_info

    error = (
        "Auto Detect could not resolve export mode. "
        f"Straight Wall: {straight_error}; Unfold Connected Walls: {unfold_error}"
    )
    direction_info = unfold_info or straight_info or {}
    direction_info["auto_resolved_mode"] = None
    return None, None, error, direction_info


def _group_export_mode(group):
    return getattr(group, "export_mode", "AUTO") or "AUTO"


def _layout_records_for_export_items(
    export_items,
    print_group_name=None,
    print_group_abbr="",
    export_options=None,
):
    """Return panel/artboard rows using the exact SVG rectangle coordinates."""
    export_options = export_options or _svg_export_options()
    min_u = min(item["min_u"] for item in export_items)
    max_v = max(_export_item_top_v(item) for item in export_items)
    include_title = bool(print_group_name) and export_options["include_print_group_title"]
    title_band_in = SVG_TITLE_BAND_IN if include_title else 0.0
    id_prefix = _sanitize_svg_id(print_group_name or "Selected Planes", fallback="panel")
    template_scale = export_options["illustrator_template_scale"]
    naming_mode = export_options["illustrator_artboard_naming"]

    records = []
    for item_index, item in enumerate(export_items, start=1):
        obj = item["object"]
        graphic_id = str(obj.get("bm_graphic_id", "")).strip()
        group_abbr = str(obj.get("bm_print_group_abbr", "")).strip() or print_group_abbr
        group_name = str(obj.get("bm_print_group_name", "")).strip() or (print_group_name or "")
        artboard_name = _artboard_name_for_record(
            group_abbr,
            group_name or id_prefix,
            graphic_id,
            item_index,
            naming_mode,
        )
        obj["bm_artboard_name"] = artboard_name
        real_x_in = meters_to_inches(item["min_u"] - min_u) + SVG_MARGIN_IN
        real_y_in = meters_to_inches(max_v - _export_item_top_v(item)) + SVG_MARGIN_IN + title_band_in
        records.append({
            "graphic_id": graphic_id,
            "print_group_abbr": group_abbr,
            "print_group_name": group_name,
            "blender_object_name": obj.name,
            "real_width_in": item["width_in"],
            "real_height_in": item["height_in"],
            "template_width_in": item["width_in"] * template_scale,
            "template_height_in": item["height_in"] * template_scale,
            "real_x_in": real_x_in,
            "real_y_in": real_y_in,
            "template_x_in": SVG_MARGIN_IN + ((real_x_in - SVG_MARGIN_IN) * template_scale),
            "template_y_in": title_band_in + SVG_MARGIN_IN + (
                (real_y_in - title_band_in - SVG_MARGIN_IN) * template_scale
            ),
            "template_scale": template_scale,
            "artboard_name": artboard_name,
        })
    return records


def _js_string(value):
    """Escape a Python string for a simple JavaScript string literal."""
    return str(value).replace("\\", "\\\\").replace('"', '\\"')


def _write_artboard_manifest_csv(filepath, records):
    with open(filepath, "w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=[
                "graphic_id",
                "print_group_abbr",
                "print_group_name",
                "blender_object_name",
                "real_width_in",
                "real_height_in",
                "template_width_in",
                "template_height_in",
                "real_x_in",
                "real_y_in",
                "template_x_in",
                "template_y_in",
                "template_scale",
                "artboard_name",
            ],
        )
        writer.writeheader()
        for record in records:
            writer.writerow({
                "graphic_id": record["graphic_id"],
                "print_group_abbr": record["print_group_abbr"],
                "print_group_name": record["print_group_name"],
                "blender_object_name": record["blender_object_name"],
                "real_width_in": f"{record['real_width_in']:.6f}",
                "real_height_in": f"{record['real_height_in']:.6f}",
                "template_width_in": f"{record['template_width_in']:.6f}",
                "template_height_in": f"{record['template_height_in']:.6f}",
                "real_x_in": f"{record['real_x_in']:.6f}",
                "real_y_in": f"{record['real_y_in']:.6f}",
                "template_x_in": f"{record['template_x_in']:.6f}",
                "template_y_in": f"{record['template_y_in']:.6f}",
                "template_scale": f"{record['template_scale']:.6f}",
                "artboard_name": record["artboard_name"],
            })


def _write_illustrator_artboard_jsx(filepath, records):
    lines = [
        "/*",
        "  BeMatrix Illustrator artboard setup script.",
        "  Open the matching SVG first, then run this file via File > Scripts > Other Script.",
        "  Coordinates are exported in inches from Blender and converted to Illustrator points.",
        "*/",
        "(function () {",
        "  if (app.documents.length === 0) {",
        '    alert("Open the exported BeMatrix SVG before running this script.");',
        "    return;",
        "  }",
        "  var doc = app.activeDocument;",
        "  var PT_PER_IN = 72.0;",
        f'  var TEMPLATE_SCALE_LABEL = "{_template_scale_label(records[0]["template_scale"]) if records else "Unknown"}";',
        "  var artboards = [",
    ]

    for index, record in enumerate(records):
        comma = "," if index < len(records) - 1 else ""
        lines.append(
            "    {"
            f'name: "{_js_string(record["artboard_name"])}", '
            f'x: {record["template_x_in"]:.6f}, '
            f'y: {record["template_y_in"]:.6f}, '
            f'w: {record["template_width_in"]:.6f}, '
            f'h: {record["template_height_in"]:.6f}, '
            f'realW: {record["real_width_in"]:.6f}, '
            f'realH: {record["real_height_in"]:.6f}'
            f"}}{comma}"
        )

    lines.extend([
        "  ];",
        "  if (!artboards.length) {",
        '    alert("No BeMatrix artboards were exported for this script.");',
        "    return;",
        "  }",
        "  function isFiniteNumber(value) {",
        "    return typeof value === 'number' && isFinite(value);",
        "  }",
        "  function fmt(value) {",
        "    return isFiniteNumber(value) ? value.toFixed(3) : String(value);",
        "  }",
        "  var baseRect = doc.artboards[0].artboardRect;",
        "  var baseLeft = baseRect[0];",
        "  var baseTop = baseRect[1];",
        "  var created = [];",
        "  var skipped = [];",
        "  for (var i = 0; i < artboards.length; i++) {",
        "    var item = artboards[i];",
        "    var widthPt = item.w * PT_PER_IN;",
        "    var heightPt = item.h * PT_PER_IN;",
        "    var left = baseLeft + (item.x * PT_PER_IN);",
        "    var top = baseTop - (item.y * PT_PER_IN);",
        "    var right = left + widthPt;",
        "    var bottom = top - heightPt;",
        "    var rect = [left, top, right, bottom];",
        "    var debug = item.name + ': left=' + fmt(left) + ', top=' + fmt(top) +",
        "      ', right=' + fmt(right) + ', bottom=' + fmt(bottom) +",
        "      ', width=' + fmt(widthPt) + ', height=' + fmt(heightPt) +",
        "      ', templateW=' + fmt(item.w) + 'in, templateH=' + fmt(item.h) + 'in' +",
        "      ', realW=' + fmt(item.realW) + 'in, realH=' + fmt(item.realH) + 'in';",
        "    if (!isFiniteNumber(left) || !isFiniteNumber(top) ||",
        "        !isFiniteNumber(right) || !isFiniteNumber(bottom) ||",
        "        !isFiniteNumber(widthPt) || !isFiniteNumber(heightPt) ||",
        "        !isFiniteNumber(item.w) || !isFiniteNumber(item.h) ||",
        "        item.w <= 0 || item.h <= 0 ||",
        "        widthPt <= 0 || heightPt <= 0 || right <= left || top <= bottom) {",
        "      skipped.push('Invalid artboard bounds - ' + debug);",
        "      continue;",
        "    }",
        "    try {",
        "      var ab;",
        "      if (created.length === 0 && doc.artboards.length > 0) {",
        "        ab = doc.artboards[0];",
        "        ab.artboardRect = rect;",
        "      } else {",
        "        ab = doc.artboards.add(rect);",
        "      }",
        "      ab.name = item.name;",
        "      created.push(item.name + ' (' + debug + ')');",
        "    } catch (err) {",
        "      skipped.push('Illustrator rejected artboard - ' + debug + ' - ' + err);",
        "    }",
        "  }",
        "  if (created.length > 0) {",
        "    doc.artboards.setActiveArtboardIndex(0);",
        "  }",
        "  var message = 'Created ' + created.length + ' named artboard(s)';",
        "  message += '\\nTemplate scale: ' + TEMPLATE_SCALE_LABEL;",
        "  message += '\\nBase artboard rect: [' + fmt(baseRect[0]) + ', ' + fmt(baseRect[1]) + ', ' + fmt(baseRect[2]) + ', ' + fmt(baseRect[3]) + ']';",
        "  if (created.length > 0) {",
        "    message += '\\n\\nArtboards created:\\n';",
        "    for (var c = 0; c < created.length; c++) {",
        "      message += created[c].split(' ')[0] + '\\n';",
        "    }",
        "  }",
        "  if (skipped.length > 0) {",
        "    message += '\\n\\nSkipped ' + skipped.length + ' invalid row(s):\\n' + skipped.join('\\n');",
        "  }",
        "  alert(message);",
        "}());",
        "",
    ])

    with open(filepath, "w", encoding="utf-8") as jsx_file:
        jsx_file.write("\n".join(lines))


def _write_illustrator_artboard_companions(svg_filepath, export_items, group, export_options):
    """Write the CSV manifest and Illustrator JSX next to a Print Group SVG."""
    base_path, _ext = os.path.splitext(svg_filepath)
    manifest_path = f"{base_path}_manifest.csv"
    jsx_path = f"{base_path}_artboards.jsx"
    records = _layout_records_for_export_items(
        export_items,
        print_group_name=group.group_name.strip() or "Print Group",
        print_group_abbr=_clean_group_abbreviation(getattr(group, "group_abbreviation", "")),
        export_options=export_options,
    )
    _write_artboard_manifest_csv(manifest_path, records)
    _write_illustrator_artboard_jsx(jsx_path, records)
    return manifest_path, jsx_path


def _print_curved_export_debug(
    export_items,
    svg_path,
    jsx_path=None,
    records=None,
    manifest_rows=None,
    export_options=None,
):
    curved_items = [item for item in export_items if item.get("curved_export")]
    if not curved_items:
        return

    records_by_name = {
        record["blender_object_name"]: record
        for record in (records or [])
    }
    manifest_by_name = {
        row["blender_object_name"]: row
        for row in (manifest_rows or [])
    }
    template_scale = (
        export_options or _svg_export_options()
    )["illustrator_template_scale"]

    print("\n=== BeMatrix Curved SVG Export Debug ===")
    for item in curved_items:
        obj = item["object"]
        measured = item["curved_export"]
        record = records_by_name.get(obj.name)
        manifest = manifest_by_name.get(obj.name)
        print(f"  object name: {obj.name}")
        print(f"  detected curved panel: {CURVED_0248_ASSET_TOKEN} ({measured['face'].title()} Panel)")
        print(f"  measured developed width: {measured['width_in']:.6f} in")
        print(f"  measured panel height: {measured['height_in']:.6f} in")
        print(f"  expected width: {measured['expected_width_in']:.6f} in")
        print(f"  expected height: {measured['expected_height_in']:.6f} in")
        print(f"  width difference: {measured['width_diff_in']:+.6f} in")
        print(f"  height difference: {measured['height_diff_in']:+.6f} in")
        print(f"  SVG width: {item['width_in']:.6f} in")
        print(f"  SVG height: {item['height_in']:.6f} in")
        print(f"  template scale: {template_scale:.6f} ({_template_scale_label(template_scale)})")
        if record:
            print(
                "  manifest values: "
                f"real={record['real_width_in']:.6f} x {record['real_height_in']:.6f} in, "
                f"template={record['template_width_in']:.6f} x "
                f"{record['template_height_in']:.6f} in, "
                f"artboard={record['artboard_name']}"
            )
        elif manifest:
            print(
                "  manifest values: "
                f"real={manifest['real_width_in']} x {manifest['real_height_in']} in, "
                f"template={manifest['template_width_in']} x "
                f"{manifest['template_height_in']} in"
            )
        else:
            print("  manifest values: not written for this export action")
        print(f"  SVG output path: {svg_path}")
        print(f"  JSX output path: {jsx_path or '(not generated)'}")


SUPPORTED_ARTWORK_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp"}


def _normalize_match_text(value):
    return re.sub(r"[^a-z0-9]+", "", (value or "").lower())


def _artwork_material_name(graphic_id, obj):
    safe_id = _sanitize_svg_id(graphic_id or obj.name, fallback="ART")
    return f"MAT_ART_{safe_id}"


def _image_datablock_for_path(filepath):
    abs_path = os.path.abspath(filepath)
    for image in bpy.data.images:
        try:
            if image.filepath and os.path.abspath(bpy.path.abspath(image.filepath)) == abs_path:
                image.reload()
                return image
        except RuntimeError:
            continue
    return bpy.data.images.load(abs_path, check_existing=True)


def _configure_artwork_material(mat, image):
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    principled = nodes.get("Principled BSDF")
    if principled is None:
        principled = nodes.new(type="ShaderNodeBsdfPrincipled")

    tex_node = nodes.get("BM Artwork Image")
    if tex_node is None:
        tex_node = nodes.new(type="ShaderNodeTexImage")
        tex_node.name = "BM Artwork Image"
        tex_node.label = "BM Artwork Image"
    tex_node.image = image

    if "Base Color" in principled.inputs:
        input_socket = principled.inputs["Base Color"]
        for link in list(input_socket.links):
            links.remove(link)
        links.new(tex_node.outputs["Color"], input_socket)
    if "Alpha" in principled.inputs and "Alpha" in tex_node.outputs:
        alpha_socket = principled.inputs["Alpha"]
        for link in list(alpha_socket.links):
            links.remove(link)
        links.new(tex_node.outputs["Alpha"], alpha_socket)
        mat.blend_method = "BLEND"
    if "Roughness" in principled.inputs:
        principled.inputs["Roughness"].default_value = 0.5
    if "Specular IOR Level" in principled.inputs:
        principled.inputs["Specular IOR Level"].default_value = 0.0
    elif "Specular" in principled.inputs:
        principled.inputs["Specular"].default_value = 0.0
    return mat


def _assign_artwork_material(obj, image_path, graphic_id):
    image = _image_datablock_for_path(image_path)
    mat_name = _artwork_material_name(graphic_id, obj)
    mat = bpy.data.materials.get(mat_name)
    if mat is None:
        mat = bpy.data.materials.new(mat_name)
    _configure_artwork_material(mat, image)

    if obj.data.materials:
        obj.data.materials[0] = mat
    else:
        obj.data.materials.append(mat)
    obj["bm_artwork_image_path"] = os.path.abspath(image_path)
    return mat


def _uv_layer_is_valid(mesh):
    uv_layer = mesh.uv_layers.active
    if uv_layer is None or not mesh.polygons:
        return False
    values = [loop.uv.copy() for loop in uv_layer.data]
    if not values:
        return False
    min_u = min(uv.x for uv in values)
    max_u = max(uv.x for uv in values)
    min_v = min(uv.y for uv in values)
    max_v = max(uv.y for uv in values)
    return (max_u - min_u) > 1e-5 and (max_v - min_v) > 1e-5


def _dominant_positive_axis(axis):
    if axis.length < 1e-9:
        return axis
    axis = axis.normalized()
    components = [abs(axis.x), abs(axis.y), abs(axis.z)]
    dominant = components.index(max(components))
    if axis[dominant] < 0:
        axis = -axis
    return axis


def _ensure_panel_uvs(obj):
    """
    Create or repair a rectangular 0-1 UV map for generated graphic planes.

    Existing non-collapsed UVs are preserved. Missing/collapsed UVs are rebuilt
    from world-space vertex positions so parented/rotated panels map correctly.
    """
    mesh = obj.data
    if mesh is None or not mesh.vertices or not mesh.polygons:
        return False, "no mesh geometry"
    if _uv_layer_is_valid(mesh):
        return False, None

    uv_layer = mesh.uv_layers.active
    if uv_layer is None:
        uv_layer = mesh.uv_layers.new(name="UVMap")
    mesh.uv_layers.active = uv_layer

    world_verts = _world_vertices_for_object(obj)
    normal = _first_world_polygon_normal(obj, world_verts)
    if normal is None:
        return False, "no valid polygon normal"

    vertical = Vector((0.0, 0.0, 1.0))
    vertical = vertical - normal * vertical.dot(normal)
    if vertical.length < 1e-9:
        longest_edge = None
        longest_len = 0.0
        for poly in mesh.polygons:
            verts = list(poly.vertices)
            for idx, vert_index in enumerate(verts):
                edge = world_verts[verts[(idx + 1) % len(verts)]] - world_verts[vert_index]
                if edge.length > longest_len:
                    longest_edge = edge
                    longest_len = edge.length
        if longest_edge is None or longest_edge.length < 1e-9:
            return False, "could not determine UV axis"
        vertical = longest_edge
    vertical = _dominant_positive_axis(vertical)

    horizontal = vertical.cross(normal)
    if horizontal.length < 1e-9:
        return False, "could not determine UV horizontal axis"
    horizontal = _dominant_positive_axis(horizontal)

    h_values = [point.dot(horizontal) for point in world_verts]
    v_values = [point.dot(vertical) for point in world_verts]
    min_h = min(h_values)
    max_h = max(h_values)
    min_v = min(v_values)
    max_v = max(v_values)
    span_h = max_h - min_h
    span_v = max_v - min_v
    if span_h <= 1e-9 or span_v <= 1e-9:
        return False, "collapsed panel bounds"

    for poly in mesh.polygons:
        for loop_index in poly.loop_indices:
            vertex_index = mesh.loops[loop_index].vertex_index
            point = world_verts[vertex_index]
            u = (point.dot(horizontal) - min_h) / span_h
            v = (point.dot(vertical) - min_v) / span_v
            uv_layer.data[loop_index].uv = (
                max(0.0, min(1.0, u)),
                max(0.0, min(1.0, v)),
            )
    mesh.update()
    return True, None


def _targets_for_artwork_apply(props):
    groups = []
    if props.apply_artwork_active_group_only:
        group = _active_print_group(props)
        if group is not None:
            groups.append(group)
    else:
        groups = list(props.print_groups)

    targets = []
    seen = set()
    skipped_refs = 0
    for group in groups:
        objects, missing, invalid = _resolve_print_group_objects(group)
        skipped_refs += len(missing) + len(invalid)
        ordered_objects, _order_error = _ordered_group_objects_for_graphic_ids(
            objects,
            direction_setting=props.straight_wall_direction,
            export_mode=_group_export_mode(group),
        )
        group_abbr = _clean_group_abbreviation(getattr(group, "group_abbreviation", ""))
        group_name = group.group_name.strip() or "Print Group"
        for index, obj in enumerate(ordered_objects, start=1):
            if obj.name in seen:
                continue
            seen.add(obj.name)
            graphic_id = str(obj.get("bm_graphic_id", "")).strip()
            obj_group_abbr = str(obj.get("bm_print_group_abbr", "")).strip() or group_abbr
            obj_group_name = str(obj.get("bm_print_group_name", "")).strip() or group_name
            artboard_name = str(obj.get("bm_artboard_name", "")).strip()
            if not artboard_name:
                artboard_name = _artboard_name_for_record(
                    obj_group_abbr,
                    obj_group_name,
                    graphic_id,
                    index,
                    props.illustrator_artboard_naming,
                )
                obj["bm_artboard_name"] = artboard_name
            targets.append({
                "object": obj,
                "graphic_id": graphic_id,
                "artboard_name": artboard_name,
            })
    return targets, skipped_refs


class BEMATRIX_OT_ApplyArtworkFromFolder(bpy.types.Operator):
    bl_idname = "bematrix.apply_artwork_from_folder"
    bl_label = "Apply Artwork From Folder"
    bl_description = "Apply exported artwork images to generated panels by Graphic ID or artboard name"
    bl_options = {"REGISTER", "UNDO"}

    directory: bpy.props.StringProperty(
        name="Artwork Folder",
        description="Folder containing artwork images exported from Illustrator",
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
        folder_path = _directory_path_from_operator(self)
        if not folder_path or not os.path.isdir(folder_path):
            self.report({"ERROR"}, "Choose a valid artwork folder.")
            return {"CANCELLED"}

        image_files = []
        for entry in os.scandir(folder_path):
            if entry.is_file():
                ext = os.path.splitext(entry.name)[1].lower()
                if ext in SUPPORTED_ARTWORK_EXTENSIONS:
                    image_files.append(entry.path)

        targets, skipped_refs = _targets_for_artwork_apply(props)
        if not targets:
            props.artwork_apply_status = "No target Print Group objects found."
            self.report({"ERROR"}, props.artwork_apply_status)
            return {"CANCELLED"}

        image_matches = {path: [] for path in image_files}
        target_matches = {}
        for target in targets:
            tokens = [
                _normalize_match_text(target["graphic_id"]),
                _normalize_match_text(target["artboard_name"]),
            ]
            tokens = [token for token in tokens if token]
            matches = []
            for image_path in image_files:
                file_token = _normalize_match_text(os.path.splitext(os.path.basename(image_path))[0])
                if any(token in file_token for token in tokens):
                    matches.append(image_path)
                    image_matches[image_path].append(target)
            target_matches[target["object"].name] = matches

        applied = 0
        missing = 0
        duplicate_targets = set()
        errors = 0
        skipped = skipped_refs
        repaired_uvs = 0
        warnings = []
        conflict_images = {
            path: matched_targets
            for path, matched_targets in image_matches.items()
            if len(matched_targets) > 1
        }

        for target in targets:
            obj = target["object"]
            matches = target_matches.get(obj.name, [])
            if obj.type != "MESH":
                skipped += 1
                continue
            if not matches:
                missing += 1
                continue
            if len(matches) > 1:
                duplicate_targets.add(obj.name)
                continue
            image_path = matches[0]
            if image_path in conflict_images:
                duplicate_targets.add(obj.name)
                continue
            try:
                repaired_uv, uv_error = _ensure_panel_uvs(obj)
                if repaired_uv:
                    repaired_uvs += 1
                elif uv_error:
                    warnings.append(f"UV warning {obj.name}: {uv_error}")
                _assign_artwork_material(obj, image_path, target["graphic_id"])
                applied += 1
            except Exception as exc:
                errors += 1
                warnings.append(f"{obj.name}: {exc}")

        duplicate_conflicts = len(duplicate_targets)
        report = (
            f"Applied {applied} images, repaired UVs on {repaired_uvs} planes, {missing} missing, "
            f"{duplicate_conflicts} duplicates, {errors} errors, {skipped} skipped."
        )
        if warnings:
            report = f"{report}\n" + "\n".join(warnings[:3])
        props.artwork_apply_status = report

        if errors or duplicate_conflicts:
            self.report({"WARNING"}, report.splitlines()[0])
        else:
            self.report({"INFO"}, report.splitlines()[0])
        return {"FINISHED"}


def export_planes_to_svg(
    context,
    objects,
    filepath,
    print_group_name=None,
    direction_setting="AUTO",
    export_mode="STRAIGHT",
    export_options=None,
):
    """
    Export generated plane objects to SVG.

    Returns (count, error_message). The caller is responsible for Blender
    reports so selected-export and group-export can add context-specific warnings.
    """
    resolved_mode, export_items, error, direction_info = _resolve_export_items_for_mode(
        objects,
        direction_setting=direction_setting,
        export_mode=export_mode,
    )
    if error:
        return 0, error, direction_info

    if not filepath.lower().endswith(".svg"):
        filepath += ".svg"

    export_options = export_options or _svg_export_options()
    svg_text = _svg_for_export_items(
        export_items,
        print_group_name=print_group_name,
        export_options=export_options,
    )

    try:
        with open(filepath, "w", encoding="utf-8") as svg_file:
            svg_file.write(svg_text)
    except OSError as exc:
        return 0, f"Unable to write SVG: {exc}", direction_info

    records = _layout_records_for_export_items(
        export_items,
        print_group_name=print_group_name or "Selected Planes",
        print_group_abbr="",
        export_options=export_options,
    )
    _print_curved_export_debug(
        export_items,
        filepath,
        jsx_path=None,
        records=records,
        manifest_rows=None,
        export_options=export_options,
    )

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
    max_u = max(
        item["min_u"] + item.get("width_m", item["max_u"] - item["min_u"])
        for item in export_items
    )
    min_v = min(item["min_v"] for item in export_items)
    max_v = max(
        item["min_v"] + item.get("height_m", item["max_v"] - item["min_v"])
        for item in export_items
    )
    return meters_to_inches(max_u - min_u), meters_to_inches(max_v - min_v)


def _direction_summary(direction_info):
    if not direction_info:
        return "direction unknown"
    if direction_info.get("mode") == "CURVED_FLAT":
        return "curved mesh developed to flat rectangle"
    if direction_info.get("mode") == "UNFOLD":
        directions = direction_info.get("segment_directions") or []
        if directions:
            labels = " then ".join(_direction_label(direction) for direction in directions)
            return f"2 segments detected: {labels}"
        return "segments unknown"
    setting = direction_info.get("setting")
    resolved = direction_info.get("resolved")
    if setting == "AUTO":
        return f"direction Auto Detect -> {_direction_label(resolved)}"
    return f"direction {_direction_label(resolved)}"


def _export_info_warning(direction_info):
    if not direction_info:
        return None
    warning = direction_info.get("warning")
    if warning:
        return warning
    warnings = direction_info.get("warnings")
    if warnings:
        return " ".join(warnings)
    return None


def _export_info_report_label(direction_info, export_mode):
    if direction_info and direction_info.get("mode") == "CURVED_FLAT":
        return _print_export_mode_label("CURVED_FLAT")
    if export_mode == "AUTO" and direction_info:
        resolved_mode = direction_info.get("auto_resolved_mode")
        if resolved_mode:
            return f"Auto Detect -> {_print_export_mode_label(resolved_mode)}"
    if export_mode == "UNFOLD":
        return f"{_print_export_mode_label(export_mode)}, {_direction_summary(direction_info)}"
    if direction_info and direction_info.get("resolved"):
        return _direction_label(direction_info["resolved"])
    return _print_export_mode_label(export_mode)


def _validate_print_group(group, direction_setting="AUTO", export_mode="STRAIGHT"):
    group_name = _group_display_name(group)
    mode_setting_label = _print_export_mode_label(export_mode)
    object_names = [
        item.object_name
        for item in group.objects
        if item.object_name
    ]

    if not object_names:
        return {
            "severity": "ERROR",
            "group_name": group_name,
            "line": f"{group_name}: ERROR - {mode_setting_label}, No objects stored in Print Group.",
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
                "line": f"{group_name}: ERROR - {mode_setting_label}, Missing object: {object_name}",
                "details": details,
            }

        if obj.type != "MESH":
            return {
                "severity": "ERROR",
                "group_name": group_name,
                "line": f"{group_name}: ERROR - {mode_setting_label}, Object is not a mesh: {object_name}",
                "details": details,
            }

        if not is_generated_panel_object(obj):
            return {
                "severity": "ERROR",
                "group_name": group_name,
                "line": f"{group_name}: ERROR - {mode_setting_label}, Object is not a generated BeMatrix panel/SEG plane: {object_name}",
                "details": details,
            }

        if obj.data is None or not obj.data.vertices or not obj.data.polygons:
            return {
                "severity": "ERROR",
                "group_name": group_name,
                "line": f"{group_name}: ERROR - {mode_setting_label}, Object has no usable mesh geometry: {object_name}",
                "details": details,
            }

        objects.append(obj)

    resolved_mode, export_items, error, direction_info = _resolve_export_items_for_mode(
        objects,
        direction_setting=direction_setting,
        export_mode=export_mode,
    )
    mode_summary_label = (
        f"Auto Detect -> {_print_export_mode_label(resolved_mode)}"
        if export_mode == "AUTO" and resolved_mode
        else mode_setting_label
    )
    if error:
        return {
            "severity": "ERROR",
            "group_name": group_name,
            "line": (
                f"{group_name}: ERROR - {mode_setting_label}, "
                f"{error}; {_direction_summary(direction_info)}"
            ),
            "details": details,
            "direction_info": direction_info,
        }

    total_width_in, total_height_in = _summarize_export_items(export_items)
    panel_heights = [item["height_in"] for item in export_items]
    warnings = []
    info_warning = _export_info_warning(direction_info)
    if info_warning:
        warnings.append(info_warning)
    if panel_heights and (max(panel_heights) - min(panel_heights)) > 0.125:
        warnings.append("Plane heights differ.")

    mode_summary = f"{mode_summary_label}, {_direction_summary(direction_info)}"
    if warnings:
        line = (
            f"{group_name}: WARNING - {len(export_items)} planes, approx "
            f"{total_width_in:.2f} in wide x {total_height_in:.2f} in high, "
            f"{mode_summary}; "
            f"{' '.join(warnings)}"
        )
        severity = "WARNING"
    else:
        line = (
            f"{group_name}: OK - {len(export_items)} planes, approx "
            f"{total_width_in:.2f} in wide x {total_height_in:.2f} in high, "
            f"{mode_summary}"
        )
        severity = "OK"

    return {
        "severity": severity,
        "group_name": group_name,
        "line": line,
        "details": details + (direction_info.get("details", []) if direction_info else []) + warnings,
        "direction_info": direction_info,
    }


def _set_validation_status(props, lines):
    props.print_group_validation_status = "\n".join(lines) if lines else "No validation result."


def _ordered_group_objects_for_graphic_ids(
    objects,
    direction_setting="AUTO",
    export_mode="STRAIGHT",
):
    """Use export layout order for stable Graphic IDs when geometry validates."""
    _resolved_mode, export_items, error, _direction_info = _resolve_export_items_for_mode(
        objects,
        direction_setting=direction_setting,
        export_mode=export_mode,
    )
    if error or not export_items:
        return list(objects), error
    return [item["object"] for item in export_items], None


class BEMATRIX_OT_GeneratePrintGroupGraphicIDs(bpy.types.Operator):
    bl_idname = "bematrix.generate_print_group_graphic_ids"
    bl_label = "Generate IDs"
    bl_description = (
        "Assign stable Graphic IDs such as BW01 to generated panel objects "
        "stored in Print Groups"
    )
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        props = context.scene.bematrix_panel_props
        if not props.print_groups:
            self.report({"ERROR"}, "No Print Groups have been created.")
            return {"CANCELLED"}

        used_abbrs = set()
        assigned_count = 0
        skipped_groups = 0
        migrated_groups = 0
        fallback_groups = 0

        for group in props.print_groups:
            group_name = group.group_name.strip() or "Print Group"
            raw_abbr = getattr(group, "group_abbreviation", "").strip()
            if raw_abbr:
                group_abbr = _clean_group_abbreviation(raw_abbr)
                if group_abbr != raw_abbr.upper() or not _is_valid_group_abbreviation(group_abbr):
                    self.report(
                        {"ERROR"},
                        f"Print Group '{group_name}' has an invalid abbreviation. "
                        "Use uppercase letters and numbers only.",
                    )
                    return {"CANCELLED"}
                if group_abbr in used_abbrs:
                    self.report(
                        {"ERROR"},
                        f"Duplicate Print Group abbreviation '{group_abbr}'.",
                    )
                    return {"CANCELLED"}
            else:
                group_abbr = _unique_group_abbreviation(
                    _suggest_group_abbreviation(group_name),
                    used_abbrs,
                )
                if not group_abbr:
                    self.report(
                        {"ERROR"},
                        f"Print Group '{group_name}' needs a Group Abbreviation.",
                    )
                    return {"CANCELLED"}
                group.group_abbreviation = group_abbr
                migrated_groups += 1

            used_abbrs.add(group_abbr)

            objects, missing, invalid = _resolve_print_group_objects(group)
            if not objects:
                skipped_groups += 1
                continue

            ordered_objects, order_error = _ordered_group_objects_for_graphic_ids(
                objects,
                direction_setting=props.straight_wall_direction,
                export_mode=_group_export_mode(group),
            )
            if order_error:
                fallback_groups += 1

            for index, obj in enumerate(ordered_objects, start=1):
                obj["bm_graphic_id"] = f"{group_abbr}{index:02d}"
                obj["bm_print_group_abbr"] = group_abbr
                obj["bm_print_group_name"] = group_name
                assigned_count += 1

        message = (
            f"Generated/refreshed {assigned_count} Graphic ID(s)"
            f" across {len(props.print_groups)} Print Group(s)."
        )
        extras = []
        if migrated_groups:
            extras.append(f"{migrated_groups} abbreviation(s) suggested")
        if skipped_groups:
            extras.append(f"{skipped_groups} empty/invalid group(s) skipped")
        if fallback_groups:
            extras.append(f"{fallback_groups} group(s) used stored object order")
        if extras:
            message = f"{message} {'; '.join(extras)}."

        self.report({"INFO"}, message)
        return {"FINISHED"}


class BEMATRIX_OT_ExportSelectedPlanesToSVG(bpy.types.Operator, ExportHelper):
    bl_idname = "bematrix.export_selected_planes_svg"
    bl_label = "Export Selected"
    bl_description = (
        "Export selected generated hard-panel or SEG plane objects as a "
        "true-size SVG using the active Print Group export mode, or Auto Detect"
    )
    bl_options = {"REGISTER"}

    filename_ext = ".svg"
    filter_glob: bpy.props.StringProperty(
        default="*.svg",
        options={"HIDDEN"},
    )

    def execute(self, context):
        props = context.scene.bematrix_panel_props
        active_group = _active_print_group(props)
        export_mode = _group_export_mode(active_group) if active_group is not None else "AUTO"
        count, error, direction_info = export_planes_to_svg(
            context,
            context.selected_objects,
            self.filepath,
            direction_setting=props.straight_wall_direction,
            export_mode=export_mode,
            export_options=_svg_export_options(
                include_print_group_title=props.include_print_group_title,
                include_panel_labels=props.include_panel_labels,
                include_artboard_guides=props.include_artboard_guides,
                include_illustrator_artboard_script=False,
                illustrator_template_scale=props.illustrator_template_scale,
                illustrator_artboard_naming=props.illustrator_artboard_naming,
            ),
        )
        if error is not None:
            self.report({"ERROR"}, error)
            return {"CANCELLED"}

        report_label = _export_info_report_label(direction_info, export_mode)
        info_warning = _export_info_warning(direction_info)
        if info_warning:
            self.report(
                {"WARNING"},
                f"Exported {count} selected plane(s) using "
                f"{report_label}; {info_warning}",
            )
            return {"FINISHED"}

        self.report(
            {"INFO"},
            f"Exported {count} selected plane(s) to SVG using "
            f"{report_label}.",
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

        existing_abbrs = {
            _clean_group_abbreviation(getattr(group, "group_abbreviation", ""))
            for group in props.print_groups
            if _clean_group_abbreviation(getattr(group, "group_abbreviation", ""))
        }
        group_abbr = _unique_group_abbreviation(
            _suggest_group_abbreviation(group_name),
            existing_abbrs,
        )
        if not group_abbr:
            self.report({"ERROR"}, "Could not suggest a Group Abbreviation from the Group Name.")
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
        group.group_abbreviation = group_abbr
        for obj in planes:
            item = group.objects.add()
            item.object_name = obj.name

        collection = _ensure_print_group_collection(context, group_name, planes)
        props.active_print_group = str(len(props.print_groups) - 1)

        self.report(
            {"INFO"},
            f"Created Print Group '{group_abbr} - {group_name}' with {len(planes)} plane(s). "
            f"Linked to collection '{collection.name}'.",
        )
        return {"FINISHED"}


class BEMATRIX_OT_SelectPrintGroupObjects(bpy.types.Operator):
    bl_idname = "bematrix.select_print_group_objects"
    bl_label = "Select Objects"
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
    bl_label = "Validate Active"
    bl_description = "Check whether the active Print Group is safe for the selected SVG export mode"
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
            export_mode=_group_export_mode(group),
        )
        _set_validation_status(props, [result["line"]])
        print("\n=== BeMatrix Print Group Validation ===")
        print(f"Export mode: {_print_export_mode_label(_group_export_mode(group))}")
        if _group_export_mode(group) in {"AUTO", "STRAIGHT"}:
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
    bl_label = "Validate All"
    bl_description = "Check every saved Print Group for the selected SVG export mode"
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
        print("Export mode: per Print Group")
        print(f"Direction setting: {_direction_label(props.straight_wall_direction)}")
        for group in props.print_groups:
            result = _validate_print_group(
                group,
                direction_setting=props.straight_wall_direction,
                export_mode=_group_export_mode(group),
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


def _create_project_export_folders(parent_folder):
    base_name = "Project_Graphics_Export"
    project_folder = os.path.join(parent_folder, base_name)
    if os.path.exists(project_folder):
        for index in range(1, 1000):
            candidate = os.path.join(parent_folder, f"{base_name}_{index:03d}")
            if not os.path.exists(candidate):
                project_folder = candidate
                break
    os.makedirs(project_folder, exist_ok=False)
    folders = {
        "project": project_folder,
        "svg": os.path.join(project_folder, "SVG"),
        "illustrator": os.path.join(project_folder, "Illustrator"),
        "metadata": os.path.join(project_folder, "Metadata"),
        "exports": os.path.join(project_folder, "Exports"),
        "logs": os.path.join(project_folder, "Logs"),
    }
    # Backward-compatible internal aliases for existing export code paths.
    folders["scripts"] = folders["illustrator"]
    folders["manifest"] = folders["metadata"]
    folders["artwork"] = folders["exports"]
    for folder in folders.values():
        os.makedirs(folder, exist_ok=True)
    return folders


def _write_project_manifest_csv(filepath, rows):
    with open(filepath, "w", encoding="utf-8", newline="") as csv_file:
        fieldnames = [
            "svg_file",
            "jsx_file",
            "print_group_abbr",
            "print_group_name",
            "export_mode_setting",
            "export_mode_resolved",
            "graphic_id",
            "artboard_name",
            "blender_object_name",
            "real_width_in",
            "real_height_in",
            "template_width_in",
            "template_height_in",
            "real_x_in",
            "real_y_in",
            "template_x_in",
            "template_y_in",
            "template_scale",
        ]
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _project_relative_path(*parts):
    return "/".join(parts)


def _json_safe_number(value):
    if value is None:
        return None
    try:
        return round(float(value), 6)
    except (TypeError, ValueError):
        return None


def _blend_file_name():
    filepath = getattr(bpy.data, "filepath", "")
    if filepath:
        return os.path.basename(filepath)
    return None


def _project_name_for_metadata(folders):
    filepath = getattr(bpy.data, "filepath", "")
    if filepath:
        return os.path.splitext(os.path.basename(filepath))[0]
    return os.path.basename(folders["project"])


def _source_unit_metadata(context):
    unit_settings = getattr(context.scene, "unit_settings", None)
    if unit_settings is None:
        return None
    return {
        "system": unit_settings.system,
        "scaleLength": _json_safe_number(unit_settings.scale_length),
        "lengthUnit": unit_settings.length_unit,
    }


def _segment_names_from_direction_info(direction_info):
    if not direction_info:
        return []
    directions = direction_info.get("segment_directions") or []
    return [_direction_label(direction) for direction in directions]


def _notes_for_export_result(result):
    notes = []
    export_mode = result.get("export_mode")
    resolved_mode = result.get("resolved_export_mode")
    direction_info = result.get("direction_info") or {}

    if export_mode:
        if export_mode == "AUTO" and resolved_mode:
            notes.append(f"Auto Detect -> {_print_export_mode_label(resolved_mode)}")
        else:
            notes.append(_print_export_mode_label(export_mode))
    if direction_info:
        summary = _direction_summary(direction_info)
        if summary and summary != "direction unknown":
            notes.append(summary)
        corner_gap_m = direction_info.get("corner_gap_m")
        if corner_gap_m is not None:
            notes.append(f"corner_gap_in={meters_to_inches(corner_gap_m):.2f}")
        warning = _export_info_warning(direction_info)
        if warning:
            notes.append(warning)
        for detail in direction_info.get("details", []):
            if detail not in notes:
                notes.append(detail)
    if result.get("jsx_path"):
        notes.append("JSX generated")
    if result.get("error"):
        notes.append(result["error"])
    return notes


def _metadata_entry_for_result(result):
    svg_filename = os.path.basename(result.get("filepath") or "") if result.get("filepath") else None
    if not svg_filename:
        svg_relative_path = None
    elif result.get("ok"):
        svg_relative_path = _project_relative_path("SVG", svg_filename)
    else:
        svg_relative_path = None

    direction_info = result.get("direction_info") or {}
    return {
        "printGroupName": result.get("group_name"),
        "displayName": result.get("group_name"),
        "svgFilename": svg_filename if result.get("ok") else None,
        "svgRelativePath": svg_relative_path,
        "jsxFilename": os.path.basename(result["jsx_path"]) if result.get("jsx_path") else None,
        "jsxRelativePath": (
            _project_relative_path("Illustrator", os.path.basename(result["jsx_path"]))
            if result.get("jsx_path") else None
        ),
        "exportStatus": "exported" if result.get("ok") else "skipped",
        "exportModeSetting": _print_export_mode_label(result.get("export_mode")) if result.get("export_mode") else None,
        "exportModeResolved": (
            _print_export_mode_label(result.get("resolved_export_mode"))
            if result.get("resolved_export_mode") else None
        ),
        "wallSegmentNames": _segment_names_from_direction_info(direction_info),
        "panelCount": int(result.get("count") or 0),
        "missingPlaneCount": len(result.get("missing") or []),
        "invalidPlaneCount": len(result.get("invalid") or []),
        "widthIn": _json_safe_number(result.get("width_in")),
        "heightIn": _json_safe_number(result.get("height_in")),
        "notes": _notes_for_export_result(result),
    }


def _write_export_metadata_json(context, folders, results, export_scope):
    metadata_path = os.path.join(folders["metadata"], "bematrix_export.json")
    exported_results = [result for result in results if result.get("ok")]
    skipped_results = [result for result in results if not result.get("ok")]
    export_modes = sorted({
        _print_export_mode_label(result.get("resolved_export_mode"))
        for result in exported_results
        if result.get("resolved_export_mode")
    })

    payload = {
        "formatVersion": 1,
        "projectName": _project_name_for_metadata(folders),
        "exportedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "exportScope": export_scope,
        "exportMode": "per Print Group" if len(export_modes) != 1 else export_modes[0],
        "exportModes": export_modes,
        "blenderFileName": _blend_file_name(),
        "sourceUnit": _source_unit_metadata(context),
        "addonVersion": ADDON_VERSION,
        "folders": {
            "svg": "SVG",
            "illustrator": "Illustrator",
            "metadata": "Metadata",
            "exports": "Exports",
            "logs": "Logs",
        },
        "files": {
            "manifest": _project_relative_path("Metadata", "Project_manifest.csv"),
            "metadata": _project_relative_path("Metadata", "bematrix_export.json"),
        },
        "summary": {
            "exportedGroupCount": len(exported_results),
            "skippedGroupCount": len(skipped_results),
            "totalPanelCount": sum(int(result.get("count") or 0) for result in exported_results),
        },
        "printGroups": [_metadata_entry_for_result(result) for result in results],
    }

    with open(metadata_path, "w", encoding="utf-8") as metadata_file:
        json.dump(payload, metadata_file, indent=2)
        metadata_file.write("\n")
    return metadata_path


def _export_print_group_to_folder(
    group,
    folders,
    direction_setting="AUTO",
    export_options=None,
):
    group_name = group.group_name.strip() or "Print Group"
    export_mode = _group_export_mode(group)
    svg_filename = _print_group_svg_filename(group)
    filepath = os.path.join(folders["svg"], svg_filename)
    base_name, _ext = os.path.splitext(svg_filename)
    jsx_filename = f"{base_name}_artboards.jsx"
    jsx_path = os.path.join(folders["scripts"], jsx_filename)
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
            "export_mode": export_mode,
            "resolved_export_mode": None,
            "width_in": None,
            "height_in": None,
        }

    export_options = export_options or _svg_export_options()
    resolved_mode, export_items, error, direction_info = _resolve_export_items_for_mode(
        objects,
        direction_setting=direction_setting,
        export_mode=export_mode,
    )
    if error:
        return {
            "ok": False,
            "group_name": group_name,
            "filepath": filepath,
            "count": 0,
            "missing": missing,
            "invalid": invalid,
            "error": error,
            "direction_info": direction_info,
            "export_mode": export_mode,
            "resolved_export_mode": resolved_mode,
            "width_in": None,
            "height_in": None,
        }

    if not filepath.lower().endswith(".svg"):
        filepath += ".svg"

    svg_text = _svg_for_export_items(
        export_items,
        print_group_name=group_name,
        export_options=export_options,
    )

    try:
        with open(filepath, "w", encoding="utf-8") as svg_file:
            svg_file.write(svg_text)

        records = _layout_records_for_export_items(
            export_items,
            print_group_name=group_name,
            print_group_abbr=_clean_group_abbreviation(getattr(group, "group_abbreviation", "")),
            export_options=export_options,
        )
        manifest_rows = []
        script_written = False
        if export_options["include_illustrator_artboard_script"]:
            _write_illustrator_artboard_jsx(jsx_path, records)
            script_written = True

        for record in records:
            row = {
                "svg_file": _project_relative_path("SVG", svg_filename),
                "jsx_file": _project_relative_path("Illustrator", jsx_filename) if script_written else "",
                "print_group_abbr": record["print_group_abbr"],
                "print_group_name": record["print_group_name"],
                "export_mode_setting": _print_export_mode_label(export_mode),
                "export_mode_resolved": _print_export_mode_label(resolved_mode),
                "graphic_id": record["graphic_id"],
                "artboard_name": record["artboard_name"],
                "blender_object_name": record["blender_object_name"],
                "real_width_in": f"{record['real_width_in']:.6f}",
                "real_height_in": f"{record['real_height_in']:.6f}",
                "template_width_in": f"{record['template_width_in']:.6f}",
                "template_height_in": f"{record['template_height_in']:.6f}",
                "real_x_in": f"{record['real_x_in']:.6f}",
                "real_y_in": f"{record['real_y_in']:.6f}",
                "template_x_in": f"{record['template_x_in']:.6f}",
                "template_y_in": f"{record['template_y_in']:.6f}",
                "template_scale": f"{record['template_scale']:.6f}",
            }
            manifest_rows.append(row)

        _print_curved_export_debug(
            export_items,
            filepath,
            jsx_path=jsx_path if script_written else None,
            records=records,
            manifest_rows=manifest_rows,
            export_options=export_options,
        )
    except OSError as exc:
        return {
            "ok": False,
            "group_name": group_name,
            "filepath": filepath,
            "count": 0,
            "missing": missing,
            "invalid": invalid,
            "error": f"Unable to write export files: {exc}",
            "direction_info": direction_info,
            "export_mode": export_mode,
            "resolved_export_mode": resolved_mode,
            "width_in": None,
            "height_in": None,
        }

    width_in, height_in = _summarize_export_items(export_items)

    return {
        "ok": True,
        "group_name": group_name,
        "filepath": filepath,
        "count": len(export_items),
        "missing": missing,
        "invalid": invalid,
        "error": None,
        "direction_info": direction_info,
        "export_mode": export_mode,
        "resolved_export_mode": resolved_mode,
        "manifest_rows": manifest_rows,
        "jsx_path": jsx_path if script_written else None,
        "width_in": width_in,
        "height_in": height_in,
    }


class BEMATRIX_OT_ExportActivePrintGroupToFolder(bpy.types.Operator):
    bl_idname = "bematrix.export_active_print_group_folder"
    bl_label = "Export Active"
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

        parent_folder = _directory_path_from_operator(self)
        if not parent_folder or not os.path.isdir(parent_folder):
            self.report({"ERROR"}, "Choose a valid parent folder.")
            return {"CANCELLED"}

        try:
            folders = _create_project_export_folders(parent_folder)
        except OSError as exc:
            self.report({"ERROR"}, f"Unable to create project export folders: {exc}")
            return {"CANCELLED"}

        result = _export_print_group_to_folder(
            group,
            folders,
            direction_setting=props.straight_wall_direction,
            export_options=_svg_export_options(
                include_print_group_title=props.include_print_group_title,
                include_panel_labels=props.include_panel_labels,
                include_artboard_guides=props.include_artboard_guides,
                include_illustrator_artboard_script=props.include_illustrator_artboard_script,
                illustrator_template_scale=props.illustrator_template_scale,
                illustrator_artboard_naming=props.illustrator_artboard_naming,
            ),
        )
        if not result["ok"]:
            self.report(
                {"ERROR"},
                f"Print Group '{result['group_name']}' export failed: {result['error']}",
            )
            return {"CANCELLED"}

        manifest_path = os.path.join(folders["manifest"], "Project_manifest.csv")
        try:
            _write_project_manifest_csv(manifest_path, result["manifest_rows"])
        except OSError as exc:
            self.report({"ERROR"}, f"Unable to write project manifest: {exc}")
            return {"CANCELLED"}

        try:
            metadata_path = _write_export_metadata_json(context, folders, [result], "active")
        except OSError as exc:
            self.report({"ERROR"}, f"Unable to write export metadata: {exc}")
            return {"CANCELLED"}

        report_label = _export_info_report_label(result["direction_info"], result["export_mode"])
        info_warning = _export_info_warning(result["direction_info"])
        if result["missing"] or result["invalid"] or info_warning:
            extra_warning = f" {info_warning}" if info_warning else ""
            companion_text = " with Illustrator artboard files" if result.get("jsx_path") else ""
            self.report(
                {"WARNING"},
                f"Exported '{result['group_name']}'{companion_text} with {result['count']} plane(s); "
                f"used {report_label}; "
                f"skipped {len(result['missing'])} missing and "
                f"{len(result['invalid'])} invalid.{extra_warning}",
            )
        else:
            companion_text = " plus Illustrator artboard files" if result.get("jsx_path") else ""
            self.report(
                {"INFO"},
                f"Exported '{result['group_name']}' to {folders['project']}{companion_text} using {report_label}.",
            )
        print(f"Metadata JSON: {metadata_path}")

        return {"FINISHED"}


class BEMATRIX_OT_ExportAllPrintGroupsToFolder(bpy.types.Operator):
    bl_idname = "bematrix.export_all_print_groups_folder"
    bl_label = "Export All"
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

        parent_folder = _directory_path_from_operator(self)
        if not parent_folder or not os.path.isdir(parent_folder):
            self.report({"ERROR"}, "Choose a valid parent folder.")
            return {"CANCELLED"}

        try:
            folders = _create_project_export_folders(parent_folder)
        except OSError as exc:
            self.report({"ERROR"}, f"Unable to create project export folders: {exc}")
            return {"CANCELLED"}

        exported = 0
        failed = 0
        warning_groups = 0
        manifest_rows = []
        metadata_results = []

        print("\n=== BeMatrix Print Group Batch SVG Export ===")
        print(f"Project export folder: {folders['project']}")
        print("Export mode: per Print Group")
        print(f"Straight-wall direction setting: {_direction_label(props.straight_wall_direction)}")

        for group in props.print_groups:
            result = _export_print_group_to_folder(
                group,
                folders,
                direction_setting=props.straight_wall_direction,
                export_options=_svg_export_options(
                    include_print_group_title=props.include_print_group_title,
                    include_panel_labels=props.include_panel_labels,
                    include_artboard_guides=props.include_artboard_guides,
                    include_illustrator_artboard_script=props.include_illustrator_artboard_script,
                    illustrator_template_scale=props.illustrator_template_scale,
                    illustrator_artboard_naming=props.illustrator_artboard_naming,
                ),
            )
            if result["ok"]:
                exported += 1
                if (
                    result["missing"]
                    or result["invalid"]
                    or _export_info_warning(result["direction_info"])
                ):
                    warning_groups += 1
                report_label = _export_info_report_label(
                    result["direction_info"],
                    result["export_mode"],
                )
                manifest_rows.extend(result["manifest_rows"])
                warning_text = ""
                info_warning = _export_info_warning(result["direction_info"])
                if info_warning:
                    warning_text = f", {info_warning}"
                companion_text = ", JSX" if result.get("jsx_path") else ""
                print(
                    f"  OK: {result['group_name']} -> {result['filepath']} "
                    f"using {report_label} ({result['count']} plane(s), "
                    f"{len(result['missing'])} missing, {len(result['invalid'])} invalid"
                    f"{warning_text}{companion_text})"
                )
            else:
                failed += 1
                print(f"  SKIPPED: {result['group_name']} - {result['error']}")
            metadata_results.append(result)

        if exported == 0:
            self.report(
                {"ERROR"},
                f"No Print Groups exported. {failed} failed/skipped. See console.",
            )
            return {"CANCELLED"}

        manifest_path = os.path.join(folders["manifest"], "Project_manifest.csv")
        try:
            _write_project_manifest_csv(manifest_path, manifest_rows)
        except OSError as exc:
            self.report({"ERROR"}, f"Unable to write project manifest: {exc}")
            return {"CANCELLED"}

        try:
            metadata_path = _write_export_metadata_json(context, folders, metadata_results, "all")
        except OSError as exc:
            self.report({"ERROR"}, f"Unable to write export metadata: {exc}")
            return {"CANCELLED"}
        print(f"Metadata JSON: {metadata_path}")

        if failed or warning_groups:
            self.report(
                {"WARNING"},
                f"Exported {exported} Print Group(s); {failed} failed/skipped, "
                f"{warning_groups} had warnings. See console. Folder: {folders['project']}",
            )
        else:
            self.report(
                {"INFO"},
                f"Exported {exported} Print Group(s) to {folders['project']}",
            )

        return {"FINISHED"}


class BEMATRIX_OT_DeletePrintGroup(bpy.types.Operator):
    bl_idname = "bematrix.delete_print_group"
    bl_label = "Delete Group"
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
