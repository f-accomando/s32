"""
graphics.py - risorse grafiche condivise dalla demo.

Spritesheet: adventure_spritesheet.png, griglia 4x5 (20 tile, 32x32).

Indici tile:
  0=spazio  1=P  2=R    3=E
  4=S       5=J  6=T    7=O
  8=A       9=pavimento  10=muro  11=giocatore
  12=cuore  13=scale  14=slash1  15=slash2
  16=nemico  17=pietra  18=grata  19=nemico_morte
  20-23=boss (griglia 2x2, 64x64 - indici CONSECUTIVI, il PPU
         li dispone come 20=alto-sx 21=alto-dx 22=basso-sx 23=basso-dx)
  24=fuoco (proiettile boss)  25=barra piena  26=barra vuota

Stage disponibili:
  1 = giorno CON grata (gate chiusa, nemici vivi)
  2 = notte (con scale di risalita in cima)
  3 = giorno SENZA grata (gate aperta, nemici morti)
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 's32'))

from memory_map import (
    TILE_GRAPHICS_VRAM_OFFSET, TILE_BYTES, TILE_SIZE_PX,
    TILEMAP_VRAM_OFFSET, TILEMAP_W, TILEMAP_ENTRY_BYTES, SCREEN_TILES_W,
    SCREEN_TILES_H, TILEMAP_BYTES,
)
from spritesheet_tool import load_spritesheet, write_tiles_to_vram, write_palette_to_cgram

_SHEET_PATH = os.path.join(os.path.dirname(__file__), 'adventure_spritesheet.png')
_sheet_cache = None


def _sheet():
    global _sheet_cache
    if _sheet_cache is None:
        _sheet_cache = load_spritesheet(_SHEET_PATH, tile_size=TILE_SIZE_PX)
    return _sheet_cache


# ---------------------------------------------------------------
# Indici tile
# ---------------------------------------------------------------
FONT_TILE_INDEX = {' ': 0, 'P': 1, 'R': 2, 'E': 3, 'S': 4,
                    'J': 5, 'T': 6, 'O': 7, 'A': 8,
                    'G': 28, 'M': 29, 'V': 30}  # aggiunte per GAME OVER
STAGE_FLOOR_IDX  = 9
STAGE_WALL_IDX   = 10
PLAYER_TILE_IDX  = 11
HEART_TILE_IDX   = 12
STAIRS_TILE_IDX  = 13
SLASH1_TILE_IDX  = 14   # frame 1 di attacco (luminoso)
SLASH2_TILE_IDX  = 15   # frame 2 di attacco (sbiadisce)
ENEMY_TILE_IDX   = 16   # nemico vivo
STONE_TILE_IDX   = 17   # pietra proiettile
GATE_TILE_IDX    = 18   # grata chiusa (al posto delle scale)
ENEMY_DEAD_IDX   = 19   # animazione morte nemico
BOSS_TILE_IDX    = 20   # primo dei 4 tile del boss (20,21,22,23)
FIRE_TILE_IDX    = 24   # proiettile di fuoco del boss
BAR_FULL_IDX     = 25   # segmento pieno barra vita boss
BAR_EMPTY_IDX    = 26   # segmento vuoto barra vita boss
SKULL_TILE_IDX   = 27   # teschio: sostituisce il giocatore al game over

PALETTE_DAY   = 0
PALETTE_NIGHT = 1

# Posizione scale/grata (colonna centrale, vicino al fondo)
STAIRS_TX      = 7
STAIRS_TY_DOWN = 22   # vicino al fondo (stanza 1)
STAIRS_TY_UP   = 1    # vicino alla cima (stanza 2)
ROOM_TILES_H   = 24   # altezza stanza in tile (768px)


def build_all_vram(vram):
    """Carica TUTTI i tile dallo spritesheet in VRAM."""
    write_tiles_to_vram(vram, TILE_GRAPHICS_VRAM_OFFSET, TILE_BYTES, 0, _sheet()['tiles'])


def build_all_cgram(cgram):
    """Palette 0 (giorno) = colori esatti dallo spritesheet.
    Palette 1 (notte)  = pavimento/muro scuri-freddi, tutto il resto
    copiato dalla palette giorno (nemici, slash, pietra, grata
    restano identici - sono elementi funzionali, non ambientali)."""
    write_palette_to_cgram(cgram, palette_index=PALETTE_DAY, palette=_sheet()['palette'])
    _build_night_cgram(cgram)


def _build_night_cgram(cgram):
    sheet = _sheet()
    day_palette = sheet['palette']

    # Prima: copia TUTTA la palette giorno come base della notte
    # (garantisce che nemici, slash, pietra, grata siano visibili)
    for color_index, rgb in enumerate(day_palette):
        _write_color(cgram, PALETTE_NIGHT, color_index + 1, rgb)

    # Poi: sovrascrive solo pavimento e muro con colori notte
    floor_indices = sorted(set(sheet['tiles'][STAGE_FLOOR_IDX]) - {0})
    wall_indices  = sorted(set(sheet['tiles'][STAGE_WALL_IDX])  - {0})
    night_floor = [(38, 42, 80), (48, 52, 94)]
    night_wall  = [(26, 28, 56), (44, 46, 78)]
    for i, ci in enumerate(floor_indices):
        _write_color(cgram, PALETTE_NIGHT, ci, night_floor[min(i, 1)])
    for i, ci in enumerate(wall_indices):
        _write_color(cgram, PALETTE_NIGHT, ci, night_wall[min(i, 1)])


def _write_color(cgram, palette_index, color_index, rgb):
    from memory_map import COLORS_PER_PALETTE
    r, g, b = rgb
    raw = ((r >> 3) & 0x1f) | (((g >> 3) & 0x1f) << 5) | (((b >> 3) & 0x1f) << 10)
    off = (palette_index * COLORS_PER_PALETTE + color_index) * 2
    cgram[off]     = raw & 0xff
    cgram[off + 1] = (raw >> 8) & 0xff


def _write_tilemap_cell(flat, tx, ty, tile_index, palette=0):
    offset = (ty * TILEMAP_W + tx) * TILEMAP_ENTRY_BYTES
    raw = (tile_index & 0x0fff) | ((palette & 0x07) << 12)
    flat[offset]     = raw & 0xff
    flat[offset + 1] = (raw >> 8) & 0xff


def build_title_tilemap():
    """Tilemap della title screen ('PRESS J START' centrata) come
    oggetto standalone - stesso schema di _make_room(), cosi' puo'
    essere registrata come stage 0 in build_stages() e RICARICATA a
    runtime con select_stage(0). Serve per il game over: dopo aver
    giocato, la tilemap della title screen e' stata sovrascritta da
    tempo dalle stanze vere - senza questo, non c'e' modo di
    tornarci se non i dati scritti una volta sola all'avvio."""
    flat = bytearray(TILEMAP_BYTES)
    message = "PRESS J START"
    start_col = (SCREEN_TILES_W - len(message)) // 2
    row = SCREEN_TILES_H // 2
    for i, ch in enumerate(message):
        _write_tilemap_cell(flat, start_col + i, row, FONT_TILE_INDEX.get(ch, 0), PALETTE_DAY)
    return flat


def build_title_vram(vram):
    """Scrive 'PRESS J START' centrata nella tilemap - usata SOLO
    per l'inizializzazione host-side iniziale (vedi cart.py). A
    runtime, la stessa tilemap si ricarica con select_stage(0)."""
    tilemap = build_title_tilemap()
    off = TILEMAP_VRAM_OFFSET
    vram[off:off + TILEMAP_BYTES] = tilemap


def _make_room(palette, stairs_down=False, stairs_up=False, gate=False):
    """Costruisce una tilemap di stanza: bordo muro, interno pavimento.
    stairs_down: aggiunge scale/grata in fondo.
    stairs_up: aggiunge scale in cima.
    gate: se stairs_down, mette la GRATA invece delle scale (stage 1).
    """
    flat = bytearray(TILEMAP_BYTES)
    w, h = SCREEN_TILES_W, ROOM_TILES_H
    for ty in range(h):
        for tx in range(w):
            is_border = tx == 0 or tx == w-1 or ty == 0 or ty == h-1
            _write_tilemap_cell(flat, tx, ty,
                                STAGE_WALL_IDX if is_border else STAGE_FLOOR_IDX,
                                palette)
    if stairs_up:
        _write_tilemap_cell(flat, STAIRS_TX, STAIRS_TY_UP, STAIRS_TILE_IDX, palette)
    if stairs_down:
        tile = GATE_TILE_IDX if gate else STAIRS_TILE_IDX
        _write_tilemap_cell(flat, STAIRS_TX, STAIRS_TY_DOWN, tile, palette)
    return flat


def build_stages():
    """
    Stage 0 = title screen ('PRESS J START') - ricaricabile a
    runtime con select_stage(0), usata dal game over per tornare al
    titolo senza dover riavviare il processo.
    Stage 1 = giorno, grata CHIUSA (gate=True).  Nemici presenti.
    Stage 2 = notte, scale di ritorno in cima.
    Stage 3 = giorno, grata APERTA (gate=False). Nemici morti.
    """
    return {
        0: build_title_tilemap(),
        1: _make_room(PALETTE_DAY,   stairs_down=True, gate=True),
        2: _make_room(PALETTE_NIGHT, stairs_up=True),
        3: _make_room(PALETTE_DAY,   stairs_down=True, gate=False),
    }
