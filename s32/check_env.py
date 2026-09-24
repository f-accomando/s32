"""check_env.py - verifica rapida delle dipendenze prima di far
girare la console (utile su una macchina nuova/reinstallata, es. un
Raspberry Pi appena flashato) invece di scoprire un pezzo mancante
alla volta a ogni ModuleNotFoundError.

Distingue essenziali (senza questi il gioco non parte: pygame-ce,
Pillow) da opzionali (solo per build_cython.py o per la suite di
test: Cython, setuptools, pytest, un compilatore C).

Uso:
    python3 check_env.py
"""
import os
os.environ.setdefault('PYGAME_HIDE_SUPPORT_PROMPT', '1')  # pygame
                                                            # stampa un
                                                            # banner
                                                            # all'import,
                                                            # rumore
                                                            # inutile
                                                            # qui
import importlib
import shutil
import sys


def check_cmd(name, cmd):
    path = shutil.which(cmd)
    print(f"{'OK  ' if path else 'MANCA'} {name}: {path or 'non trovato nel PATH'}")


def check_module(name, import_name=None):
    import_name = import_name or name
    try:
        mod = importlib.import_module(import_name)
        ver = getattr(mod, '__version__', None) or getattr(mod, 'ver', None) or '?'
        print(f"OK   {name}: versione {ver} ({mod.__file__})")
        return mod
    except ImportError as e:
        print(f"MANCA {name}: {e}")
        return None


def main():
    print(f"python3: {sys.version.split()[0]} ({sys.executable})")
    check_cmd("pip3", "pip3")
    check_cmd("gcc (per build_cython.py)", "gcc")
    check_cmd("arm-linux-gnueabihf-gcc (per build_cython.py, ARM)", "arm-linux-gnueabihf-gcc")

    print()
    print("--- essenziali per giocare ---")
    pg = check_module("pygame")
    if pg:
        is_ce = hasattr(pg, 'IS_CE')
        print(f"     {'pygame-ce (consigliato)' if is_ce else 'pygame mainline (differenze note, vedi README)'}")
    check_module("Pillow", "PIL")

    print()
    print("--- opzionali (build Cython / test) ---")
    check_module("Cython")
    check_module("setuptools")
    check_module("pytest")


if __name__ == "__main__":
    main()
