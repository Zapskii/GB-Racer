import re, sys
from pyboy import PyBoy
from PIL import Image
rom = "build/racer.gb"
sym = {}
for l in open("build/racer.noi"):
    m = re.match(r"DEF _(\w+) 0x([0-9A-Fa-f]+)", l)
    if m: sym[m.group(1)] = int(m.group(2), 16)
import shutil, tempfile, os
d = tempfile.mkdtemp(); r = os.path.join(d, "t.gb"); shutil.copy(rom, r)
pb = PyBoy(r, window="null", sound_emulated=False)
def run(n):
    for _ in range(n): pb.tick()
def tap(b, n=6):
    pb.button_press(b); run(n); pb.button_release(b); run(4)
def shot(name): pb.screen.image.resize((480, 432), Image.NEAREST).save(f"build/{name}.png")
run(150); tap("select"); tap("select"); shot("v2_title")
tap("start"); run(50 * 3 + 80); pb.button_press("a"); run(240); tap("start", 3); run(10); shot("v2_pause")
pb.stop(save=False)
