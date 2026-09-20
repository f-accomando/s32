"""
carts_registry.py - scoperta delle cartucce disponibili per il
mini-OS di avvio (os_menu.py).

CONVENZIONE per una cartuccia valida (una sottocartella di carts/):
  - deve contenere ALMENO uno tra:
      game.py    - entry point Python (import diretto, come main.py
                   faceva in v1: il modulo espone ROM_SOURCE, testo
                   assembly compilato al volo dal launcher)
      game.asm   - sorgente assembly puro, assemblato al volo
  - puo' opzionalmente contenere:
      cart_info.py  - se presente e definisce TITLE, quello e' il
                      titolo mostrato nel menu; altrimenti si usa il
                      nome della cartella (con underscore -> spazi,
                      prima lettera maiuscola)

CARTUCCIA SINGLE-FILE (nuova convenzione, vedi carts/barebone/): se
non c'e' cart_info.py, TITLE puo' essere definito direttamente dentro
game.py - stesso discorso per build_vram/build_cgram/build_oam/
build_stages al posto di cart.py (vedi launcher._load_cart_graphics).
Una cartuccia del genere e' fatta di UN SOLO file Python (piu' gli
eventuali spritesheet .png) - niente cart.py/cart_info.py separati.

Questo modulo NON usa pygame e NON esegue nulla - solo scoperta e
metadati, per restare interamente testabile senza un display.
"""

import os
import importlib.util


class Cart:
    def __init__(self, name, path, title, has_py, has_asm):
        self.name = name          # nome della cartella (identificatore stabile)
        self.path = path          # percorso assoluto della cartella
        self.title = title        # titolo da mostrare nel menu
        self.has_py = has_py
        self.has_asm = has_asm

    def entry_py(self):
        return os.path.join(self.path, 'game.py') if self.has_py else None

    def entry_asm(self):
        return os.path.join(self.path, 'game.asm') if self.has_asm else None

    def __repr__(self):
        kinds = []
        if self.has_py: kinds.append('py')
        if self.has_asm: kinds.append('asm')
        return f'Cart({self.name!r}, title={self.title!r}, kinds={kinds})'


def _default_title(folder_name):
    return folder_name.replace('_', ' ').replace('-', ' ').strip().title()


def _read_title_from_module(module_path):
    """Legge la variabile TITLE da un modulo Python (cart_info.py, o
    game.py per una cartuccia single-file) - import mirato, non tocca
    sys.modules."""
    spec = importlib.util.spec_from_file_location('cart_title_tmp', module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return getattr(module, 'TITLE', None)


def discover_carts(carts_dir):
    """Scansiona carts_dir e ritorna una lista di Cart validi,
    ordinata per titolo. Cartelle senza game.py NE' game.asm vengono
    ignorate silenziosamente (es. carts/README.md non e' una
    cartuccia)."""
    if not os.path.isdir(carts_dir):
        return []

    result = []
    for entry in sorted(os.listdir(carts_dir)):
        full_path = os.path.join(carts_dir, entry)
        if not os.path.isdir(full_path):
            continue

        has_py = os.path.isfile(os.path.join(full_path, 'game.py'))
        has_asm = os.path.isfile(os.path.join(full_path, 'game.asm'))
        if not has_py and not has_asm:
            continue

        title = _default_title(entry)
        cart_info_path = os.path.join(full_path, 'cart_info.py')
        game_py_path = os.path.join(full_path, 'game.py')
        if os.path.isfile(cart_info_path):
            custom_title = _read_title_from_module(cart_info_path)
            if custom_title:
                title = custom_title
        elif has_py:
            # cartuccia single-file (niente cart_info.py separato):
            # TITLE, se definito, vive direttamente in game.py
            custom_title = _read_title_from_module(game_py_path)
            if custom_title:
                title = custom_title

        result.append(Cart(entry, full_path, title, has_py, has_asm))

    result.sort(key=lambda c: c.title.lower())
    return result
