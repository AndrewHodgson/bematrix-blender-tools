"""
Scene PropertyGroup for the BeMatrix Graphic Panels add-on.

Registered first (before operators and the panel) so that the
`Scene.bematrix_panel_props` pointer the UI and operators read is always
available.
"""

import bpy


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
