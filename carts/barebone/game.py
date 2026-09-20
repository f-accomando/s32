"""
game.py - cartuccia BAREBONE, convenzione single-file.

UN SOLO file Python (piu' lo spritesheet font_spritesheet.png) - niente
cart.py, niente cart_info.py, niente cartella _shared: tutto cio' che
serve a questa cartuccia vive qui o nella sua stessa cartella (vedi
carts/README.md, sezione "Convenzione single-file"). Pensata come
punto di partenza minimo per nuove cartucce: un giocatore mosso con le
frecce, un titolo scritto con lo stesso spritesheet font (a-z, 0-9)
usato per il giocatore stesso.

Perche' non serve un graphics.py separato: le uniche risorse grafiche
di questa cartuccia sono un caricamento diretto dello spritesheet
(spritesheet_tool, gia' generico nel motore) e una tilemap statica di
poche righe - abbastanza piccolo da restare qui invece che in un
modulo riusabile a parte.
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

TITLE = "Barebone"

SOURCE_LANG = "consolelang"

# Giocatore mosso con le frecce, un tile 32x32, nessuna animazione -
# il minimo indispensabile per vedere qualcosa muoversi a schermo.
ROM_SOURCE = """
state playerX = 224
state playerY = 160

if (input() & 1) {
    playerY = playerY - 3
}
if (input() & 2) {
    playerY = playerY + 3
}
if (input() & 4) {
    playerX = playerX - 3
}
if (input() & 8) {
    playerX = playerX + 3
}

regx = playerX
regy = playerY
clamp_x(0, 448)
clamp_y(32, 288)
playerX = regx
playerY = regy

write_oam(0, playerX, playerY, 15, 0)

halt()
"""

# ---------------------------------------------------------------
# Grafica: font_spritesheet.png, griglia 9x4 (36 tile 32x32):
# a-z agli indici 0-25, 0-9 agli indici 26-35 (riga per riga).
# ---------------------------------------------------------------
CHAR_TILE_INDEX = {c: i for i, c in enumerate("abcdefghijklmnopqrstuvwxyz0123456789")}
PLAYER_TILE_IDX = CHAR_TILE_INDEX['p']  # riusa la lettera 'p' come avatar

# BLANK_TILE_IDX punta a un tile MAI caricato in VRAM (lo spritesheet
# ne ha solo 36, indici 0-35) - resta quindi a zero di default, e un
# tile tutto a indice-colore 0 e' interamente trasparente. Funziona da
# "spazio" senza bisogno di un trentasettesimo tile dedicato nel PNG.
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
    """'s32 barebone' centrata sulla prima riga. Riempie di
    BLANK_TILE_IDX solo l'area DAVVERO visibile (15x10 tile, scroll
    fermo a 0,0 in questa demo) - il resto della tilemap 128x128 resta
    a zero ma non e' mai disegnato, quindi non serve inizializzarlo."""
    flat = bytearray(TILEMAP_BYTES)
    for ty in range(SCREEN_TILES_H):
        for tx in range(SCREEN_TILES_W):
            _write_tilemap_cell(flat, tx, ty, BLANK_TILE_IDX)

    message = "s32 barebone"
    start_col = (SCREEN_TILES_W - len(message)) // 2
    for i, ch in enumerate(message):
        idx = CHAR_TILE_INDEX.get(ch, BLANK_TILE_IDX)
        _write_tilemap_cell(flat, start_col + i, 0, idx)
    return flat


def _write_title(vram):
    tilemap = _build_title_tilemap()
    vram[TILEMAP_VRAM_OFFSET:TILEMAP_VRAM_OFFSET + len(tilemap)] = tilemap
