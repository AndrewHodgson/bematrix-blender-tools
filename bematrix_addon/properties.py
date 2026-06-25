"""
Scene PropertyGroup for the BeMatrix Graphic Panels add-on.

Registered first (before operators and the panel) so that the
`Scene.bematrix_panel_props` pointer the UI and operators read is always
available.
"""

import bpy


def _print_group_items(self, context):
    """Dynamic dropdown entries for saved Print Groups."""
    items = []
    for index, group in enumerate(self.print_groups):
        count = len(group.objects)
        group_name = group.group_name or f"Print Group {index + 1}"
        group_abbr = group.group_abbreviation.strip()
        label = f"{group_abbr} - {group_name}" if group_abbr else group_name
        items.append((str(index), label, f"{count} stored object(s)"))

    if not items:
        return [("NONE", "No Print Groups", "Create a Print Group first")]

    return items


class BEMATRIX_PrintGroupObjectItem(bpy.types.PropertyGroup):
    object_name: bpy.props.StringProperty(
        name="Object Name",
        description="Name of a generated panel/SEG object stored in this Print Group",
        default="",
    )


class BEMATRIX_PrintGroup(bpy.types.PropertyGroup):
    group_abbreviation: bpy.props.StringProperty(
        name="Group Abbreviation",
        description="Short stable code for this Print Group, such as BW, RW, CF, or SEG1",
        default="",
    )

    group_name: bpy.props.StringProperty(
        name="Group Name",
        description="Saved Print Group name",
        default="",
    )

    export_mode: bpy.props.EnumProperty(
        name="Export Mode",
        description="SVG export mode for this Print Group",
        items=[
            ("AUTO", "Auto Detect", "Resolve straight wall or simple L-shape during validation/export"),
            ("STRAIGHT", "Straight Wall", "Export one straight, coplanar wall layout"),
            ("UNFOLD", "Unfold Connected Walls", "Export a simple connected World X / World Y corner as one flat SVG"),
        ],
        default="AUTO",
    )

    objects: bpy.props.CollectionProperty(
        type=BEMATRIX_PrintGroupObjectItem,
        name="Objects",
        description="Generated panel/SEG object names stored in this Print Group",
    )


class BEMATRIX_PanelProperties(bpy.types.PropertyGroup):
    source_mode: bpy.props.EnumProperty(
        name="Source",
        description="Choose where the add-on should look for BeMatrix frames",
        items=[
            ("SELECTED", "Selected Objects", "Use selected frame objects"),
            ("ACTIVE_COLLECTION", "Active Object Collection", "Use the active object's collection"),
            ("CHOSEN_COLLECTION", "Chosen Collection", "Use the chosen collection"),
        ],
        default="SELECTED",
    )

    target_collection: bpy.props.PointerProperty(
        name="Collection",
        type=bpy.types.Collection,
        description="Collection to scan for BeMatrix frames",
    )

    panel_type: bpy.props.EnumProperty(
        name="Panel Type",
        description="Hard graphic panels (trimmed, one per frame/array position) "
                    "or SEG fabric (full frame size, one continuous plane per row)",
        items=[
            ("HARD", "Hard Panel", "Trimmed flat panels, one per frame or array position"),
            ("SEG", "SEG Fabric", "Full-size fabric planes, combined across the X array run"),
        ],
        default="HARD",
    )

    panel_side: bpy.props.EnumProperty(
        name="Panel Side",
        description="Choose which side of the frame gets a panel",
        items=[
            ("FRONT", "Front -Y", "Create/update panel on local -Y side"),
            ("BACK", "Back +Y", "Create/update panel on local +Y side"),
            ("BOTH", "Both Sides", "Create/update panels on both local -Y and +Y sides"),
        ],
        default="FRONT",
    )

    trim_mm: bpy.props.FloatProperty(
        name="Panel Trim mm",
        description="Amount subtracted from frame width and height to get panel size",
        default=6.0,
        min=0.0,
        precision=2,
    )

    front_offset_mm: bpy.props.FloatProperty(
        name="Front Offset mm",
        description="Local Y position for front panel. Negative Y is front.",
        default=-31.0,
        precision=2,
    )

    back_offset_mm: bpy.props.FloatProperty(
        name="Back Offset mm",
        description="Local Y position for back panel. Positive Y is back.",
        default=31.0,
        precision=2,
    )

    seg_front_offset_mm: bpy.props.FloatProperty(
        name="SEG Front Offset mm",
        description="Local Y position for front SEG fabric. 1 mm outside the hard panel.",
        default=-32.0,
        precision=2,
    )

    seg_back_offset_mm: bpy.props.FloatProperty(
        name="SEG Back Offset mm",
        description="Local Y position for back SEG fabric. 1 mm outside the hard panel.",
        default=32.0,
        precision=2,
    )

    replace_existing: bpy.props.BoolProperty(
        name="Update Existing Panels",
        description="Update existing generated panels instead of creating duplicates",
        default=True,
    )

    # --- Print Layout Export / Print Groups ---
    print_group_name: bpy.props.StringProperty(
        name="Group Name",
        description="Name for a new Print Group created from the selected planes",
        default="",
    )

    print_groups: bpy.props.CollectionProperty(
        type=BEMATRIX_PrintGroup,
        name="Print Groups",
        description="Saved sets of generated panel/SEG objects for SVG export",
    )

    active_print_group: bpy.props.EnumProperty(
        name="Active Print Group",
        description="Saved Print Group to select or export",
        items=_print_group_items,
        default=0,
    )

    print_export_mode: bpy.props.EnumProperty(
        name="Export Mode",
        description="Choose straight-wall export or simple two-segment corner unfolding",
        items=[
            ("STRAIGHT", "Straight Wall", "Export one straight, coplanar wall layout"),
            ("UNFOLD", "Unfold Connected Walls", "Export a simple connected World X / World Y corner as one flat SVG"),
        ],
        default="STRAIGHT",
    )

    straight_wall_direction: bpy.props.EnumProperty(
        name="Straight Wall Direction",
        description="World axis used as the left-to-right direction for straight-wall SVG export",
        items=[
            ("AUTO", "Auto Detect", "Choose World X or World Y from the group's larger world-space spread"),
            ("WORLD_X", "World X", "Use World X as the left-to-right wall/export direction"),
            ("WORLD_Y", "World Y", "Use World Y as the left-to-right wall/export direction"),
        ],
        default="AUTO",
    )

    illustrator_template_scale: bpy.props.EnumProperty(
        name="Illustrator Template Scale",
        description="Scale used for SVG templates, manifests, and Illustrator artboards",
        items=[
            ("1.0", "Full Size 1:1", "Export templates at full real-world size"),
            ("0.5", "50%", "Export templates at half size"),
            ("0.25", "25%", "Export templates at quarter size"),
            ("0.1", "10%", "Export templates at ten percent size"),
        ],
        default="0.1",
    )

    illustrator_artboard_naming: bpy.props.EnumProperty(
        name="Artboard Naming",
        description="Naming pattern used for manifest artboard_name and Illustrator JSX artboards",
        items=[
            ("GRAPHIC_ID", "Graphic ID only", "Use the generated Graphic ID, such as LWT01"),
            ("GROUP_NAME_NUMBER", "Group Name + Number", "Use group name and panel number, such as L_Wall_Test_01"),
            ("ABBR_GROUP_NAME_NUMBER", "Abbreviation + Group Name + Number", "Use abbreviation, group name, and panel number, such as LWT_L_Wall_Test_01"),
        ],
        default="ABBR_GROUP_NAME_NUMBER",
    )

    include_print_group_title: bpy.props.BoolProperty(
        name="Include Print Group Title",
        description="Include the Print Group title text in exported SVG files",
        default=True,
    )

    include_panel_labels: bpy.props.BoolProperty(
        name="Include Panel Labels",
        description="Include production panel labels in exported SVG files",
        default=True,
    )

    include_artboard_guides: bpy.props.BoolProperty(
        name="Include Artboard Guides",
        description="Include separate guide rectangles matching each panel for Illustrator artboards",
        default=True,
    )

    include_illustrator_artboard_script: bpy.props.BoolProperty(
        name="Include Illustrator Artboard Script",
        description="Write matching JSX files for named Illustrator artboards during Print Group folder export",
        default=True,
    )

    show_print_groups_section: bpy.props.BoolProperty(
        name="Show Print Groups",
        description="Expand the Print Groups controls in the Print Layout Export section",
        default=False,
    )

    show_export_options_section: bpy.props.BoolProperty(
        name="Show Export Options",
        description="Expand the SVG export controls in the Print Layout Export section",
        default=False,
    )

    show_validation_options_section: bpy.props.BoolProperty(
        name="Show Validation Options",
        description="Expand the validation controls in the Print Layout Export section",
        default=False,
    )

    show_artwork_images_section: bpy.props.BoolProperty(
        name="Show Artwork Images",
        description="Expand the artwork image import controls in the Print Layout Export section",
        default=False,
    )

    apply_artwork_active_group_only: bpy.props.BoolProperty(
        name="Apply to Active Group Only",
        description="Only match artwork images to objects stored in the active Print Group",
        default=True,
    )

    artwork_apply_status: bpy.props.StringProperty(
        name="Artwork Apply Status",
        description="Latest artwork image apply result",
        default="No artwork applied yet.",
    )

    print_group_validation_status: bpy.props.StringProperty(
        name="Validation Status",
        description="Latest Print Group validation result",
        default="No Print Group validation run yet.",
    )

    # --- Frame Transform (vertex-to-vertex snapping) ---
    snap_target: bpy.props.FloatVectorProperty(
        name="Snap Target",
        description="Stored world-space target location for vertex-to-vertex snapping",
        size=3,
        subtype="TRANSLATION",
        default=(0.0, 0.0, 0.0),
    )

    snap_target_set: bpy.props.BoolProperty(
        name="Snap Target Set",
        description="Whether a snap target has been stored",
        default=False,
    )
