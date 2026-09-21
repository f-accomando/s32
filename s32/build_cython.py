"""build_cython.py - compila cpu.py in un'estensione nativa con
Cython (issue #22: PyPy da' un guadagno reale ma richiede riscaldarsi
per minuti ad ogni avvio e rompe la build di pygame - vedi
doc_networking.md/README.md per i dettagli. Cython compila in
anticipo: nessun riscaldamento, nessuna modifica all'interprete usato
per pygame, che resta CPython normale.

cpu.py NON viene modificato per questo - cpu.pxd (accanto a questo
file) dice al compilatore quali tipi C usare per i registri, senza
toccare la logica. Il file .py resta valido ed eseguibile anche senza
mai lanciare questo script (fallback naturale: se l'estensione
compilata non esiste, Python usa semplicemente cpu.py cosi' com'e' -
nessun codice di fallback esplicito necessario, e' il comportamento
normale dell'import quando non trova un .so).

Uso:
    python3 build_cython.py

Produce un file tipo cpu.cpython-311-x86_64-linux-gnu.so (il nome
esatto dipende da piattaforma/versione Python) ACCANTO a cpu.py, in
questa stessa cartella - Python lo trova e lo usa al posto di cpu.py
automaticamente ad ogni `import cpu`/`from cpu import CPU`, senza
bisogno di cambiare una riga altrove nel progetto (stessa cartella,
stesso nome di modulo: le estensioni compilate hanno sempre la
precedenza sul sorgente .py nel meccanismo di import di Python).

ATTENZIONE ALLA TRAPPOLA PIU' COMUNE: se modifichi cpu.py DOPO aver
compilato, il file .so compilato resta quello VECCHIO finche' non
rilanci questo script - Python continuera' silenziosamente a usare
la versione compilata, ignorando le modifiche al sorgente. In caso
di comportamento "impossibile" durante lo sviluppo di cpu.py, la
prima cosa da controllare e' se esiste un .so compilato in questa
cartella (`ls s32/cpu*.so`) - se si', ricompilare o cancellarlo.

SU RASPBERRY PI 1 (ARMv6, RAM limitata): il -O2 di default puo'
far si' che il processo gcc che compila cpu.c termini senza produrre
il .so e senza un errore chiaro nel log (osservato senza traccia di
OOM kill in dmesg - probabilmente solo troppo oneroso per la CPU/RAM
disponibili su questo modello). Se succede, ricompilare con
ottimizzazione piu' bassa risolve, a costo di poco (il guadagno di
Cython viene soprattutto dalla tipizzazione statica dei registri in
cpu.pxd, non da -O2):

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
    ext = Extension(name="cpu", sources=["cpu.py"])
    setup(
        ext_modules=cythonize(
            [ext],
            compiler_directives={
                "language_level": "3",
                "boundscheck": False,   # niente controllo limiti su mem[i] -
                                         # gia' garantito dai mask (& 0xffffff)
                                         # applicati prima di ogni accesso
                "wraparound": False,    # nessun indice negativo usato in cpu.py
                "infer_types": True,    # tipizza automaticamente le variabili
                                         # locali dove il compilatore puo'
                                         # dedurlo con certezza (es. risultati
                                         # intermedi in _add/_sub) - senza
                                         # dover annotare cpu.py a mano
            },
            build_dir="build_cython_tmp",  # file .c intermedi - non il .so
                                            # finale, che resta accanto a
                                            # cpu.py per essere trovato
                                            # dall'import
            force=True,
        ),
        script_args=["build_ext", "--inplace"],
    )
    print()
    print("Compilazione completata - cerca un file cpu.*.so in questa cartella.")
    print("Verifica: python3 -c \"import cpu; print(cpu.__file__)\" deve mostrare .so, non .py")


if __name__ == "__main__":
    sys.argv = [sys.argv[0]]  # setup() rilegge sys.argv se script_args
                               # non basta su alcune versioni - azzerato
                               # per sicurezza, non ci servono altri argomenti
    main()
