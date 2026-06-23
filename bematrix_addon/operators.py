"""
Operators for the BeMatrix Graphic Panels add-on.

Dispatches each source frame to either the hard-panel or SEG-fabric generator
based on the Panel Type, and prints diagnostics to the system console. bl_idname
values are unchanged so existing UI/keymaps keep working.
"""

import bpy

from .utils import (
    ADDON_VERSION,
    get_target_frames,
    get_frame_size_mm,
    get_frame_depth_mm,
    get_frame_spacing_dims_m,
    is_marked_panel,
)
from .array_helpers import (
    detect_all_array_settings,
    get_array_step_m,
    dump_source_frame_modifiers,
)
from .hard_panels import create_or_update_panel_for_frame
from .seg_fabric import create_or_update_seg_for_frame


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

        success_count = 0
        deleted_count = 0

        # SEG fabric sits 1 mm outside the hard-panel offsets by default.
        if props.panel_type == "SEG":
            front_off, back_off = props.seg_front_offset_mm, props.seg_back_offset_mm
        else:
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

            if props.panel_type == "SEG":
                print(
                    f"  Name dimensions (W x H): {frame_width_mm} x {frame_height_mm} mm"
                )
                print("  SEG size uses the FULL frame size (no trim).")
            else:
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
                if props.panel_type == "SEG":
                    panel_count, details = create_or_update_seg_for_frame(
                        frame_obj=frame_obj,
                        side_label=side_label,
                        side_offset_mm=offset_mm,
                        frame_width_mm=frame_width_mm,
                        frame_height_mm=frame_height_mm,
                        array_list=array_list,
                        replace_existing=props.replace_existing,
                    )
                else:
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
