"""
Material creation for generated BeMatrix panels and SEG planes.

Each generated object gets its own unique material datablock named from the
object's name, so panels can be edited independently. Re-running reuses the
material by name instead of creating duplicates.
"""

import bpy

from .utils import MATERIAL_PREFIX


def _configure_panel_material(mat):
    """
    Apply the standard graphic-panel look to a material, tolerating socket name
    changes between Blender versions. Used for every generated panel material so
    they all share the same settings while remaining separate datablocks.
    """
    mat.use_nodes = True

    if mat.node_tree:
        nodes = mat.node_tree.nodes
        principled = nodes.get("Principled BSDF")

        if principled:
            if "Base Color" in principled.inputs:
                principled.inputs["Base Color"].default_value = (1, 1, 1, 1)

            if "Roughness" in principled.inputs:
                principled.inputs["Roughness"].default_value = 0.5

            # Blender 4.x/5.x commonly uses "Specular IOR Level".
            # Older versions may use "Specular".
            if "Specular IOR Level" in principled.inputs:
                principled.inputs["Specular IOR Level"].default_value = 0.0
            elif "Specular" in principled.inputs:
                principled.inputs["Specular"].default_value = 0.0

    return mat


def panel_material_name(panel_name):
    """
    Unique material name based on the panel object name. Spaces become
    underscores so the result is a clean identifier, e.g.
    BM_PANEL_FRONT_B62 0992 0992_A001 -> MAT_BM_PANEL_FRONT_B62_0992_0992_A001
    """
    return f"{MATERIAL_PREFIX}{panel_name.replace(' ', '_')}"


def get_or_create_unique_panel_material(panel_name):
    """
    Return a material unique to this panel object. Each generated panel gets its
    own material datablock (not one shared material) so they can be edited
    independently later. Re-running reuses the existing material by name instead
    of creating endless duplicate materials.
    """
    mat_name = panel_material_name(panel_name)
    mat = bpy.data.materials.get(mat_name)

    if mat is None:
        mat = bpy.data.materials.new(mat_name)

    return _configure_panel_material(mat)
