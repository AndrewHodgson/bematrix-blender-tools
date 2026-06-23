"""
Sidebar UI panel for the BeMatrix Graphic Panels add-on.

Location: View3D > Sidebar > BeMatrix > Graphic Panels. Labels and workflow are
unchanged from the single-file version.
"""

import bpy

from .utils import ADDON_VERSION


class BEMATRIX_PT_GraphicPanelsPanel(bpy.types.Panel):
    bl_label = "Graphic Panels"
    bl_idname = "BEMATRIX_PT_graphic_panels"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "BeMatrix"

    def draw(self, context):
        layout = self.layout
        props = context.scene.bematrix_panel_props

        # Visible version so you can confirm Blender loaded the latest file.
        layout.label(text=f"Version: {ADDON_VERSION}", icon="INFO")
        layout.separator()

        layout.prop(props, "source_mode")

        if props.source_mode == "CHOSEN_COLLECTION":
            layout.prop(props, "target_collection")

        layout.separator()

        layout.prop(props, "panel_type")
        layout.prop(props, "panel_side")

        layout.separator()

        if props.panel_type == "SEG":
            # SEG uses full frame size (no trim) and its own offsets.
            layout.prop(props, "seg_front_offset_mm")
            layout.prop(props, "seg_back_offset_mm")
        else:
            layout.prop(props, "trim_mm")
            layout.prop(props, "front_offset_mm")
            layout.prop(props, "back_offset_mm")

        layout.separator()

        layout.prop(props, "replace_existing")

        layout.separator()

        layout.operator("bematrix.add_graphic_panels", icon="MESH_PLANE")
        layout.operator("bematrix.delete_generated_panels", icon="TRASH")
