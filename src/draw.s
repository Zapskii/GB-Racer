; void draw_rival(rival_t *r, const uint8_t *scx_tbl)       sdcccall(1): r in DE, scx_tbl in BC
;
; Hand-written version of the C draw_rival that was ~1,000 cycles per rival.  Same maths, same
; results (tools/oamcmp.py compares OAM frame by frame against the C version's ROM):
;
;   zi   = min(255, z16 >> 4);  y = y_of_z[zi]            (y < 12: hide the car)
;   hw   = 3 + 3y/4
;   cx   = 80 - (scx_tbl[IDX0 + y] - SCX_BASE) + floor(lane * hw / 64)
;   w    = 1 (y<30), 2 (y<54), 3          left = cx - 4w   (left < -7 or > 159: hide)
;   OAM  = w objects, y = ROAD_TOP + y + 1, x = left + 8 + 8k, tile = draw_tiles[w-1] + 2k; rest cleared
;
; Hill pitch: the picture is scrolled up by g_pitch lines, so the tarmac on road line y is the one for
; row y + g_pitch; hw uses that.
;
; rival_t layout (see sprites.c): +0 z16 (2)  +2 lane  +3 speed  +4 obj0  +5 foot  +6 w  +7 cx (2)
; Constants below must equal layout.h (checked by a typedef in sprites.c).

IDX0        = 47
ROAD_TOP    = 48
SCX_BASE    = 48

        .module draw
        .globl  _y_of_z, _draw_tiles, _shadow_OAM, _g_pitch

        .area   _DATA
dr_r:       .ds 2       ; the rival pointer
dr_y:       .ds 1       ; road line
dr_lo:      .ds 1       ; lane term in px (signed)
dr_w:       .ds 1       ; width in objects
dr_t:       .ds 1       ; first tile

        .area   _CODE
_draw_rival::
        ld      hl, #dr_r
        ld      (hl), e
        inc     hl
        ld      (hl), d
        push    bc                      ; scx_tbl
        ld      h, d
        ld      l, e
        ld      a, (hl+)                ; z16 low
        ld      c, a
        ld      b, (hl)                 ; z16 high
        ld      a, b
        cp      a, #0x10                ; z16 >> 4 > 255 ?
        jr      nc, 1$
        swap    a                       ; (hi << 4) | (lo >> 4)
        ld      b, a
        ld      a, c
        swap    a
        and     a, #0x0F
        or      a, b
        jr      2$
1$:     ld      a, #0xFF
2$:     ld      hl, #_y_of_z
        ld      c, a
        ld      b, #0
        add     hl, bc
        ld      a, (hl)                 ; A = y
        ld      (dr_y), a
        cp      a, #12
        jr      nc, dr_cont

; ---- hide: clear the three OAM y's and r->foot ----
hide:
        pop     bc                      ; discard scx_tbl
hide_nopop:
        ld      a, (dr_r)
        ld      e, a
        ld      a, (dr_r + 1)
        ld      d, a
        ld      hl, #4
        add     hl, de
        ld      a, (hl+)                ; obj0
        ld      (hl), #0                ; r->foot = 0   (hl = r + 5)
        add     a, a
        add     a, a
        ld      l, a
        ld      h, #>_shadow_OAM
        xor     a, a
        ld      (hl), a
        ld      a, l
        add     a, #4
        ld      l, a
        xor     a, a
        ld      (hl), a
        ld      a, l
        add     a, #4
        ld      l, a
        xor     a, a
        ld      (hl), a
        ret

dr_cont:                                ; ---- hw = 3 + ((3 * (y + pitch)) >> 2): the BG is scrolled by SCY = pitch, so line y shows road row y + pitch ----
        ld      b, a                    ; B = y
        ld      hl, #_g_pitch
        add     a, (hl)                 ; y + pitch  (y >= 12, pitch >= -6: never negative; <= 82 so 3x fits a byte)
        ld      c, a
        add     a, a
        add     a, c
        srl     a
        srl     a
        add     a, #3
        ld      e, a                    ; E = hw
        ld      d, #0
        ; ---- w and first tile from y ----
        ld      a, b
        ld      c, #0                   ; table index
        cp      a, #30
        jr      c, 4$
        inc     c
        cp      a, #54
        jr      c, 4$
        inc     c
4$:     ld      a, c
        inc     a
        ld      (dr_w), a
        ld      hl, #_draw_tiles
        ld      b, #0
        add     hl, bc
        ld      a, (hl)
        ld      (dr_t), a
        ; ---- lane term: floor(lane * hw / 64) ----
        ld      a, (dr_r)
        ld      l, a
        ld      a, (dr_r + 1)
        ld      h, a
        inc     hl
        inc     hl
        ld      a, (hl)                 ; lane (signed)
        ld      c, a
        bit     7, a
        jr      z, 5$
        cpl
        inc     a                       ; |lane|
5$:     ld      b, a                    ; multiplier
        ld      hl, #0
        or      a, a
        jr      z, 8$
6$:     srl     b
        jr      nc, 7$
        add     hl, de
7$:     sla     e
        rl      d
        ld      a, b
        or      a, a
        jr      nz, 6$
8$:     bit     7, c
        jr      z, 9$
        ld      de, #63                 ; negative: -ceil(p/64) = -((p + 63) >> 6)
        add     hl, de
9$:     ld      a, l                    ; (HL >> 6) low byte = (h << 2) | (l >> 6)
        rlca
        rlca
        and     a, #3
        ld      e, a
        ld      a, h
        add     a, a
        add     a, a
        or      a, e
        bit     7, c
        jr      z, 10$
        cpl
        inc     a
10$:    ld      (dr_lo), a
        ; ---- cx = 80 - delta + lane term ----
        pop     hl                      ; scx_tbl
        ld      a, (dr_y)
        ld      c, a
        ld      b, #0
        add     hl, bc
        ld      bc, #IDX0
        add     hl, bc
        ld      a, (hl)
        sub     a, #SCX_BASE            ; delta (signed 8 bit)
        cpl                             ; -delta = ~delta + 1, done in 16 bits below
        ld      e, a
        rla
        sbc     a, a
        ld      d, a                    ; DE = sext(~delta)
        inc     de                      ; DE = -delta
        ld      a, (dr_lo)
        ld      l, a
        rla
        sbc     a, a
        ld      h, a                    ; HL = sext(lane term)
        add     hl, de
        ld      de, #80
        add     hl, de
        ld      b, h
        ld      c, l                    ; BC = cx
        ; ---- r->foot, r->w, r->cx ----
        ld      a, (dr_r)
        ld      e, a
        ld      a, (dr_r + 1)
        ld      d, a
        ld      hl, #5
        add     hl, de
        ld      a, (dr_y)
        add     a, #ROAD_TOP
        ld      (hl+), a                ; foot
        ld      a, (dr_w)
        ld      (hl+), a                ; w
        ld      (hl), c                 ; cx
        inc     hl
        ld      (hl), b
        ; ---- left = cx - 4w ; offscreen if left < -7 or left > 159 ----
        add     a, a
        add     a, a                    ; A = 4w
        ld      e, a
        ld      a, c
        sub     a, e
        ld      c, a
        ld      a, b
        sbc     a, #0
        ld      b, a                    ; BC = left
        ld      hl, #7
        add     hl, bc                  ; left + 7 must be in 0..166
        ld      a, h
        or      a, a
        jr      nz, 11$
        ld      a, l
        cp      a, #167
        jr      c, 12$
11$:    jp      hide_nopop              ; (r->foot gets cleared there)
12$:    ; ---- write the objects ----
        ld      a, c
        add     a, #8
        ld      c, a                    ; C = x of object 0 (low byte)
        ld      a, (dr_r)
        ld      l, a
        ld      a, (dr_r + 1)
        ld      h, a
        ld      de, #4
        add     hl, de
        ld      a, (hl+)                ; obj0
        ld      b, (hl)                 ; foot
        inc     b                       ; OAM y = foot + 1
        add     a, a
        add     a, a
        ld      l, a
        ld      h, #>_shadow_OAM
        ld      a, (dr_t)
        ld      d, a                    ; D = tile
        ld      a, (dr_w)
        ld      e, a                    ; E = objects to write
13$:    ld      a, b
        ld      (hl+), a                ; y
        ld      a, c
        ld      (hl+), a                ; x
        ld      a, d
        ld      (hl+), a                ; tile
        inc     l                       ; skip attributes
        ld      a, c
        add     a, #8
        ld      c, a
        inc     d
        inc     d
        dec     e
        jr      nz, 13$
        ld      a, (dr_w)
        cpl
        add     a, #4                   ; 3 - w  (= ~w + 4 = 3 - w)
        ld      e, a
        jr      z, 15$
14$:    xor     a, a
        ld      (hl), a                 ; y = 0 (hidden)
        ld      a, l
        add     a, #4
        ld      l, a
        dec     e
        jr      nz, 14$
15$:    ret
