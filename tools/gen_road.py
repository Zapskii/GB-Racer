#!/usr/bin/env python3
"""
Generates src/road_data.c and src/road_data.h for the GB racer.

Renders a static 256x80 road trapezoid (centred on map x=128), dedupes it into
8x8 tiles, and emits tile data + the final 32x18 BG tilemap.

Colour indices used by the road art (the per-scanline BGP table decides the
actual shade of each):
    0 grass   1 road   2 rumble strip   3 centre line

VRAM plan (LCDC.4 = 0, signed tile addressing):
    BG ids   0..127  -> $9000  road tiles           (this script: ROAD_*)
    BG ids 128..255  -> $8800  sky / hills / HUD    (this script: SKY_*)
    $8000-$87FF stays free for sprites.

Usage:  gen_road.py <output_dir>
"""
import math
import sys
from pathlib import Path

# ---- layout (must match src/main.c) ----------------------------------------
MAP_W, MAP_H = 32, 32        # the whole 32x32 BG map: the view scrolls vertically (SCY) for hills
ROAD_ROW0 = 6                # map row where the road starts  (line 48)
ROAD_ROWS = 11               # rows drawn: 80 road lines + one extra row (y 80..87) that SCY can pull into view
ROAD_LINES = 80              # lines the ISR tables drive (the extra row is below line 127 at pitch 0)
ROAD_DRAW_LINES = ROAD_ROWS * 8
CENTRE_X = 128               # map pixel x of the road centre
HILL_ROW = 5                 # map row holding the hill silhouette

# ---- road shape (the knobs to play with) -----------------------------------
def road_hw(y):    return 3 + (3 * y) // 4      # half-width of tarmac, 3/4 px per line
def rumble_w(y):   return 1 + y // 16           # rumble strip thickness
def centre_hw(y):  return y // 40               # centre line half-width (0 -> 1px, 1 -> 3px)

def render_road():
    """Return 88 rows of 256 colour indices."""
    rows = []
    for y in range(ROAD_DRAW_LINES):
        hw, rw, cw = road_hw(y), rumble_w(y), centre_hw(y)
        row = []
        for x in range(256):
            d = abs(x - CENTRE_X)
            if d <= cw:
                c = 3
            elif d <= hw:
                c = 1
            elif d <= hw + rw:
                c = 2
            else:
                c = 0
            row.append(c)
        rows.append(row)
    return rows

def render_hills():
    """8 rows x 256 px silhouette (colour 2 on colour 0); periodic over 256."""
    heights = []
    for x in range(256):
        h = 3.5 + 2.0 * math.sin(2 * math.pi * x / 128) + 1.4 * math.sin(2 * math.pi * x / 64 + 1.0)
        heights.append(max(1, min(7, int(round(h)))))
    rows = []
    for y in range(8):
        rows.append([2 if y >= 8 - heights[x] else 0 for x in range(256)])
    return rows

def solid(c):
    return tuple([c] * 64)

def cut_tiles(bitmap, tile_rows):
    """Cut a bitmap (list of rows) into tiles; return list of tile-tuples per cell."""
    cells = []
    for ty in range(tile_rows):
        line = []
        for tx in range(32):
            t = []
            for py in range(8):
                t.extend(bitmap[ty * 8 + py][tx * 8: tx * 8 + 8])
            line.append(tuple(t))
        cells.append(line)
    return cells

def encode(tile):
    """64 colour indices -> 16 bytes of Game Boy 2bpp tile data."""
    out = []
    for py in range(8):
        lo = hi = 0
        for px in range(8):
            c = tile[py * 8 + px]
            lo |= (c & 1) << (7 - px)
            hi |= ((c >> 1) & 1) << (7 - px)
        out += [lo, hi]
    return out

class TileSet:
    def __init__(self):
        self.tiles, self.index = [], {}
    def add(self, t):
        if t not in self.index:
            self.index[t] = len(self.tiles)
            self.tiles.append(t)
        return self.index[t]

def emit_array(name, data, per_line=16):
    s = f"const unsigned char {name}[{len(data)}] = {{\n"
    for i in range(0, len(data), per_line):
        s += "    " + ", ".join(f"0x{b:02X}" for b in data[i:i + per_line]) + ",\n"
    return s + "};\n\n"

def main():
    out_dir = Path(sys.argv[1])
    out_dir.mkdir(parents=True, exist_ok=True)

    road, sky = TileSet(), TileSet()

    # sky block ids start at 128: 128 = plain sky (the HUD is the window layer, drawn over the BG)
    SKY_ID = sky.add(solid(0))

    grass_id = road.add(solid(0))          # road id 0 = pure grass

    road_cells = cut_tiles(render_road(), ROAD_ROWS)
    hill_cells = cut_tiles(render_hills(), 1)

    bg_map = [[128 + SKY_ID] * 32 for _ in range(MAP_H)]
    for ty in range(ROAD_ROWS):
        for tx in range(32):
            bg_map[ROAD_ROW0 + ty][tx] = road.add(road_cells[ty][tx])
    for tx in range(32):
        bg_map[HILL_ROW][tx] = 128 + sky.add(hill_cells[0][tx])

    if len(road.tiles) > 128:
        sys.exit(f"ERROR: {len(road.tiles)} unique road tiles (max 128). "
                 f"Pick a simpler edge slope or thinner rumble strips.")
    if len(sky.tiles) > 128:
        sys.exit(f"ERROR: {len(sky.tiles)} sky tiles (max 128).")

    road_bytes = [b for t in road.tiles for b in encode(t)]
    sky_bytes = [b for t in sky.tiles for b in encode(t)]
    map_bytes = [v for row in bg_map for v in row]

    # 64-entry sine table, +-50, used by the demo to sway the curve
    sine = [int(round(50 * math.sin(2 * math.pi * i / 64))) for i in range(64)]

    # 16 stripe-phase rows, one 256-byte page each, indexed by LY like the SCX table:
    # row[p][IDX0 + y] = BGP for road line y when the stripe phase is p.
    # Must match BGP_* / FOG_LINES / IDX0 in src/main.c (the selftest checks it).
    # Three palette sets, one per track.  Set 1 (CANYON) is the original and lives at $6000 in bank 1;
    # sets for OVAL (bank 2) and ALPINE (bank 3) are linked at $6000 of their own banks, so the ISR
    # code is the same and only the ROM bank register differs.  SKY is the BGP of lines above the road.
    IDX0, FOG = 47, 14
    HUD_BGP = 0xE4
    SETS = {   # bank: (sky, A, B, fog)
        1: (0xE4, 0x09, 0xB8, 0x99),     # CANYON: as before
        2: (0xE4, 0x38, 0x09, 0x99),     # OVAL: white/light grass stripes, black/white rumble strips
        3: (0xD8, 0x4D, 0xB8, 0x99),     # ALPINE: dusk, dark grass
    }
    def build(sky, A, B, FG):
        pat = []
        for p in range(16):
            page = [sky] * 256
            for y in range(ROAD_LINES):
                if y < FOG:
                    page[IDX0 + y] = FG
                else:
                    page[IDX0 + y] = B if (((4096 // (y + 4)) + p) >> 3) & 1 else A
            for i in range(IDX0 + ROAD_LINES, 256):
                page[i] = HUD_BGP
            pat += page
        return pat
    pat = build(*SETS[1])

    c = '/* GENERATED by tools/gen_road.py - do not edit */\n#pragma bank 1   /* boot-time data: ROM bank 1 */\n#include "road_data.h"\n\n'
    # The table is emitted as assembler in its own absolute area: the linker concatenates
    # same-named ABS areas from different files, which shifted a C `__at` table off its page.
    s = "; GENERATED by tools/gen_road.py - do not edit\n"
    s += "; 16 stripe-phase rows, one 256-byte page each, at $6000 so the HBlank ISR can use\n"
    s += "; H = page, L = LY.  Row p = page $60+p.\n"
    s += "        .area   PATROWS (ABS)\n        .org    0x6000\n_pat_rows::\n"
    for i in range(0, len(pat), 16):
        s += "        .db     " + ", ".join(f"0x{b:02X}" for b in pat[i:i + 16]) + "\n"
    (out_dir / "pat_rows.s").write_text(s)
    for bank in (2, 3):
        t = "; GENERATED by tools/gen_road.py - palette set for bank %d, linked at $6000 of that bank\n" % bank
        t += "        .area   _CODE_%d\n        .ds     0x2000\n_pat_rows_b%d::\n" % (bank, bank)
        pb = build(*SETS[bank])
        for i in range(0, len(pb), 16):
            t += "        .db     " + ", ".join(f"0x{b:02X}" for b in pb[i:i + 16]) + "\n"
        (out_dir / f"pat_rows{bank}.s").write_text(t)

    c += emit_array("road_tile_data", road_bytes)
    c += emit_array("sky_tile_data", sky_bytes)
    c += emit_array("bg_map", map_bytes, 32)
    c += "const signed char sine64[64] = {\n    " + ", ".join(str(v) for v in sine) + "\n};\n"
    (out_dir / "road_data.c").write_text(c)

    h = "/* GENERATED by tools/gen_road.py - do not edit */\n#ifndef ROAD_DATA_H\n#define ROAD_DATA_H\n\n"
    h += f"#define ROAD_TILE_COUNT {len(road.tiles)}\n#define SKY_TILE_COUNT  {len(sky.tiles)}\n"
    h += f"#define BG_MAP_W {MAP_W}\n#define BG_MAP_H {MAP_H}\n\n"
    h += "#define PAT_PAGE0 0x60   /* high byte of pat_rows; row p is page PAT_PAGE0 + p */\n"
    h += "extern const unsigned char pat_rows[];   /* pat_rows.s, absolute at $6000 */\n"
    h += "extern const unsigned char road_tile_data[];\nextern const unsigned char sky_tile_data[];\n"
    h += "extern const unsigned char bg_map[];\nextern const signed char sine64[64];\n\n#endif\n"
    (out_dir / "road_data.h").write_text(h)

    print(f"road tiles: {len(road.tiles)}/128   sky/hill/hud tiles: {len(sky.tiles)}/128")
    print(f"road: {2*road_hw(0)+1}px wide at top, {2*road_hw(ROAD_LINES-1)+1}px at bottom "
          f"(+{rumble_w(ROAD_LINES-1)}px rumble each side)")

if __name__ == "__main__":
    main()
