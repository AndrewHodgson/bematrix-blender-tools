"""
Sidebar UI panel for the BeMatrix Graphic Panels add-on.

Location: View3D > Sidebar > BeMatrix. The parent panel shows version/update
controls; native child panels hold the main tool sections in a stable order.
This file is layout only and contains no panel/array/export logic.
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

        row = layout.row(align=True)
        row.label(text=f"Version: {ADDON_VERSION}", icon="INFO")
        row.operator("bematrix.update_addon_from_zip", text="Update", icon="FILE_REFRESH")


class BEMATRIX_PT_GraphicPanelsSection(bpy.types.Panel):
    bl_label = "Graphic Panels"
    bl_idname = "BEMATRIX_PT_graphic_panels_section"
    bl_parent_id = "BEMATRIX_PT_graphic_panels"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "BeMatrix"
    bl_order = 1

    def draw(self, context):
        layout = self.layout
        props = context.scene.bematrix_panel_props

        setup_box = layout.box()
        setup_box.label(text="Panel Setup")
        setup_box.prop(props, "source_mode")
        if props.source_mode == "CHOSEN_COLLECTION":
            setup_box.prop(props, "target_collection")
        setup_box.prop(props, "panel_type")
        setup_box.prop(props, "panel_side")

        adv_header, adv_body = layout.panel(
            "bematrix_advanced_panel_settings",
            default_closed=True,
        )
        adv_header.label(text="Advanced Panel Settings")
        if adv_body is not None:
            adv_box = adv_body.box()
            if props.panel_type == "SEG":
                adv_box.prop(props, "seg_front_offset_mm")
                adv_box.prop(props, "seg_back_offset_mm")
            else:
                adv_box.prop(props, "trim_mm")
                adv_box.prop(props, "front_offset_mm")
                adv_box.prop(props, "back_offset_mm")

        options_box = layout.box()
        options_box.label(text="Options")
        options_box.prop(props, "replace_existing")

        actions_box = layout.box()
        actions_box.label(text="Actions")
        actions = actions_box.row(align=True)
        actions.operator("bematrix.add_graphic_panels", icon="MESH_PLANE")
        actions.operator("bematrix.delete_generated_panels", icon="TRASH")


class BEMATRIX_PT_PrintLayoutExportSection(bpy.types.Panel):
    bl_label = "Print Layout Export"
    bl_idname = "BEMATRIX_PT_print_layout_export_section"
    bl_parent_id = "BEMATRIX_PT_graphic_panels"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "BeMatrix"
    bl_order = 2

    def draw(self, context):
        layout = self.layout
        props = context.scene.bematrix_panel_props

        active_group = None
        if props.active_print_group != "NONE":
            try:
                active_index = int(props.active_print_group)
                if 0 <= active_index < len(props.print_groups):
                    active_group = props.print_groups[active_index]
            except (TypeError, ValueError):
                active_group = None

        groups_box = layout.box()
        groups_header = groups_box.row(align=True)
        groups_icon = "TRIA_DOWN" if props.show_print_groups_section else "TRIA_RIGHT"
        groups_header.prop(
            props,
            "show_print_groups_section",
            text="Print Groups",
            icon=groups_icon,
            emboss=False,
        )
        if props.show_print_groups_section:
            groups_box.label(text="Create New")
            groups_box.prop(props, "print_group_name")
            groups_box.operator(
                "bematrix.create_print_group_from_selected",
                icon="ADD",
            )
            groups_box.separator()
            groups_box.label(text="Active Group")
            groups_box.prop(props, "active_print_group")
            if active_group is not None:
                groups_box.prop(active_group, "group_name")
                groups_box.prop(active_group, "group_abbreviation")
                groups_box.prop(active_group, "export_mode")
            group_buttons = groups_box.row(align=True)
            group_buttons.operator(
                "bematrix.generate_print_group_graphic_ids",
                icon="SORTALPHA",
            )
            group_buttons.operator(
                "bematrix.select_print_group_objects",
                icon="RESTRICT_SELECT_OFF",
            )
            group_buttons.operator(
                "bematrix.delete_print_group",
                icon="TRASH",
            )

        export_box = layout.box()
        options_header = export_box.row(align=True)
        options_icon = "TRIA_DOWN" if props.show_export_options_section else "TRIA_RIGHT"
        options_header.prop(
            props,
            "show_export_options_section",
            text="Export Options",
            icon=options_icon,
            emboss=False,
        )
        if props.show_export_options_section:
            export_box.prop(props, "illustrator_template_scale")
            export_box.prop(props, "illustrator_artboard_naming")
            toggles = export_box.row(align=True)
            toggles.prop(props, "include_print_group_title", text="Title")
            toggles.prop(props, "include_panel_labels", text="Labels")
            toggles.prop(props, "include_artboard_guides", text="Guides")
            export_box.prop(props, "include_illustrator_artboard_script", text="Artboard Script")
            export_buttons = export_box.row(align=True)
            export_buttons.operator(
                "bematrix.export_selected_planes_svg",
                icon="EXPORT",
            )
            export_buttons.operator(
                "bematrix.export_active_print_group_folder",
                icon="EXPORT",
            )
            export_buttons.operator(
                "bematrix.export_all_print_groups_folder",
                icon="EXPORT",
            )

        validation_box = layout.box()
        validation_header = validation_box.row(align=True)
        validation_icon = "TRIA_DOWN" if props.show_validation_options_section else "TRIA_RIGHT"
        validation_header.prop(
            props,
            "show_validation_options_section",
            text="Validation Options",
            icon=validation_icon,
            emboss=False,
        )
        if props.show_validation_options_section:
            validation_buttons = validation_box.row(align=True)
            validation_buttons.operator(
                "bematrix.validate_active_print_group",
                icon="CHECKMARK",
            )
            validation_buttons.operator(
                "bematrix.validate_all_print_groups",
                icon="CHECKMARK",
            )
            validation_box.separator()
            validation_box.label(text="Latest:")
            for line in props.print_group_validation_status.splitlines()[:4]:
                validation_box.label(text=line)

        artwork_box = layout.box()
        artwork_header = artwork_box.row(align=True)
        artwork_icon = "TRIA_DOWN" if props.show_artwork_images_section else "TRIA_RIGHT"
        artwork_header.prop(
            props,
            "show_artwork_images_section",
            text="Artwork Images",
            icon=artwork_icon,
            emboss=False,
        )
        if props.show_artwork_images_section:
            artwork_box.prop(props, "apply_artwork_active_group_only")
            artwork_box.operator(
                "bematrix.apply_artwork_from_folder",
                icon="FILE_IMAGE",
            )
            artwork_box.separator()
            artwork_box.label(text="Latest:")
            for line in props.artwork_apply_status.splitlines()[:4]:
                artwork_box.label(text=line)


class BEMATRIX_PT_UtilitiesSection(bpy.types.Panel):
    bl_label = "Utilities"
    bl_idname = "BEMATRIX_PT_utilities_section"
    bl_parent_id = "BEMATRIX_PT_graphic_panels"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "BeMatrix"
    bl_order = 3

    def draw(self, context):
        layout = self.layout

        array_box = layout.box()
        array_box.label(text="Array Tools")
        array_box.operator("bematrix.convert_array_to_frames", icon="MOD_ARRAY")


class BEMATRIX_PT_FrameTransformSection(bpy.types.Panel):
    bl_label = "Frame Transform"
    bl_idname = "BEMATRIX_PT_frame_transform_section"
    bl_parent_id = "BEMATRIX_PT_graphic_panels"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "BeMatrix"
    bl_order = 4

    def draw(self, context):
        layout = self.layout
        props = context.scene.bematrix_panel_props

        origin_box = layout.box()
        origin_box.label(text="Origin Tools")
        if props.snap_target_set:
            origin_box.label(
                text=f"Target: {props.snap_target.x:.3f}, "
                     f"{props.snap_target.y:.3f}, {props.snap_target.z:.3f}",
                icon="PIVOT_CURSOR",
            )
        else:
            origin_box.label(text="No snap target set", icon="DOT")
        snap_buttons = origin_box.row(align=True)
        snap_buttons.operator("bematrix.set_snap_target", icon="CURSOR")
        snap_buttons.operator("bematrix.snap_frame_to_target", icon="SNAP_ON")

        object_box = layout.box()
        object_box.label(text="Object Tools")
        object_box.operator("bematrix.make_selected_local", icon="LINKED")
