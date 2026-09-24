"""verify_cpu_lua.py - meta' Python del confronto di correttezza tra
cpu.py e cpu.lua (vedi verify_cpu_lua.lua per l'altra meta' e
cpu_lua_coverage_test.asm per il programma usato). Assembla il
programma di copertura, lo esegue con cpu.py, e stampa lo stato finale
in un formato facile da confrontare a colpo d'occhio con l'output Lua -
se le due righe "STATO:" sono identiche, cpu.lua si comporta
ESATTAMENTE come cpu.py su tutto cio' che il programma esercita."""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from assembler import assemble
from cpu import CPU

CART_LOAD_ADDR = 0x001000
INPUT_BYTE = 42

with open("cpu_lua_coverage_test.asm") as f:
    src = f.read()

rom = assemble(src, base_addr=CART_LOAD_ADDR)

with open("cpu_lua_coverage_test.rom", "wb") as f:
    f.write(bytes(rom))

cpu = CPU()
for i, b in enumerate(rom):
    cpu.mem[CART_LOAD_ADDR + i] = b

steps = cpu.run(CART_LOAD_ADDR, input_byte=INPUT_BYTE)

mem_dump = bytes(cpu.mem[0x3000:0x3034])

print(f"Python: istruzioni eseguite = {steps}")
print(f"STATO: a={cpu.a} x={cpu.x} y={cpu.y} pc={cpu.pc} flags={cpu.flags} sp={cpu.sp} "
      f"mem[0x3000:0x3034]={mem_dump.hex()}")
