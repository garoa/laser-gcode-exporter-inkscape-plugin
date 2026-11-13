# Changelog

All notable changes to this project are documented in this file.

## [2.0.0] — Inkscape 1.x port

Port of the extension from Inkscape 0.48/0.91 + Python 2.7 to **Inkscape 1.0+ and
Python 3**. Developed and verified against Inkscape 1.3 (inkex 1.3.0, Python 3.10,
Pillow 9.4) on macOS. The code targets the documented inkex 1.0 API and carries
fallbacks for the API renames since, so it should run on 1.0 through 1.4 — but only
1.3 has actually been exercised. A copy for Inkscape 1.5 lives in `inkscape-1.5/`
and is waiting on a first test on Windows.

The extension no longer runs on Inkscape 0.9x — that release line ships Python 2
and the pre-1.0 `inkex` API, both of which are gone here. If you still run
Inkscape 0.91, keep using the last Python 2 version, now in `inkscape-0.91/`
(it reports itself as `1.0.1` and matches commit `1038e01`).

`VERSION` in `turnkeylaser.py` is bumped from `1.0.1` to `2.0.0`.

---

### Compatibility

| | Before | After |
|---|---|---|
| Inkscape | 0.48 / 0.91 | 1.0+ (verified on 1.3; 1.5 untested) |
| Python | 2.7 | 3.6+ |
| SVG user unit | 1/90 inch | 1/96 inch (SVG 1.1 standard) |
| Document units | had to be `px` | any (mm, in, px, …) |
| Pillow / PIL | required | optional (only needed for raster objects) |

---

### `turnkeylaser.inx` — extension descriptor

Inkscape 1.x uses a new INX schema; the old file was silently rejected.

* Added the `xmlns="http://www.inkscape.org/namespace/inkscape/extension"` namespace
  on `<inkscape-extension>`.
* `<command reldir="extensions" interpreter="python">` → `<command location="inx"
  interpreter="python">`. `location="inx"` resolves the script relative to the `.inx`
  file, so the extension can live in any extensions directory.
* Dropped the `<dependency ...>inkex.py</dependency>` line — `inkex` is a package now,
  not a single module, so the dependency check always failed.
* Translatable attributes lost their leading underscore: `_name` → `name`,
  `_gui-text` → `gui-text`.
* `<_param name="help" type="description">` → `<label>`. The long help text uses
  `xml:space="preserve"` so its line breaks survive.
* `type="boolean"` → `type="bool"`.
* `type="enum"` + `<item>` → `type="optiongroup" appearance="combo"` + `<option>`.
* Notebook pages need unique names; the three pages were all called `tab` and are now
  `help`, `advanced` and `preferences`.
* `<submenu _name="Export"/>` → `<submenu name="Export"/>`.
* Added `needs-live-preview="false"` on `<effect>`. Without it Inkscape 1.x re-runs the
  extension on every change in the dialog, which would write a gcode file each time you
  nudged a spinner.
* Moved `<effect>` and `<script>` after the `<param>` block to match the order the 1.x
  schema expects.

---

### `turnkeylaser.py` — Python 3

* `print`/`xrange`/`raise X, y`/`except X, e`/`__div__` converted to their Python 3
  equivalents; added `__truediv__` to the `P` point class (`__div__` kept as an alias).
* Normalised the file's indentation. Several blocks mixed tabs and spaces, which
  Python 3 rejects outright with `TabError`.
* `base64.b64encode` now takes and returns `bytes`: raster chunks are packed with
  `bytes(bytearray(chunk))` and the result decoded back to ASCII before being written
  into the gcode.
* Integer division sites reviewed for the `/` vs `//` change.
* File handles are opened with `with` blocks so they are closed on error paths.
* `e.affect()` at module scope → `if __name__ == '__main__': Gcode_tools().run()`.

---

### `turnkeylaser.py` — inkex 1.x API

* `inkex.Effect` → `inkex.EffectExtension`.
* `self.OptionParser.add_option(...)` (optparse) → `add_arguments(self, pars)` with
  `pars.add_argument(...)` (argparse). `type="inkbool"` → `type=inkex.Boolean`.
  Explicit `dest=` kept where the option name and the attribute name differ
  (`--filename` → `options.file`, `--draw-curves` → `options.drawCurves`).
* The `simplestyle`, `simplepath`, `cubicsuperpath`, `simpletransform` and `bezmisc`
  modules were removed in Inkscape 1.0. Replaced with:
  * `simplestyle.formatStyle(...)` → `str(inkex.Style({...}))`
  * `cubicsuperpath.parsePath(d)` → `inkex.paths.Path(d).to_superpath()`
  * `simpletransform.parseTransform` / `composeTransform` → `inkex.transforms.Transform`
    and its `@` operator
  * `simpletransform.applyTransformToPath` → `Path.transform(...)`
  * `bezmisc.*` → `inkex.bezier.*`
* `inkex.etree.SubElement` → `lxml.etree.SubElement` (`inkex.etree` is gone).
* `self.selected.values()` → `self.svg.selection.values()`, with a fallback to
  `self.svg.selected` so Inkscape 1.0 still works.
* `self.args[-1]` (the input filename) → `self.options.input_file`.
* Also fixed the CSS in the preview styles: `strokeWidth` is not a property name,
  it is now `stroke-width`.

---

### Units, DPI and page height

This is the change most likely to alter your output, so check a test cut.

* **90 dpi → 96 dpi.** Inkscape 0.48 treated one SVG user unit as 1/90 inch, so the
  exporter hard-coded `unitScale = 0.282222` (25.4/90) for mm and `0.011111` (1/90) for
  inches. Inkscape 0.92 and later follow the SVG standard, where a user unit is 1/96
  inch. Geometry exported from a legacy 90 dpi document will now come out **6.25%
  smaller** than it did under Inkscape 0.48 — which matches what Inkscape 1.x itself
  shows on screen.
* The scale is no longer hard-coded at all. It is derived per-document from the
  `width`/`height` and `viewBox` attributes, so mm-based documents (`width="210mm"
  viewBox="0 0 210 297"`, where one user unit is one millimetre) and documents with a
  scaled viewBox both export at the correct size.
* **The document no longer has to be set up in `px`.** The old code did
  `float(root.get("height"))`, which threw as soon as the height carried a unit suffix
  (`297mm`) and told the user to switch the document to pixels. Page height is now read
  from the viewBox, falling back to a unit-aware parse of the `height` attribute.
* The `R` word of the `M649` raster command is computed as `25.4 / 270` rather than
  being hard-coded to `0.09406`, and is now correct regardless of the document's dpi
  because `--export-dpi` is a physical measure.

---

### Raster export

* Inkscape 1.x renamed the export CLI flags. The shelled-out command changed from
  `inkscape --export-dpi 270 -i ID --export-id-only -e out.png -b "#ffffff" file.svg`
  to `--export-type=png --export-filename=... --export-id=... --export-id-only
  --export-dpi=270 --export-background=#ffffff`.
* Both sub-invocations (the PNG render and the `--query-all` position lookup) now go
  through `inkex.command.inkscape()`, which locates the Inkscape binary properly
  instead of assuming `inkscape` is on `PATH` — this is what was broken on macOS, where
  the binary lives inside `Inkscape.app`.
* `--query-all` reports **viewport pixels**, not user units. Under Inkscape 0.48 those
  were the same thing; they are not in an mm-based 1.x document. Raster positions are
  now converted from px to user units before the offset/scale maths, so rasters land in
  the right place in mm documents.
* The `y_position -= imageDataheight/3` fudge (which assumed 270 dpi ÷ 90 dpi = 3) is
  now `imageDataheight * 96/270`, converted to user units.
* The temporary directory is `tempfile.gettempdir()` instead of a hard-coded
  `C:\WINDOWS\Temp\` / `/tmp/`.
* Pillow constants: `Image.FLIP_TOP_BOTTOM` moved to `Image.Transpose.FLIP_TOP_BOTTOM`
  in Pillow 9.1 and the old alias was deleted in Pillow 10. Resolved at runtime so both
  old and new Pillow work.
* **Pillow is now optional.** It is imported lazily and vector cutting works without
  it; only a selection containing a raster object produces an error, and that error now
  tells you to `pip install Pillow` instead of failing with an `ImportError`
  traceback.
* Raster export failures (Inkscape returning an error, no PNG produced, an object
  missing from the `--query-all` output) report a readable message and skip the object
  instead of raising.

---

### Bug fixes

These were all latent in the 1.0.1 code; most were silent on Python 2 and are hard
errors on Python 3.

* **Groups were silently dropped.** `compile_paths(...)` was called as
  `compile_paths(...).copy()` inside a `try`, relying on Python 2 lists *not* having a
  `.copy()` method to route groups into the `except` branch. Python 3 lists do have
  `.copy()`, so selecting a group would have appended a raw list into the path list and
  blown up later on `curve['type']`. `compile_paths` now always returns a list and the
  `try`/`except` is gone. Both call sites (the layer loop and the leftover-selection
  loop) were affected.
* `calculate_arc_params` compared `(R-P0).mag` — the bound method, not its result —
  against `min_arc_radius`. On Python 2 that comparison was always false, so the minimum
  arc radius check never fired; on Python 3 it is a `TypeError`. Now `.mag()`.
* `biarc_split` called `biarc(sp1, sp2, depth+1, z1, zm)` but the signature is
  `biarc(sp1, sp2, z1, z2, depth)`, so `depth` was passed as `z1` and the recursion
  never respected `biarc-max-split-depth`. Arguments corrected.
* `generate_raster_gcode` compared `cutFeed` (the string `"F300"`) against
  `self.options.Mfeed` (an int). Python 2 compared them by type name; Python 3 raises.
  Now compares the numeric feed rates.
* `distance_from_point_to_arc` returned `None` for a zero-radius arc, which `min()`
  then tried to order against a tuple. It now returns the distance to the arc centre.
* `get_distance_from_csp_to_arc` used `max()` on `(float, list)` tuples; once the floats
  tied, Python 3 tried to order a tuple against a list and raised. Comparison is now on
  the distance only.
* `if (node.get("x") > 0)` compared a string (or `None`) against an int. Replaced with
  an explicit `is not None` check, preserving the original intent.
* `tool_change()` referenced an undefined `TOOL_CHANGE` constant, so enabling
  **Cut both sides of material** crashed with a `NameError`. The constant is now
  defined (`M6 T%d`).
* `generate_gcode` read the loop variable `si` after the loop; on a curve with fewer
  than two points that was an `UnboundLocalError`. Guarded.
* `layer.get(SVG_LABEL_TAG).strip()` crashed on a layer with no `inkscape:label`
  (possible in 1.x documents). Falls back to the layer `id`.
* **Draw curves in inkscape layer never drew anything.** `draw_curve(curve)` was handed
  the curve *dictionary* and iterated it, which yields the strings `"type"` and
  `"data"` rather than the segments. It is now passed `curve['data']`. The preview group
  is also created on the document root with a compensating `scale(1,-1)` when the origin
  is top-left, so the overlay lands on top of the real geometry instead of being
  double-transformed by the layer.
* Output paths are built with `os.path.join` instead of string concatenation with `/`.
* The logger no longer aborts the export if the log file cannot be written.

---

### Documentation and repository housekeeping

* **README rewritten for 1.x.** It states the Inkscape 1.0+ / Python 3 requirement
  and replaces the Windows Python 2.7 install steps (renaming Inkscape's bundled
  `python` folder, installing the Pillow 2.7 wheel, unpacking `Python27.rar`). The new
  install section gives the user extensions folder for Windows, macOS and Linux, and
  explains how to `pip install Pillow` into Inkscape's own interpreter, which is only
  needed when the plugin reports Pillow missing. It also warns against
  replacing Inkscape's bundled Python, which breaks 1.x.
* The README no longer tells you to set the document up in `px`, since the exporter
  now reads the scale from the document.
* `turnkeylaser.py` and `turnkeylaser.inx` were converted from CRLF to LF line
  endings. This is why the port's diff touches nearly every line of both files. Use
  `git diff -w` / `git blame -w` to see the real changes. The files have since moved
  into per-version folders, so add `--follow` (e.g. `git log --follow -p
  inkscape-1.3/turnkeylaser.py`) to see their history from before the move.
* This `CHANGELOG.md` was added.
* **One folder per Inkscape release.** The plugin files moved out of the repository
  root:
  * `inkscape-0.91/`: the untouched 1.0.1 Python 2 version, plus the Python 2.7-era
    install extras that only it uses (`PIL/`, `files/Python27.rar` and the two
    install screenshots).
  * `inkscape-1.3/`: the 2.0.0 port, verified on Inkscape 1.3.
  * `inkscape-1.5/`: an identical copy of the 2.0.0 port. It is kept separate so fixes
    for 1.5 don't touch the tested 1.3 version. It has not been tested yet.

  Install by copying `turnkeylaser.py` and `turnkeylaser.inx` from the folder for
  your Inkscape version.
* The README install section now opens with a table of the folders, showing which
  Inkscape releases each one covers, its plugin version and whether it has been
  tested. 0.91 users are pointed to `inkscape-0.91/` and the 1.0.1 README at
  commit `1038e01`.
* Removed references to a `1.0.1` git tag from the README. No such tag exists on any
  remote.

---

### Behaviour changes worth knowing about

* Geometry from a pre-0.92 document exports 6.25% smaller — see the DPI note above.
  Re-measure before your first real cut.
* **Draw curves in inkscape layer** now actually produces a preview group in the
  document — it silently did nothing before. Because that means the observed behaviour
  for every existing user has been "no preview", its dialog default was flipped from
  checked to **unchecked**. Tick it if you want the overlay. Note that each export adds
  a new preview group without removing the previous one, so delete them as you go.
* The "Finished processing" notice now includes the full path of the file that was
  written.

---

### Known limitations (unchanged from 1.0.1)

* Rastering shells out to a second Inkscape process per export, which is slow for
  documents with many raster objects.
* The `SVG_IMAGE_TAG` branch that read embedded base64 images directly is still
  commented out; images go through the same Inkscape render path as every other
  non-path object.
* Scaling via **Scale along X/Y axis** still scales about the document origin, not about
  the centre of the selection.
* **Inkscape 1.5 is untested.** The things most likely to break there are:
  * the older `inkex.bezier` helpers (`bezierpointatt`, `beziersplitatt`,
    `beziertatlength`, `bezierlength`) that the arc fitting relies on, if 1.5
    removed them;
  * the raster command-line export and `--query-all` behaviour.
* Every raster is rendered to the same temporary file (`tmpinkscapeexport.png`), and
  the file is not deleted beforehand. If Inkscape fails to overwrite it (on Windows,
  for example because it is locked), the previous object's image could be used
  without any warning.
* The Python 2.7-era Pillow wheels and the bundled `Python27.rar` are kept, now under
  `inkscape-0.91/`. Inkscape 1.x doesn't need them because it ships its own Python 3
  with Pillow.

---

## [1.0.1] — post-release fixes (2015, community PRs)

These landed after the README change log stops and without a version bump, so the
code still reported `1.0.1`:

* **Home only X and Y** (#2, quillford). *Home before starting* now emits `G28 XY`
  instead of `G28`, so the Z axis is no longer homed.
* **Layer power ignored after the first layer** (#5, Anton Todorov). A missing space
  in the first `G01` of each path produced `X..Y..S..` with the `S` word run into
  the last coordinate (e.g. `Y12.5S40.00`), so the layer's power was ignored.

## [1.0.1] and earlier

See the "Change log" section of `README.md` for the 2015 history of the project.
