#!/usr/bin/env python3
"""
Generates src/sprite_data.c / sprite_data.h and a preview PNG for the car sprites.

Cars are rear views drawn in code (no PNG source).  Colour indices:
    0 transparent   1 body   2 detail (window, lights)   3 outline / tyres
Palettes (set in sprites.c):  OBP0 player = body white, OBP1 rivals = body light grey.

Sprites run in 8x16 mode: one OAM object = a tile pair (even tile = top 8 rows, next = bottom).
A car W objects wide uses W consecutive pairs, left to right.  Art is bottom-aligned in the
16-row box so a car's "foot" is always the last row of the object.

    tile base   what
    SPR_PLAYER  0    3 frames (straight, left, right) x 3 objects x 2 tiles = 18 tiles
    SPR_R3      18   rival, 24 px wide (3 objects)
    SPR_R2      24   rival, 16 px wide (2 objects)
    SPR_R1      28   rival,  8 px wide (1 object)

Also emits y_of_z[256]: road line (0..79) at depth z, the inverse of the stripe depth
z = 4096 / (y + 4) used by gen_road.py, so sprites sit on the same perspective as the stripes.

Usage: gen_sprites.py <output_dir> [preview.png]
"""
import sys
from pathlib import Path

W, H = 24, 16

def blank(w=W, h=H):
    return [[0] * w for _ in range(h)]

def rect(img, x0, y0, x1, y1, c):
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            if 0 <= y < len(img) and 0 <= x < len(img[0]):
                img[y][x] = c

def car_master(lean=0):
    """24x16 rear view.  lean shifts the cabin (rows 0-8) sideways to suggest a turn."""
    img = blank()
    # silhouette half-widths per row (outline included), symmetric about x = 11.5
    half = [5, 6, 6, 7, 9, 10, 10, 11, 11, 11, 11, 11, 11, 11, 11, 11]
    for y, h in enumerate(half):
        rect(img, 12 - h, y, 11 + h, y, 1)
        img[y][12 - h] = 3
        img[y][11 + h] = 3
    rect(img, 12 - half[0], 0, 11 + half[0], 0, 3)          # roof outline
    # rear window
    rect(img, 7, 1, 16, 3, 2)
    rect(img, 7, 4, 16, 4, 3)                                # window sill
    # tail lights
    rect(img, 3, 6, 6, 8, 2)
    rect(img, 17, 6, 20, 8, 2)
    # number plate + bumper
    rect(img, 10, 9, 13, 11, 2)
    rect(img, 3, 12, 20, 12, 3)
    rect(img, 4, 13, 19, 14, 1)
    rect(img, 4, 15, 19, 15, 3)
    # tyres stick out at the bottom corners
    rect(img, 0, 8, 3, 15, 3)
    rect(img, 20, 8, 23, 15, 3)
    rect(img, 1, 9, 2, 10, 2)                                # hub highlights
    rect(img, 21, 9, 22, 10, 2)
    if lean:
        out = blank()
        for y in range(H):
            for x in range(W):
                v = img[y][x]
                if not v:
                    continue
                dx = lean if y <= 7 else (lean // 2 if y <= 9 else 0)   # cabin shifts most, tyres not at all
                nx = x + dx
                if 0 <= nx < W and not (out[y][nx] == 3 and v != 3):
                    out[y][nx] = v
        # fill any gap the shift left between cabin rows and tyres
        for y in range(H):
            if lean and y <= 9 and out[y][0 if lean > 0 else W - 1] == 0 and y >= 8:
                pass
        return out
    return img

def downscale(img, w, h):
    """Area-vote downscale keeping the most common non-zero value (ties -> darker)."""
    sw, sh = len(img[0]), len(img)
    out = blank(w, h)
    for y in range(h):
        for x in range(w):
            x0, x1 = x * sw // w, max(x * sw // w + 1, (x + 1) * sw // w)
            y0, y1 = y * sh // h, max(y * sh // h + 1, (y + 1) * sh // h)
            votes = {}
            for yy in range(y0, y1):
                for xx in range(x0, x1):
                    v = img[yy][xx]
                    votes[v] = votes.get(v, 0) + 1
            filled = sum(n for v, n in votes.items() if v)
            if filled * 2 < (x1 - x0) * (y1 - y0):
                out[y][x] = 0
            else:
                best = max((v for v in votes if v), key=lambda v: (votes[v], v))
                out[y][x] = best
    return out

# hand-tuned smallest car (8x8): the area vote turns it into mush
R1_ART = [
    "..3333..",
    ".311113.",
    ".322223.",
    "31111113",
    "32211223",
    "31111113",
    "33333333",
    "3.3..3.3",
]

def from_rows(rows):
    return [[int(c) if c != "." else 0 for c in r] for r in rows]

def place(img, w_objs, bottom_rows=None):
    """Put an image bottom-aligned/centred in a (8*w_objs) x 16 box."""
    box = blank(8 * w_objs, 16)
    ih, iw = len(img), len(img[0])
    ox, oy = (8 * w_objs - iw) // 2, 16 - ih
    for y in range(ih):
        for x in range(iw):
            box[oy + y][ox + x] = img[y][x]
    return box

def encode_tile(rows8):
    out = []
    for r in rows8:
        lo = hi = 0
        for x in range(8):
            c = r[x]
            lo |= (c & 1) << (7 - x)
            hi |= ((c >> 1) & 1) << (7 - x)
        out += [lo, hi]
    return out

def tiles_for(box):
    """box (8*n wide x 16 tall) -> list of 16-byte tiles: for each column pair, top then bottom."""
    n = len(box[0]) // 8
    out = []
    for k in range(n):
        for half in (0, 1):
            rows = [box[half * 8 + y][k * 8:(k + 1) * 8] for y in range(8)]
            out.append(encode_tile(rows))
    return out

def main():
    out_dir = Path(sys.argv[1])
    out_dir.mkdir(parents=True, exist_ok=True)
    preview = sys.argv[2] if len(sys.argv) > 2 else None

    master = {0: car_master(0), 1: car_master(-2), 2: car_master(2)}
    r3 = place(master[0], 3)
    r2 = place(downscale(master[0], 16, 11), 2)
    r1 = place(from_rows(R1_ART), 1)

    tiles = []
    for f in (0, 1, 2):
        tiles += tiles_for(place(master[f], 3))
    base_r3 = len(tiles); tiles += tiles_for(r3)
    base_r2 = len(tiles); tiles += tiles_for(r2)
    base_r1 = len(tiles); tiles += tiles_for(r1)
    # roadside posts (speed cue): three sizes, one 8x16 object each; banded black / dark grey, 1-2 px wide
    base_post = len(tiles)
    def band(h, w):
        return from_rows([("3" if (y // 2) % 2 == 0 else "2") * w for y in range(h)])
    for h, w in ((4, 1), (8, 2), (14, 2)):
        tiles += tiles_for(place(band(h, w), 1))
    # corner-warning chevrons (sky sign): "<" and ">", 8 x 16, solid black, 3 px thick, leaning one pixel per row towards the point
    base_sign = len(tiles)
    for flip in (True, False):
        rows = []
        for y in range(16):
            x0 = min(y if y < 8 else 15 - y, 5)
            r = [0] * 8
            for k in range(3):
                r[x0 + k] = 3
            rows.append(r[::-1] if flip else r)
        tiles += tiles_for(rows)
    data = [b for t in tiles for b in t]

    # y_of_z: road line at depth z (z = 4096/(y+4) in gen_road.py), clamped to the 80 road lines
    y_of_z = []
    for z in range(256):
        y = 79 if z == 0 else 4096 // z - 4
        y_of_z.append(max(0, min(79, y)))

    c = '/* GENERATED by tools/gen_sprites.py - do not edit */\n#pragma bank 1   /* boot-time data: ROM bank 1 */\n#include "sprite_data.h"\n\n'
    c += f"const unsigned char spr_tile_data[{len(data)}] = {{\n"
    for i in range(0, len(data), 16):
        c += "    " + ", ".join(f"0x{b:02X}" for b in data[i:i + 16]) + ",\n"
    c += "};\n\n"
    (out_dir / "sprite_data.c").write_text(c)
    t = '/* GENERATED by tools/gen_sprites.py - do not edit */\n#include "sprite_data.h"\n\n'
    t += "const unsigned char post_off[96] = {       /* post distance from the road centre by road line (+ pitch): tarmac + rumble + 3 */\n"
    for i in range(0, 96, 16):
        t += "    " + ", ".join(str(3 + (3 * y) // 4 + 1 + y // 16 + 3) for y in range(i, i + 16)) + ",\n"
    t += "};\n\n"
    t += "const unsigned char y_of_z[256] = {\n"
    for i in range(0, 256, 16):
        t += "    " + ", ".join(str(v) for v in y_of_z[i:i + 16]) + ",\n"
    t += "};\n"
    (out_dir / "sprite_tab.c").write_text(t)

    h = "/* GENERATED by tools/gen_sprites.py - do not edit */\n#ifndef SPRITE_DATA_H\n#define SPRITE_DATA_H\n\n"
    h += f"#define SPR_PLAYER 0   /* 3 frames x 6 tiles: straight, left, right */\n"
    h += f"#define SPR_R3     {base_r3}\n#define SPR_R2     {base_r2}\n#define SPR_R1     {base_r1}\n"
    h += f"#define SPR_POST   {base_post}   /* 3 post sizes x 2 tiles: 4, 8 and 14 px tall */\n"
    h += f"#define SPR_SIGN   {base_sign}   /* corner-warning chevrons: '<' then '>' (2 tiles each) */\n"
    h += f"#define SPR_TILE_COUNT {len(tiles)}\n\n"
    h += "extern const unsigned char spr_tile_data[];\nextern const unsigned char y_of_z[256];\nextern const unsigned char post_off[96];\n\n#endif\n"
    (out_dir / "sprite_data.h").write_text(h)
    print(f"sprite tiles: {len(tiles)} (player 0, R3 {base_r3}, R2 {base_r2}, R1 {base_r1}); "
          f"y_of_z: z=49 -> {y_of_z[49]}, z=227 -> {y_of_z[227]}, z=255 -> {y_of_z[255]}")

    if preview:
        from PIL import Image
        # on-screen shades: player OBP0 (body white), rival OBP1 (body light grey); road dark grey behind
        pal0 = {0: 85, 1: 255, 2: 85, 3: 0}
        pal1 = {0: 85, 1: 170, 2: 85, 3: 0}
        items = [("p0", place(master[0], 3), pal0), ("pL", place(master[1], 3), pal0), ("pR", place(master[2], 3), pal0),
                 ("R3", r3, pal1), ("R2", r2, pal1), ("R1", r1, pal1)]
        S = 8
        sheet = Image.new("L", (sum(len(b[0]) + 4 for _, b, _ in items) * S, 20 * S), 85)
        x0 = 0
        for _, box, pal in items:
            for y, row in enumerate(box):
                for x, v in enumerate(row):
                    if v:
                        sheet.paste(pal[v], (x0 + (x + 2) * S, (y + 2) * S, x0 + (x + 3) * S, (y + 3) * S))
            x0 += (len(box[0]) + 4) * S
        Path(preview).parent.mkdir(parents=True, exist_ok=True)
        sheet.save(preview)

if __name__ == "__main__":
    main()
