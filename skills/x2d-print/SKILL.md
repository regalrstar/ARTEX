---
name: x2d-print
description: Plan, tune, simulate and hand off 3D prints on the user's Bambu Lab X2D. Use whenever the user wants to print something, find something fun to print, slice or re-slice a model or MakerWorld/Printables file, check the printer, diagnose failed or spaghetti prints, dry filament, or watch a running print.
---

# X2D print workflow

**Standing rule from the user:** every print is tuned for high quality + speed + low filament, and is simulated before it is proposed. Never start, pause, cancel, heat, dry or change printer settings without the user's explicit OK for that action.

Toolkit (no dependencies beyond macOS python3, node and Bambu Studio):
- `python3 -I ~/.claude/skills/x2d-print/scripts/x2d.py status | decode | scale | slice | watch`
- `node ~/.claude/skills/x2d-print/scripts/bambu_call.mjs call <tool> '<json>' [timeout]` for any other bambu-printer MCP tool (`list` shows them). It reads the `bambu-printer` entry in `~/.claude.json` and never prints the access code. If the bambu-printer MCP tools are loaded in the session, use them directly instead.

## 1. Read the live state first (it changes)
`x2d.py status` → job state, decoded `fail_reason` / `print_error` / HMS codes, nozzles, plate, every AMS slot with its resolved X2D profile, AMS humidity, external spools.
- The AMS 2 Pro feeds the **left** (direct-drive) nozzle = slicer extruder 1, which reaches the whole 256 x 256 bed. The **right** (Bowden) nozzle = extruder 2 only takes external spool 255 and cannot reach x < 20.5 mm. External 254 = left nozzle.
- Humidity > 30 % RH: PETG/TPU/PA/PC must be dried before printing (AMS 2 Pro drying via the `set_ams_drying` tool: PETG 65 °C 8 h, PLA 55 °C 8 h). Ask first.
- Decode any code with `x2d.py decode <int|hex|attr:code>` (Bambu's own X2D table). Empty-message codes are hidden status codes, not errors.

## 2. Inspect the source
For a downloaded .3mf: read `Metadata/project_settings.config` (`printer_settings_id`, `print_settings_id`, `filament_settings_id`, `curr_bed_type`, `spiral_mode`) and `Metadata/plate_N.json`. Files made for P1S/P2S/X1C/A1 are re-targeted to X2D profiles by the job. Never print them unchanged.

## 3. Write a job file at `~/Downloads/X2D-prints/<name>/job.json`
```json
{
  "name": "mini-mossglow-lantern",
  "src": "~/Downloads/model.3mf",          // .3mf or .stl
  "scale": 0.5,                             // optional; exports STL, scales, centres, drops to z=0
  "filaments": [{"slot": 2}],               // live AMS slot -> profile + colour; or {"profile": "...", "colour": "#RRGGBB"}
  "nozzle_map": ["1"],                      // default all "1" (left/AMS nozzle); "2" = right/external 255
  "process": "0.20mm Standard @BBL X2D",    // default
  "overrides": {"spiral_mode": "1"},        // process keys, applied to every variant
  "filament_overrides": {},
  "variants": {"quality": {}, "fast": {"overrides": {"layer_height": "0.24"}},
               "hq": {"process": "0.20mm High Quality @BBL X2D"}}   // a variant may pick its own stock profile
}
```
(Comments are for illustration only; real job files are plain JSON.) Examples live in `~/Downloads/X2D-prints/*/job.json`.

## 4. Simulate: `x2d.py slice <job.json>` (about 1 min for small jobs, longer for full plates; run big ones in the background)
Per variant it writes `<name>.gcode.3mf`, `log.txt`, and `plateN_first_layer.png`, `plateN_top.png`, `plateN_side.png` (real G-code toolpaths in filament colours; the red strip is where the right nozzle cannot reach). It also writes `report.md`/`report.json` with time, grams per filament, purge (flush) grams, layers, peak commanded flow vs the filament limit, first-layer temps and area, the biggest time sinks, and checks (bed bounds, nozzle reach, flow, large first layer).
- **Always open the first-layer and side previews with Read before recommending**, and describe what the toolpaths show. Model thumbnails hide holes, lattices and floating parts.
- Return code -100 = an object floats or the mesh is broken. -101 = path conflict (usually the prime tower). Both are explained in the report.
- Benign log noise: `Invalid T command (T65279/T65535)` and `can not find system preset file` for foreign printers.

## 5. Tricks: try them as variants and keep what the numbers support
| Goal | Trick | When |
|---|---|---|
| filament + speed | vase mode (`spiral_mode` 1, 1 wall, 0 % infill, 0 top layers) | lamps, vases, shades, decorative shells |
| filament | prime tower off (`enable_prime_tower` 0) | every filament on the left/AMS nozzle; also fixes -101 on full plates |
| filament | second colour on the right nozzle's external spool (`nozzle_map` ["1","2"]) | many colour changes per layer; keep that colour's parts at x >= 20.5 |
| filament | fewer bottom layers (4 instead of 9) and no brim | non-structural bases with a good footprint |
| speed | `filament_z_hop` 0.2 + `Slope Lift` | many small islands (logos, patterns); saved 18 min on the fan |
| speed | grid/zig-zag infill instead of gyroid; lightning for decorative parts | infill hidden and non-structural |
| speed | 0.24 mm layers | only if peak flow stays below about 90 % of the filament limit, else the gain is tiny |
| quality | keep 0.20 mm (0.12-0.16 for fine detail), 50 mm/s first layer, auto bed leveling on | always for visible parts and after failures |
| reliability | PLA for decorative parts while PETG is wet; textured PEI cleaned with dish soap | after spaghetti or adhesion failures |
| reliability | first layer bed +5 C (`textured_plate_temp_initial_layer` 60) + part fan off for 3 layers (`close_fan_the_first_x_layers` 3) | flat multi-part plates (gears, plates); costs ~0 min; check a bridge layer still gets fan |
| smoothness | `seam_slope_type` external (scarf seam) + `precise_outer_wall` 1 + outer wall 120 mm/s (pass the 6-item list) | visible or meshing parts; cost only +3 min on the gyro launcher |
| avoid | `reduce_crossing_wall` 1 (+10 min) and crosshatch infill (+9 min vs grid) on X2D | the profile's 0.4 mm z-hop already clears curled edges; 0.20 High Quality costs +69 min, 0.16 mm +51 min |

## 6. Recommend
Give the chosen variant with its numbers (time, grams, purge, peak flow vs limit), what the previews show, the AMS slot mapping, and a preflight list: wash the plate (dish soap + warm water, no touching), plate seated with the textured side up, nozzle free of old blobs, filament dry. Then ask whether to print.

## 7. Hand the print over (the printer is in cloud mode)
- In cloud mode the add-on's `print_3mf` fails with `native_print result=-26` ("uploading failed, wrong ip address"): the X2D refuses third-party LAN prints. Don't try it. Run `open -a BambuStudio <file>.gcode.3mf` and have the user click **Print plate** → choose the X2D (signed in to their Bambu account) → map each filament to the AMS slot from the report → Bed leveling on → **Send**.
- Only if the user has switched the printer to **LAN Only + Developer Mode** (which disables Bambu Handy and cloud printing): `print_3mf` with `bambu_model` "x2d", `ams_slots` from the report, `bed_type` "textured_plate", `bed_leveling` true, after an explicit OK.

## 8. Watch
After the user sends it: `x2d.py watch first-layer 30 5400` with `run_in_background`. It returns when layer 2 starts (adhesion phase passed), on a pause (decoded error) or on failure. Run `watch done` for the rest of the print if wanted. There is no camera from here (needs LAN liveview + ffmpeg); the printer's own spaghetti and first-layer detectors are on.

## 9. Learn
After every print, append one line to `~/Downloads/X2D-prints/print_log.md`: date | job | variant | filament + slot | result (finished / failed + decoded code) | what the user saw. Before tuning a new job, read the log and prefer settings that have already worked on this printer.
