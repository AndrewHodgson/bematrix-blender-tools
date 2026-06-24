"""
Array / grid detection and step math for the BeMatrix Graphic Panels add-on.

This reads Blender's classic Array modifier AND the Blender 5.1 Geometry Nodes
"Array" asset into a single normalized ArraySettings, computes per-copy step
vectors, and builds the (index_1, index_2, offset) positions used by both the
hard-panel and SEG generators. It also contains the modifier debug dump.
"""

import bpy
from mathutils import Vector

from .utils import (
    GENERATED_ARRAY_PREFIX,
    get_frame_spacing_dims_m,
)


class ArraySettings:
    """
    Normalized array description used by the panel generator.

    Blender exposes "array" behavior through two completely different modifier
    types, and they are NOT read the same way in Python:

    1. Classic Array modifier (`modifier.type == 'ARRAY'`,
       `bpy.types.ArrayModifier`). Values are real Python attributes:
         - `count` (int)
         - `use_relative_offset` (bool) / `relative_offset_displace` (Vector,
           a fraction of the object's local bounding box)
         - `use_constant_offset` (bool) / `constant_offset_displace` (Vector,
           in Blender units / meters)

    2. Geometry Nodes modifier (`modifier.type == 'NODES'`,
       `bpy.types.NodesModifier`). This is what the BeMatrix frames in the
       screenshot actually use ("Shape: Line", "Offset Method", "Realize
       Instances" are Geometry Nodes inputs, not classic Array fields). There is
       NO `.count` / `.relative_offset_displace` attribute. Input values live in
       the node group interface and are read by socket identifier:
         value = modifier[socket.identifier]
       where the socket's human label (e.g. "Count", "Offset", "Offset Method")
       comes from `modifier.node_group.interface.items_tree`.

    This class flattens both into the same fields so the rest of the add-on does
    not care which modifier type produced them.
    """

    def __init__(
        self,
        modifier_name,
        source_type,
        count,
        use_relative_offset,
        relative_offset,
        use_constant_offset,
        constant_offset,
        notes=None,
    ):
        self.modifier_name = modifier_name
        self.source_type = source_type  # "ARRAY" or "NODES"
        self.count = int(count)
        self.use_relative_offset = bool(use_relative_offset)
        self.relative_offset = Vector(relative_offset)
        self.use_constant_offset = bool(use_constant_offset)
        self.constant_offset = Vector(constant_offset)
        self.notes = list(notes) if notes else []


def _as_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_vector3(value):
    """Coerce an IDProperty array / sequence / scalar into a 3D Vector."""
    if value is None:
        return Vector((0.0, 0.0, 0.0))
    try:
        return Vector((value[0], value[1], value[2]))
    except (TypeError, KeyError, IndexError):
        scalar = _as_float(value)
        return Vector((scalar, 0.0, 0.0))


def _array_settings_from_classic(modifier):
    """Read a classic `bpy.types.ArrayModifier`."""
    # Only fixed-count arrays are supported. Fit Length / Fit Curve are skipped.
    if getattr(modifier, "fit_type", "FIXED_COUNT") != "FIXED_COUNT":
        return None

    if modifier.count < 1:
        return None

    return ArraySettings(
        modifier_name=modifier.name,
        source_type="ARRAY",
        count=modifier.count,
        use_relative_offset=modifier.use_relative_offset,
        relative_offset=modifier.relative_offset_displace,
        use_constant_offset=modifier.use_constant_offset,
        constant_offset=modifier.constant_offset_displace,
    )


def _gn_input_map(modifier):
    """
    Map a Geometry Nodes modifier's INPUT socket labels to their stored values.

    Returns { socket_label: value }. Values are read with
    `modifier[socket.identifier]`, which is how Geometry Nodes stores per-object
    modifier inputs.
    """
    node_group = getattr(modifier, "node_group", None)
    inputs = {}

    if node_group is None:
        return inputs

    interface = getattr(node_group, "interface", None)
    if interface is None:
        return inputs

    for item in interface.items_tree:
        if getattr(item, "item_type", None) != "SOCKET":
            continue
        if getattr(item, "in_out", None) != "INPUT":
            continue

        identifier = getattr(item, "identifier", None)
        if identifier is None:
            continue

        # modifier.get() avoids a KeyError if the input was never set.
        inputs[item.name] = modifier.get(identifier)

    return inputs


def _lookup_socket(inputs, candidate_labels):
    """Case-insensitive lookup of the first matching socket label."""
    lowered = {label.lower(): value for label, value in inputs.items()}
    for candidate in candidate_labels:
        if candidate.lower() in lowered:
            return lowered[candidate.lower()]
    return None


def _is_vector_like(value):
    """True if value has at least 3 indexable components (e.g. a Vector input)."""
    if value is None or isinstance(value, str):
        return False
    try:
        return len(value) >= 3
    except TypeError:
        return False


def _gn_offset_vector(inputs):
    """
    Assemble the Array offset vector from a Geometry Nodes input map, handling
    BOTH representations Blender may use:

    1. A single 3D vector socket (commonly named "Offset"/"Translation").
    2. Separate scalar sockets "Offset X", "Offset Y", "Offset Z".

    The separate-scalar case is important: matching only "Offset X" and coercing
    it to a vector would silently drop the Y and Z offsets, which is exactly the
    kind of bug that makes a local-Y array "not work".
    """
    # Case 1: a single vector socket.
    vector_value = _lookup_socket(
        inputs, ["Offset", "Translation", "Displace", "Spacing", "Direction"]
    )
    if _is_vector_like(vector_value):
        return _as_vector3(vector_value), "vector socket"

    # Case 2: separate scalar components.
    x = _lookup_socket(inputs, ["Offset X", "X Offset", "Offset_X"])
    y = _lookup_socket(inputs, ["Offset Y", "Y Offset", "Offset_Y"])
    z = _lookup_socket(inputs, ["Offset Z", "Z Offset", "Offset_Z"])
    if any(component is not None for component in (x, y, z)):
        return (
            Vector((_as_float(x), _as_float(y), _as_float(z))),
            "separate X/Y/Z sockets",
        )

    # Last resort: whatever the single-label lookup returns, coerced.
    return _as_vector3(vector_value), "fallback scalar"


def _offset_method_name(value):
    """
    Normalize a Geometry Nodes "Offset Method" menu value to one of
    RELATIVE / OFFSET / ENDPOINT. Menu sockets may store an int index or a
    string, so both are handled.
    """
    if isinstance(value, str):
        upper = value.upper()
        if "REL" in upper:
            return "RELATIVE"
        if "END" in upper:
            return "ENDPOINT"
        if "OFF" in upper:
            return "OFFSET"

    try:
        index = int(value)
    except (TypeError, ValueError):
        return "RELATIVE"

    # UI order in the screenshot: Relative (0), Offset (1), Endpoint (2).
    return {0: "RELATIVE", 1: "OFFSET", 2: "ENDPOINT"}.get(index, "RELATIVE")


def _array_settings_from_nodes(modifier):
    """
    Read a Geometry Nodes "array" modifier. Tuned to Blender 5.1's bundled
    "Array" asset (confirmed from a real modifier dump), whose relevant inputs
    are:

        Count          (Int)    -> number of copies
        Offset         (Vector) -> per-copy offset, e.g. (1, 0, 0)
        Relative Space (Bool)   -> True: offset is a MULTIPLE of the frame size
                                   (1.0 = one frame). False: offset is a constant
                                   distance in meters.
        Shape          (Menu)   -> 0 == Line (the only supported shape)

    IMPORTANT: the asset also has an "Offset Method" menu, but it does NOT mean
    Relative/Constant the way an older node group did. The reliable relative-vs-
    constant signal is the "Relative Space" boolean. Reading "Offset Method"
    instead made a relative offset of 1.0 be treated as a literal 1.0 m step
    (panels at 0, 1, 2 m) instead of one frame width (0, 0.992, 1.984 m).
    """
    inputs = _gn_input_map(modifier)
    if not inputs:
        return None

    count_value = _lookup_socket(inputs, ["Count", "Number", "Amount", "Copies"])
    if count_value is None:
        return None  # Not an array-like node group; ignore it.

    count = int(round(_as_float(count_value, 1.0)))
    if count < 1:
        return None

    node_group_name = getattr(getattr(modifier, "node_group", None), "name", "?")
    notes = [
        f"Geometry Nodes array (node group: {node_group_name})",
        f"Count = {count}",
    ]

    # Only a straight Line array is supported. Menu 0 == Line in this asset.
    shape_value = _lookup_socket(inputs, ["Shape"])
    if shape_value is not None and int(_as_float(shape_value, 0.0)) != 0:
        notes.append(
            f"WARNING: Shape={shape_value} is not Line; only Line arrays are "
            f"supported. Placement may be wrong."
        )

    offset_vec, offset_source = _gn_offset_vector(inputs)
    notes.append(
        f"Offset read from {offset_source}: "
        f"{tuple(round(v, 4) for v in offset_vec)}"
    )

    # Decide relative vs constant. Prefer the "Relative Space" boolean (Blender
    # 5.1 asset). Fall back to the older "Offset Method" menu if it is absent.
    relative_space = _lookup_socket(inputs, ["Relative Space", "Relative"])

    if relative_space is not None:
        use_relative = bool(relative_space)
        notes.append(
            f"Relative Space = {use_relative} -> "
            f"{'relative (x frame size)' if use_relative else 'constant (meters)'}"
        )
    else:
        method = _offset_method_name(
            _lookup_socket(inputs, ["Offset Method", "Method", "Mode"])
        )
        use_relative = method == "RELATIVE"
        notes.append(
            f"Offset Method = {method} -> "
            f"{'relative (x frame size)' if use_relative else 'constant (meters)'}"
        )

    zero = Vector((0.0, 0.0, 0.0))

    if use_relative:
        # Offset X = 1.0 -> one frame width per copy. The per-axis frame size is
        # applied later in get_array_step_m. Never divided by (count - 1).
        return ArraySettings(
            modifier_name=modifier.name,
            source_type="NODES",
            count=count,
            use_relative_offset=True,
            relative_offset=offset_vec,
            use_constant_offset=False,
            constant_offset=zero,
            notes=notes,
        )

    # Constant offset is already in Blender units (meters); added directly.
    return ArraySettings(
        modifier_name=modifier.name,
        source_type="NODES",
        count=count,
        use_relative_offset=False,
        relative_offset=zero,
        use_constant_offset=True,
        constant_offset=offset_vec,
        notes=notes,
    )


def _array_settings_from_modifier(modifier):
    """Read one modifier into ArraySettings, or None if not a supported array."""
    if modifier.type == "ARRAY":
        return _array_settings_from_classic(modifier)
    if modifier.type == "NODES":
        return _array_settings_from_nodes(modifier)
    return None


def is_supported_array_modifier(modifier):
    """
    True if this modifier is a supported array (classic Array or a Geometry Nodes
    array asset). Used to strip array modifiers from generated/broken frames
    without touching unrelated modifiers.
    """
    return _array_settings_from_modifier(modifier) is not None


def detect_array_settings(frame_obj):
    """
    Return normalized ArraySettings for the FIRST supported array-like modifier
    on the frame, or None. Kept for callers that only need a single array.
    """
    for modifier in frame_obj.modifiers:
        settings = _array_settings_from_modifier(modifier)
        if settings:
            return settings

    return None


def detect_all_array_settings(frame_obj, limit=2):
    """
    Return up to `limit` normalized ArraySettings, one per supported array-like
    modifier, in modifier order. Empty list means no array.

    This is what enables TWO stacked simple Arrays (e.g. one for columns and one
    for rows): each is read independently and combined later as a grid. Arrays
    beyond `limit` are ignored. Array modifiers are never copied onto panels.
    """
    found = []

    for modifier in frame_obj.modifiers:
        settings = _array_settings_from_modifier(modifier)
        if settings:
            found.append(settings)
            if len(found) >= limit:
                break

    return found


def _printable(value):
    """Coerce a value to something readable for the console dump."""
    if value is None or isinstance(value, str):
        return value
    if hasattr(value, "__len__"):
        try:
            return tuple(round(v, 5) if isinstance(v, float) else v for v in value)
        except TypeError:
            return value
    if isinstance(value, float):
        return round(value, 5)
    return value


def dump_source_frame_modifiers(frame_obj):
    """
    Diagnostic dump of every modifier on the source frame.

    Prints modifier name/type, all readable standard RNA properties, all custom
    / ID property keys and values, and (for Geometry Nodes modifiers) every
    INPUT socket label, identifier and value. This is how to verify what
    Blender 5.1 actually exposes for the "Array" modifier (Count, Offset X/Y/Z,
    Offset Method, Rotation, Scale, Realize Instances) without assuming the old
    classic ARRAY API.
    """
    print(f"  --- MODIFIER DUMP for '{frame_obj.name}' ---")

    if not frame_obj.modifiers:
        print("    (no modifiers)")
        return

    for modifier in frame_obj.modifiers:
        print(f"    Modifier: name='{modifier.name}'  type='{modifier.type}'")

        # Standard RNA properties.
        try:
            rna_props = modifier.bl_rna.properties
        except Exception as exc:  # pragma: no cover - defensive
            rna_props = []
            print(f"      <could not read RNA properties: {exc}>")

        for prop in rna_props:
            pid = prop.identifier
            if pid == "rna_type":
                continue
            try:
                if prop.type == "COLLECTION":
                    continue
                if prop.type == "POINTER":
                    pointed = getattr(modifier, pid, None)
                    name = getattr(pointed, "name", None)
                    if name is not None:
                        print(f"      rna {pid} -> <{name}>")
                    continue
                value = getattr(modifier, pid)
                print(f"      rna {pid} = {_printable(value)}")
            except Exception as exc:
                print(f"      rna {pid} = <unreadable: {exc}>")

        # Custom / ID properties (this is where Geometry Nodes stores inputs).
        try:
            id_keys = list(modifier.keys())
        except Exception:
            id_keys = []

        for key in id_keys:
            try:
                print(f"      id['{key}'] = {_printable(modifier[key])}")
            except Exception as exc:
                print(f"      id['{key}'] = <unreadable: {exc}>")

        # Geometry Nodes: resolve socket labels to identifiers and values.
        if modifier.type == "NODES":
            node_group = getattr(modifier, "node_group", None)
            print(f"      node_group = {getattr(node_group, 'name', None)}")
            interface = getattr(node_group, "interface", None) if node_group else None
            if interface is not None:
                for item in interface.items_tree:
                    if getattr(item, "item_type", None) != "SOCKET":
                        continue
                    if getattr(item, "in_out", None) != "INPUT":
                        continue
                    identifier = getattr(item, "identifier", "?")
                    try:
                        value = modifier.get(identifier)
                    except Exception as exc:
                        value = f"<unreadable: {exc}>"
                    socket_type = getattr(item, "socket_type", "?")
                    print(
                        f"      gn input '{item.name}' "
                        f"[{identifier}, {socket_type}] = {_printable(value)}"
                    )

    print("  --- END MODIFIER DUMP ---")


def get_array_step_m(frame_obj, array_settings):
    """
    Calculates the per-copy local offset (one array step) in meters.

    Relative offset is multiplied by the source frame's real per-axis dimensions
    (X = parsed frame width, Z = parsed frame height, Y = parsed/raw frame
    depth) so the panels' center-to-center spacing matches the frame spacing.
    The trim is NOT involved: it only changes panel size, never the step.
    Constant offset is already in Blender units and is added directly. If both
    are enabled they combine.
    """
    step = Vector((0.0, 0.0, 0.0))

    if array_settings.use_relative_offset:
        dimensions = get_frame_spacing_dims_m(frame_obj)
        relative = array_settings.relative_offset
        step += Vector((
            relative.x * dimensions.x,
            relative.y * dimensions.y,
            relative.z * dimensions.z,
        ))

    if array_settings.use_constant_offset:
        step += array_settings.constant_offset

    return step


def get_panel_array_positions(frame_obj, array_list):
    """
    Returns one (index_1, index_2, offset_vector) per generated panel.

    array_list holds 0, 1, or 2 ArraySettings:

    * No array  -> [(None, None, 0)] : a single base panel at the frame origin.
    * One array -> [(i, None, step1*(i-1))] : _A001 at step1*0, _A002 at step1*1,
      etc.
    * Two arrays -> every combination (grid):
        offset = step1 * (i1 - 1) + step2 * (i2 - 1)
        _A001_B001 = (1, 1) -> step1*0 + step2*0
        _A001_B002 = (1, 2) -> step1*0 + step2*1
        _A002_B001 = (2, 1) -> step1*1 + step2*0

    Steps are the spacing between copies and are never divided by (count - 1).
    """
    if not array_list:
        return [(None, None, Vector((0.0, 0.0, 0.0)))]

    step_1 = get_array_step_m(frame_obj, array_list[0])

    if len(array_list) == 1:
        return [
            (i1, None, step_1 * (i1 - 1))
            for i1 in range(1, array_list[0].count + 1)
        ]

    step_2 = get_array_step_m(frame_obj, array_list[1])

    positions = []
    for i1 in range(1, array_list[0].count + 1):
        for i2 in range(1, array_list[1].count + 1):
            offset = step_1 * (i1 - 1) + step_2 * (i2 - 1)
            positions.append((i1, i2, offset))

    return positions


def remove_generated_array_modifiers(panel_obj):
    """Remove only Array modifiers previously synced by this add-on."""
    for modifier in list(panel_obj.modifiers):
        if (
            modifier.type == "ARRAY"
            and modifier.name.startswith(GENERATED_ARRAY_PREFIX)
        ):
            panel_obj.modifiers.remove(modifier)
