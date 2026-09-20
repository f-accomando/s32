"""
game.py - cartuccia BAREBONE_P2P, clone di carts/barebone/ con il
multiplayer locale (fino a 4 giocatori sulla stessa LAN/WiFi, vedi
s32/netplay.py e doc_networking.md per il design di rete).

Stessa convenzione single-file di barebone: UN SOLO file Python (piu'
lo spritesheet font_spritesheet.png) - niente cart.py/cart_info.py/
_shared.

Differenza rispetto a barebone: QUATTRO avatar invece di uno, ognuno
mosso dall'input del proprio slot:
  - giocatore 1 (locale, tastiera) -> input()            (PORT_INPUT)
  - giocatore 2 (rete)             -> peek(0x042005)      (PORT_INPUT_P2)
  - giocatore 3 (rete)             -> peek(0x042007)      (PORT_INPUT_P3)
  - giocatore 4 (rete)             -> peek(0x042009)      (PORT_INPUT_P4)

Questa cartuccia NON apre lei stessa le connessioni di rete - come il
resto della CPU S32, non sa nulla dell'esistenza della rete: legge
solo 4 byte di input da 4 indirizzi fissi. E' compito del chiamante
(vedi s32/netplay.py + l'integrazione nel launcher, prossimo step)
procurarsi l'input dei giocatori 2-4 via rete e scriverlo in quelle
celle PRIMA di ogni cpu.run() - esattamente come gia' fa per il
giocatore 1 con la tastiera. Separazione gia' vista altrove nel
motore: ppu.py non sa nulla di pygame, cpu.py non sa nulla di audio.

Per provarla SENZA rete (un solo processo, sviluppo/debug): vedi
test_barebone_p2p.py - lancia il ROM passando input_p2/p3/p4 a
cpu.run() direttamente, nessun socket coinvolto.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 's32'))

from memory_map import (
    TILE_GRAPHICS_VRAM_OFFSET, TILE_BYTES, TILE_SIZE_PX,
    TILEMAP_VRAM_OFFSET, TILEMAP_W, TILEMAP_ENTRY_BYTES, TILEMAP_BYTES,
    SCREEN_TILES_W, SCREEN_TILES_H,
)
from spritesheet_tool import load_spritesheet, write_tiles_to_vram, write_palette_to_cgram

TITLE = "Barebone P2P"

SOURCE_LANG = "consolelang"

# Quattro giocatori, un tile 32x32 ciascuno, nessuna animazione - stesso
# minimalismo di barebone/game.py, moltiplicato per 4. Posizioni di
# partenza distanziate cosi' i 4 avatar non si sovrappongono subito.
ROM_SOURCE = """
state p1x = 96
state p1y = 160
state p2x = 192
state p2y = 160
state p3x = 288
state p3y = 160
state p4x = 384
state p4y = 160

if (input() & 1) { p1y = p1y - 3 }
if (input() & 2) { p1y = p1y + 3 }
if (input() & 4) { p1x = p1x - 3 }
if (input() & 8) { p1x = p1x + 3 }

if (peek(0x042005) & 1) { p2y = p2y - 3 }
if (peek(0x042005) & 2) { p2y = p2y + 3 }
if (peek(0x042005) & 4) { p2x = p2x - 3 }
if (peek(0x042005) & 8) { p2x = p2x + 3 }

if (peek(0x042007) & 1) { p3y = p3y - 3 }
if (peek(0x042007) & 2) { p3y = p3y + 3 }
if (peek(0x042007) & 4) { p3x = p3x - 3 }
if (peek(0x042007) & 8) { p3x = p3x + 3 }

if (peek(0x042009) & 1) { p4y = p4y - 3 }
if (peek(0x042009) & 2) { p4y = p4y + 3 }
if (peek(0x042009) & 4) { p4x = p4x - 3 }
if (peek(0x042009) & 8) { p4x = p4x + 3 }

regx = p1x
regy = p1y
clamp_x(0, 448)
clamp_y(32, 288)
p1x = regx
p1y = regy

regx = p2x
regy = p2y
clamp_x(0, 448)
clamp_y(32, 288)
p2x = regx
p2y = regy

regx = p3x
regy = p3y
clamp_x(0, 448)
clamp_y(32, 288)
p3x = regx
p3y = regy

regx = p4x
regy = p4y
clamp_x(0, 448)
clamp_y(32, 288)
p4x = regx
p4y = regy

write_oam(0, p1x, p1y, 15, 0)
write_oam(1, p2x, p2y, 16, 0)
write_oam(2, p3x, p3y, 17, 0)
write_oam(3, p4x, p4y, 18, 0)

halt()
"""

# ---------------------------------------------------------------
# Grafica: stesso font_spritesheet.png di barebone (a-z indici 0-25,
# 0-9 indici 26-35) - un avatar per giocatore, lettere consecutive
# p,q,r,s cosi' si riconoscono a colpo d'occhio chi e' chi.
# ---------------------------------------------------------------
CHAR_TILE_INDEX = {c: i for i, c in enumerate("abcdefghijklmnopqrstuvwxyz0123456789")}
PLAYER_TILE_IDX = [
    CHAR_TILE_INDEX['p'],
    CHAR_TILE_INDEX['q'],
    CHAR_TILE_INDEX['r'],
    CHAR_TILE_INDEX['s'],
]

# BLANK_TILE_IDX: vedi barebone/game.py - un tile MAI caricato in VRAM
# (lo spritesheet ne ha solo 36, indici 0-35), quindi resta a zero di
# default = interamente trasparente, "spazio" senza un 37esimo tile.
BLANK_TILE_IDX = 36

_SHEET_PATH = os.path.join(os.path.dirname(__file__), 'font_spritesheet.png')
_sheet_cache = None


def _sheet():
    global _sheet_cache
    if _sheet_cache is None:
        _sheet_cache = load_spritesheet(_SHEET_PATH, tile_size=TILE_SIZE_PX)
    return _sheet_cache


def build_vram(vram):
    write_tiles_to_vram(vram, TILE_GRAPHICS_VRAM_OFFSET, TILE_BYTES, 0, _sheet()['tiles'])
    _write_title(vram)


def build_cgram(cgram):
    write_palette_to_cgram(cgram, palette_index=0, palette=_sheet()['palette'])


def _write_tilemap_cell(flat, tx, ty, tile_index, palette=0):
    offset = (ty * TILEMAP_W + tx) * TILEMAP_ENTRY_BYTES
    raw = (tile_index & 0x0fff) | ((palette & 0x07) << 12)
    flat[offset] = raw & 0xff
    flat[offset + 1] = (raw >> 8) & 0xff


def _build_title_tilemap():
    """'s32 barebone p2p' centrata sulla prima riga. Riempie di
    BLANK_TILE_IDX solo l'area DAVVERO visibile (15x10 tile, scroll
    fermo a 0,0 in questa demo) - vedi barebone/game.py per il perche'
    il resto della tilemap 128x128 non serve inizializzarlo."""
    flat = bytearray(TILEMAP_BYTES)
    for ty in range(SCREEN_TILES_H):
        for tx in range(SCREEN_TILES_W):
            _write_tilemap_cell(flat, tx, ty, BLANK_TILE_IDX)

    message = "barebone p2p"
    start_col = (SCREEN_TILES_W - len(message)) // 2
    for i, ch in enumerate(message):
        idx = CHAR_TILE_INDEX.get(ch, BLANK_TILE_IDX)
        _write_tilemap_cell(flat, start_col + i, 0, idx)
    return flat


def _write_title(vram):
    tilemap = _build_title_tilemap()
    vram[TILEMAP_VRAM_OFFSET:TILEMAP_VRAM_OFFSET + len(tilemap)] = tilemap
