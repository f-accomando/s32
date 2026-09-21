"""bench_cpu_micro.py - micro-benchmark ISOLATO della sola CPU
(nessun rendering, nessuna cartuccia vera), per misurare il guadagno
"al meglio" dell'estensione Cython (build_cython.py, issue #22) senza
il rumore del resto del frame (render_frame() in launcher.py
--benchmark pesa 10-100 volte piu' della CPU su un gioco reale, vedi
README.md - qui isoliamo la CPU per vedere il suo limite teorico).

Il programma caricato e' un loop stretto che esegue 5 istruzioni ALU
diverse (ADD/SUB/AND/OR/XOR, quelle il cui operando e' un registro
tipizzato in cpu.pxd) piu' un JMP indietro, ripetuto milioni di volte
- cosi' il tempo speso e' quasi tutto dispatch+ALU, non un caso raro.

run() con max_steps solleva RuntimeError quando il limite viene
raggiunto SENZA un HALT (vedi cpu.py: e' pensato per rilevare loop
infiniti nei giochi veri) - qui lo sfruttiamo di proposito come modo
semplice per eseguire esattamente N passi ed e' l'errore ATTESO, non
un fallimento del benchmark: catturato sotto.

Uso:
    python3 bench_cpu_micro.py [passi_totali]
"""
import sys
import time

from cpu import CPU

def u16(v):
    return [v & 0xff, (v >> 8) & 0xff]

def u24(v):
    return [v & 0xff, (v >> 8) & 0xff, (v >> 16) & 0xff]

def load(cpu, addr, bytes_list):
    for i, b in enumerate(bytes_list):
        cpu.mem[addr + i] = b

START = 0x1000
LOOP = START + 3  # dopo LDA #0 (1 opcode + 2 byte immediato)

def build_program():
    prog = [0x10, *u16(0)]                  # LDA #0
    prog += [0x30, *u16(1)]                 # ADD #1
    prog += [0x31, *u16(1)]                 # SUB #1
    prog += [0x32, *u16(0xffff)]            # AND #0xffff
    prog += [0x33, *u16(0)]                 # OR  #0
    prog += [0x34, *u16(0)]                 # XOR #0
    prog += [0x60, *u24(LOOP)]              # JMP LOOP
    return prog

INSTRUCTIONS_PER_ITER = 6  # ADD/SUB/AND/OR/XOR + JMP

def main():
    total_steps = int(sys.argv[1]) if len(sys.argv) > 1 else 6_000_000
    # arrotonda a un multiplo esatto del corpo del loop, solo per
    # numeri puliti nel report finale (non cambia il risultato)
    total_steps -= total_steps % INSTRUCTIONS_PER_ITER

    cpu = CPU()
    load(cpu, START, build_program())

    print(f"backend CPU: {sys.modules['cpu'].__file__}")
    print(f"passi totali: {total_steps:,} ({total_steps // INSTRUCTIONS_PER_ITER:,} iterazioni del loop)")

    t0 = time.perf_counter()
    try:
        cpu.run(START, max_steps=total_steps)
    except RuntimeError:
        pass  # atteso: e' cosi' che fermiamo il loop infinito apposta, vedi docstring
    elapsed = time.perf_counter() - t0

    ns_per_instr = elapsed / total_steps * 1e9
    mips = total_steps / elapsed / 1e6

    print(f"tempo totale:        {elapsed:.3f} s")
    print(f"per istruzione:      {ns_per_instr:.1f} ns")
    print(f"throughput:          {mips:.2f} milioni di istruzioni/s")

if __name__ == "__main__":
    main()
