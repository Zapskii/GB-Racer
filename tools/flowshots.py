import sys,re
from pyboy import PyBoy
rom="build/racer.gb"
sym={}
for l in open("build/racer.noi"):
    m=re.match(r"DEF _(\w+) 0x([0-9A-Fa-f]+)",l)
    if m: sym[m.group(1)]=int(m.group(2),16)
pb=PyBoy(rom,window="null",sound_emulated=False)
mem=lambda n:pb.memory[sym[n]]
def run(n):
    for _ in range(n): pb.tick()
def tap(b,n=8):
    pb.button_press(b); run(n); pb.button_release(b); run(3)
def shot(name): pb.screen.image.resize((480,432)).save(f"build/{name}.png")
run(120); print("state",mem("g_state")); shot("flow_title")
tap("right"); tap("right"); print("sel",mem("g_laps_sel")); tap("left"); shot("flow_title2")
tap("start"); run(10); print("state",mem("g_state"),"cd",mem("g_cd")); shot("flow_cd3")
run(60); shot("flow_cd2")
while mem("g_state")==1: run(1)
run(5); print("state",mem("g_state")); shot("flow_go")
pb.button_press("a")
laps=0; last=0; f=0
while mem("g_state") in (2,3) and f<60*600:
    run(1); f+=1
    if f%1200==0: print(f,"state",mem("g_state"),"lap",mem("g_lap"),"diff",mem("g_diff"),"speed",pb.memory[sym["g_speed"]])
    if mem("g_lap")==2 and last==0: shot("flow_lap2"); last=1
print("frames",f,"state",mem("g_state"),"lap",mem("g_lap"))
run(100); print("state",mem("g_state")); shot("flow_results")
pb.button_release("a"); tap("start"); run(10); print("back to state",mem("g_state"))
