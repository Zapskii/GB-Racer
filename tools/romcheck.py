#!/usr/bin/env python3
"""Bank layout guard: all code and run-time data must end below $4000 (bank 0 is the only bank that is always mapped,
and the track palette banks replace $4000-$7FFF), boot-time data (_CODE_1) must fit under the palette rows at $6000."""
import re, sys
m = open(sys.argv[1].replace(".gb", ".map")).read()
end0 = 0
areas = {}
for name, base, size in re.findall(r"^(_\w+)\s+([0-9A-F]{8})\s+([0-9A-F]{8})", m, re.M):
    b, s = int(base, 16), int(size, 16)
    areas[name] = b + s
    if b < 0x4000 and name not in ("_CODE_0",): end0 = max(end0, b + s)
c1 = re.search(r"^_CODE_1\s+[0-9A-F]{8}\s+([0-9A-F]{8})", m, re.M)
c1 = int(c1.group(1), 16) if c1 else 0
free0 = 0x4000 - end0
ok = end0 <= 0x4000 and c1 <= 0x2000 and free0 >= 64
fails = []
if end0 > 0x4000:
    fails.append(f"bank 0 ends at ${end0:04X} > $4000")
if free0 < 64:
    fails.append(f"bank 0 free {free0} < 64 bytes")
if c1 > 0x2000:
    fails.append(f"bank-1 boot data {c1} > 8192 bytes")
for name in ("_DATA", "_BSS"):
    if name in areas and areas[name] >= 0xD000:
        fails.append(f"{name} ends at ${areas[name]:04X} >= $D000")
print(f"bank 0 ends at ${end0:04X} ({free0} bytes free), bank-1 boot data {c1} bytes (limit 8192): {'OK' if ok else 'FAIL'}")
if fails:
    print(f"RESULT: FAIL ({'; '.join(fails)})")
    sys.exit(1)
print("RESULT: PASS")
