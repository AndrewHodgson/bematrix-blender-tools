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
    operators.py      Add/Update, Delete, Export, and utility operators
    ui.py             sidebar panel

Registration order matters: the PropertyGroup must be registered before the
operators and panel, and the Scene pointer is created after the classes. The
unregister order is reversed.
"""

bl_info = {
    "name": "BeMatrix Graphic Panels",
    "author": "Andrew Hodgson / ChatGPT",
    "version": (0, 6, 7),
    "blender": (5, 1, 0),
    "location": "View3D > Sidebar > BeMatrix > Graphic Panels",
    "description": "Add correctly sized graphic panel planes to selected BeMatrix frames.",
    "category": "Object",
}

import bpy

# Import the submodules first (binds their names even if a stale copy is cached).
from . import (
    utils,
    materials,
    array_helpers,
    hard_panels,
    seg_fabric,
    properties,
    operators,
    ui,
)

# When the add-on is re-enabled or reinstalled inside a RUNNING Blender session,
# Python keeps the previously imported submodules in sys.modules. New or renamed
# classes (e.g. a new operator) then look "missing" until Blender restarts, which
# raises errors like: cannot import name 'BEMATRIX_OT_...' from
# 'bematrix_addon.operators'. Force-reload the submodules in dependency order so
# the latest code is used without requiring a restart.
if "_BEMATRIX_MODULES_LOADED" in globals():
    import importlib

    for _module in (
        utils,
        materials,
        array_helpers,
        hard_panels,
        seg_fabric,
        properties,
        operators,
        ui,
    ):
        importlib.reload(_module)

_BEMATRIX_MODULES_LOADED = True

from .properties import (
    BEMATRIX_PrintGroupObjectItem,
    BEMATRIX_PrintGroup,
    BEMATRIX_PanelProperties,
)
from .operators import (
    BEMATRIX_OT_UpdateAddonFromZip,
    BEMATRIX_OT_AddGraphicPanels,
    BEMATRIX_OT_DeleteGeneratedPanels,
    BEMATRIX_OT_ExportSelectedPlanesToSVG,
    BEMATRIX_OT_CreatePrintGroupFromSelected,
    BEMATRIX_OT_SelectPrintGroupObjects,
    BEMATRIX_OT_ValidateActivePrintGroup,
    BEMATRIX_OT_ValidateAllPrintGroups,
    BEMATRIX_OT_ExportActivePrintGroupToFolder,
    BEMATRIX_OT_ExportAllPrintGroupsToFolder,
    BEMATRIX_OT_DeletePrintGroup,
    BEMATRIX_OT_ConvertArrayToFrames,
    BEMATRIX_OT_SetSnapTarget,
    BEMATRIX_OT_SnapFrameToTarget,
    BEMATRIX_OT_MakeSelectedLocal,
)
from .ui import BEMATRIX_PT_GraphicPanelsPanel


# Nested PropertyGroups first, then the main PropertyGroup, operators, and panel.
classes = (
    BEMATRIX_PrintGroupObjectItem,
    BEMATRIX_PrintGroup,
    BEMATRIX_PanelProperties,
    BEMATRIX_OT_UpdateAddonFromZip,
    BEMATRIX_OT_AddGraphicPanels,
    BEMATRIX_OT_DeleteGeneratedPanels,
    BEMATRIX_OT_ExportSelectedPlanesToSVG,
    BEMATRIX_OT_CreatePrintGroupFromSelected,
    BEMATRIX_OT_SelectPrintGroupObjects,
    BEMATRIX_OT_ValidateActivePrintGroup,
    BEMATRIX_OT_ValidateAllPrintGroups,
    BEMATRIX_OT_ExportActivePrintGroupToFolder,
    BEMATRIX_OT_ExportAllPrintGroupsToFolder,
    BEMATRIX_OT_DeletePrintGroup,
    BEMATRIX_OT_ConvertArrayToFrames,
    BEMATRIX_OT_SetSnapTarget,
    BEMATRIX_OT_SnapFrameToTarget,
    BEMATRIX_OT_MakeSelectedLocal,
    BEMATRIX_PT_GraphicPanelsPanel,
)


def _unregister_stale_class(cls):
    """
    Blender can keep class objects registered when a zip is installed over an
    enabled add-on in the same session. If a class with this name already exists
    in bpy.types, unregister it before registering the freshly imported class.
    """
    existing = getattr(bpy.types, cls.__name__, None)
    if existing is not None:
        try:
            bpy.utils.unregister_class(existing)
        except RuntimeError:
            pass


def register():
    if hasattr(bpy.types.Scene, "bematrix_panel_props"):
        del bpy.types.Scene.bematrix_panel_props

    for cls in reversed(classes):
        _unregister_stale_class(cls)

    for cls in classes:
        bpy.utils.register_class(cls)

    bpy.types.Scene.bematrix_panel_props = bpy.props.PointerProperty(
        type=BEMATRIX_PanelProperties
    )


def unregister():
    if hasattr(bpy.types.Scene, "bematrix_panel_props"):
        del bpy.types.Scene.bematrix_panel_props

    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass


if __name__ == "__main__":
    register()
