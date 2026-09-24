; cpu_lua_coverage_test.asm - programma sintetico per verificare che
; cpu.lua produca ESATTAMENTE lo stesso stato finale di cpu.py (stesso
; ROM, stesso input, stesso risultato) - non deve avere senso come
; gioco, deve solo esercitare quanti piu' opcode possibile. Vedi
; verify_cpu_lua.py/verify_cpu_lua.lua per il confronto.

LDA #1000
STA 0x3000
LDX #10
STX 0x3002
LDY #20
STY 0x3004

TAX
TXA
TAY
TYA
TXY
TYX

LDA #500
ADD #250
STA 0x3006
LDA #500
SUB #250
STA 0x3008
LDA #0b1100
AND #0b1010
STA 0x300A
LDA #0b1100
OR #0b1010
STA 0x300C
LDA #0b1100
XOR #0b1010
STA 0x300E

LDA #77
STA 0x3010
LDA #500
ADD 0x3010
STA 0x3012
SUB 0x3010
STA 0x3014
AND 0x3010
STA 0x3016
OR 0x3010
STA 0x3018
XOR 0x3010
STA 0x301A

LDA #50
CMP #50
CMP #30
CMP #80
CMP 0x3010

LDA #0b0101
ASL
STA 0x301C
LDA #0b1010
LSR
STA 0x301E

INC 0x3000
DEC 0x3002
INX
INY
DEX
DEY

LDA #5
CMP #5
JZ zero_branch_taken
LDA #999
STA 0x3020
JMP after_zero

zero_branch_taken:
LDA #111
STA 0x3020

after_zero:
LDA #5
CMP #6
JNZ notzero_taken
LDA #888
STA 0x3022
JMP after_notzero

notzero_taken:
LDA #222
STA 0x3022

after_notzero:
LDA #0xFFFF
CMP #0
JLT neg_taken
LDA #777
STA 0x3024
JMP after_neg

neg_taken:
LDA #333
STA 0x3024

after_neg:
LDA #5
CMP #3
JGE ge_taken
LDA #666
STA 0x3026
JMP after_ge

ge_taken:
LDA #444
STA 0x3026

after_ge:
LDA #10
CMP #5
JCS carry_taken
LDA #555
STA 0x3028
JMP after_carry

carry_taken:
LDA #555
STA 0x3028

after_carry:
LDA #3
CMP #10
JCC nocarry_taken
LDA #333
STA 0x302A
JMP after_nocarry

nocarry_taken:
LDA #666
STA 0x302A

after_nocarry:
JSR subroutine_a
STA 0x302C

LDA #12
PHA
LDX #34
PHX
LDY #56
PHY
LDA #0
LDX #0
LDY #0
PLY
PLX
PLA

IN
STA 0x302E

LDX #500
CLAMPX 100,200
STX 0x3030
LDY #5
CLAMPY 100,200
STY 0x3032

HALT

subroutine_a:
LDA #9999
RTS
