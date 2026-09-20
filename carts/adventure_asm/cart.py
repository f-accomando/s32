import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '_shared'))

from graphics import build_all_vram, build_all_cgram, build_title_vram, build_stages
from sound_bank import build_sound_bank


def build_vram(vram):
    build_all_vram(vram)     # tutti i tile (font+stage+giocatore) dallo spritesheet
    build_title_vram(vram)   # scritta della title screen nella tilemap


def build_cgram(cgram):
    build_all_cgram(cgram)   # palette giorno + notte, stesso spritesheet


# build_stages e build_sound_bank sono gia' importate direttamente -
# il launcher le cerca come funzioni di modulo
# (hasattr(module, 'build_stages')/'build_sound_bank')
