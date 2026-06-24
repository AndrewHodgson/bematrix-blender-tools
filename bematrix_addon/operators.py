"""
Operators for the BeMatrix Graphic Panels add-on.

Dispatches each source frame to either the hard-panel or SEG-fabric generator
based on the Panel Type, and prints diagnostics to the system console. bl_idname
values are unchanged so existing UI/keymaps keep working.
"""

import bpy
import bmesh
from mathutils import Matrix, Vector

from .utils import (
    ADDON_VERSION,
    get_target_frames,
    get_frame_size_mm,
    get_frame_depth_mm,
    get_frame_spacing_dims_m,
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
