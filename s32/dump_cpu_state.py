"""dump_cpu_state.py - scrive su disco un'immagine ESATTA della memoria
di CPU (16MB, vedi memory_map.ADDRESS_SPACE) cosi' come si trova appena
prima del primo cpu.run() di una cartuccia - stessa preparazione che fa
run_benchmark()/run_direct() in launcher.py (carica la ROM assemblata/
compilata a CART_LOAD_ADDR, scrive le variabili di stato iniziali).

Serve per confrontare cpu.py (Python/Cython) con un'eventuale
reimplementazione in un altro linguaggio (vedi cpu.lua) a PARITA' di
input: invece di riscrivere l'assembler o il compilatore ConsoleLang
nell'altro linguaggio, si assembla/compila UNA VOLTA qui in Python (che
gia' lo sa fare) e si scrive il risultato in un blob binario che
qualunque linguaggio puo' leggere con una lettura di file grezza.

Uso:
    python3 dump_cpu_state.py <path_cartuccia> [output.bin]

Esempio:
    python3 dump_cpu_state.py ../carts/adventure_asm/game.asm cpu_bench_mem.bin

Il file prodotto e' ESATTAMENTE ADDRESS_SPACE byte (16MB) - la stessa
identica immagine di partenza che vedrebbe cpu.mem in Python. Chi lo
legge in un altro linguaggio deve solo sapere che l'esecuzione parte da
CART_LOAD_ADDR (stampato qui sotto, e comunque una costante fissa del
progetto, vedi launcher.py)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from launcher import load_cart_rom, determine_mode, CART_LOAD_ADDR, LauncherError
from cpu import CPU
from memory_map import ADDRESS_SPACE


def main():
    if len(sys.argv) < 2:
        print("Uso: python3 dump_cpu_state.py <path_cartuccia> [output.bin]")
        sys.exit(1)
    cart_path = sys.argv[1]
    out_path = sys.argv[2] if len(sys.argv) > 2 else "cpu_bench_mem.bin"

    mode = determine_mode([sys.argv[0], cart_path])
    if mode[0] != 'direct':
        print(f"Errore: \"{cart_path}\" non e' una cartuccia diretta valida (.py/.asm)")
        sys.exit(1)
    _, resolved_path, kind = mode

    rom, state_vars = load_cart_rom(resolved_path, kind)

    cpu = CPU()
    for i, b in enumerate(rom):
        cpu.mem[CART_LOAD_ADDR + i] = b
    for name, (addr, init_val) in state_vars.items():
        cpu.write16(addr, init_val)

    assert len(cpu.mem) == ADDRESS_SPACE
    with open(out_path, "wb") as f:
        f.write(cpu.mem)

    print(f"Scritto {out_path}: {len(cpu.mem):,} byte")
    print(f"CART_LOAD_ADDR = 0x{CART_LOAD_ADDR:06X} ({CART_LOAD_ADDR}) - punto di partenza per run()")
    print(f"ROM: {len(rom)} byte, variabili di stato iniziali: {len(state_vars)}")


if __name__ == "__main__":
    main()
