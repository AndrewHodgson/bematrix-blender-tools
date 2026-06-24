"""
Sidebar UI panel for the BeMatrix Graphic Panels add-on.

Location: View3D > Sidebar > BeMatrix. The panel shows the add-on version at the
top, then collapsible sections (Graphic Panels, Utilities) built with the native
`layout.panel()` API. This file is layout only — it draws existing properties and
operators and contains no panel/array logic.
"""

import bpy

from .utils import ADDON_VERSION


class BEMATRIX_PT_GraphicPanelsPanel(bpy.types.Panel):
    bl_label = "BeMatrix Tools"
    bl_idname = "BEMATRIX_PT_graphic_panels"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "BeMatrix"

    def draw(self, context):
        layout = self.layout
        props = context.scene.bematrix_panel_props

        # Add-on version, shown above all collapsible sections so it is always
        # visible regardless of which sections are expanded.
        layout.label(text=f"Version: {ADDON_VERSION}", icon="INFO")

        # --- Graphic Panels (collapsible, open by default) ---
        gp_header, gp_body = layout.panel(
            "bematrix_graphic_panels_section", default_closed=False
        )
        gp_header.label(text="Graphic Panels")
        if gp_body is not None:
            gp_body.prop(props, "source_mode")

            if props.source_mode == "CHOSEN_COLLECTION":
                gp_body.prop(props, "target_collection")

            gp_body.prop(props, "panel_type")
            gp_body.prop(props, "panel_side")

            # Rarely-changed sizing/offset settings, tucked into a sub-dropdown
            # that is collapsed by default to save vertical space.
            adv_header, adv_body = gp_body.panel(
                "bematrix_advanced_panel_settings", default_closed=True
            )
            adv_header.label(text="Advanced Panel Settings")
            if adv_body is not None:
                if props.panel_type == "SEG":
                    # SEG uses full frame size (no trim) and its own offsets.
                    adv_body.prop(props, "seg_front_offset_mm")
                    adv_body.prop(props, "seg_back_offset_mm")
                else:
                    adv_body.prop(props, "trim_mm")
                    adv_body.prop(props, "front_offset_mm")
                    adv_body.prop(props, "back_offset_mm")

            gp_body.prop(props, "replace_existing")
            gp_body.operator("bematrix.add_graphic_panels", icon="MESH_PLANE")
            gp_body.operator("bematrix.delete_generated_panels", icon="TRASH")

        # --- Utilities (separate collapsible section) ---
        util_header, util_body = layout.panel(
            "bematrix_utilities_section", default_closed=False
        )
        util_header.label(text="Utilities")
        if util_body is not None:
            util_body.operator("bematrix.convert_array_to_frames", icon="MOD_ARRAY")

        # --- Frame Transform (separate collapsible section) ---
        ft_header, ft_body = layout.panel(
            "bematrix_frame_transform_section", default_closed=False
        )
        ft_header.label(text="Frame Transform")
        if ft_body is not None:
            if props.snap_target_set:
                ft_body.label(
                    text=f"Target: {props.snap_target.x:.3f}, "
                         f"{props.snap_target.y:.3f}, {props.snap_target.z:.3f}",
                    icon="PIVOT_CURSOR",
                )
            else:
                ft_body.label(text="No snap target set", icon="DOT")
            ft_body.operator("bematrix.set_snap_target", icon="CURSOR")
            ft_body.operator("bematrix.snap_frame_to_target", icon="SNAP_ON")

            # Separate utility: make selected objects + data local/editable.
            ft_body.separator()
            ft_body.operator("bematrix.make_selected_local", icon="LINKED")
