"""
BeMatrix Graphic Panels add-on (package entry point).

This is a behavior-preserving split of the original single-file add-on into
modules. Responsibilities:

    utils.py          shared helpers, constants, frame detection, naming
    materials.py      unique per-object material creation
    array_helpers.py  array/grid detection, step math, modifier dump
    hard_panels.py    hard graphic panel placement
    seg_fabric.py     SEG fabric placement (not yet fully working)
    properties.py     Scene PropertyGroup
    operators.py      Add/Update and Delete operators
    ui.py             sidebar panel

Registration order matters: the PropertyGroup must be registered before the
operators and panel, and the Scene pointer is created after the classes. The
unregister order is reversed.
"""

bl_info = {
    "name": "BeMatrix Graphic Panels",
    "author": "Andrew Hodgson / ChatGPT",
    "version": (0, 2, 0),
    "blender": (5, 1, 0),
    "location": "View3D > Sidebar > BeMatrix > Graphic Panels",
    "description": "Add correctly sized graphic panel planes to selected BeMatrix frames.",
    "category": "Object",
}

import bpy

from .properties import BEMATRIX_PanelProperties
from .operators import (
    BEMATRIX_OT_AddGraphicPanels,
    BEMATRIX_OT_DeleteGeneratedPanels,
)
from .ui import BEMATRIX_PT_GraphicPanelsPanel


# PropertyGroup first, then operators, then the panel.
classes = (
    BEMATRIX_PanelProperties,
    BEMATRIX_OT_AddGraphicPanels,
    BEMATRIX_OT_DeleteGeneratedPanels,
    BEMATRIX_PT_GraphicPanelsPanel,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    bpy.types.Scene.bematrix_panel_props = bpy.props.PointerProperty(
        type=BEMATRIX_PanelProperties
    )


def unregister():
    if hasattr(bpy.types.Scene, "bematrix_panel_props"):
        del bpy.types.Scene.bematrix_panel_props

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
