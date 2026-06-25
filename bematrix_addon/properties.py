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
        label = group.group_name or f"Print Group {index + 1}"
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
    group_name: bpy.props.StringProperty(
        name="Group Name",
        description="Saved Print Group name",
        default="",
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
