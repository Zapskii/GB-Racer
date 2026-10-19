# Cycle benchmark (development artifact).
#
# NOTE: this build includes ../src/main.c and links the whole game, so with GBDK 4.5 it needs
# about 1.6 KB more bank 0 than is available.  It is not part of `make`; building it requires a
# bank-layout refactor (move the table builders out of main.c).  See README.
GBDK ?= $(HOME)/vendor/gbdk
LCC   = $(GBDK)/bin/lcc
all: ../build/bench.gb
../build/bench.gb: bench_main.c bench_cal.s ../src/main.c ../src/raster.s ../src/draw.s ../src/road_data.c ../src/pat_rows.s ../src/sprites.c ../src/sprite_data.c ../src/sprite_tab.c ../src/game.c ../src/hud.c ../src/hud_data.c ../src/hud_tab.c ../src/audio.c ../src/audio_data.c ../src/flow.c ../src/sram.c ../src/pat_rows2.s ../src/pat_rows3.s
	mkdir -p ../build
	$(LCC) -Wm-yt0x03 -Wm-yo4 -Wm-ya1 -Wm-yn"BENCH" -Wl-m -Wl-j -o $@ bench_main.c bench_cal.s ../src/raster.s ../src/draw.s ../src/road_data.c ../src/pat_rows.s ../src/sprites.c ../src/sprite_data.c ../src/sprite_tab.c ../src/game.c ../src/hud.c ../src/hud_data.c ../src/hud_tab.c ../src/audio.c ../src/audio_data.c ../src/flow.c ../src/sram.c ../src/pat_rows2.s ../src/pat_rows3.s
