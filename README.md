# BeMatrix Blender Tools

A Blender add-on for working with BeMatrix exhibit frames at real-world scale.

The first tool in this plugin is the **Graphic Panels** tool. It creates correctly sized panel planes on selected BeMatrix frame objects, using the frame dimensions from the object name or from the object’s measured size.

## Current Status

Version: `0.2.0-seg-fabric`
Blender target: `5.1.0`
Primary feature: Add/update graphic panel planes on BeMatrix frames.
Packaging: multi-file add-on package in the `bematrix_addon/` folder (see
[Project Structure](#project-structure--current-architecture)). The old single
`bematrix_graphic_panels.py` file is no longer the add-on.

### Feature Status

| Feature | Status |
| --- | --- |
| Hard panels (single frame) | ✅ Working |
| Hard panels: horizontal / vertical array | ✅ Working |
| Hard panels: two-array X/Z grid | ✅ Working |
| Front / back / both-side placement | ✅ Working |
| Unique per-panel materials | ✅ Working |
| Duplicate prevention / update-in-place | ✅ Working |
| **SEG fabric** | ⚠️ Added, **partially working** — still needs testing and fixes |

SEG fabric is included so the workflow and UI exist, but it is **not** fully
verified yet. Treat SEG output as work-in-progress. Hard-panel behavior is the
stable, supported path.

### Confirming Blender Loaded the Latest Files

Blender caches enabled add-ons, so an old copy can keep running after you edit
the package. To confirm the latest code is active:

1. The version label is shown at the top of **View3D > Sidebar > BeMatrix >
   Graphic Panels** (e.g. `Version: 0.2.0-seg-fabric`).
2. When you click **Add / Update Graphic Panels**, the System Console prints the
   add-on version and the full loaded file path (this path points at a module
   inside the installed `bematrix_addon/` package, e.g. `.../operators.py`).

If the version label or console version does not match the files you just edited,
fully remove and reinstall the add-on (Edit > Preferences > Add-ons), then
restart Blender.

### Modifier Debug Dump

Each run also prints a full **modifier dump** for every source frame: every
modifier's name and type, all readable standard RNA properties, all custom / ID
properties, and (for Geometry Nodes modifiers) every input socket label,
identifier, type and value. Open the System Console (**Window > Toggle System
Console**) before clicking the button. If array placement is still wrong, copy
the section between `--- MODIFIER DUMP ---` and `--- END MODIFIER DUMP ---`
along with the `Spacing dims` and `Computed array step` lines.

This is an early version of the add-on. The first goal is to make panel placement fast and consistent. Future versions may add material/image tools, accessory placement, frame labels, export data, and more BeMatrix-specific workflows.

---

## What This Add-on Does

The Graphic Panels tool can:

* Add a panel plane to one selected BeMatrix frame.
* Add panels to multiple selected BeMatrix frames.
* Scan a collection and add panels to valid BeMatrix frame objects.
* Add a panel to the front side, back side, or both sides.
* Parent generated panels to their source frame.
* Avoid duplicate panels by updating existing generated panels.
* Automatically assign a basic panel material.
* Use real-world millimeter dimensions converted to Blender meters.
* Generate real `_A001`, `_A002`, etc. panel objects for frames with one simple Array modifier.
* Generate a grid of `_A###_B###` panel objects for frames with two stacked Array modifiers.
* Generate **SEG Fabric** planes that use the full frame size and combine an X array into one continuous plane per row. ⚠️ *Partially working — still being tested and fixed.*

---

## Frame Assumptions

This add-on assumes BeMatrix frames are modeled at real-world scale.

### Blender Axis Setup

The plugin assumes each frame object uses the following local axes:

```text
X = frame width
Y = frame depth
Z = frame height
```

For a normal frame at world origin:

```text
Local -Y = front side
Local +Y = back side
```

Default panel offsets:

```text
Front panel: -31 mm on local Y
Back panel:  +31 mm on local Y
```

Generated panels are created in the frame’s local X/Z plane, then parented to the frame. This allows panels to follow frames that are rotated vertically or horizontally, as long as the frame object’s local axes are consistent.

---

## Supported Frame Naming

The add-on is designed around BeMatrix frame object names like:

```text
B62 0496 2418
B62 0992 2418
B62 2418 0992
B62 0496 2418.001
```

The dimensions are interpreted as millimeters.

For example:

```text
B62 0992 2418
```

is read as:

```text
Width:  992 mm
Height: 2418 mm
```

Blender duplicate suffixes such as `.001`, `.002`, and `.003` are ignored when detecting dimensions.

---

## Panel Sizing Logic

The current version uses a configurable trim value.

Default:

```text
Panel trim: 6 mm
```

The trim is subtracted from both the frame width and frame height.

Example:

```text
Frame: 992 mm x 2418 mm
Trim:  6 mm

Panel: 986 mm x 2412 mm
```

This matches the working assumption that the infill panel is usually 6 mm smaller than the frame dimension.

Later versions may add a true chart-based lookup for separate inside and outside panel dimensions.

---

## Installation

This add-on is now a **multi-file package** in the `bematrix_addon/` folder. You
must install the whole package, **not** a single `.py` file.

### Recommended: install a zip of the package folder

1. Zip the **`bematrix_addon` folder itself** so the archive is
   `bematrix_addon.zip` and contains `bematrix_addon/__init__.py` inside it.

   ```text
   bematrix_addon.zip
     └── bematrix_addon/
           __init__.py
           utils.py
           ...
   ```

   > Do **not** zip only `__init__.py`, and do not zip the loose module files
   > without the `bematrix_addon/` folder around them.

2. Open Blender and go to:

   ```text
   Edit > Preferences > Add-ons > Install...
   ```

3. Choose `bematrix_addon.zip`.

4. Enable **BeMatrix Graphic Panels** in the list.

5. After enabling, the installed path should look like:

   ```text
   .../scripts/addons/bematrix_addon/__init__.py
   ```

6. In the 3D Viewport, open the sidebar with `N`, then go to:

   ```text
   BeMatrix > Graphic Panels
   ```

### Alternative: copy the folder directly

You can also copy the entire `bematrix_addon` folder into your Blender add-ons
directory:

```text
.../scripts/addons/bematrix_addon/
```

Then enable the add-on in Preferences. Restart Blender if it does not appear.

### Do NOT install only `__init__.py`

Selecting just `bematrix_addon/__init__.py` in the Install dialog will fail,
because that file imports its sibling modules (`utils.py`, `operators.py`, etc.)
which will not be present next to it. See
[Troubleshooting installation](#troubleshooting-installation) below.

### Troubleshooting installation

If Blender reports something like:

```text
Modules Installed () from '.../__init__.py'
```

(note the empty parentheses), it means **only the file was selected instead of
the full add-on package**. Blender copied a lone `__init__.py` with no package
folder and no sibling modules, so nothing registered.

Fix it by installing the **zipped `bematrix_addon` folder** (or copying the whole
`bematrix_addon/` folder into `scripts/addons/`) as described above, so the final
path is `.../scripts/addons/bematrix_addon/__init__.py` with all the module files
beside it.

---

## Basic Usage

### Add Panels to Selected Frames

1. Select one or more BeMatrix frame objects.
2. Open:

```text
View3D Sidebar > BeMatrix > Graphic Panels
```

3. Set **Source** to:

```text
Selected Objects
```

4. Choose **Panel Side**:

```text
Front -Y
Back +Y
Both Sides
```

5. Confirm the trim and offsets:

```text
Panel Trim mm: 6
Front Offset mm: -31
Back Offset mm: 31
```

6. Click:

```text
Add / Update Graphic Panels
```

The add-on will create panel planes and parent them to the selected frames.

---

## Collection Usage

The add-on can also scan a collection for valid BeMatrix frames.

Available source modes:

```text
Selected Objects
Active Object Collection
Chosen Collection
```

### Active Object Collection

Use this when the active frame belongs to the collection you want to process.

### Chosen Collection

Use this when you want to manually pick a collection and process all valid BeMatrix frames inside it.

Only mesh objects with recognizable BeMatrix dimensions will be processed.

---

## Duplicate Prevention

Generated panels are marked with custom properties, including:

```text
is_bematrix_panel
bematrix_parent_frame
bematrix_panel_side
bematrix_frame_width_mm
bematrix_frame_height_mm
bematrix_panel_width_mm
bematrix_panel_height_mm
```

When **Update Existing Panels** is enabled, the add-on checks for an existing generated panel on the same frame and side. If one already exists, it updates the existing panel instead of creating a duplicate.

This allows you to safely run the tool again after changing trim or offset settings.

### Troubleshooting Nested Panel Names

If repeated runs create names like `BM_PANEL_BACK_BM_PANEL_BACK_...`, a generated
panel is being processed as if it were a source frame. Generated panels should be
excluded from frame detection by their `is_bematrix_panel` custom property, with
the `BM_PANEL_` name prefix as a fallback.

### Troubleshooting Duplicate / Stacked Panels

If repeated clicks of **Add / Update Graphic Panels** create duplicate panels in
the same spot, or if stale `_A###` panels are not deleted when the Array count
decreases, the duplicate-detection check is failing to recognise existing
panels.

Blender stores a boolean custom property as an integer, so reading
`is_bematrix_panel` back returns `1`, not Python `True`. Identity tests such as
`obj.get("is_bematrix_panel") is True` therefore evaluate to `False` and the
add-on never matches its own panels. The add-on now uses a truthy check
(`bool(obj.get("is_bematrix_panel"))`) everywhere it looks for existing or stale
panels, so updates and deletions match correctly.

---

## Array Modifier Support

If a source frame has one simple count-based Array modifier, **Add / Update
Graphic Panels** creates one real panel object per array position and side. The
generated objects use `_A001`, `_A002`, etc. suffixes.

Example for `B62 0992 0992` with Array count `2` and Relative Offset X `1.0`:

```text
BM_PANEL_FRONT_B62 0992 0992_A001
BM_PANEL_FRONT_B62 0992 0992_A002
BM_PANEL_BACK_B62 0992 0992_A001
BM_PANEL_BACK_B62 0992 0992_A002
```

`_A001` is placed at the base frame position. `_A002` is offset using the source
frame's Array spacing. Relative Offset X uses the detected frame width, so
`B62 0992 0992` spaces panels by `0.992 m`, not by the trimmed panel width.

### Array Position Formula

The Array offset is the **spacing between each copy**. The generated panel for
array index *N* is placed at:

```text
position(N) = base_position + step * (N - 1)
```

so:

```text
_A001 = base + step * 0
_A002 = base + step * 1
_A003 = base + step * 2
_A004 = base + step * 3
```

The step is the spacing itself — it is **not** divided by `(count - 1)`.
Dividing would happen to look correct for count `2` but would place the count `3`
panel halfway between the frames instead of aligning to the third frame.

Example, `B62 0992 0992` with Relative Offset X `1.0`:

```text
Count 3  ->  X positions: 0, 0.992, 1.984
```

With Relative Offset X `2.0`:

```text
Count 3  ->  X positions: 0, 1.984, 3.968
```

### Array Step Uses the Source Frame Dimensions (Not the Bounding Box)

The Array **step** (center-to-center spacing) is calculated from the source
frame's real dimensions, **not** the trimmed panel size and **not** the
evaluated bounding box:

```text
X step -> parsed frame width  from the name (e.g. 0992 -> 0.992 m)
Z step -> parsed frame height from the name (e.g. 0992 -> 0.992 m)
Y step -> parsed frame depth  from the B-number (e.g. B62 -> 0.062 m),
          falling back to the raw mesh depth (pre-modifier) if needed
```

The **panel size** is still the name dimension minus trim (a `992 mm` frame
with `6 mm` trim makes a `986 mm` panel). **Trim only affects panel size, never
the spacing.**

Why not the bounding box? `obj.bound_box` / `obj.dimensions` are *evaluated* and
can be slightly larger than the nominal frame (e.g. a `992 mm` frame whose mesh
measures ~`998 mm`) or can include the Array's duplicated copies. Using them
made the second panel land ~`6 mm` too far. Parsing the name avoids this.

```text
Relative Offset X -> multiplies parsed frame width
Relative Offset Z -> multiplies parsed frame height
Relative Offset Y -> multiplies parsed frame depth (B-number)
Constant Offset    -> already in Blender units, added directly
Relative + Constant -> combined
```

Spacing example for `B62 0992 0992` (panel trim `6 mm`, panel size
`986 mm x 986 mm`) with Relative Offset X `1.0`: the X step is the parsed frame
width, `0.992 m`, giving an exact center spacing of `992 mm` and a visible gap
of about `6 mm` (`992 - 986`).

### Array on Local Y (Depth)

Local Y is frame depth: local `-Y` is the front side, local `+Y` is the back
side. The front/back base Y offsets (`-31 mm` / `+31 mm`) are the panel's base
position. Array Y movement is **added** to that base, never overwriting it:

```text
panel Y = front/back base Y offset + array step Y * (N - 1)
```

Running the action again updates existing `_A###` panels. If the Array count
increases, missing panels are created. If the count decreases, extra generated
panels for that frame and side are deleted.

### Two Stacked Arrays (Grid)

The add-on supports **up to two** simple count-based Arrays on a frame — for
example one Array for columns and one for rows. It generates one real panel
object for **every combination**:

```text
total panels per side = Array 1 count x Array 2 count
3 x 3 = 9 panels per side
2 x 4 = 8 panels per side
```

Two-array panels are named with both indices:

```text
BM_PANEL_FRONT_B62 0992 0992_A001_B001
BM_PANEL_FRONT_B62 0992 0992_A001_B002
BM_PANEL_FRONT_B62 0992 0992_A002_B001
```

Each panel's location combines both array steps:

```text
panel_location = base_location + step_1 * (index_1 - 1) + step_2 * (index_2 - 1)
_A001_B001 -> indices 1,1 -> step_1*0 + step_2*0
_A001_B002 -> indices 1,2 -> step_1*0 + step_2*1
_A002_B001 -> indices 2,1 -> step_1*1 + step_2*0
```

Re-running updates existing panels (matched by parent frame, side, index 1 and
index 2), creates missing combinations when a count increases, and deletes stale
ones when a count decreases. One-array frames keep the existing `_A001`,
`_A002`, … naming and behavior, and no-array frames are unchanged.

The supported Array workflow is limited to **one or two** count-based Arrays
using Relative Offset and/or Constant Offset along local X, Y, or Z. Three or
more stacked Arrays are not combined (only the first two are used). Array
modifiers are never copied onto generated panels.

---

## Panel Type: Hard Panel vs SEG Fabric

The **Panel Type** dropdown selects what the tool generates:

* **Hard Panel** (default) — the original behavior: trimmed flat panels, one per
  frame and per array position, with `6 mm` trim and `-31 / +31 mm` offsets.
  Everything above about arrays, grids, duplicates and materials applies.
* **SEG Fabric** — fabric graphic planes for SEG frames.

### SEG Fabric Behavior

* SEG planes are flat planes that use the **full frame size** (no trim). A
  `B62 0992 2418` frame makes a `992 mm x 2418 mm` SEG plane.
* SEG offsets sit **1 mm outside** the hard panel: front `-32 mm`, back `+32 mm`.
* **X array → one continuous plane.** If the frame has an X array, the SEG plane
  spans the whole X run instead of one plane per frame:

  ```text
  frame width 992 mm, X array count 3  ->  SEG width = 992 * 3 = 2976 mm
  SEG height = frame height
  ```

* **X/Z grid → one plane per Z row.** A 3-wide × 2-high grid makes **2** SEG
  planes per side; each plane is the full X span wide and one frame tall.
* SEG planes are named per row:

  ```text
  BM_SEG_FRONT_B62 0992 2418_ROW001
  BM_SEG_BACK_B62 0992 2418_ROW001
  BM_SEG_FRONT_B62 0992 2418_ROW002
  ```

* Re-running updates existing SEG planes (matched by parent frame, side, and row
  index). Increasing the X count updates the plane width; increasing/decreasing
  the Z count creates/deletes row planes; changing offsets moves the planes.
* Each SEG plane gets its **own unique material** named from the SEG object name
  (e.g. `MAT_BM_SEG_FRONT_B62_0992_2418_ROW001`), white with Specular IOR
  Level `0`.
* Generated `BM_SEG_` objects are excluded from source-frame detection, like
  `BM_PANEL_` objects.

Hard panels and SEG planes are tracked independently (via a `bematrix_panel_kind`
property), so switching type and re-running does not delete the other type. Use
**Delete Generated Panels** to clear everything.

---

### Two Different "Array" Modifier Types

Blender has **two** completely different ways to make an array, and they are
read very differently in Python. The add-on now supports both:

1. **Classic Array modifier** (Add Modifier > *Array*). Exposes `count`,
   `use_relative_offset` / `relative_offset_displace`, and `use_constant_offset`
   / `constant_offset_displace` as direct attributes.
2. **Geometry Nodes array** (a node-group modifier, shown with the geometry
   nodes icon and controls like *Shape: Line*, *Offset Method*, *Realize
   Instances*, *Randomize*, *Merge*). This modifier's type is `NODES` and has
   **no** `count` attribute — its inputs (`Count`, `Offset`, `Offset Method`)
   are read from the node group's socket interface.

**Blender 5.1 "Array" asset:** the array you add in Blender 5.1 is the bundled
Geometry Nodes *Array* asset. Its relative-vs-constant behavior is controlled by
its **`Relative Space`** boolean, not by `Offset Method`:

* `Relative Space = True` → the `Offset` vector is a **multiple of the frame
  size** (Offset X `1.0` = one frame width per copy). This is the normal BeMatrix
  case and gives `992 mm` center spacing for a `B62 0992 …` frame.
* `Relative Space = False` → the `Offset` vector is a **constant distance in
  metres**, added directly.

The add-on reads `Relative Space` first. (Reading `Offset Method` instead made a
relative offset of `1.0` behave like a literal `1.0 m` step, putting panels at
`0, 1, 2 m` instead of `0, 0.992, 1.984 m`.) Older node groups that expose an
`Offset Method` menu instead of `Relative Space` still fall back to that menu.

> Tip: If array panels behave unexpectedly, the classic Array modifier is the
> most predictable option. When you click **Add / Update Graphic Panels**, the
> console prints which modifier type was detected, the count, the offset
> settings, and the computed step vector, so you can confirm what the add-on
> read.

---

## Generated Object Names

Generated panels use names like:

```text
BM_PANEL_FRONT_B62 0992 2418
BM_PANEL_BACK_B62 0992 2418
```

If the source frame has a Blender duplicate suffix, the suffix is removed from the generated panel name.

Example:

```text
Source frame:
B62 0992 2418.001

Generated panel:
BM_PANEL_FRONT_B62 0992 2418
```

The panel still stores the exact parent frame name in its custom properties.

---

## Material

**Each generated panel gets its own unique material** (not one shared material).
The material name is based on the panel object name, with spaces replaced by
underscores:

```text
BM_PANEL_FRONT_B62 0992 0992_A001  ->  MAT_BM_PANEL_FRONT_B62_0992_0992_A001
BM_PANEL_FRONT_B62 0992 0992_A002  ->  MAT_BM_PANEL_FRONT_B62_0992_0992_A002
```

This lets you edit each panel's material independently (for example, to assign a
different graphic per panel later). Each material is created with the same
default look:

```text
Base Color: White
Roughness: 0.5
Specular IOR Level: 0   (falls back to "Specular" on older Blender)
```

Re-running **Add / Update Graphic Panels** reuses each panel's existing material
by name and updates its settings, instead of creating endless duplicate
materials. The console prints the material assigned to each generated panel.

Image texture and UV workflow may be added in a future version.

---

## Known Limitations

This version assumes:

* Frame objects are modeled at real-world scale.
* Frame local axes are consistent.
* Frame origins are centered.
* Object names contain valid BeMatrix dimensions, or the object bounding box closely matches known BeMatrix sizes.
* Panels are flat mesh planes without thickness.
* Panel trim is controlled by a simple value, currently defaulting to 6 mm.
* Full inside/outside panel chart logic is not implemented yet.

If a frame origin is not centered, the panel may be correctly sized but visually offset. Future versions may calculate the local bounding box center to improve placement.

---

## Project Structure / Current Architecture

The add-on was refactored from one large `bematrix_graphic_panels.py` file into a
multi-file package. The repository now looks like:

```text
bematrix-blender-tools/
  README.md
  AGENTS.md
  bematrix_addon/            <- the installable add-on package
    __init__.py              registration (bl_info, register/unregister)
    utils.py                 shared helpers, constants, frame detection, naming
    materials.py             unique per-object material creation
    array_helpers.py         array/grid detection, step math, modifier dump
    hard_panels.py           hard graphic panel placement
    seg_fabric.py            SEG fabric placement (partially working)
    properties.py            Scene PropertyGroup (UI state)
    operators.py             Add/Update and Delete operators
    ui.py                    sidebar panel (View3D > BeMatrix)
```

### What each module does

* **`__init__.py`** — defines `bl_info`, imports the classes, and registers them.
  Registers the PropertyGroup **before** the operators and panel, and unregisters
  in **reverse** order. This is the file Blender loads as the add-on entry point.
* **`utils.py`** — pure/shared helpers with no dependency on other modules:
  constants and name prefixes, mm↔m conversion, frame-name and depth parsing,
  frame-size detection, generated-object naming, the generated-object marker
  check, and source-frame selection. Bottom of the dependency graph.
* **`materials.py`** — creates/reuses a unique material per generated object.
* **`array_helpers.py`** — reads classic Array and Geometry Nodes "Array"
  modifiers into a single `ArraySettings`, computes per-copy step vectors, builds
  the (index_1, index_2) grid positions, and prints the modifier debug dump.
  Shared by both hard panels and SEG.
* **`hard_panels.py`** — hard panel placement, sizing, duplicate prevention and
  update logic. The stable, supported path.
* **`seg_fabric.py`** — SEG fabric placement (full frame size, combined X run,
  one plane per Z row). Still being tested/fixed; kept separate from hard panels.
* **`properties.py`** — the `BEMATRIX_PanelProperties` group backing the UI.
* **`operators.py`** — the operators; dispatches each frame to the hard or SEG
  generator based on Panel Type and prints diagnostics.
* **`ui.py`** — the sidebar panel layout only (no placement logic).

### Dependency direction (no circular imports)

```text
utils  <-  materials, array_helpers
utils, materials, array_helpers  <-  hard_panels, seg_fabric
utils, array_helpers, hard_panels, seg_fabric  <-  operators
utils  <-  ui
properties  (stands alone)
__init__  imports properties, operators, ui and registers everything
```

`utils.py` imports nothing from the package, so the graph stays acyclic.

---

## Testing Checklist

Test inside Blender after every meaningful change. Open the System Console
(**Window > Toggle System Console**) so you can read the diagnostics.

**Hard panels (supported):**

* [ ] Single frame, hard panel (no array).
* [ ] Horizontal array hard panels (X array) — panels span left↔right correctly.
* [ ] Vertical array hard panels (Z array) — panels stack top↔bottom correctly.
* [ ] Grid array hard panels (X + Z) — full `count1 × count2` grid generated.
* [ ] Front / back / both-side placement (offsets `-31` / `+31 mm`).
* [ ] Material / image assignment — each panel has its own `MAT_…` material.
* [ ] Re-run does not create duplicates; changing counts adds/removes panels.

**SEG fabric (partially working — expect issues, log them):**

* [ ] Single frame SEG — one full-size plane per side, offsets `-32` / `+32 mm`.
* [ ] Horizontal array SEG — one continuous plane across the whole X run.
* [ ] Grid array SEG — one plane per Z row.

**General:**

* [ ] Frame with a Blender duplicate suffix (e.g. `.001`) is handled.
* [ ] Rotated frame — panels follow the frame's local axes.
* [ ] Collection source modes work.
* [ ] `BM_PANEL_` / `BM_SEG_` objects are never treated as source frames.

Do not claim SEG is fixed until its three checks above pass in Blender.

---

## Development Notes

The plugin should remain compatible with Blender `5.1.0`.

Important development rules:

* Keep operators undoable.
* Avoid destructive changes unless explicitly requested.
* Preserve generated panel custom properties.
* Keep frame detection predictable.
* Use millimeters for user-facing dimensions.
* Convert millimeters to meters internally for Blender geometry.
* Test inside Blender after every meaningful code change.

### Multi-file structure guidance

* Keep **UI code** (`ui.py`) separate from **placement logic** (`hard_panels.py`,
  `seg_fabric.py`). The panel should only draw; it must not compute geometry.
* Keep **hard panel logic** (`hard_panels.py`) separate from **SEG logic**
  (`seg_fabric.py`). When fixing SEG, do not change hard-panel behavior.
* Keep **shared array/grid detection and step math** in helper modules
  (`array_helpers.py`, `utils.py`) so both panel types use the same code.
* **Avoid circular imports.** `utils.py` must not import other package modules;
  higher-level modules import downward only (see the dependency direction above).
* **Register PropertyGroups before operators and panels**, and **unregister in
  reverse order** (handled in `__init__.py`).
* Bump `ADDON_VERSION` in `utils.py` on meaningful changes so the sidebar label
  and console output confirm the loaded build.

---

## Suggested Git Workflow

Before making future changes, commit the working baseline:

```bash
git add .
git commit -m "Add initial BeMatrix graphic panel add-on"
```

For future updates:

```bash
git status
git add .
git commit -m "Describe the change"
```

Use small commits. Test each feature in Blender before committing.

---

## Future Roadmap

Potential future features:

### Graphic Panel Improvements

* Add true panel type options:

  * Inside panel
  * Outside panel
  * Both panel types
* Add chart-based panel dimension lookup.
* Add UV setup for graphic placement.
* Add image texture assignment.
* Add automatic image aspect-fit tools.
* Add panel naming based on size and side.
* Add optional panel thickness.

### Frame Tools

* Detect BeMatrix frame size more robustly.
* Add frame labels.
* Add frame dimension callouts.
* Add collection-wide frame audit.
* Report unmatched or invalid frame names.

### Material Tools

* Create standard BeMatrix material presets.
* Assign graphic materials by panel side.
* Add white, black, fabric, SEG, and placeholder graphic presets.

### Workflow Tools

* Export a panel list.
* Export panel dimensions for production.
* Select all generated panels.
* Delete all generated panels in a collection.
* Convert panels to named graphic placeholders.

### Accessory Tools

* Add stem lights.
* Add monitor placeholders.
* Add shelves.
* Add counters.
* Add extrusion/accessory markers.

---

## Codex / AI Development Guidance

When using Codex or another coding assistant, work on one feature at a time. The
add-on is now the `bematrix_addon/` package — point prompts at the relevant
module, not at the old `bematrix_graphic_panels.py` file.

Good example prompts:

```text
In bematrix_addon/seg_fabric.py, fix SEG plane placement. Do not change
hard_panels.py or any hard-panel behavior. Preserve Blender 5.1.0 compatibility.
```

```text
In bematrix_addon/array_helpers.py, improve Geometry Nodes array detection.
Keep the shared ArraySettings shape so hard_panels.py and seg_fabric.py both work.
```

```text
In bematrix_addon/utils.py, improve frame detection so names like
B62 0496 2418.001 are parsed correctly, and add clear comments.
```

```text
Add UV coordinates to generated panel meshes in bematrix_addon/hard_panels.py so
image textures map cleanly from corner to corner. Do not touch SEG.
```

Avoid asking the assistant to rebuild the entire add-on at once. Small, controlled
updates to a single module are safer for Blender add-on development.

---

## License

Internal project. Add a license later if this will be shared publicly.
