"""build_cython.py - compila cpu.py E ppu.py in estensioni native con
Cython (issue #22: PyPy da' un guadagno reale ma richiede riscaldarsi
per minuti ad ogni avvio e rompe la build di pygame - vedi
doc_networking.md/README.md per i dettagli. Cython compila in
anticipo: nessun riscaldamento, nessuna modifica all'interprete usato
per pygame, che resta CPython normale.

ppu.py compilato per lo stesso motivo di cpu.py sotto, non perche'
"tanto vale" - un profilo vero (--profile, sia su x86 che su
Raspberry Pi 1) mostra che il rendering (ppu.py) pesa il ~64% del
tempo per frame contro il ~2% della CPU: e' il bersaglio con la leva
maggiore, non un'aggiunta simmetrica per completezza.

cpu.py/ppu.py NON vengono modificati per questo - cpu.pxd/ppu.pxd
(accanto a questo file) dicono al compilatore quali tipi C usare
(registri per cpu.py, indici/contatori per ppu.py), senza toccare la
logica. I file .py restano validi ed eseguibili anche senza mai
lanciare questo script (fallback naturale: se l'estensione compilata
non esiste, Python usa semplicemente il .py cosi' com'e' - nessun
codice di fallback esplicito necessario, e' il comportamento normale
dell'import quando non trova un .so).

Uso:
    python3 build_cython.py

Produce due file tipo cpu.cpython-311-x86_64-linux-gnu.so e
ppu.cpython-311-x86_64-linux-gnu.so (il nome esatto dipende da
piattaforma/versione Python) ACCANTO ai rispettivi .py, in questa
stessa cartella - Python li trova e li usa al posto dei .py
automaticamente a ogni `import cpu`/`import ppu`, senza bisogno di
cambiare una riga altrove nel progetto (stessa cartella, stesso nome
di modulo: le estensioni compilate hanno sempre la precedenza sul
sorgente .py nel meccanismo di import di Python).

ATTENZIONE ALLA TRAPPOLA PIU' COMUNE: se modifichi cpu.py o ppu.py
DOPO aver compilato, il .so compilato resta quello VECCHIO finche'
non rilanci questo script - Python continuera' silenziosamente a
usare la versione compilata, ignorando le modifiche al sorgente. In
caso di comportamento "impossibile" durante lo sviluppo, la prima
cosa da controllare e' se esiste un .so compilato in questa cartella
(`ls s32/cpu*.so s32/ppu*.so`) - se si', ricompilare o cancellarlo.

SU RASPBERRY PI 1 (ARMv6, RAM limitata): il -O2 di default puo'
far si' che il processo gcc che compila cpu.c/ppu.c termini senza
produrre il .so e senza un errore chiaro nel log (osservato senza
traccia di OOM kill in dmesg - probabilmente solo troppo oneroso per
la CPU/RAM disponibili su questo modello). Se succede, ricompilare
con ottimizzazione piu' bassa risolve, a costo di poco (il guadagno
di Cython viene soprattutto dalla tipizzazione statica in
cpu.pxd/ppu.pxd, non da -O2):

    CFLAGS="-O0" python3 build_cython.py

L'estensione compilata e' SPECIFICA della piattaforma (architettura
CPU + versione Python) che l'ha generata - un .so compilato su questo
Pi 1 (ARMv6) non funziona su un'altra macchina, e viceversa. Per
questo non va mai committato nel repository (vedi .gitignore) - ogni
macchina che vuole il guadagno di velocita' deve compilarselo da se'
lanciando questo script una volta."""
import os
import sys

from setuptools import Extension, setup
from Cython.Build import cythonize


def main():
    os.chdir(os.path.dirname(os.path.abspath(__file__)))  # sempre relativo
                                                            # a questo file,
                                                            # non alla
                                                            # cartella da cui
                                                            # viene lanciato
    ext_modules = [
        Extension(name="cpu", sources=["cpu.py"]),
        Extension(name="ppu", sources=["ppu.py"]),
    ]
    setup(
        ext_modules=cythonize(
            ext_modules,
            compiler_directives={
                "language_level": "3",
                "boundscheck": False,   # niente controllo limiti su mem[i] -
                                         # gia' garantito dai mask (& 0xffffff)
                                         # applicati prima di ogni accesso in
                                         # cpu.py; in ppu.py sono solo oggetti
                                         # Python normali (bytearray/list), non
                                         # buffer/memoryview C - la direttiva
                                         # non ha alcun effetto li'
                "wraparound": False,    # nessun indice negativo usato in cpu.py/ppu.py
                "infer_types": True,    # tipizza automaticamente le variabili
                                         # locali dove il compilatore puo'
                                         # dedurlo con certezza (es. risultati
                                         # intermedi in _add/_sub, o gli indici
                                         # riga/colonna in ppu.py) - senza
                                         # dover annotare i .py a mano
            },
            build_dir="build_cython_tmp",  # file .c intermedi - non i .so
                                            # finali, che restano accanto ai
                                            # rispettivi .py per essere trovati
                                            # dall'import
            force=True,
        ),
        script_args=["build_ext", "--inplace"],
    )
    print()
    print("Compilazione completata - cerca i file cpu.*.so e ppu.*.so in questa cartella.")
    print("Verifica: python3 -c \"import cpu, ppu; print(cpu.__file__, ppu.__file__)\" deve mostrare .so per entrambi, non .py")


if __name__ == "__main__":
    sys.argv = [sys.argv[0]]  # setup() rilegge sys.argv se script_args
                               # non basta su alcune versioni - azzerato
                               # per sicurezza, non ci servono altri argomenti
    main()
