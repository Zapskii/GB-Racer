#!/usr/bin/env python3
"""Draw GB Racer's 256x224 Super Game Boy border art: a circuit round the screen.

Chequered flag strips top and bottom, the title on dark asphalt, red/white kerbs
round the Game Boy screen, mown-stripe grass at the sides and a starting grid
below.  Every pattern repeats on the 8 px tile grid so the art dedupes to a few
dozen tiles.  The output is the input to GB-SGB-Tooling's `mkborder.py --art`,
which clears the screen hole and packs the palettes; the title uses that tool's
font.

  racer_art.py out.png [path/to/GB-SGB-Tooling]
"""
import os
import sys
from PIL import Image

tooling = sys.argv[2] if len(sys.argv) > 2 else os.path.expanduser("~/GB-SGB-Tooling")
sys.path.insert(0, tooling)
from mkborder import FONT                     # noqa: E402  (the shared 5x7 font)

W, H = 256, 224
HX, HY, HW, HH = 48, 40, 160, 144           # the Game Boy screen (transparent)

BLACK = (16, 16, 24)
WHITE = (240, 240, 232)
GRASS = [(48, 128, 48), (64, 152, 56)]      # mown stripes, dark / light
ASPHALT = (56, 56, 64)
ASPHALT_DK = (40, 40, 48)
KERB_RED = (208, 40, 32)
TITLE = (248, 208, 48)
TITLE_SHADOW = (168, 32, 24)

img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
px = img.load()


def rect(x, y, w, h, c):
    for yy in range(max(y, 0), min(y + h, H)):
        for xx in range(max(x, 0), min(x + w, W)):
            px[xx, yy] = c + (255,)


def checker(y, rows):
    """chequered flag: 4 px squares, so one 8x8 tile repeats"""
    for yy in range(y, y + rows):
        for x in range(W):
            px[x, yy] = (BLACK if ((x >> 2) + (yy >> 2)) & 1 else WHITE) + (255,)


def text(s, y, scale, c, dx=0):
    pitch = 6 * scale
    width = len(s) * pitch - scale
    x0 = (W - width) // 2 + dx
    for i, ch in enumerate(s):
        if ch == " ":
            continue
        for gy, row in enumerate(FONT[ch].split("|")):
            for gx, bit in enumerate(row):
                if bit == "#":
                    rect(x0 + i * pitch + gx * scale, y + gy * scale, scale, scale, c)


# grass everywhere, in 16 px mown bands
for y in range(H):
    for x in range(W):
        px[x, y] = GRASS[(y >> 4) & 1] + (255,)

# the circuit: asphalt round the screen, 8 px of road on each side of the kerbs
rect(HX - 16, HY - 8, HW + 32, HH + 16, ASPHALT)
# title panel above, starting grid below: both asphalt, full width
rect(0, 8, W, HY - 8 - 8, ASPHALT_DK)
rect(0, HY + HH + 8, W, H - 8 - (HY + HH + 8), ASPHALT)
checker(0, 8)
checker(H - 8, 8)

# title, 3x, with a drop shadow
text("GB RACER", 11, 3, TITLE_SHADOW, dx=2)
text("GB RACER", 9, 3, TITLE)

# red/white kerbs hugging the screen, 4 px deep, in 8 px blocks
for y in range(HY - 4, HY + HH + 4):
    for x in range(HX - 4, HX + HW + 4):
        if HX <= x < HX + HW and HY <= y < HY + HH:
            continue
        along = x if (y < HY or y >= HY + HH) else y
        px[x, y] = (KERB_RED if (along >> 3) & 1 else WHITE) + (255,)

# starting grid: white boxes, two rows staggered like a real grid
gy = HY + HH + 12
for i, x in enumerate(range(16, W - 16, 32)):
    yy = gy + (8 if i & 1 else 0)
    rect(x, yy, 16, 1, WHITE)               # the box's front line
    rect(x, yy, 1, 8, WHITE)                # and its sides
    rect(x + 15, yy, 1, 8, WHITE)

# the screen itself: transparent (mkborder.py --art also enforces this)
rect(HX, HY, HW, HH, (0, 0, 0))
for y in range(HY, HY + HH):
    for x in range(HX, HX + HW):
        px[x, y] = (0, 0, 0, 0)

img.save(sys.argv[1])
