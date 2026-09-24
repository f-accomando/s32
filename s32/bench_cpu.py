"""bench_cpu.py - meta' del confronto Python/LuaJIT (vedi bench_cpu.lua
per l'altra meta'): carica l'immagine di memoria prodotta da
dump_cpu_state.py e cronometra N chiamate a cpu.run() con cpu.py
(Python/Cython, quello che gira davvero nel motore) - stesso identico
lavoro che bench_cpu.lua fa con cpu.lua, per un confronto onesto a
parita' di input.

Uso:
    python3 bench_cpu.py [cpu_bench_mem.bin] [start_pc esadecimale] [n_frame]

Esempio:
    python3 bench_cpu.py cpu_bench_mem.bin 0x1000 1000
"""
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cpu import CPU

mem_path = sys.argv[1] if len(sys.argv) > 1 else "cpu_bench_mem.bin"
start_pc = int(sys.argv[2], 0) if len(sys.argv) > 2 else 0x001000
n_frames = int(sys.argv[3]) if len(sys.argv) > 3 else 1000

with open(mem_path, "rb") as f:
    data = f.read()

cpu = CPU()
cpu.mem[:] = data

cpu_total = 0.0
total_instr = 0
for _ in range(n_frames):
    t0 = time.perf_counter()
    n = cpu.run(start_pc, input_byte=0)
    t1 = time.perf_counter()
    cpu_total += (t1 - t0)
    total_instr += n

cpu_ms = cpu_total / n_frames * 1000
avg_instr = total_instr / n_frames
us_per_instr = (cpu_total / total_instr) * 1e6 if total_instr else 0.0

print(f"Python (cpu.py: {CPU.__module__}, verifica .so/.py con 'import cpu; print(cpu.__file__)')")
print(f"  {n_frames} frame, cpu totale {cpu_total*1000:.2f}ms, "
      f"media {cpu_ms:.4f}ms/frame, istruzioni media {avg_instr:.1f}/frame, "
      f"{us_per_instr:.2f}us/istruzione")
