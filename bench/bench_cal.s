; calibration: exactly 1024 nops (1 M-cycle each) + ret, to validate the DIV scaling
        .area   _CODE
_bench_cal1024::
        .rept   1024
        nop
        .endm
        ret
