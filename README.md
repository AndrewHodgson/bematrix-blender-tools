# BeMatrix Blender Tools

A Blender add-on for working with BeMatrix exhibit frames at real-world scale.

The first tool in this plugin is the **Graphic Panels** tool. It creates correctly sized panel planes on selected BeMatrix frame objects, using the frame dimensions from the object name or from the object’s measured size.

## Current Status

Version: `0.8.2-dimension-calibration`
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
| Print Layout Export: grouped SVG, per-group export modes, validation, simple L-wall unfold, Illustrator guide groups, Graphic IDs, project manifest, metadata JSON, Illustrator artboard script | Phase 7 project export |
| Utility: Convert Array to Individual Frames | ✅ Working |
| **SEG fabric (Smart SEG)** | ✅ Working — one connected mesh across selected frames |
| Frame Transform: vertex-to-vertex snap | ✅ Working |

SEG fabric is included so the workflow and UI exist, but it is **not** fully
verified yet. Treat SEG output as work-in-progress. Hard-panel behavior is the
stable, supported path.

### Confirming Blender Loaded the Latest Files

Blender caches enabled add-ons, so an old copy can keep running after you edit
the package. To confirm the latest code is active:

1. The version label is shown at the top of **View3D > Sidebar > BeMatrix >
   Graphic Panels** (e.g. `Version: 0.8.2-dimension-calibration`).
2. When you click **Add / Update Graphic Panels**, the System Console prints the
   add-on version and the full loaded file path (this path points at a module
   inside the installed `bematrix_addon/` package, e.g. `.../operators.py`).

If the version label or console version does not match the files you just edited,
build a fresh ZIP and use **Update** in the BeMatrix sidebar.
Restart Blender if new panels, operators, or UI changes still do not appear.

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
* Export selected/generated hard-panel or SEG plane objects as a true-size SVG
  layout for Illustrator, including straight walls and simple two-segment
  unfolded corner groups.
* Generate **Smart SEG Fabric**: one connected fabric mesh that follows only the selected frames (one quad per frame, shared edges, empty cells left empty, real-world UVs).

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

### Build an install ZIP

From the repo root, run:

```bash
python build_zip.py
```

The script reads the version from `bematrix_addon/__init__.py` when possible and
creates a clean install ZIP in:

```text
dist/
```

Example output:

```text
dist/bematrix_blender_tools_v0.8.2.zip
```

The ZIP contains the correct top-level add-on folder:

```text
bematrix_addon/
  __init__.py
  utils.py
  ...
```

It excludes development files such as `.git`, `__pycache__`, `.pytest_cache`,
`.vscode`, `dist`, backup files, and temporary files.

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

### Update an installed add-on from ZIP

After the add-on is installed, use the sidebar update workflow instead of
manually uninstalling and reinstalling:

1. Run `python build_zip.py`.
2. In Blender, open:

   ```text
   View3D > Sidebar > BeMatrix
   ```

3. Beside the visible version number, click **Update**.
4. Choose the ZIP from `dist/`.

The updater installs the selected ZIP over the existing add-on with overwrite
enabled. Restart Blender after updating; Blender can invalidate the running
operator when an enabled add-on overwrites itself, so the updater avoids
in-session reloads.

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
* **SEG Fabric (Smart SEG)** — one continuous fabric mesh that follows only the
  **selected frames**.

### Smart SEG Fabric Behavior

With **Panel Type = SEG Fabric**, select the frame objects you want covered and
click **Add / Update Graphic Panels**. The add-on builds **one SEG mesh object
per side** that follows those frames:

* **One cell per frame (and per array instance).** Each frame is one rectangular
  SEG cell using the **full frame size** (no trim). If a selected frame still has
  Array modifiers, each array instance becomes its own cell (same array math as
  the panels), so straight arrays/grids work too.
* **Outside-face offset (frame depth aware).** `B62` frames are `62 mm` deep with
  a centered origin: the physical front face is at local Y `-31 mm` and the back
  face at `+31 mm`. SEG sits **1 mm outside** the face: `±32 mm` along local Y.
* **Understands the outside of a box.** For each frame the side is chosen by the
  **group centroid**: the SEG goes on the face pointing **away from the centre of
  the selected frames**, so a box of frames gets fabric on the **outside**
  (and the **inside** for the Back side / `Both Sides` makes both). For a flat
  coplanar wall the centroid is in-plane, so it falls back to local `-Y` (Front) /
  `+Y` (Back) exactly as before. The chosen direction is each frame's local Y in
  world space, so rotated frames are handled.
* **Plane grouping — bends at corners, no diagonal stretch.** Cells are grouped
  by their **face plane**. Coplanar, touching cells weld into **one connected
  planar section** (a straight wall or in-plane X/Z array/grid becomes one large
  flat section). A rotated frame or **90° corner** has a different face normal,
  so it becomes a **separate planar section in the same object** — the fabric
  *bends* at the corner instead of being stretched flat across it.
* **Corner bridges (spans the frame depth).** Where two perpendicular sections
  meet at a corner, a **bridge face** is added across the frame depth so there is
  **no gap** between, e.g., a bottom run and a side run. Parallel/opposite walls
  are not bridged.
* **One object, multiple sections.** All sections and bridges live in a single
  SEG mesh object for easy selection and material assignment; only genuinely
  different planes are split (no extra objects).
* **Empty grid spaces stay empty.** Only real cells get a quad (an L-shaped
  selection makes an L-shaped mesh, no missing-cell fill). Within a coplanar
  section, near-adjacent cells are welded within a tolerance (10% of the smallest
  frame dimension) so small placement gaps still connect.
* **Parented to the main frame and rotation-safe.** The mesh is built in the
  **main frame's local space** and parented to it, so it follows the frames and
  is correct even if the whole group is rotated. The **main frame** is the active
  selected frame (the last one you clicked), or the first frame if none is
  active. `Both Sides` makes one mesh per side.

Examples (39.06 = a 992 mm frame in inches):

```text
3 frames in a row        -> one mesh, 1 coplanar section, overall 117.18 x 39.06
2 in a row + 1 above #2  -> one mesh, 1 section, L-shaped (no upper-left fill)
straight run + 90deg run -> one mesh, 2 planar sections that bend at the corner
```

**UVs** use real-world planar coordinates (meters), computed **per section in
that section's own plane**, so rotated/corner sections unwrap cleanly (a vertical
or perpendicular run is not collapsed). Sections are packed side-by-side in U so
they do not overlap; within a section UVs are continuous and preserve real
dimensions (a 3-frame-wide run unwraps three frame widths wide). Normals face
outward on the chosen side.

* The mesh object is named `SEG_Fabric_Panel_<SIDE>_<main frame>` (e.g.
  `SEG_Fabric_Panel_FRONT_B62 0992 0992`), is **parented to the main frame**,
  gets its own unique material (white, Specular IOR Level `0`), and is marked so
  it is excluded from source-frame detection.
* **Re-running with the same main frame updates that frame's SEG mesh.**
  Selecting a **different** group (different main frame) makes a **separate** SEG
  mesh and leaves the earlier ones intact.
* Because the SEG mesh is now a child of its main frame, **Delete Generated
  Panels** removes it along with other generated children of that frame.

Hard panels and SEG meshes are tracked independently (via a
`bematrix_panel_kind` property), so switching type does not delete the other.

---

## Print Layout Export

The **Print Layout Export** section provides SVG export for Illustrator. It can
export the currently selected generated hard-panel or SEG plane objects, or a
saved **Print Group**. It does **not** scan the whole scene.

The panel is organized into **Print Groups**, **Export Options**, and
**Validation Options** so creation/selection, export settings/actions, and
preflight checks stay separate.

Use it for straight-wall layouts or simple two-segment corner unfolds:

1. Select the generated panel/SEG plane objects to export.
2. Open **View3D Sidebar > BeMatrix > Print Layout Export**.
3. Create or select a **Print Group**.
4. Set that Print Group's **Export Mode** to **Auto Detect**, **Straight Wall**,
   or **Unfold Connected Walls**.
5. Expand **Export Options**, then click **Export Active** or **Export All**.

The SVG is true-size, uses inches as the document unit, and preserves the real
world spacing/gaps between the selected planes based on their world-space mesh
vertices. Each exported plane becomes an editable SVG rectangle with a text label
showing the object name plus width and height in inches.

### Export Options

The **Export Options** section controls both selected-plane export and Print
Group folder export:

* **Include Print Group Title** adds the Print Group name above the layout.
  Selected-plane exports do not have a Print Group name, so this option only
  affects saved Print Groups.
* **Include Panel Labels** adds production labels to each panel. Labels include
  the Graphic ID when available, the Print Group display name, the Blender object
  name, the true-size dimensions, and the selected Illustrator template scale:

  ```text
  BW01
  Back Wall
  Object: BM_PANEL_FRONT_B62 0992 2418
  Real: 38.82 in x 94.96 in
  Scale: 10%
  ```

* **Include Artboard Guides** adds a separate guide rectangle for each panel.
  Each guide exactly matches the panel rectangle's exported size and position.
* **Include Illustrator Artboard Script** writes a matching JSX file during
  **Export Active** and **Export All**:

  ```text
  Project_Graphics_Export/
    SVG/BW_Back_Wall.svg
    Illustrator/BW_Back_Wall_artboards.jsx
    Metadata/Project_manifest.csv
    Metadata/bematrix_export.json
  ```

  `Project_manifest.csv` records the exported panel bounds, Graphic IDs,
  artboard names, SVG filename, JSX filename, real-size coordinates, and
  template-scale coordinates. `bematrix_export.json` records project-level and
  print-group-level metadata for the separate Illustrator Script Panel. The JSX
  script can be run in Illustrator to create correctly named artboards from
  those same template-scale bounds.

* **Illustrator Template Scale** controls the size of the exported Illustrator
  working template:

  ```text
  Full Size 1:1
  50%
  25%
  10%
  ```

  The default is **10%**, which is recommended for render/mockup workflows and
  large exhibit graphics that may exceed Illustrator's normal canvas/artboard
  limits at full size. SVG panel rectangles, artboard guide rectangles, manifest
  template coordinates, and JSX artboards use the selected scale. Real-world
  dimensions are still preserved in labels and manifest data.

* **Artboard Naming** controls the `artboard_name` written to the manifest and
  used by the generated Illustrator JSX:

  ```text
  Graphic ID only                 -> LWT01
  Group Name + Number             -> L_Wall_Test_01
  Abbreviation + Group Name + Number -> LWT_L_Wall_Test_01
  ```

  The default is **Abbreviation + Group Name + Number**. The manifest still
  includes the raw `graphic_id` column regardless of the selected artboard name
  format.

All four options are enabled by default.

### Project Export Folder

**Export Active** and **Export All** ask for a parent folder, then create a new
project export folder:

```text
Project_Graphics_Export/
  SVG/
  Illustrator/
  Metadata/
  Exports/
  Logs/
```

If `Project_Graphics_Export` already exists, the add-on creates the next
available numbered folder, such as `Project_Graphics_Export_001`.

Each exported Print Group writes one SVG to `SVG/` and, when enabled, one
matching Illustrator artboard script to `Illustrator/`. The export writes one
combined manifest and one metadata JSON file to:

```text
Metadata/Project_manifest.csv
Metadata/bematrix_export.json
```

For **Export Active**, the combined manifest contains that one group. For
**Export All**, it contains all successfully exported groups. Groups that fail
validation are skipped and reported in the console instead of stopping the whole
batch export.

The `Exports/` folder is created as the recommended destination for artwork
images exported from Illustrator. `Logs/` is reserved for external workflow
logs.

### Export Metadata JSON

The Blender add-on writes metadata for the separate Illustrator Script Panel to:

```text
Metadata/bematrix_export.json
```

The JSON starts with `formatVersion: 1` and treats Blender as the source of
truth for exported Print Groups. It includes project/export-level information
such as project name, export date/time, export scope, resolved export modes,
Blender file name when the `.blend` has been saved, scene unit settings, add-on
version, and relative folder names.

It also includes one `printGroups` entry per exported or skipped Print Group
with fields such as:

```text
printGroupName
displayName
svgFilename
svgRelativePath
jsxFilename
jsxRelativePath
exportStatus
exportModeSetting
exportModeResolved
wallSegmentNames
panelCount
missingPlaneCount
invalidPlaneCount
widthIn
heightIn
notes
```

Fields that are not available for a group are written as `null`, empty arrays,
or omitted only where the format does not need the field. Illustrator should use
this file instead of guessing group names, SVG paths, or panel counts from
filenames.

### Illustrator SVG Structure

Exported SVG files are organized into readable groups so Illustrator opens them
with selectable sections:

```text
print_group_title
panel_rectangles
artboard_guides
panel_labels
```

Panel rectangles remain normal editable SVG `<rect>` elements. Artboard Guides
are separate dashed rectangles with ids such as `artboard_BW01` when Graphic IDs
exist, falling back to names such as `artboard_Back_Wall_01` for older groups.
They are intended to make it easier to create matching Illustrator artboards
from the exported panel positions. They do not change the Blender panel geometry
or validation; they are drawn at the selected template scale. The generated JSX
script is now the preferred way to create and name Illustrator artboards.
Automatic artwork export, PDF export, bleed, crop marks, and safe lines are not
part of this phase.

### Illustrator Artboard Setup

For Print Group folder exports, the preferred Illustrator workflow is:

1. In Blender, run **Export Active** or **Export All**.
2. Open the generated SVG in Illustrator.
3. In Illustrator, choose **File > Scripts > Other Script**.
4. Select the matching `*_artboards.jsx` file from the `Illustrator/` folder.
5. Confirm the artboards use the selected **Artboard Naming** format.
6. Export artboards from Illustrator as PNG/JPG using artboard names.

The generated JSX uses the currently open Illustrator document. It creates one
artboard per exported panel using the same template-scale inch coordinates as
the SVG, converted to Illustrator points (`1 in = 72 pt`). It anchors those
artboards to the current document's first artboard instead of assuming document
origin `0,0`. It names each artboard from the panel's Graphic ID when available.
The script reuses the initial Illustrator artboard for the first valid panel
where possible, then adds the remaining named panel artboards. It validates each
rectangle before creating an artboard and reports skipped invalid rows with
left/top/right/bottom and width/height debug values.

The companion manifest CSV is written with one row per panel:

```text
svg_file,jsx_file,print_group_abbr,print_group_name,export_mode_setting,export_mode_resolved,graphic_id,artboard_name,blender_object_name,real_width_in,real_height_in,template_width_in,template_height_in,real_x_in,real_y_in,template_x_in,template_y_in,template_scale
SVG/LWT_L_Wall_Test.svg,Illustrator/LWT_L_Wall_Test_artboards.jsx,LWT,L Wall Test,Auto Detect,Unfold Connected Walls,LWT01,LWT_L_Wall_Test_01,BM_PANEL_FRONT_B62 0992 1984_A001,38.80,77.83,3.88,7.78,0.25,0.90,0.25,0.90,0.10
```

The manifest is written once per project export at
`Metadata/Project_manifest.csv`, not once per SVG.

### Artwork Images

After exporting Illustrator artboards as images, use **Artwork Images > Apply
Artwork From Folder** to assign those files back onto the matching generated
graphic planes in Blender.

Recommended workflow:

1. Export the Print Group project folder from Blender.
2. Open the SVG in Illustrator and run the generated `*_artboards.jsx`.
3. Export artboards as images into the project `Exports/` folder, keeping
   filenames that contain either the Graphic ID or the artboard name:

   ```text
   LWT01.png
   LWT_L_Wall_Test_01.png
   LWT_L_Wall_Test_01_final.png
   ```

4. In Blender, expand **Print Layout Export > Artwork Images**.
5. Leave **Apply to Active Group Only** enabled to limit matching to the active
   Print Group, or disable it to scan all Print Groups.
6. Click **Apply Artwork From Folder** and choose the image folder.

Matching is case-insensitive. A filename may match either `bm_graphic_id` or the
generated `bm_artboard_name`. If no image is found for a panel, it is reported
as missing. If multiple images match one panel, or one image appears to match
multiple panels, the add-on reports a duplicate conflict and does not apply that
image automatically.

For each match, the add-on creates or updates a material named like
`MAT_ART_LWT01`, loads/reuses the image, connects it to a Principled BSDF base
color, and assigns it to the graphic plane.

Before assigning the material, the add-on checks the target plane's UV map. If
the UV map is missing, empty, or collapsed, it creates/repairs a simple
rectangular 0-1 UV layout so the artwork fills the panel:

```text
bottom-left  = 0,0
bottom-right = 1,0
top-right    = 1,1
top-left     = 0,1
```

Valid existing UVs are preserved. Mesh geometry is not moved, resized, or
unwrapped beyond assigning UV coordinates. Re-running **Apply Artwork From
Folder** reuses the artwork material and does not create duplicate UV maps when
the existing UVs are valid.

This phase does not add automatic Illustrator image export, automatic file
renaming, PDF export, bleed, crop marks, safe lines, or callout materials.

### Export Mode

Each Print Group stores its own **Export Mode**:

* **Auto Detect** is the default for new Print Groups. During validation and
  export, the add-on first tries the straight-wall layout. If that does not
  validate, it tries the simple two-segment L-wall unfold. If neither geometry
  type validates, the group reports an error and **Export All** skips that group
  while continuing with the others.
* **Straight Wall** preserves the Phase 4 straight-wall behavior: all exported
  planes must be rectangular, approximately coplanar, and compatible with the
  hidden straight-wall direction setting.
* **Unfold Connected Walls** requires a simple connected two-segment corner
  group, such as one World X wall segment meeting one perpendicular World Y wall
  segment.

Unfold export lays the segments into one flat horizontal SVG: World X first,
then World Y, with panels inside each segment sorted by their world position
along that segment. Real spacing and gaps inside each segment are preserved. The
real world corner/endcap/post gap between the two segments is also preserved, so
the second segment starts after the first segment plus the measured corner gap.

For example, if the model has a 62 mm BeMatrix corner/endcap condition between
the back wall graphics and the right wall graphics, the unfolded SVG includes
that real-world spacing between the two wall runs instead of collapsing the
segments together.

Unfold mode is intentionally limited in this phase. It does not support complex
U-shapes, multiple corners, curved walls, angled/non-axis-aligned walls, manual
drag-and-drop ordering, bleed, crop marks, safe lines, PDF export, Illustrator
artwork export automation, or re-import/apply-art workflows.

### Straight Wall Direction

The straight-wall direction is currently kept as an internal/global setting and
defaults to **Auto Detect**. It controls which world axis becomes the
left-to-right direction in the SVG when a Print Group resolves to
**Straight Wall**:

* **Auto Detect** — compares the group's world-space X and Y spread and uses the
  larger spread as the wall direction. If the spread is ambiguous, it falls back
  to World X and reports a warning.
* **World X** — preserves spacing/gaps along World X and lays the wall out
  horizontally in the SVG.
* **World Y** — preserves spacing/gaps along World Y and lays the wall out
  horizontally in the SVG.

Straight Wall mode supports straight walls running along World X or World Y.
Geometry is still read from world-space mesh vertices
(`object.matrix_world @ vertex.co`) so parented generated planes remain
exportable.

### Print Groups

Print Groups let you save selected generated plane objects as a named export set
so you can export the same layout later without manually reselecting the panels.
Each Print Group can also have a short **Group Abbreviation**. The abbreviation
is the stable production code that links Blender objects, SVG files, Illustrator
artboards, future callouts, schedules, and future artwork re-import.

Each Print Group also stores its own export mode. New groups default to
**Auto Detect**, and existing saved groups continue to work with that default
unless you choose **Straight Wall** or **Unfold Connected Walls** in the Active
Group fields.

Recommended abbreviations use uppercase letters and numbers only:

```text
BW  - Back Wall
RW  - Right Wall
LW  - Left Wall
CF  - Counter Front
HS  - Header SEG
EC  - Endcaps
SEG1 - SEG Run 1
```

When Graphic IDs are generated, each panel in the group receives a two-digit ID:

```text
BW - Back Wall -> BW01, BW02, BW03
RW - Right Wall -> RW01, RW02
CF - Counter Front -> CF01
```

The IDs are stored on the generated panel objects as custom properties:

```text
bm_graphic_id
bm_print_group_abbr
bm_print_group_name
```

Blender object names are not changed automatically.

Group export is folder-based: the add-on creates the SVG filename from the Print
Group abbreviation and name when possible. For example, `BW - Back Wall` exports
as `BW_Back_Wall.svg`. Older Print Groups without abbreviations fall back to the
previous filename behavior, such as `Back_Wall.svg`.

To create and use a Print Group:

1. Select the generated hard-panel or SEG plane objects.
2. Enter a **Group Name**. The add-on suggests a Group Abbreviation from it.
3. Click **Create Print Group From Selected**.
4. Choose that group in **Active Print Group**.
5. Edit the active group's **Group Name**, **Group Abbreviation**, or
   **Export Mode** if needed.
6. Click **Generate IDs**.
7. Use **Select Objects** to reselect the saved planes.
8. Click **Export Active** and choose an output folder.

Existing groups can be edited in the Active Group fields. Use **Generate IDs**
after editing abbreviations or group membership so object metadata, SVG labels,
and artboard guide IDs stay aligned.

To export every saved group at once, click **Export All** and choose a parent
folder. The add-on creates a project export folder and writes one SVG per valid
Print Group:

```text
Project_Graphics_Export/
  SVG/
    Back_Wall.svg
    Left_Wall.svg
    Right_Wall.svg
    Counter_Front.svg
  Illustrator/
    Back_Wall_artboards.jsx
    Left_Wall_artboards.jsx
    Right_Wall_artboards.jsx
    Counter_Front_artboards.jsx
  Metadata/
    Project_manifest.csv
    bematrix_export.json
  Exports/
  Logs/
```

Filenames are sanitized for Windows/macOS compatibility: spaces become
underscores, invalid filename characters are replaced, and readable names are
preserved where possible.

The add-on stores object names in scene data and also creates a matching
`BM_PRINT_<Group Name>` collection for Outliner visibility. Objects are linked
to that collection without being moved out of their existing collections. If a
stored object was deleted, renamed, or is no longer a generated panel/SEG plane,
the group export warns and skips it; if no valid planes remain, that group is
skipped or cancelled with a clear report. Batch export reports how many groups
exported successfully and how many failed or were skipped.

Print Group SVGs include the Print Group name as a larger title above the panel
layout. The title sits in the top margin and does not change the true-size panel
geometry, dimensions, or real spacing.

### Phase 3 / 4 Validation

Before exporting production SVGs, use **Validate Active** or **Validate All**
in the Validation Options section. Validation checks the stored object
references, confirms the objects still exist and are generated mesh planes, then
uses the same world-space geometry logic as each Print Group's own
**Export Mode**. **Auto Detect** reports the resolved mode when the geometry
validates.

Validation reports whether each group is OK, has warnings, or has errors. A
typical valid result looks like:

```text
Back Wall: OK - 3 planes, approx 118.11 in wide x 95.87 in high
```

Warnings and errors are shown in Blender's report area, printed to the System
Console, and summarized in the sidebar under **Latest Validation**. Validation
messages include the selected export mode and, in Unfold Connected Walls mode,
the detected segment order. A simple corner may report:

```text
L Wall: OK - 5 planes, approx 196.85 in wide x 95.87 in high, Unfold Connected Walls, 2 segments detected: World X then World Y
```

If the selected planes are not valid for the chosen mode, the export is
cancelled with a warning or error. Unfold mode also warns when it can detect a
small corner gap between the two segments. That reported gap is the same
world-space measurement used in the exported SVG layout.

---

## Utilities

The sidebar panel has a generic **Utilities** section for tools that are not
panel generation.

### Convert Array to Individual Frames

This turns an arrayed BeMatrix frame into real, separate frame objects — one per
array position — without applying the Array modifier to a single mesh and
without joining anything.

**How it works:**

1. Select one or more BeMatrix **frame** objects (generated `BM_PANEL_` and
   `BM_SEG_` objects are ignored).
2. Click **Utilities > Convert Array to Individual Frames**.
3. For each selected frame:
   * If it has **no** supported Array modifier, it is skipped and reported as
     "No Array found".
   * If it has **one or two** simple count-based Array modifiers, the add-on
     creates one real frame object per array position, using the **same
     array-position math** as the graphic panels.

**Each generated frame:**

* Is a separate, selectable object with its **own duplicated mesh** (not an
  instance, not one joined mesh).
* Keeps the original **material(s), rotation, scale, and collection**.
* Has **no Array modifiers**.
* Is named after the source frame plus the array index:

  ```text
  B62 0992 0992_A001
  B62 0992 0992_A002
  B62 0992 0992_A001_B001
  B62 0992 0992_A001_B002
  ```

* Gets custom properties:

  ```text
  bematrix_array_broken_object = True
  bematrix_source_frame_name   = <original frame name>
  bematrix_array_index_1       = <1-based index along Array 1>
  bematrix_array_index_2       = <1-based index along Array 2, or 0 if single array>
  ```

**The original array source is hidden, not deleted.** It keeps its Array modifier
and is tagged with `bematrix_array_source = True`, so you can unhide and re-array
it later if needed.

> Note: this is a one-way "break apart" utility — it duplicates objects. Running
> it again on the same already-broken frames does nothing (they no longer have an
> Array modifier) and is reported as "No Array found".

This utility is separate from panel generation and does **not** change panel
sizing, offsets, materials, duplicate prevention, or array/grid panel behavior.

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

## Frame Transform

A collapsible **Frame Transform** section provides CAD-like vertex-to-vertex
placement of frames. Both buttons work in **Edit Mode** with **one vertex
selected**.

### Set Snap Target

1. Tab into Edit Mode on any object and select **one vertex** (the destination).
2. Click **Set Snap Target**.

The vertex's world-space location is stored as the snap target and the **3D
cursor** moves there. The object is **not** moved.

### Snap Frame to Target

1. Tab into Edit Mode on the frame/object you want to move and select **one
   vertex** (the source point).
2. Click **Snap Frame to Target**.

The **whole object** moves so the selected source vertex lands exactly on the
stored target. **Rotation and scale are preserved** (it is a pure translation),
and the 3D cursor stays at the target.

Typical use: select the destination vertex on a placed frame → Set Snap Target;
then in the frame you are positioning, select the matching corner vertex → Snap
Frame to Target, and the two vertices coincide exactly.

### Make Selected Local

Click **Make Selected Local** (Object Mode, with object(s) selected) to make the
selected objects **and their mesh data** local/editable. This is the equivalent
of **Object > Relations > Make Local > Selected Objects and Data**, useful after
appending/linking BeMatrix frames so they can be edited and snapped. It is
independent of the snap tools above.

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
    operators.py             Add/Update, Delete, Export, and utility operators
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
* **`operators.py`** — the operators: Add/Update (dispatches each frame to the
  hard or SEG generator based on Panel Type), Delete Generated Panels, and the
  **Convert Array to Individual Frames** utility. Prints diagnostics.
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

**Smart SEG fabric (Panel Type = SEG Fabric, select frames):**

* [ ] Three frames in a row → one mesh, **1 coplanar section**, overall 3× frame
  width. Console shows `sections=1`.
* [ ] L-shape (2 in a row + 1 above the second) → one mesh, 1 section, no filled
  missing cell, no gap at the junction.
* [ ] **90° corner:** a straight run plus a frame rotated 90° next to it → one
  mesh with **2 planar sections** that **bend** at the corner (the face does
  **not** stretch diagonally), and a **corner bridge** closes the depth gap
  (console shows `sections=2`, `bridges=1`, no gap at the corner).
* [ ] **Box of frames (3+ faces):** every frame's SEG is on the **outside**
  (none on the inside), and corners are bridged (no gaps). `Both Sides` adds the
  inside fabric too. Console prints the group centroid and per-frame `y_sign`.
* [ ] **Rotated whole group** → mesh follows the rotation; front faces sit 1 mm
  outside each frame's local-Y face (`-32`/`+32 mm`).
* [ ] **Array still on the frame** → array instances are expanded into cells and
  merge into the coplanar section (straight arrays/grids still work).
* [ ] UVs: a 3-wide run unwraps three frame widths wide; a rotated section is
  **not** collapsed; sections don't overlap in the UV editor.
* [ ] The SEG mesh is **parented to the main (active) frame** and moves with it.
* [ ] Group A then group B → **two** separate SEG meshes; A is not removed.
  Re-running the same group updates it (no duplicate).
* [ ] Both Sides → one `SEG_Fabric_Panel_FRONT_<frame>` and one `..._BACK_<frame>`.
* [ ] Console debug prints frame transforms, per-cell normals/corners, section
  assignment, and the object name + dimensions.
* [ ] **Delete Generated Panels** removes the SEG mesh (child of its frame).

**Utilities — Convert Array to Individual Frames:**

* [ ] Single X-array frame → one real frame per copy (`_A001`, `_A002`, …) at the
  array positions; original hidden and tagged `bematrix_array_source`.
* [ ] Two-array (X/Z grid) frame → `_A###_B###` frames for every combination.
* [ ] Frame with no Array → skipped and reported "No Array found".
* [ ] Generated frames keep material, rotation, scale, collection, and have no
  Array modifier; each has its own mesh (edit one, others unaffected).
* [ ] Generated frames carry `bematrix_array_broken_object`,
  `bematrix_source_frame_name`, `bematrix_array_index_1`, `bematrix_array_index_2`.

**Print Layout Export (Phase 5):**

* [ ] Select generated hard-panel objects from one straight wall and export SVG.
* [ ] Open the SVG in Illustrator and confirm real-world inch dimensions.
* [ ] Confirm gaps between selected panels match the Blender scene spacing.
* [ ] Confirm each plane is an editable SVG rectangle with a text label.
* [ ] Set Straight Wall Direction to World X and export a wall running along World X.
* [ ] Set Straight Wall Direction to World Y and export a wall running along World Y.
* [ ] Set Straight Wall Direction to Auto Detect and confirm validation/export report the resolved direction.
* [ ] Set Export Mode to Unfold Connected Walls and validate a two-segment World X / World Y corner group.
* [ ] Export the unfolded corner and confirm the SVG places World X first, then World Y, as one true-size layout.
* [ ] Confirm Unfold Connected Walls warns for a small corner gap and errors for ambiguous or unsupported geometry.
* [ ] Create a named Print Group from selected generated planes.
* [ ] Use Select Objects to reselect the saved planes.
* [ ] Validate Active and confirm an OK result for a straight wall.
* [ ] Validate All and confirm OK/warning/error counts are reported.
* [ ] Delete or rename one stored object and confirm validation reports an error.
* [ ] Add an angled/non-coplanar group and confirm validation reports an error.
* [ ] Export Active and confirm the SVG filename comes from the group name.
* [ ] Export All and confirm one SVG is created per valid group.
* [ ] Confirm Print Group SVGs include the group name as a title above the panels.
* [ ] Delete or rename one stored object and confirm group export warns/skips it.
* [ ] Delete a Print Group and confirm the objects remain in the scene.
* [ ] Select non-coplanar / angled wall planes and confirm export is cancelled.
* [ ] Confirm non-selected generated planes are not included.

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
