# AGENTS.md

## Project Overview

This project is a Blender add-on for working with BeMatrix exhibit frames inside Blender.

The first feature is a **Graphic Panels** tool that adds correctly sized flat panel planes to BeMatrix frame objects. The add-on should support selected frames, multiple selected frames, and collection-based workflows.

The add-on is intended for real exhibit-design production workflows, not just generic Blender modeling.

## Blender Version

Target Blender version:

```text
Blender 5.1.0
```

Maintain compatibility with Blender 5.1.0 unless explicitly instructed otherwise.

## Primary User Workflow

The user works with BeMatrix frame objects in Blender.

A typical frame object may be named:

```text
B62 0496 2418
B62 0992 2418
B62 0992 2418.001
B62 2418 0992
```

The numbers in the object name are millimeter dimensions.

Example:

```text
B62 0992 2418
```

means:

```text
Width:  992 mm
Height: 2418 mm
```

Blender duplicate suffixes such as `.001`, `.002`, and `.003` should be ignored when parsing frame dimensions.

## Frame Geometry Assumptions

BeMatrix frames are modeled at real-world scale.

Local object axes:

```text
X = width
Y = depth
Z = height
```

For a standard unrotated frame:

```text
Local -Y = front side
Local +Y = back side
```

Panel placement defaults:

```text
Front panel offset: -31 mm on local Y
Back panel offset:  +31 mm on local Y
```

Panels should be created in the frame’s local X/Z plane and parented to the frame.

This is important because frames may be rotated vertically or horizontally. The generated panels should follow the frame’s local transform, not global scene axes.

## Panel Sizing Logic

The current panel sizing rule is a configurable trim value.

Default:

```text
Panel trim: 6 mm
```

The trim is subtracted from both frame width and frame height.

Example:

```text
Frame size: 992 mm x 2418 mm
Trim:       6 mm

Panel size: 986 mm x 2412 mm
```

Do not assume the panel is always 8 mm smaller. The working default is 6 mm unless the user changes it.

Future versions may add chart-based lookup for inside and outside panel dimensions.

## Current Feature Scope

The current add-on should support:

```text
Select one frame → add/update one panel
Select many frames → add/update panels on all selected frames
Select or choose a collection → add/update panels on all valid frames in that collection
```

Panel side options:

```text
Front -Y
Back +Y
Both Sides
```

Generated panels should be mesh planes, not solid panels.

## Generated Panel Requirements

Generated panels should:

* Be parented to the source frame.
* Use the frame’s local X/Z plane.
* Use local Y offset for front/back placement.
* Be centered on the frame.
* Use real-world dimensions converted from millimeters to meters.
* Receive a default material.
* Store custom properties for duplicate detection.
* Update existing generated panels instead of creating duplicates when possible.
* For a source frame with one simple count-based Array modifier, generate one
  real panel object per array position and side, named with `_A001`, `_A002`,
  etc.
* For a source frame with two simple count-based Array modifiers (e.g. columns
  and rows), generate one real panel object per combination, named with both
  indices: `_A001_B001`, `_A001_B002`, `_A002_B001`, etc. Total panels per side
  = Array 1 count x Array 2 count.

Do not copy Array modifiers onto generated panels. Calculate each generated
panel object's local position from the source frame's Array settings:

```text
panel_location = base_location + step_1 * (index_1 - 1) + step_2 * (index_2 - 1)
```

Support up to TWO Array modifiers using Relative Offset and/or Constant Offset
along local X, Y, or Z. Read each Array independently and combine them as a grid
(cartesian product). Three or more stacked Arrays are not combined — use only the
first two. Match existing generated panels by parent frame, side, array index 1,
and array index 2 (stored as `bematrix_array_index` and
`bematrix_array_index_2`; absent reads back as None for no-array and one-array
panels). Increasing a count creates the missing combinations; decreasing a count
deletes the stale ones.

## Panel Types: Hard Panel and SEG Fabric

The **Panel Type** dropdown chooses what is generated. `Hard Panel` is the
original behavior and MUST be preserved exactly (trim `6 mm`, offsets
`-31 / +31 mm`, one panel per frame/array position, grid logic, duplicate
prevention, unique materials). Hard panels are the stable, supported path.

`SEG Fabric` uses the **Smart SEG** builder (`create_smart_seg_panel` in
`seg_fabric.py`). **The rule: one SEG mesh OBJECT per side, containing one or more
planar face SECTIONS** — coplanar runs are one section, rotated frames / 90°
corners become additional sections in the SAME object (do not split into separate
objects unless absolutely necessary, and never stretch one flat face diagonally
across a corner).

* Operate on the frames returned by `get_target_frames`.
* **One cell per frame AND per array instance.** Use the **full frame size** (no
  trim). Expand Array modifiers with the same math as the panels
  (`detect_all_array_settings` + `get_panel_array_positions`); each instance is a
  cell. `_seg_cells_for_frame` returns each cell's 4 world corners and outward
  normal.
* **Frame depth / outside face.** `B62` = 62 mm deep, centered origin (front face
  local Y `-31`, back `+31`). SEG sits 1 mm outside: front `-32`, back `+32`,
  applied along each frame's **local Y**, then transformed by the frame's world
  matrix — so rotated frames get the correct world-space face and normal.
* **Group by plane.** Group cells by `_plane_key` (rounded unit normal + signed
  plane distance). Coplanar, touching cells weld within a tolerance (**10% of the
  smallest frame dimension**) into one connected section; a different plane
  (rotated/corner) is a separate section. **Weld only within a section**, never
  across a bend, so corners stay sharp and undistorted.
* **Leave empty cells empty** — only real cells get a quad (L-shape stays L-shape).
* **Parent to the main frame** (active selected frame, else first) and build the
  mesh in that frame's LOCAL space (`main_frame.matrix_world.inverted() @ world`),
  with identity local transform + identity `matrix_parent_inverse`, so it follows
  the frames and is rotation-safe.
* Winding sets outward normals (FRONT = local `-Y`, BACK = local `+Y`).
* **UVs per section** in that section's own plane (real-world meters), sections
  packed side-by-side in U so they do not overlap. Never collapse a rotated
  section by projecting onto a single global axis; a 3-frame run must unwrap three
  frame widths wide.
* Object name `SEG_Fabric_Panel_<SIDE>_<main frame>`, unique material (Specular
  IOR Level `0`), marked `is_bematrix_panel` / `bematrix_panel_kind = "SEG_SMART"`.
  Identity is per main frame (match the main frame's `SEG_SMART` child of that
  side; update on re-run; a different selection makes a separate object).
* Print debug per run: frame name + world transform, side, each cell's normal and
  corners, section/group assignment, and the generated object name + dimensions.

`Both Sides` makes one mesh per side. The legacy per-frame SEG function
(`create_or_update_seg_for_frame`) is kept for reference but is no longer called.

Hard panels and SEG meshes are distinguished by a `bematrix_panel_kind` property.
**Only apply smart-cell behavior when Panel Type is SEG Fabric.** Hard-panel
behavior (sizing, offsets, arrays/grids, duplicate prevention, materials) must
stay unchanged.

## Utilities: Convert Array to Individual Frames

There is a generic **Utilities** section in the sidebar. Its first tool,
**Convert Array to Individual Frames** (`bematrix.convert_array_to_frames`),
breaks an arrayed frame into real, separate frame objects.

Rules for converting arrays:

* Operate on **selected** valid BeMatrix frames only. Ignore generated objects
  (`BM_PANEL_`, `BM_SEG_`) and skip objects already marked
  `bematrix_array_source`.
* If a selected frame has **no** supported Array modifier, skip it and report
  that no Array was found.
* If it has one or two simple count-based Array modifiers, **create one real
  frame object per array position** using the SAME array-position math as the
  graphic panels (`get_panel_array_positions`). Do **not** apply the Array
  modifier destructively to one mesh, and do **not** create one joined mesh.
* Each generated frame must be a separate, selectable object that **duplicates
  the original mesh/object**, keeps the original material(s), rotation, scale and
  collection, and has **no Array modifiers**.
* Name generated frames `<frame>_A001`, `<frame>_A002`, `<frame>_A001_B001`,
  `<frame>_A001_B002`, etc.
* **Hide the original array source instead of deleting it**, and tag it
  `bematrix_array_source = True` (it keeps its Array modifier).
* Tag each generated frame with `bematrix_array_broken_object = True`,
  `bematrix_source_frame_name`, `bematrix_array_index_1`, and
  `bematrix_array_index_2` (use `0` for the second index when there is only one
  array).
* This utility lives in `operators.py` and reuses `array_helpers.py`. It must
  **not** change panel sizing, offsets, materials, duplicate prevention, or
  array/grid panel behavior.

## Duplicate Prevention

Do not rely only on object names for duplicate prevention.

**Rule: generated panels must never be processed as source frames.** Every code
path that detects, iterates, or selects source frames must exclude any object
that the add-on generated. An object is a generated panel if **either** of these
is true:

* `is_bematrix_panel` is set (truthy) on the object.
* `obj.name.startswith("BM_PANEL_")` or `obj.name.startswith("BM_SEG_")`
  (safety fallback).

If a generated panel is ever treated as a source frame, the add-on produces
nested names like `BM_PANEL_BACK_BM_PANEL_BACK_...`. This must never happen. Both
hard panels (`BM_PANEL_`) and SEG fabric planes (`BM_SEG_`) are generated objects
and must be excluded.

**Boolean custom-property gotcha:** Blender stores a boolean custom property as
an integer, so `obj["is_bematrix_panel"] = True` reads back as `1`, and
`obj.get("is_bematrix_panel") is True` is always `False`. Never use an identity
test (`is True` / `is not True`) on a custom property. Use a truthy check
(`bool(obj.get("is_bematrix_panel"))`) so duplicate detection, panel updates, and
stale-panel deletion actually match the add-on's own panels. Getting this wrong
causes duplicates to stack in the same spot and stale `_A###` panels to survive.

Generated panels should use custom properties such as:

```text
is_bematrix_panel
bematrix_panel_kind         (HARD or SEG)
bematrix_parent_frame
bematrix_panel_side
bematrix_frame_width_mm
bematrix_frame_height_mm
bematrix_panel_width_mm      (hard panels)
bematrix_panel_height_mm     (hard panels)
bematrix_trim_mm             (hard panels)
bematrix_y_offset_mm
bematrix_array_index         (hard panels)
bematrix_array_index_2       (hard panels)
bematrix_array_count         (hard panels)
bematrix_seg_row             (SEG planes)
bematrix_seg_width_mm        (SEG planes)
bematrix_seg_height_mm       (SEG planes)
```

When updating panels, check the frame’s children for existing generated panels with matching panel-side metadata.

**Array duplicate detection must match BOTH side AND array index.** When a frame
has an array, each array position is a separate panel object (`_A001`, `_A002`,
…). The existing-panel lookup must compare `bematrix_panel_side` *and*
`bematrix_array_index`. Matching by side alone makes `_A001` and `_A002`
resolve to the same object, so one overwrites the other and copies pile up in
the same spot. Re-running must update the panel with the same side and index;
increasing the count must create the missing indices; decreasing the count must
delete the now-stale indices for that frame and side.

## Array Position Math

The Array offset is the **spacing between each copy**. Generated panel positions
must use:

```text
position(index) = base_position + step * (index - 1)
```

`_A001` sits at `base + step * 0`, `_A002` at `base + step * 1`, `_A003` at
`base + step * 2`, and so on. **Never divide the step by `(count - 1)`** (or by
the count). Divided spacing happens to look correct at count `2` but places the
count `3` copy halfway between frames instead of aligning to the third frame.
This applies to every offset method, including a Geometry Nodes "Endpoint"
method — treat its offset as per-copy spacing, not a total span to divide.

**Array step uses the SOURCE FRAME dimensions; panel size uses the name
dimension minus trim. Trim never affects spacing.** These are different sizes
and must not be confused:

* Array spacing/step per axis:
  * X = parsed frame width from the name (e.g. `0992` -> `0.992 m`).
  * Z = parsed frame height from the name (e.g. `0992` -> `0.992 m`).
  * Y = parsed frame depth from the leading B-number (e.g. `B62` -> `0.062 m`),
    falling back to the RAW mesh depth (`obj.data.vertices`, pre-modifier) if
    the name has no usable depth.
* Panel size = name dimension minus trim (e.g. `992 - 6 = 986`). Used only for
  the panel mesh, never for spacing.

Do NOT use `obj.bound_box` or `obj.dimensions` for the array step. They are
evaluated and can be slightly larger than the nominal frame (a `992 mm` frame
whose mesh measures ~`998 mm`) or can include the Array's duplicated copies.
Either case pushes later copies off by roughly the difference (often close to
the `6 mm` trim, which is a misleading coincidence). Do not add or subtract trim
to/from the step.

Per-axis relative offset rules:

* Relative Offset X multiplies the parsed frame width.
* Relative Offset Z multiplies the parsed frame height.
* Relative Offset Y multiplies the parsed frame depth.
* Constant Offset is already in Blender units and is added directly.
* If both relative and constant offsets are enabled, combine them.

Local Y is frame depth (local `-Y` front, local `+Y` back). The front/back base
Y offset (`-31 mm` / `+31 mm`) is the panel's base location. Array Y movement is
**added** to the base location (`front/back base Y + array step Y * (index - 1)`)
and must never overwrite it. Keep the panel mesh centered at local Y = 0 and put
the front/back offset in the object location so the array step adds cleanly.

## Array Modifier Detection (Classic vs Geometry Nodes)

There are two distinct modifier types that produce an array, and they are read
differently in Python. The add-on must support both:

* **Classic Array** — `modifier.type == 'ARRAY'`. Read `count`,
  `use_relative_offset` / `relative_offset_displace`, `use_constant_offset` /
  `constant_offset_displace` as direct attributes.
* **Geometry Nodes array** — `modifier.type == 'NODES'`. There is **no**
  `count` attribute. Inputs (`Count`, `Offset`, `Offset Method`) are read from
  the node group interface: iterate
  `modifier.node_group.interface.items_tree` for INPUT sockets and read each
  value with `modifier[socket.identifier]`.

Never assume an "Array" in the UI is a classic Array modifier. A modifier shown
with the geometry-nodes icon and controls like *Shape*, *Offset Method*,
*Realize Instances*, *Randomize*, or *Merge* is a Geometry Nodes modifier
(`type == 'NODES'`). Detecting only `type == 'ARRAY'` silently misses it, the
frame is treated as having no array, and only one unsuffixed panel per side is
created. Always log the detected modifier type, count, offsets, and computed
step so this is visible.

**Blender 5.1 warning — inspect the modifier before assuming property names.**
In Blender 5.1 the "Array" the user adds is typically a Geometry Nodes modifier
asset (Shape / Offset Method / Realize Instances), not the classic `ARRAY`
modifier. Its inputs are ID properties keyed by socket identifier, and the
offset may be exposed **either** as a single 3D vector socket **or** as separate
`Offset X` / `Offset Y` / `Offset Z` scalar sockets. Matching only `Offset X`
and coercing it to a vector silently drops Y and Z — that is a real cause of a
local-Y array "not working". Read the offset robustly: prefer a vector socket,
otherwise assemble it from the separate scalar sockets.

Before trusting any read, dump the modifier. `dump_source_frame_modifiers()`
prints every modifier's name, type, RNA properties, ID properties, and (for
Geometry Nodes) every input socket label, identifier, type and value. When array
math is wrong, read the dump first instead of guessing property names.

**Blender 5.1 bundled "Array" asset (confirmed from a real dump).** The array
users add in Blender 5.1 is the Geometry Nodes *Array* asset. Its key inputs are
`Count` (Int), `Offset` (Vector), `Relative Space` (Bool), and `Shape` (Menu,
`0` = Line). The relative-vs-constant decision MUST come from **`Relative
Space`**, not from `Offset Method`:

* `Relative Space = True` → `Offset` is a multiple of the frame size
  (`1.0` = one frame). Multiply by the parsed frame dimension per axis.
* `Relative Space = False` → `Offset` is a constant distance in metres; add it
  directly.

This asset also exposes an `Offset Method` menu, but it does NOT mean
relative/constant here. Treating `Offset Method = Endpoint` as a constant made a
relative `Offset` of `1.0` become a literal `1.0 m` step (panels at `0, 1, 2 m`)
instead of one frame width (`0, 0.992, 1.984 m`). Read `Relative Space` first and
only fall back to `Offset Method` for older node groups that lack it. Only
`Shape = Line` is supported; warn otherwise.

## Material Requirements

**Each generated panel gets its own unique material**, not one shared material.
The material name is derived from the panel object name with spaces replaced by
underscores, prefixed with `MAT_`:

```text
BM_PANEL_FRONT_B62 0992 0992_A001  ->  MAT_BM_PANEL_FRONT_B62_0992_0992_A001
BM_PANEL_FRONT_B62 0992 0992_A002  ->  MAT_BM_PANEL_FRONT_B62_0992_0992_A002
```

On re-runs, reuse each panel's existing material by name and update its
settings, rather than creating duplicate materials.

Default material settings (applied to every generated panel material):

```text
Base Color: White
Roughness: 0.5
Specular IOR Level: 0
```

For Blender material compatibility:

* Prefer `Specular IOR Level` when available.
* Fall back to `Specular` if needed.
* Do not fail if a material input is missing.

## UI Requirements

The add-on should use the Blender 3D View sidebar.

Location:

```text
View3D > Sidebar > BeMatrix > Graphic Panels
```

The UI should include:

```text
Source:
- Selected Objects
- Active Object Collection
- Chosen Collection

Panel Type:
- Hard Panel
- SEG Fabric

Panel Side:
- Front -Y
- Back +Y
- Both Sides

Settings (Hard Panel):
- Panel Trim mm
- Front Offset mm
- Back Offset mm

Settings (SEG Fabric):
- SEG Front Offset mm
- SEG Back Offset mm

Common:
- Update Existing Panels

Actions:
- Add / Update Graphic Panels
- Delete Generated Panels

Utilities:
- Convert Array to Individual Frames

Frame Transform:
- Set Snap Target
- Snap Frame to Target
- Make Selected Local
```

The sidebar panel name stays `Graphic Panels`. The `Utilities` and `Frame
Transform` sections are generic collapsible groups for tools that are not panel
generation; they will grow over time.

**Frame Transform (vertex-to-vertex snapping).** `Set Snap Target` (Edit Mode,
one vertex selected) stores that vertex's world location in
`bematrix_panel_props.snap_target` and moves the 3D cursor there without moving
the object. `Snap Frame to Target` (Edit Mode, one vertex selected on the object
to move) translates the whole object by `target - source_vertex_world` so the
source vertex lands exactly on the stored target, preserving rotation and scale
(`obj.matrix_world = Matrix.Translation(delta) @ obj.matrix_world`), and leaves
the cursor at the target. `Make Selected Local` (Object Mode) wraps
`bpy.ops.object.make_local(type="SELECT_OBDATA")` to make the selected objects
and their data local/editable.

Keep the UI clear and expandable because this plugin will likely grow beyond graphic panels.

## Coding Standards

Use clear, maintainable Python.

Follow these rules:

* Keep code compatible with Blender 5.1.0.
* Use Blender Python API conventions.
* Keep operators undoable with `bl_options = {"REGISTER", "UNDO"}` where appropriate.
* Avoid destructive behavior unless explicitly requested.
* Preserve existing working behavior unless the task specifically asks to change it.
* Add comments for transform logic, frame detection, and panel placement.
* Keep millimeters as the user-facing unit.
* Convert millimeters to meters internally for Blender geometry.
* Avoid hard-coding project-specific scene names.
* Avoid broad rewrites unless requested.
* Prefer small, safe changes.

Module-structure rules (multi-file package):

* Keep UI (`ui.py`) separate from placement logic (`hard_panels.py`,
  `seg_fabric.py`).
* Keep hard panel logic separate from SEG logic. Do not change hard-panel
  behavior while fixing SEG.
* Put shared array/grid detection and step math in `array_helpers.py` /
  `utils.py`.
* Avoid circular imports: `utils.py` imports nothing from the package; other
  modules import downward only.
* Register PropertyGroups before operators and panels; unregister in reverse
  order (in `__init__.py`).

## Testing Expectations

After any code change, the add-on should still install as the **`bematrix_addon`
package** through:

```text
Edit > Preferences > Add-ons > Install...   (select bematrix_addon.zip)
```

or by copying the `bematrix_addon/` folder into `scripts/addons/`. Do not install
only `__init__.py`.

Manual Blender tests should include:

```text
Hard panels:
  Single selected frame
  Multiple selected frames
  Horizontal array (X) hard panels
  Vertical array (Z) hard panels
  Grid array (X + Z) hard panels
  Front-only panel
  Back-only panel
  Both-side panels
  Material assigned per panel
  Repeated button press to confirm duplicates are not created
  Changed trim value
  Changed front/back offset values
  Frame with Blender duplicate suffix, such as .001
  Rotated frame object
  Collection source mode

SEG fabric (partially working — expect issues):
  Single frame SEG
  Horizontal array SEG (one continuous plane across the X run)
  Grid array SEG (one plane per Z row)
```

Do not claim a feature is fully verified unless it has been tested in Blender.
SEG fabric is **not** considered working yet.

## File Structure (Current — Multi-File Package)

The add-on was refactored from one large `bematrix_graphic_panels.py` file into a
multi-file package. The add-on is now the **`bematrix_addon/`** folder:

```text
bematrix-blender-tools/
  README.md
  AGENTS.md
  bematrix_addon/            <- the installable add-on package
    __init__.py              bl_info + register/unregister
    utils.py                 shared helpers, constants, frame detection, naming
    materials.py             unique per-object material creation
    array_helpers.py         array/grid detection, step math, modifier dump
    hard_panels.py           hard graphic panel placement (stable)
    seg_fabric.py            SEG fabric placement (partially working)
    properties.py            Scene PropertyGroup (UI state)
    operators.py             Add/Update, Delete, Convert-Array-to-Frames operators
    ui.py                    sidebar panel
```

Module responsibilities and rules:

* `utils.py` imports **nothing** from the package (bottom of the dependency
  graph). Higher-level modules import downward only. This keeps imports acyclic —
  **avoid circular imports**.
* Keep **UI** (`ui.py`) separate from **placement logic**
  (`hard_panels.py`, `seg_fabric.py`). The panel only draws.
* Keep **hard panel** logic separate from **SEG** logic. When fixing SEG, do not
  change hard-panel behavior.
* Keep **shared array/grid detection and step math** in `array_helpers.py` /
  `utils.py` so both panel types use the same code.
* `__init__.py` registers the **PropertyGroup before** operators and the panel,
  and **unregisters in reverse order**.

Install as the whole package: zip the `bematrix_addon` folder into
`bematrix_addon.zip` and install that, or copy the `bematrix_addon/` folder into
`scripts/addons/`. The final path must be
`.../scripts/addons/bematrix_addon/__init__.py`. **Do not install only
`__init__.py`** — if Blender reports `Modules Installed () from .../__init__.py`
(empty parentheses), the lone file was selected instead of the full package.

Do not add further module splits or rename modules unless asked.

## Git Workflow

Use small commits.

Recommended commit style:

```bash
git add .
git commit -m "Add initial BeMatrix graphic panel add-on"
```

Future commit examples:

```bash
git commit -m "Improve BeMatrix frame size detection"
git commit -m "Add collection mode for graphic panels"
git commit -m "Prevent duplicate generated panels"
git commit -m "Add UVs to generated graphic panels"
```

Before suggesting a commit, check the changed files and summarize what changed.

## Future Roadmap

Potential future features include:

### Graphic Panel Features

* Inside panel mode.
* Outside panel mode.
* Both inside and outside panel generation.
* Chart-based panel dimensions.
* UV mapping for image textures.
* Image texture assignment.
* Node Wrangler-friendly material setup.
* Automatic graphic placeholder naming.
* Optional panel thickness.

### BeMatrix Frame Tools

* Frame dimension labels.
* Frame audit/report tool.
* Invalid frame name detection.
* Select all frames by size.
* Select all generated panels.
* Delete generated panels by collection.
* Export frame and panel counts.

### Accessory Tools

* Add monitor placeholders.
* Add shelves.
* Add stem lights.
* Add counters.
* Add accessory markers.
* Align accessories to frame faces.

### Production Tools

* Export panel size list.
* Export graphic production list.
* Generate graphic naming schedule.
* Create print-ready reference data.

## Instructions for AI Coding Assistants

When modifying this project:

1. Read this file first.
2. Preserve the BeMatrix-specific assumptions.
3. Make one focused change at a time.
4. Do not rewrite the entire add-on unless explicitly asked.
5. Keep the existing workflow working.
6. Explain what changed and what needs to be tested in Blender.
7. Do not invent new frame rules without asking.
8. Do not silently change default dimensions, offsets, or trim values.
9. Keep the code readable for a non-programmer who is learning plugin development.
10. When unsure about geometry placement, ask before changing behavior.

## Good Task Examples

Good prompt:

```text
Add UV coordinates to the generated panel mesh so image textures map corner-to-corner. Do not change panel placement or sizing.
```

Good prompt:

```text
Refactor the frame name parsing into a separate function and add comments. Do not change behavior.
```

Good prompt:

```text
Add a button to select all generated BeMatrix panels in the chosen collection.
```

Good prompt:

```text
Add collection scanning for nested child collections, but keep the current direct collection behavior as the default.
```

## Bad Task Examples

Avoid broad prompts like:

```text
Rebuild the plugin.
```

```text
Make the plugin better.
```

```text
Add all BeMatrix tools.
```

```text
Rewrite this in a more advanced way.
```

Use specific, controlled prompts instead.

## Important Geometry Reminder

For this plugin, panel placement should be based on the frame object’s local axes:

```text
Width  = local X
Depth  = local Y
Height = local Z
Front  = local -Y
Back   = local +Y
```

Do not place panels using global Y unless explicitly instructed. Global Y will fail when frames are rotated.

## Project Priority

The priority is practical exhibit-design workflow reliability.

Correct sizing, predictable placement, duplicate prevention, and safe updates are more important than complex automation.
