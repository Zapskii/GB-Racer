import re,sys
from pyboy import PyBoy
from PIL import Image
rom=sys.argv[1] if len(sys.argv)>1 else "build/racer.gb"
sym={}
for l in open(rom.replace(".gb",".noi")):
    m=re.match(r"DEF _(\w+) 0x([0-9A-Fa-f]+)",l)
    if m: sym[m.group(1)]=int(m.group(2),16)
import shutil,tempfile,os
ims=[]
for t in range(3):
    d=tempfile.mkdtemp(); r=os.path.join(d,"t.gb"); shutil.copy(rom,r)
    pb=PyBoy(r,window="null",sound_emulated=False)
    def run(n):
        for _ in range(n): pb.tick()
    def tap(b,n=8):
        pb.button_press(b); run(n); pb.button_release(b); run(3)
    run(150)
    for _ in range(3): tap("up")
    for _ in range(t): tap("down")
    tap("start"); run(50*4+30)
    pb.button_press("a"); run(150)
    ims.append(pb.screen.image.copy().resize((320,288),Image.NEAREST))
    print(t,"state",pb.memory[sym["g_state"]],"track",pb.memory[sym["g_track"]])
    pb.stop()
W=Image.new("RGB",(960,288))
for i,im in enumerate(ims): W.paste(im,(i*320,0))
W.save("build/track_sheet.png")
