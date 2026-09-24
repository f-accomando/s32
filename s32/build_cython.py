"""build_cython.py - compila cpu.py, ppu.py E fb_convert.py in
estensioni native con Cython (issue #22: PyPy da' un guadagno reale
ma richiede riscaldarsi per minuti ad ogni avvio e rompe la build di
pygame - vedi doc_networking.md/README.md per i dettagli. Cython
compila in anticipo: nessun riscaldamento, nessuna modifica
all'interprete usato per pygame, che resta CPython normale.

ppu.py compilato per lo stesso motivo di cpu.py sotto, non perche'
"tanto vale" - un profilo vero (--profile, sia su x86 che su
Raspberry Pi 1) mostra che il rendering (ppu.py) pesa il ~64% del
tempo per frame contro il ~2% della CPU: e' il bersaglio con la leva
maggiore, non un'aggiunta simmetrica per completezza.

fb_convert.py (conversione RGB888->RGB565 per --fbdev-renderer, vedi
launcher.py) compilato per lo stesso motivo: MISURATO a ~4 secondi/
frame in Python puro su Raspberry Pi 1 vero (150.000+ pixel/frame),
completamente inutilizzabile senza compilarlo.

cpu.py/ppu.py/fb_convert.py NON vengono modificati per questo -
cpu.pxd/ppu.pxd/fb_convert.pxd (accanto a questo file) dicono al
compilatore quali tipi C usare (registri per cpu.py, indici/contatori
per ppu.py, un memoryview tipizzato per fb_convert.py), senza toccare
la logica. I file .py restano validi ed eseguibili anche senza mai
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
far si' che gcc, compilando il file .c generato da Cython, non
finisca mai (osservato senza traccia di OOM kill in dmesg -
probabilmente solo troppo oneroso per la CPU/RAM disponibili su
questo modello, non davvero "bloccato": lasciato girare abbastanza a
lungo probabilmente finirebbe, ma su questo hardware "abbastanza a
lungo" non e' praticabile). NON e' un problema di cpu.py in
particolare - e' una questione di QUANTO E' GRANDE il file .c
generato: sia cpu.c che ppu.c superano le 13.000 righe (decine di
opcode diversi in cpu.py, tutta la logica di compositing/tile/sprite
in ppu.py), e ci vanno a sbattere ENTRAMBI. fb_convert.c invece resta
piccolo (una sola funzione, un loop) e compila senza problemi anche
a -O2.

CFLAGS=-O1 (non -O0) PER CPU.PY/PPU.PY - ESPERIMENTO IN CORSO:
misurato su Raspberry Pi 1 vero, in condizioni completamente diverse
tra loro (renderer dirty-rects E --fbdev-renderer, cartuccia asm E
ConsoleLang, schermata ferma E scroll E combattimento), cpu.run()
costava SEMPRE ~52-57 microsecondi/istruzione - contro i ~4
microsecondi/istruzione di un benchmark precedente sullo stesso
progetto (--benchmark-frames, CPython, anch'esso su Pi 1 vero). Un
fattore ~12-14x, troppo uniforme per essere l'hardware (temperatura
normale, throttled=0x0, niente swap, niente build free-threading -
tutti esclusi) o la fase di gioco (identico a riposo, in scroll e in
combattimento) - il sospetto forte e' che sia semplicemente il prezzo
di -O0, MAI potuto verificare finora perche' l'unica alternativa
provata (nessun CFLAGS, cioe' il default del compilatore, tipicamente
-O2) e' quello che blocca gcc su questo hardware (vedi sopra). -O1 e'
un compromesso mai testato prima: recupera spesso gran parte del
guadagno di -O2 (elimina il boilerplate di conteggio riferimenti/
controlli di tipo che Cython genera, che -O0 esegue alla lettera)
restando molto piu' leggero da compilare - potrebbe evitare il blocco
mantenendo un vantaggio reale a runtime. Se anche questo blocca gcc su
un dato hardware, si torna a -O0 passando CFLAGS a mano (vedi sotto) -
nessun danno, e' solo un tentativo.

TRAPPOLE GIA' PRESE (lezioni imparate sul Pi 1 vero):
1) Prima questo script compilava tutti e tre in un'UNICA chiamata,
   quindi un CFLAGS="-O0" messo per far compilare cpu.py si applicava
   ANCHE a fb_convert.py - piccolo e senza bisogno di -O0, reso
   inutilmente lento a RUNTIME (misurato: fb_convert.py passava da
   ~0.3ms a 129ms/frame per la stessa conversione, un fattore 400x).
2) Poi si e' provato a forzare -O0 SOLO per cpu.py, lasciando ppu.py
   all'ottimizzazione normale insieme a fb_convert.py - errore
   opposto: ppu.c e' grande quanto cpu.c (stesso ordine di
   grandezza), quindi ci si e' ripresentato lo STESSO blocco in
   compilazione, solo spostato su un file diverso (segnalato
   dall'utente: la build si fermava sempre sui warning di ppu.c,
   mai prodotti i .so). La divisione corretta non e' "cpu.py da solo"
   ma "i file .c GRANDI" (cpu.py + ppu.py) contro "i file .c piccoli"
   (fb_convert.py) - una questione di dimensione del sorgente
   generato, non di quale modulo e' piu' importante a runtime.

Se -O1 dovesse bloccarsi su qualche hardware (o se in futuro ANCHE
fb_convert.py dovesse farlo), si puo' comunque forzare CFLAGS a mano -
un CFLAGS impostato esplicitamente dall'utente ha sempre la
precedenza su quanto lo script sceglie da solo, per tutti e tre i
moduli:

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


COMPILER_DIRECTIVES = {
    "language_level": "3",
    "boundscheck": False,   # niente controllo limiti su mem[i] -
                             # gia' garantito dai mask (& 0xffffff)
                             # applicati prima di ogni accesso in
                             # cpu.py; in ppu.py sono solo oggetti
                             # Python normali (bytearray/list), non
                             # buffer/memoryview C - la direttiva
                             # non ha alcun effetto li'; in
                             # fb_convert.py invece SI applica
                             # davvero (frame_buf e' un memoryview
                             # tipizzato, vedi fb_convert.pxd) - il
                             # loop resta sempre dentro len(frame_buf)
                             # per costruzione (range(0, n, 3))
    "wraparound": False,    # nessun indice negativo usato in cpu.py/ppu.py/fb_convert.py
    "infer_types": True,    # tipizza automaticamente le variabili
                             # locali dove il compilatore puo'
                             # dedurlo con certezza (es. risultati
                             # intermedi in _add/_sub, gli indici
                             # riga/colonna in ppu.py, o r/g/b/p in
                             # fb_convert.py) - senza dover annotare
                             # i .py a mano
}


def _build(ext_modules, forced_cflags, user_cflags):
    """Compila ext_modules con CFLAGS controllato: se l'utente ne ha
    impostato uno esplicitamente (user_cflags, letto UNA VOLTA in
    main() prima di ogni chiamata - non ri-letto qui, altrimenti la
    prima _build() che lo forza lo "sporcherebbe" per quelle dopo)
    quello vince sempre; altrimenti si usa forced_cflags (puo' essere
    None per lasciare l'ottimizzazione di default del compilatore)."""
    prev = os.environ.get("CFLAGS")
    chosen = user_cflags if user_cflags is not None else forced_cflags
    if chosen is None:
        os.environ.pop("CFLAGS", None)
    else:
        os.environ["CFLAGS"] = chosen
    try:
        setup(
            ext_modules=cythonize(
                ext_modules,
                compiler_directives=COMPILER_DIRECTIVES,
                build_dir="build_cython_tmp",  # file .c intermedi - non i .so
                                                # finali, che restano accanto ai
                                                # rispettivi .py per essere trovati
                                                # dall'import
                force=True,
            ),
            script_args=["build_ext", "--inplace"],
        )
    finally:
        if prev is None:
            os.environ.pop("CFLAGS", None)
        else:
            os.environ["CFLAGS"] = prev


def main():
    os.chdir(os.path.dirname(os.path.abspath(__file__)))  # sempre relativo
                                                            # a questo file,
                                                            # non alla
                                                            # cartella da cui
                                                            # viene lanciato
    user_cflags = os.environ.get("CFLAGS")  # se impostato esplicitamente,
                                              # vince sempre su tutto (vedi
                                              # _build) - letto una volta sola
                                              # qui, PRIMA che _build() lo
                                              # tocchi internamente

    print("[1/2] Compilazione cpu.py + ppu.py (CFLAGS=-O1 forzato: compromesso "
          "tra velocita' a runtime e rischio di bloccare gcc su hardware debole "
          "come Raspberry Pi 1 - se questo passo si blocca, ricompila con "
          "CFLAGS=\"-O0\" python3 build_cython.py, vedi il docstring in cima a "
          "questo file)")
    _build([Extension(name="cpu", sources=["cpu.py"]),
            Extension(name="ppu", sources=["ppu.py"])],
           forced_cflags="-O1", user_cflags=user_cflags)

    print("[2/2] Compilazione fb_convert.py (ottimizzazione normale - file "
          "piccolo, compila senza problemi anche a -O2, e MISURATO che -O0 lo "
          "rende inutilmente lento a runtime senza bisogno reale di evitarlo)")
    _build([Extension(name="fb_convert", sources=["fb_convert.py"])],
           forced_cflags=None, user_cflags=user_cflags)

    print()
    print("Compilazione completata - cerca i file cpu.*.so, ppu.*.so e fb_convert.*.so in questa cartella.")
    print("Verifica: python3 -c \"import cpu, ppu, fb_convert; print(cpu.__file__, ppu.__file__, fb_convert.__file__)\" deve mostrare .so per tutti e tre, non .py")


if __name__ == "__main__":
    sys.argv = [sys.argv[0]]  # setup() rilegge sys.argv se script_args
                               # non basta su alcune versioni - azzerato
                               # per sicurezza, non ci servono altri argomenti
    main()
