# GB racer - needs GBDK-2020 (set GBDK=/path/to/gbdk) and python3
#
#   make                 release ROM (asm table builder)         -> build/racer.gb
#   make variants        profiling ROMs, asm and C builders      -> build/prof_*.gb
#   make check           fast structural + regression checks (needs PyBoy)
#   make test            full behaviour suite (needs PyBoy; slow)
#
# GBDK defaults to $HOME/vendor/gbdk; override with GBDK=/path/to/gbdk.
# The Python checks need PyBoy; see README (a .venv is not assumed).

GBDK   ?= $(HOME)/vendor/gbdk
LCC     = $(GBDK)/bin/lcc
PYTHON ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
OPT     = -Wf--opt-code-size          # bank 0 is full: the PROFILE builds spill into bank 1 without it
CART    = -Wm-yt0x03 -Wm-yo4 -Wm-ya1  # MBC1 + RAM + battery, 64 KB ROM (3 palette banks), 8 KB save RAM
SRC     = src/main.c src/game.c src/hud.c src/menus.c src/sprites.c src/raster.s src/draw.s src/road_data.c src/pat_rows.s src/pat_rows2.s src/pat_rows3.s src/sprite_data.c src/sprite_tab.c src/hud_data.c src/hud_tab.c src/audio.c src/audio_data.c src/flow.c src/sram.c
HDR     = $(wildcard src/*.h)
ROADGEN = src/road_data.c src/road_data.h src/pat_rows.s src/pat_rows2.s src/pat_rows3.s
SPRGEN  = src/sprite_data.c src/sprite_tab.c src/sprite_data.h
HUDGEN  = src/hud_data.c src/hud_tab.c src/hud_data.h
AUDGEN  = src/audio_data.c src/audio_data.h

all: build/racer.gb

$(HUDGEN): tools/gen_hud.py
	python3 tools/gen_hud.py src

$(AUDGEN): tools/gen_audio.py
	python3 tools/gen_audio.py src

$(SPRGEN): tools/gen_sprites.py
	python3 tools/gen_sprites.py src build/shots/sprites_preview.png

$(ROADGEN): tools/gen_road.py
	python3 tools/gen_road.py src

build/racer.gb: $(SRC) $(HDR) Makefile
	mkdir -p build
	$(LCC) $(CART) $(OPT) -Wm-yn"GBRACER" -Wl-m -Wl-j -o $@ $(SRC)

variants: $(ROADGEN) $(SPRGEN) $(HUDGEN) $(AUDGEN) $(HDR) Makefile
	mkdir -p build
	$(LCC) $(OPT) -DPROFILE -DSELFTEST -DAUTOSTART -DTRAFFIC -DLEGACY_PHYSICS $(CART) -Wm-yn"GBRACER" -Wl-m -Wl-j -o build/prof_asm.gb $(SRC)
	$(LCC) $(OPT) -DPROFILE -DSELFTEST -DHILLS_OFF -DAUTOSTART -DTRAFFIC -DDIFF_OFF -DSEG_LEN16=2400 -DLEGACY_PHYSICS -DCANYON_CLASSIC -DSTEER_BASE=80 -DSTEER_GAIN=2 $(CART) -Wm-yn"GBRACER" -Wl-m -Wl-j -o build/prof_nohill.gb $(SRC)
	$(LCC) $(OPT) -DPROFILE -DSELFTEST -DAUTOSTART -DTRAFFIC -DLEGACY_PHYSICS -DUSE_C_BUILDER $(CART) -Wm-yn"GBRACER" -Wl-m -Wl-j -o build/prof_c.gb $(SRC)
	$(LCC) $(OPT) -DPROFILE $(CART) -Wm-yn"GBRACER" -Wl-m -Wl-j -o build/prof_flow.gb $(SRC)
	$(LCC) $(OPT) -DPROFILE -DAUTOSTART $(CART) -Wm-yn"GBRACER" -Wl-m -Wl-j -o build/prof_race.gb $(SRC)
	$(LCC) $(OPT) -DPROFILE -DAUTOSTART -DNO_DODGE $(CART) -Wm-yn"GBRACER" -Wl-m -Wl-j -o build/prof_nododge.gb $(SRC)

bench:
	@echo "The cycle bench is a development artifact and does not fit bank 0 with GBDK 4.5; see bench/Makefile."; false

# fast: layout + both table builders + the three regression checks
check: all variants
	$(PYTHON) tools/romcheck.py build/racer.map
	$(PYTHON) tools/profile.py build/prof_asm.gb
	$(PYTHON) tools/modelcheck.py build/prof_asm.gb
	$(PYTHON) tools/crosscheck.py build/prof_asm.gb build/prof_c.gb
	$(PYTHON) tools/brakecheck.py build/prof_race.gb
	$(PYTHON) tools/levelcheck.py build/prof_race.gb
	$(PYTHON) tools/offroadcheck.py build/prof_race.gb
	$(PYTHON) tools/steercheck.py build/prof_race.gb
	$(PYTHON) tools/flickercheck.py build/prof_race.gb
	$(PYTHON) tools/audiostatecheck.py build/prof_flow.gb
	$(PYTHON) tools/pausecheck.py build/prof_flow.gb

# full: everything above plus the behaviour/DSP/save suites
test: check
	$(PYTHON) tools/gamecheck.py build/prof_flow.gb
	$(PYTHON) tools/racecheck.py build/prof_race.gb
	$(PYTHON) tools/cornercheck.py build/prof_race.gb
	$(PYTHON) tools/phasecheck.py build/prof_race.gb
	$(PYTHON) tools/postcheck.py build/prof_race.gb
	$(PYTHON) tools/spritecheck.py build/prof_race.gb
	$(PYTHON) tools/hillcheck.py build/prof_asm.gb
	$(PYTHON) tools/warncheck.py build/prof_race.gb
	$(PYTHON) tools/audiocheck.py build/prof_race.gb
	$(PYTHON) tools/savecheck.py

clean:
	rm -rf build src/road_data.c src/road_data.h src/pat_rows.s src/pat_rows2.s src/pat_rows3.s src/sprite_data.c src/sprite_tab.c src/sprite_data.h src/hud_data.c src/hud_tab.c src/hud_data.h src/audio_data.c src/audio_data.h

.PHONY: all variants clean check test bench
