#!/usr/bin/env python3
"""X2D print toolkit: read the printer, decode errors, prepare models, slice + check + preview, watch a print.

  python3 -I x2d.py status                       live state, AMS loadout, humidity, decoded errors
  python3 -I x2d.py decode <code> [...]          fail_reason int, 8-hex error, or HMS "attr:code"
  python3 -I x2d.py scale <in.stl> <out.stl> <k> scale, centre on the bed and drop to z=0
  python3 -I x2d.py slice <job.json>             slice every variant, check G-code, write previews + report
  python3 -I x2d.py watch [first-layer|done] [interval_s] [timeout_s]

Nothing here starts, pauses or stops a print. Printer reads go through bambu_call.mjs (same folder).
"""
import json
import math
import os
import re
import struct
import subprocess
import sys
import time
import zipfile
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
BBL = Path('/Applications/BambuStudio.app/Contents/Resources/profiles/BBL')
HMS_DIR = Path('/Applications/BambuStudio.app/Contents/Resources/hms')
EXE = '/Applications/BambuStudio.app/Contents/MacOS/BambuStudio'
CALL = HERE / 'bambu_call.mjs'
OUT_ROOT = Path(os.path.expanduser('~/Downloads/X2D-prints'))
SERIAL_PREFIX = '20P'                      # X2D serials start with 20P -> hms_en_20P.json
BED, RIGHT_MIN_X, MAX_Z = 256.0, 20.5, 261.0
FIL_AREA = math.pi * 0.875 ** 2            # 1.75 mm filament cross-section, mm^2
BENIGN = ('Invalid T command (T65279)', 'Invalid T command (T65535)', 'can not find system preset file')
RC_HELP = {
    -100: 'slicing failed: usually an object floating above the bed (empty layers) or a broken mesh',
    -101: 'G-code path conflict: usually the prime tower overlaps a part; turn the tower off for '
          'single-nozzle jobs, or make room for it',
}
WET_SENSITIVE = ('PETG', 'TPU', 'PA', 'PC', 'PVA', 'ASA', 'ABS')
SKIP_FEATURES = ('Custom', 'Flush')
ACTIVE = ('PREPARE', 'RUNNING', 'SLICING', 'PAUSE')

# ---------------------------------------------------------------- printer + tables


def printer(tool, args=None, timeout=90):
    r = subprocess.run(['node', str(CALL), 'call', tool, json.dumps(args or {}), str(timeout)],
                       capture_output=True, text=True, timeout=timeout + 30)
    if r.returncode != 0:
        raise RuntimeError(f'{tool} failed: {(r.stdout or r.stderr)[-600:]}')
    return json.loads(r.stdout)


_hms = None


def hms_table():
    global _hms
    if _hms is None:
        _hms = {}

        def walk(o):
            if isinstance(o, dict):
                if 'ecode' in o:
                    _hms[str(o['ecode']).upper()] = o.get('intro', '') or ''
                for v in o.values():
                    walk(v)
            elif isinstance(o, list):
                for v in o:
                    walk(v)
        walk(json.loads((HMS_DIR / f'hms_en_{SERIAL_PREFIX}.json').read_text()))
    return _hms


def decode(code):
    s = str(code).strip()
    if s in ('', '0', '00000000'):
        return 'none', ''
    if ':' in s:
        a, c = (int(x) for x in s.split(':'))
        key = f'{a:08X}{c:08X}'
        pretty = '-'.join(key[i:i + 4] for i in range(0, 16, 4))
    elif len(s.replace('-', '')) == 16:              # dashed HMS form, e.g. 0C00-0300-0003-0008
        key = s.replace('-', '').upper()
        pretty = '-'.join(key[i:i + 4] for i in range(0, 16, 4))
    else:
        s = s.replace('-', '')                          # 0300-8003 -> 03008003
        as_hex = s.lower().startswith('0x') or not s.isdigit() or (len(s) == 8 and s[0] == '0')
        key = f'{int(s, 16 if as_hex else 10):08X}'
        pretty = f'{key[:4]}-{key[4:]}'
    t = hms_table()
    if key not in t:
        return pretty, '(not in Bambu error table)'
    return pretty, t[key] or '(hidden status code, no message: not an error)'


_index = None


def resolve(name, stack=()):
    global _index
    if _index is None:
        _index = {p.stem: p for p in BBL.rglob('*.json')}
    if name in stack:
        raise ValueError('circular profile inheritance')
    if name not in _index:
        raise KeyError(f'no Bambu profile named {name!r}')
    d = json.loads(_index[name].read_text())
    out = {}
    parents = d.get('inherits', [])
    for p in ([parents] if isinstance(parents, str) else parents):
        if p:
            out.update(resolve(p, stack + (name,)))
    for p in d.get('include', []):
        out.update(resolve(p, stack + (name,)))
    out.update({k: v for k, v in d.items() if k not in ('inherits', 'include')})
    return out


def apply(base, overrides):
    """Profile values are strings or lists of strings; keep each key's shape."""
    for k, v in (overrides or {}).items():
        if isinstance(v, list):
            base[k] = [str(x) for x in v]
        elif isinstance(base.get(k), list):
            base[k] = [str(v)] * max(1, len(base[k]))
        else:
            base[k] = str(v)
    return base


def first_float(v, default):
    v = v[0] if isinstance(v, list) and v else v
    m = re.match(r'\s*([0-9.]+)\s*(%?)', str(v or ''))
    if not m:
        return default
    return float(m.group(1)) * (0.4 / 100 if m.group(2) else 1)   # percentages are of the 0.4 nozzle

# ---------------------------------------------------------------- status / watch


def cmd_status():
    s = printer('get_printer_status')
    f = printer('get_printer_filaments')
    r = s['raw']
    print(f"{s['model']} {s['serial']} | state {r.get('gcode_state')} | job {r.get('subtask_name')!r} "
          f"layer {r.get('layer_num')}/{r.get('total_layer_num')} | print_type {r.get('print_type')}")
    t = s['temperatures']
    print(f"temps nozzle {t['nozzle']['actual']}/{t['nozzle']['target']}  bed {t['bed']['actual']}/{t['bed']['target']}"
          f"  chamber {t.get('chamber')} | wifi {r.get('wifi_signal')} | sdcard {r.get('sdcard')}")
    dev = r.get('device', {})
    noz = [f"{n.get('id')}:{n.get('type')} {n.get('diameter')}" for n in dev.get('nozzle', {}).get('info', [])]
    print(f"nozzles {noz} | plate {dev.get('plate')} | xcam {r.get('xcam')}")
    for a in r.get('ams', {}).get('ams', []):
        info = int(a.get('info', '0'), 16)
        side = 'LEFT nozzle' if (info >> 8) & 0xF == 1 else 'RIGHT nozzle'
        hum = int(a.get('humidity_raw', 0) or 0)
        flag = '  <-- too damp for PETG/TPU/PA, dry first' if hum > 30 else ''
        print(f"AMS {a.get('id')} -> {side} | humidity {hum}% RH | temp {a.get('temp')} C | "
              f"drying {a.get('dry_time')} min left{flag}")
    for tr in f.get('trays', []):
        print(f"  slot {tr['slot']} ({tr.get('label')}) {tr.get('tray_type')} {tr.get('tray_sub_brands') or ''} "
              f"#{(tr.get('tray_color') or '')[:6]} remain {tr.get('remain_percent')}% -> "
              f"{Path(tr.get('resolved_profile_path') or '').stem} [{tr.get('match_confidence')}]")
    for v in r.get('vir_slot', []):
        side = 'LEFT' if str(v.get('id')) == '254' else 'RIGHT'
        print(f"  external {v.get('id')} ({side} nozzle): {v.get('tray_type') or 'empty'} #{(v.get('tray_color') or '')[:6]}")
    print('last job fail_reason:', *decode(r.get('fail_reason', 0)))
    print('print_error:', *decode(r.get('print_error', 0)))
    for h in r.get('hms', []):
        print('HMS:', *decode(f"{h['attr']}:{h['code']}"), '| at', h.get('ts_unix'))


def cmd_watch(until='first-layer', interval=30, timeout=5400):
    t0 = time.time()
    started, last = False, None
    while time.time() - t0 < timeout:
        try:
            r = printer('get_printer_status', timeout=60)['raw']
        except Exception as e:                      # keep watching through a dropped read
            print(time.strftime('%H:%M:%S'), 'status read failed:', str(e)[:120], flush=True)
            time.sleep(interval)
            continue
        state, layer = r.get('gcode_state'), int(r.get('layer_num') or 0)
        if state in ACTIVE:
            started = True                          # a stale FAILED/FINISH from the last job never counts
        line = (f"state={state} job={r.get('subtask_name')!r} layer={layer}/{r.get('total_layer_num')} "
                f"{r.get('mc_percent')}% left={r.get('mc_remaining_time')}min nozzle={r.get('nozzle_temper')}/"
                f"{r.get('nozzle_target_temper')} bed={r.get('bed_temper')}/{r.get('bed_target_temper')}")
        if line != last:
            print(time.strftime('%H:%M:%S'), line, flush=True)
            last = line
        for h in r.get('hms', []):
            code, text = decode(f"{h['attr']}:{h['code']}")
            if not text.startswith('(hidden'):
                print('   HMS', code, text, flush=True)
        if started and state == 'PAUSE':
            print('PAUSED - needs attention:', *decode(r.get('print_error', 0)))
            return 2
        if started and state in ('FAILED', 'FINISH'):
            print('ENDED', state, '| fail_reason:', *decode(r.get('fail_reason', 0)))
            return 0 if state == 'FINISH' else 1
        if started and until == 'first-layer' and state == 'RUNNING' and layer >= 2:
            print('FIRST LAYER DONE - adhesion phase passed')
            return 0
        time.sleep(interval)
    print('watch timed out' + ('' if started else ' (the new job never started)'))
    return 3

# ---------------------------------------------------------------- models


def cmd_scale(src, dst, k):
    k = float(k)
    data = Path(src).read_bytes()
    n = struct.unpack_from('<I', data, 80)[0]
    if len(data) != 84 + 50 * n:
        raise SystemExit('only binary STL is supported')
    recs = list(struct.iter_unpack('<12fH', data[84:]))
    xs = [v for r in recs for v in (r[3], r[6], r[9])]
    ys = [v for r in recs for v in (r[4], r[7], r[10])]
    zs = [v for r in recs for v in (r[5], r[8], r[11])]
    cx, cy, z0 = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2, min(zs)
    out = bytearray(data[:84])
    pack = struct.Struct('<12fH').pack
    for r in recs:
        v = list(r)
        for i in (3, 6, 9):
            v[i] = (v[i] - cx) * k + BED / 2
            v[i + 1] = (v[i + 1] - cy) * k + BED / 2
            v[i + 2] = (v[i + 2] - z0) * k
        out += pack(*v)
    Path(dst).write_bytes(out)
    size = ((max(xs) - min(xs)) * k, (max(ys) - min(ys)) * k, (max(zs) - min(zs)) * k)
    print(f'{n} triangles -> {size[0]:.1f} x {size[1]:.1f} x {size[2]:.1f} mm, centred, base at z=0')
    if size[0] > BED or size[1] > BED or size[2] > MAX_Z:
        print('WARNING: larger than the X2D build volume (256 x 256 x 261 mm)')
    return size


def export_stl(src_3mf, workdir):
    workdir.mkdir(parents=True, exist_ok=True)
    subprocess.run([EXE, '--datadir', str(workdir / 'datadir'), '--export-stl', '--outputdir', str(workdir),
                    str(src_3mf)], capture_output=True, timeout=900)
    stls = sorted(workdir.rglob('*.stl'))
    if not stls:
        raise SystemExit(f'could not export an STL from {src_3mf}')
    return stls[0]

# ---------------------------------------------------------------- G-code analysis + previews


class Canvas:
    def __init__(self, w, h, bg=(24, 24, 27)):
        self.w, self.h = w, h
        self.px = bytearray(bytes(bg) * (w * h))

    def dot(self, x, y, c):
        if 0 <= x < self.w and 0 <= y < self.h:
            i = (y * self.w + x) * 3
            self.px[i:i + 3] = c

    def line(self, x0, y0, x1, y1, c):
        n = int(max(abs(x1 - x0), abs(y1 - y0))) + 1
        for k in range(n + 1):
            t = k / n
            self.dot(int(round(x0 + (x1 - x0) * t)), int(round(y0 + (y1 - y0) * t)), c)

    def rect(self, x0, y0, x1, y1, c):
        for y in range(max(0, y0), min(self.h, y1)):
            i = (y * self.w + max(0, x0)) * 3
            j = (y * self.w + min(self.w, x1)) * 3
            self.px[i:j] = bytes(c) * ((j - i) // 3)

    def save(self, path):
        rows = b''.join(b'\x00' + bytes(self.px[y * self.w * 3:(y + 1) * self.w * 3]) for y in range(self.h))

        def chunk(tag, body):
            return struct.pack('>I', len(body)) + tag + body + struct.pack('>I', zlib.crc32(tag + body) & 0xFFFFFFFF)
        Path(path).write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', self.w, self.h, 8, 2, 0, 0, 0))
                               + chunk(b'IDAT', zlib.compress(rows, 6)) + chunk(b'IEND', b''))


def hex_rgb(h):
    h = (h or '#cccccc').lstrip('#')[:6]
    c = tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    return c if sum(c) > 90 else (110, 110, 118)          # keep black visible on the dark canvas


def parse_gcode(text):
    """Extrusion segments (layer, z, tool, feature, x0, y0, x1, y1) plus flow/temperature facts."""
    segs, temps, features = [], {'nozzle': [], 'bed': []}, set()
    x = y = z = f = 0.0
    tool, layer, feature = 0, 0, ''
    flow = {}                                    # feature -> max mm^3/s on segments >= 1 mm
    l1_speed = 0.0
    num = re.compile(r'([XYZEFIJ])(-?[0-9.]+)')
    for raw in text.splitlines():
        if raw.startswith(';'):
            if raw.startswith('; CHANGE_LAYER'):
                layer += 1
            elif raw.startswith('; Z_HEIGHT:'):
                z = float(raw.split(':', 1)[1])
            elif raw.startswith('; FEATURE:'):
                feature = raw.split(':', 1)[1].strip()
                features.add(feature)
            continue
        line = raw.split(';', 1)[0].strip()
        if not line:
            continue
        word = line.split(None, 1)[0]
        if word in ('G0', 'G1', 'G2', 'G3'):
            p = {k: float(v) for k, v in num.findall(line)}
            nx, ny = p.get('X', x), p.get('Y', y)
            f = p.get('F', f)
            e = p.get('E', 0.0)
            pts = [(x, y), (nx, ny)]
            length = math.hypot(nx - x, ny - y)
            if word in ('G2', 'G3') and ('I' in p or 'J' in p):
                cx, cy = x + p.get('I', 0.0), y + p.get('J', 0.0)
                rad = math.hypot(x - cx, y - cy)
                a0, a1 = math.atan2(y - cy, x - cx), math.atan2(ny - cy, nx - cx)
                if word == 'G3' and a1 <= a0:
                    a1 += 2 * math.pi
                if word == 'G2' and a1 >= a0:
                    a1 -= 2 * math.pi
                sweep = a1 - a0
                length = abs(sweep) * rad
                n = max(2, int(length) + 1)
                pts = [(cx + rad * math.cos(a0 + sweep * i / n), cy + rad * math.sin(a0 + sweep * i / n)) for i in range(n + 1)]
            if layer and e > 0 and length > 0 and feature not in SKIP_FEATURES and -2 <= nx <= BED + 2 and -2 <= ny <= BED + 2:
                for (ax, ay), (bx, by) in zip(pts, pts[1:]):
                    segs.append((layer, z, tool, feature, ax, ay, bx, by))
                if length >= 1.0 and f > 0:
                    q = e * FIL_AREA / (length / (f / 60.0))
                    flow[feature] = max(flow.get(feature, 0.0), q)
                if layer == 1:
                    l1_speed = max(l1_speed, f / 60.0)
            x, y = nx, ny
        elif re.fullmatch(r'T\d+', word):
            t = int(word[1:])
            if t < 64:
                tool = t
        elif word in ('M104', 'M109') and layer <= 1:
            m = re.search(r'S(\d+)', line)
            if m and int(m.group(1)) > 0:
                temps['nozzle'].append(int(m.group(1)))
        elif word in ('M140', 'M190') and layer <= 1:
            m = re.search(r'S(\d+)', line)
            if m and int(m.group(1)) > 0:
                temps['bed'].append(int(m.group(1)))
    return segs, dict(flow=flow, first_layer_max_speed=round(l1_speed), temps=temps, layers=layer,
                      features=sorted(features))


def previews(segs, colours, outdir, tag):
    s = 3                                              # px per mm
    W = int(BED * s)
    zmax = max((g[1] for g in segs), default=1.0)
    for name, only_first in (('top', False), ('first_layer', True)):
        c = Canvas(W, W)
        c.rect(0, 0, W, W, (40, 40, 46))
        c.rect(0, 0, int(RIGHT_MIN_X * s), W, (58, 36, 40))   # right nozzle cannot reach this strip
        for g in segs:
            if only_first and g[0] != 1:
                continue
            col = hex_rgb(colours[g[2]] if g[2] < len(colours) else None)
            c.line(g[4] * s, W - 1 - g[5] * s, g[6] * s, W - 1 - g[7] * s, col)
        c.save(outdir / f'{tag}_{name}.png')
    H = int(min(MAX_Z, zmax + 5) * s)
    c = Canvas(W, H)
    for g in segs:                                     # side elevation: X across, Z up
        col = hex_rgb(colours[g[2]] if g[2] < len(colours) else None)
        yz = H - 1 - int(g[1] * s)
        c.line(g[4] * s, yz, g[6] * s, yz, col)
    c.save(outdir / f'{tag}_side.png')

# ---------------------------------------------------------------- slicing


def live_filaments():
    data = printer('get_printer_filaments')
    status = printer('get_printer_status')['raw']
    hum = max((int(a.get('humidity_raw', 0) or 0) for a in status.get('ams', {}).get('ams', [])), default=0)
    return {t['slot']: t for t in data.get('trays', [])}, hum


def resolve_filaments(job):
    specs = job.get('filaments') or [{'slot': 0}]
    trays, hum, notes, out = None, 0, [], []
    for spec in specs:
        if 'slot' in spec and 'profile' not in spec:
            if trays is None:
                trays, hum = live_filaments()
            t = trays.get(spec['slot'])
            if not t or not t.get('loaded'):
                raise SystemExit(f"AMS slot {spec['slot']} is empty")
            item = dict(slot=spec['slot'], profile=Path(t['resolved_profile_path']).stem,
                        colour='#' + (t.get('tray_color') or 'CCCCCC')[:6], type=t.get('tray_type'))
            if t.get('match_confidence') != 'high':
                notes.append(f"slot {spec['slot']}: profile match is {t.get('match_confidence')}, check it")
            if (t.get('tray_type') or '').upper() in WET_SENSITIVE and hum > 30:
                notes.append(f"slot {spec['slot']} is {t.get('tray_type')} at {hum}% RH in the AMS: dry it first")
        else:
            item = dict(slot=spec.get('slot'), profile=spec['profile'], colour=spec.get('colour', '#CCCCCC'),
                        type=spec.get('type'))
        out.append(item)
    return out, notes


def run_variant(job, vname, var, fils, notes, outdir):
    outdir.mkdir(parents=True, exist_ok=True)
    bed = job.get('bed', 'Textured PEI Plate')
    machine = resolve(job.get('machine', 'Bambu Lab X2D 0.4 nozzle'))
    machine['curr_bed_type'] = bed
    process = resolve(var.get('process') or job.get('process', '0.20mm Standard @BBL X2D'))   # per-variant profile wins
    process.update(curr_bed_type=bed, filament_map_mode='Manual')
    apply(process, job.get('overrides'))
    apply(process, var.get('overrides'))
    nozzle_map = [str(n) for n in (var.get('nozzle_map') or job.get('nozzle_map') or ['1'] * len(fils))]
    process['filament_map'] = nozzle_map
    (outdir / 'machine.json').write_text(json.dumps(machine, indent=1))
    (outdir / 'process.json').write_text(json.dumps(process, indent=1))
    fil_paths, colours, limits = [], [], []
    for i, fl in enumerate(fils):
        d = resolve(fl['profile'])
        d['filament_colour'] = [fl['colour']]
        apply(d, job.get('filament_overrides'))
        apply(d, var.get('filament_overrides'))
        p = outdir / f'filament_{i + 1}.json'
        p.write_text(json.dumps(d, indent=1))
        fil_paths.append(str(p))
        colours.append(fl['colour'])
        limits.append(first_float(d.get('filament_max_volumetric_speed'), 0.0))
    name = job['name']
    args = [EXE, '--datadir', str(outdir / 'datadir'), '--load-settings', f"{outdir / 'machine.json'};{outdir / 'process.json'}",
            '--load-filaments', ';'.join(fil_paths), '--orient', '0',
            *(['--arrange', '1'] if job.get('arrange') else []),
            '--slice', str(job.get('plate', 0)), '--outputdir', str(outdir), '--export-3mf', f'{name}.gcode.3mf',
            str(job['_model'])]
    with (outdir / 'log.txt').open('w') as fh:
        rc = subprocess.run(args, stdout=fh, stderr=subprocess.STDOUT, cwd=outdir, timeout=3600).returncode
    res = json.loads((outdir / 'result.json').read_text()) if (outdir / 'result.json').exists() else {}
    log = (outdir / 'log.txt').read_text(errors='ignore')
    warns = sorted({w for w in re.findall(r'(?i)(?:warning|error|floating|empty layer|conflict|collision)[^\n]{0,160}', log)
                    if not any(b in w for b in BENIGN)})
    row = dict(variant=vname, return_code=res.get('return_code', rc), error=res.get('error_string', ''),
               help=RC_HELP.get(res.get('return_code'), ''), plates=[], warnings=warns[:8], checks=[], notes=list(notes))
    sliced = outdir / f'{name}.gcode.3mf'
    if res.get('return_code') != 0 or not sliced.exists():
        return row
    plates = {p['id']: p for p in res.get('sliced_plates', [])}
    lw = first_float(process.get('initial_layer_line_width'), 0.5)
    with zipfile.ZipFile(sliced) as z:
        for member in sorted(n for n in z.namelist() if re.match(r'Metadata/plate_\d+\.gcode$', n)):
            pid = int(re.search(r'(\d+)', member.rsplit('/', 1)[1]).group(1))
            segs, facts = parse_gcode(z.read(member).decode(errors='ignore'))
            pinfo = plates.get(pid, {})
            fil = pinfo.get('filaments', [])
            used = {f['id']: round(f.get('total_used_g', 0), 2) for f in fil}
            flush = round(sum(f.get('total_used_g', 0) - f.get('main_used_g', f.get('total_used_g', 0)) for f in fil), 2)
            ft = pinfo.get('feature_type_times', {})
            top = sorted(((k, v) for k, v in ft.items() if v > 0), key=lambda kv: -kv[1])[:5]
            checks = []
            xs = [g[4] for g in segs] + [g[6] for g in segs]
            ys = [g[5] for g in segs] + [g[7] for g in segs]
            if xs and (min(xs) < 0 or max(xs) > BED or min(ys) < 0 or max(ys) > BED):
                checks.append('FAIL toolpaths leave the 256 x 256 bed')
            for t, nz in enumerate(nozzle_map):
                if nz == '2' and any(g[2] == t and min(g[4], g[6]) < RIGHT_MIN_X for g in segs):
                    checks.append(f'FAIL filament {t + 1} is on the right nozzle but prints at x < {RIGHT_MIN_X} mm')
            peak = max(facts['flow'].values(), default=0)
            lim = max(limits) if limits else 0
            if lim and peak > lim * 1.05:
                checks.append(f'WARN peak commanded flow {peak:.1f} mm3/s exceeds the filament limit {lim:.0f}')
            l1_area = sum(math.hypot(g[6] - g[4], g[7] - g[5]) for g in segs if g[0] == 1) * lw
            if l1_area > 15000:
                checks.append(f'NOTE large first layer (~{l1_area / 100:.0f} cm2): clean plate + auto bed leveling matter most')
            if facts['first_layer_max_speed'] > 120:
                checks.append(f"NOTE first layer reaches {facts['first_layer_max_speed']} mm/s on some moves")
            previews(segs, colours, outdir, f'plate{pid}')
            row['plates'].append(dict(plate=pid, time_min=round(pinfo.get('total_predication', 0) / 60, 1), grams=used,
                                      flush_g=flush, layers=facts['layers'], peak_flow=round(peak, 1), flow_limit=lim,
                                      first_layer_area_cm2=round(l1_area / 100),
                                      first_layer_temps=dict(nozzle=max(facts['temps']['nozzle'], default=None),
                                                             bed=(facts['temps']['bed'] or [None])[-1]),
                                      top_features={k: round(v / 60, 1) for k, v in top}, features=facts['features'],
                                      checks=checks))
            row['checks'] += checks
    row['total_min'] = round(sum(p['time_min'] for p in row['plates']), 1)
    row['total_g'] = round(sum(sum(p['grams'].values()) for p in row['plates']), 2)
    row['file'] = str(sliced)
    return row


def cmd_slice(job_path):
    job = json.loads(Path(job_path).read_text())
    name = job['name']
    root = Path(os.path.expanduser(job.get('out_dir', str(OUT_ROOT / name))))
    root.mkdir(parents=True, exist_ok=True)
    src = Path(os.path.expanduser(job['src']))
    if not src.exists():
        raise SystemExit(f'source not found: {src}')
    scale = float(job.get('scale', 1.0))
    model = src
    if src.suffix.lower() == '.stl' or scale != 1.0 or job.get('as_stl'):
        stl = export_stl(src, root / '_export') if src.suffix.lower() == '.3mf' else src
        model = root / 'model.stl'
        cmd_scale(stl, model, scale)               # always centre + drop to bed (CLI --scale leaves parts floating)
    job['_model'] = model
    fils, notes = resolve_filaments(job)
    variants = job.get('variants') or {'base': {}}
    rows = [run_variant(job, v, cfg, fils, notes, root / v) for v, cfg in variants.items()]
    report = dict(job=name, src=str(src), filaments=fils, variants=rows)
    (root / 'report.json').write_text(json.dumps(report, indent=1))
    lines = [f'# {name}', '', f'Source: {src}',
             'Filaments: ' + ', '.join(f"{f['profile']} {f['colour']} (slot {f['slot']})" for f in fils), '',
             '| variant | result | time | filament | flush | checks |', '|---|---|---|---|---|---|']
    for r in rows:
        ok = 'ok' if r['return_code'] == 0 else f"FAILED {r['return_code']}: {r['help'] or r['error']}"
        lines.append(f"| {r['variant']} | {ok} | {r.get('total_min', '-')} min | {r.get('total_g', '-')} g | "
                     f"{round(sum(p['flush_g'] for p in r['plates']), 2) if r['plates'] else '-'} g | "
                     f"{'; '.join(sorted(set(r['checks']))) or 'none'} |")
    (root / 'report.md').write_text('\n'.join(lines) + '\n')
    print('\n'.join(lines))
    for r in rows:
        print(f"\n## {r['variant']}: {r.get('file', '')}")
        for p in r['plates']:
            print(f"  plate {p['plate']}: {p['time_min']} min, {p['grams']} g, flush {p['flush_g']} g, {p['layers']} layers, "
                  f"peak flow {p['peak_flow']}/{p['flow_limit']} mm3/s, first layer {p['first_layer_temps']} "
                  f"~{p['first_layer_area_cm2']} cm2, top {p['top_features']}")
        for w in r['warnings'] + r['notes']:
            print('  !', w)
    print(f'\nReport + previews: {root}')


if __name__ == '__main__':
    a = sys.argv[1:]
    if not a:
        raise SystemExit(__doc__)
    if a[0] == 'status':
        cmd_status()
    elif a[0] == 'decode':
        for code in a[1:]:
            print(code, '->', *decode(code))
    elif a[0] == 'scale':
        cmd_scale(a[1], a[2], a[3])
    elif a[0] == 'slice':
        cmd_slice(a[1])
    elif a[0] == 'watch':
        sys.exit(cmd_watch(a[1] if len(a) > 1 else 'first-layer', int(a[2]) if len(a) > 2 else 30,
                           int(a[3]) if len(a) > 3 else 5400))
    else:
        raise SystemExit(__doc__)
