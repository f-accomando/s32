from ppu import decode_tile, decode_color, read_tilemap_entry, render_frame, get_pixel
from memory_map import (
    VRAM_SIZE, CGRAM_SIZE, OAM_SIZE, TILE_GRAPHICS_VRAM_OFFSET, TILE_BYTES,
    TILEMAP_VRAM_OFFSET, TILEMAP_W, OAM_SLOT_BYTES, TILE_SIZE_PX, SCREEN_W_PX,
)

fails = 0
T = TILE_SIZE_PX  # scorciatoia - i test seguono qualunque dimensione
                   # sia impostata in memory_map.py, non un valore fisso

def check(label, got, expected):
    global fails
    status = "OK  " if got == expected else "FAIL"
    if got != expected:
        fails += 1
    print(f"{status} {label}: atteso {expected!r}, ottenuto {got!r}")

def new_vram():
    return bytearray(VRAM_SIZE)

def new_cgram():
    return bytearray(CGRAM_SIZE)

def new_oam():
    return bytearray(OAM_SIZE)

def write_tile(vram, tile_index, pixel_rows):
    """pixel_rows: lista di T liste da T interi (indici colore 0-255)."""
    base = TILE_GRAPHICS_VRAM_OFFSET + tile_index * TILE_BYTES
    for row in range(T):
        for col in range(T):
            vram[base + row * T + col] = pixel_rows[row][col]

def solid_tile(color):
    return [[color] * T for _ in range(T)]

def write_tilemap(vram, tx, ty, tile_index, palette=0):
    offset = TILEMAP_VRAM_OFFSET + (ty * TILEMAP_W + tx) * 2
    raw = (tile_index & 0x0fff) | ((palette & 0x07) << 12)
    vram[offset] = raw & 0xff
    vram[offset + 1] = (raw >> 8) & 0xff

def write_color(cgram, palette, color_index, r5, g5, b5):
    offset = (palette * 256 + color_index) * 2
    raw = (r5 & 0x1f) | ((g5 & 0x1f) << 5) | ((b5 & 0x1f) << 10)
    cgram[offset] = raw & 0xff
    cgram[offset + 1] = (raw >> 8) & 0xff

def write_sprite(oam, slot, x, y, tile_index, attr):
    base = slot * OAM_SLOT_BYTES
    oam[base] = x & 0xff; oam[base+1] = (x >> 8) & 0xff
    oam[base+2] = y & 0xff; oam[base+3] = (y >> 8) & 0xff
    oam[base+4] = tile_index & 0xff; oam[base+5] = (tile_index >> 8) & 0xff
    oam[base+6] = attr & 0xff; oam[base+7] = (attr >> 8) & 0xff

# ---------------------------------------------------------------
# Test 1: decode_tile - 8bpp, un byte per pixel diretto
# ---------------------------------------------------------------
vram1 = new_vram()
pattern = [[(r * T + c) % 256 for c in range(T)] for r in range(T)]
write_tile(vram1, 5, pattern)
grid = decode_tile(vram1, 5)
check("decode_tile: angolo (0,0)", grid[0][0], 0)
check("decode_tile: valore centrale (3,4)", grid[3][4], (3 * T + 4) % 256)

# ---------------------------------------------------------------
# Test 2: decode_color - RGB555 -> RGB 0-255
# ---------------------------------------------------------------
cgram2 = new_cgram()
write_color(cgram2, 0, 1, 31, 0, 0)
write_color(cgram2, 0, 2, 0, 31, 0)
write_color(cgram2, 0, 3, 0, 0, 31)
write_color(cgram2, 1, 1, 15, 15, 15)
check("decode_color: rosso pieno", decode_color(cgram2, 0, 1), (255, 0, 0))
check("decode_color: verde pieno", decode_color(cgram2, 0, 2), (0, 255, 0))
check("decode_color: blu pieno", decode_color(cgram2, 0, 3), (0, 0, 255))
r, g, b = decode_color(cgram2, 1, 1)
check("decode_color: palette 1 e' INDIPENDENTE dalla palette 0", (r, g, b) != (255, 0, 0), True)

# ---------------------------------------------------------------
# Test 3: read_tilemap_entry - tile index + palette impacchettati
# ---------------------------------------------------------------
vram3 = new_vram()
write_tilemap(vram3, 5, 7, tile_index=300, palette=4)
tile_idx, pal = read_tilemap_entry(vram3, 5, 7)
check("tilemap: tile_index estratto correttamente", tile_idx, 300)
check("tilemap: palette estratta correttamente", pal, 4)
write_tilemap(vram3, 0, 0, tile_index=9, palette=1)
tile_idx2, pal2 = read_tilemap_entry(vram3, 128, 128)  # wraparound
check("tilemap: wraparound orizzontale/verticale", (tile_idx2, pal2), (9, 1))

# ---------------------------------------------------------------
# Test 4: render_frame - sfondo, trasparenza, palette per-tile
# ---------------------------------------------------------------
vram4 = new_vram()
cgram4 = new_cgram()
write_tile(vram4, 1, solid_tile(5))
half = [[0 if c < T // 2 else 5 for c in range(T)] for _ in range(T)]
write_tile(vram4, 2, half)
write_tilemap(vram4, 0, 0, tile_index=1, palette=0)
write_tilemap(vram4, 1, 0, tile_index=2, palette=2)
write_color(cgram4, 0, 5, 31, 0, 0)   # palette 0, indice 5 = rosso
write_color(cgram4, 2, 5, 0, 31, 0)   # palette 2, STESSO indice 5 = verde

pixels4 = render_frame(vram4, bytearray(OAM_SIZE), cgram4)
check("sfondo: tile1 (palette0) e' rosso", get_pixel(pixels4, 0, 0), (255, 0, 0))
check("sfondo: tile2 lato opaco (palette2) e' VERDE (palette per-tile funziona)",
      get_pixel(pixels4, T + 3 * T // 4, 0), (0, 255, 0))
check("sfondo: tile2 lato trasparente resta nero (sfondo default)",
      get_pixel(pixels4, T + T // 4, 0), (0, 0, 0))

# ---------------------------------------------------------------
# Test 5: scroll in ENTRAMBE le direzioni
# ---------------------------------------------------------------
vram5 = new_vram()
cgram5 = new_cgram()
write_tile(vram5, 1, solid_tile(9))
write_tilemap(vram5, 3, 2, tile_index=1, palette=0)  # tile a (3*T, 2*T) nel mondo
write_color(cgram5, 0, 9, 20, 20, 20)
wx, wy = 3 * T, 2 * T

p_noscroll = render_frame(vram5, bytearray(OAM_SIZE), cgram5, scroll_x=0, scroll_y=0)
check("scroll=0: tile visibile alla sua posizione naturale", get_pixel(p_noscroll, wx, wy) != (0, 0, 0), True)

p_scrollx = render_frame(vram5, bytearray(OAM_SIZE), cgram5, scroll_x=wx, scroll_y=0)
check("scroll_x: lo stesso tile ora appare a x=0 (scroll orizzontale funziona)",
      get_pixel(p_scrollx, 0, wy) != (0, 0, 0), True)

p_scrolly = render_frame(vram5, bytearray(OAM_SIZE), cgram5, scroll_x=0, scroll_y=wy)
check("scroll_y: lo stesso tile ora appare a y=0 (scroll verticale funziona)",
      get_pixel(p_scrolly, wx, 0) != (0, 0, 0), True)

# ---------------------------------------------------------------
# Test 6: sprite semplice (1 tile = TxT), con trasparenza
# ---------------------------------------------------------------
vram6 = new_vram()
cgram6 = new_cgram()
oam6 = new_oam()
write_tile(vram6, 10, [[0 if (r + c) % 2 else 7 for c in range(T)] for r in range(T)])
write_color(cgram6, 3, 7, 31, 31, 0)  # giallo, palette 3
write_sprite(oam6, 0, x=50, y=60, tile_index=10, attr=(3 << 2))  # size_code=0, palette 3

pixels6 = render_frame(vram6, oam6, cgram6)
check("sprite: pixel opaco (0,0) e' giallo", get_pixel(pixels6, 50, 60), (255, 255, 0))
check("sprite: pixel trasparente (0,1) resta sfondo", get_pixel(pixels6, 51, 60), (0, 0, 0))

# ---------------------------------------------------------------
# Test 7: sprite grande, size_code=1 -> griglia 2x2 di tile
# (dimensione reale: (2*T)x(2*T) - con T=32, e' 64x64)
# ---------------------------------------------------------------
vram7 = new_vram()
cgram7 = new_cgram()
oam7 = new_oam()
for idx, color in [(20, 1), (21, 2), (22, 3), (23, 4)]:
    write_tile(vram7, idx, solid_tile(color))
write_color(cgram7, 0, 1, 31, 0, 0)
write_color(cgram7, 0, 2, 0, 31, 0)
write_color(cgram7, 0, 3, 0, 0, 31)
write_color(cgram7, 0, 4, 31, 31, 31)
write_sprite(oam7, 0, x=100, y=100, tile_index=20, attr=1)  # size_code=1 -> 2x2

pixels7 = render_frame(vram7, oam7, cgram7)
check("sprite grande (2x2 tile): alto-sx", get_pixel(pixels7, 100, 100), (255, 0, 0))
check("sprite grande (2x2 tile): alto-dx", get_pixel(pixels7, 100 + T, 100), (0, 255, 0))
check("sprite grande (2x2 tile): basso-sx", get_pixel(pixels7, 100, 100 + T), (0, 0, 255))
check("sprite grande (2x2 tile): basso-dx", get_pixel(pixels7, 100 + T, 100 + T), (255, 255, 255))
check("sprite grande: pixel appena fuori torna sfondo",
      get_pixel(pixels7, 100 + 2 * T + 4, 100 + 2 * T + 4), (0, 0, 0))

# ---------------------------------------------------------------
# Test 7b: sprite ENORME, size_code=2 -> griglia 4x4 di tile
# (con T=32, dimensione reale 128x128)
# ---------------------------------------------------------------
vram7b = new_vram()
cgram7b = new_cgram()
oam7b = new_oam()
for k in range(16):
    color = (k % 4) + 1
    write_tile(vram7b, 40 + k, solid_tile(color))
write_color(cgram7b, 0, 1, 31, 0, 0)
write_color(cgram7b, 0, 2, 0, 31, 0)
write_color(cgram7b, 0, 3, 0, 0, 31)
write_color(cgram7b, 0, 4, 31, 31, 31)
write_sprite(oam7b, 0, x=200, y=150, tile_index=40, attr=2)  # size_code=2 -> 4x4

pixels7b = render_frame(vram7b, oam7b, cgram7b)
check("sprite enorme: angolo alto-sx (tile 40, colore1)", get_pixel(pixels7b, 200, 150), (255, 0, 0))
check("sprite enorme: angolo alto-dx (tile 43, colore4)", get_pixel(pixels7b, 200 + 3 * T, 150), (255, 255, 255))
check("sprite enorme: angolo basso-sx (tile 52, colore1)", get_pixel(pixels7b, 200, 150 + 3 * T), (255, 0, 0))
check("sprite enorme: angolo basso-dx (tile 55, colore4)", get_pixel(pixels7b, 200 + 3 * T, 150 + 3 * T), (255, 255, 255))
last_in_x = 200 + 4 * T - 1
last_in_y = 150 + 4 * T - 1
check("sprite enorme: ultimo pixel dentro e' ancora sprite", get_pixel(pixels7b, last_in_x, last_in_y) != (0, 0, 0), True)
check("sprite enorme: pixel appena fuori torna sfondo", get_pixel(pixels7b, last_in_x + 1, last_in_y + 1), (0, 0, 0))

# ---------------------------------------------------------------
# Test 8: sprite nascosto (Y molto grande)
# ---------------------------------------------------------------
vram8 = new_vram()
cgram8 = new_cgram()
oam8 = new_oam()
write_tile(vram8, 1, solid_tile(1))
write_color(cgram8, 0, 1, 31, 0, 0)
write_sprite(oam8, 0, x=50, y=0xffff, tile_index=1, attr=0)
pixels8 = render_frame(vram8, oam8, cgram8)
check("sprite nascosto (Y molto grande) non disegnato", get_pixel(pixels8, 50, 0), (0, 0, 0))

# ---------------------------------------------------------------
# Test 9: render_background() + draw_sprites() usate SEPARATAMENTE
# devono dare lo STESSO risultato di render_frame() - questa e' la
# base della cache usata da launcher.py (sfondo cachato, sprite
# ridisegnati ogni frame sopra una copia)
# ---------------------------------------------------------------
from ppu import render_background, draw_sprites, render_background_window

vram9 = new_vram()
cgram9 = new_cgram()
oam9 = new_oam()
write_tile(vram9, 1, solid_tile(1))
write_tilemap(vram9, 2, 2, tile_index=1, palette=0)
write_color(cgram9, 0, 1, 10, 20, 30)
write_tile(vram9, 5, [[0 if (r+c) % 2 else 2 for c in range(T)] for r in range(T)])
write_color(cgram9, 0, 2, 31, 0, 31)
write_sprite(oam9, 0, x=60, y=70, tile_index=5, attr=0)

combined = render_frame(vram9, oam9, cgram9)

bg_only = render_background(vram9, cgram9)
manual = bytearray(bg_only)  # copia, come farebbe la cache nel launcher
draw_sprites(manual, oam9, cgram9, vram9)

check("render_background()+draw_sprites() == render_frame() (sfondo)",
      get_pixel(manual, 2*T, 2*T), get_pixel(combined, 2*T, 2*T))
check("render_background()+draw_sprites() == render_frame() (sprite)",
      get_pixel(manual, 60, 70), get_pixel(combined, 60, 70))
check("render_background() da SOLA non disegna lo sprite",
      get_pixel(bg_only, 60, 70), (0, 0, 0))

# ---------------------------------------------------------------
# Test 10: iter_visible_sprite_tiles() - la funzione condivisa che
# analizza la OAM, usata sia da draw_sprites() che dal rendering
# incrementale nel launcher
# ---------------------------------------------------------------
from ppu import iter_visible_sprite_tiles

oam10 = new_oam()
n_slots = OAM_SIZE // OAM_SLOT_BYTES
for slot in range(n_slots):
    write_sprite(oam10, slot, x=0, y=0xffff, tile_index=0, attr=0)  # nascosto di default
write_sprite(oam10, 0, x=10, y=20, tile_index=5, attr=0)   # 1x1, palette 0
write_sprite(oam10, 1, x=100, y=200, tile_index=8, attr=(3 << 2) | 1)  # 2x2, palette 3
write_sprite(oam10, 2, x=0, y=0xffff, tile_index=1, attr=0)  # nascosto

results = list(iter_visible_sprite_tiles(oam10))
check("iter_visible_sprite_tiles: sprite nascosto ESCLUSO", len(results), 5)  # 1 (slot0) + 4 (slot1, 2x2) = 5
check("iter_visible_sprite_tiles: slot0 (1x1)", (5, 0, 10, 20) in results, True)
check("iter_visible_sprite_tiles: slot1 angolo alto-sx", (8, 3, 100, 200) in results, True)
check("iter_visible_sprite_tiles: slot1 angolo basso-dx (griglia 2x2)",
      (8 + 1*2 + 1, 3, 100 + T, 200 + T) in results, True)

# ---------------------------------------------------------------
# Test 11: iter_visible_sprite_tiles() FILTRA gli sprite fuori
# schermo, non solo quelli esplicitamente nascosti - bug reale
# trovato dall'utente su Raspberry Pi: un nemico lontano dalla
# telecamera lasciava una "scia" visibile, perche' veniva comunque
# disegnato ben oltre i 480x320 dello schermo (il ripristino dello
# sfondo li' non aveva nulla da ripristinare, dato che bg_surface e'
# grande esattamente 480x320)
# ---------------------------------------------------------------
oam11 = new_oam()
for slot in range(OAM_SIZE // OAM_SLOT_BYTES):
    write_sprite(oam11, slot, x=0, y=0xffff, tile_index=0, attr=0)

# nemico "lontano dalla telecamera" - scenario reale: mondo=100,
# scroll=448 (massimo) -> schermo = 100-448 = -348, che come intero
# senza segno diventa un numero enorme (65188)
write_sprite(oam11, 0, x=200, y=(100 - 448) & 0xffff, tile_index=16, attr=0)
# nemico ben oltre il bordo destro/basso (scroll=0, mondo=672)
write_sprite(oam11, 1, x=900, y=672, tile_index=16, attr=0)
# nemico regolare, dentro lo schermo - deve restare
write_sprite(oam11, 2, x=200, y=150, tile_index=16, attr=0)
# nemico ESATTAMENTE al bordo (parzialmente visibile) - deve restare
write_sprite(oam11, 3, x=470, y=150, tile_index=16, attr=0)

results11 = list(iter_visible_sprite_tiles(oam11))
check("iter_visible_sprite_tiles: sprite con scroll estremo (fuori schermo) escluso",
      any(x == 200 and y > 60000 for _, _, x, y in results11), False)
check("iter_visible_sprite_tiles: sprite ben oltre il bordo destro escluso",
      any(x == 900 for _, _, x, y in results11), False)
check("iter_visible_sprite_tiles: sprite normale dentro lo schermo incluso",
      (16, 0, 200, 150) in results11, True)
check("iter_visible_sprite_tiles: sprite al bordo (parzialmente visibile) incluso",
      (16, 0, 470, 150) in results11, True)
check("iter_visible_sprite_tiles: solo i 2 sprite validi prodotti",
      len(results11), 2)

# ---------------------------------------------------------------
# Test 11: render_background_window() - una finestra Y deve dare
# ESATTAMENTE lo stesso contenuto della corrispondente fetta di
# render_background() - questa e' la base dello scroll incrementale
# (sposta il gia' disegnato, ricalcola solo la striscia nuova)
# ---------------------------------------------------------------
vram11 = new_vram()
cgram11 = new_cgram()
for idx, color in [(1, 1), (2, 2), (3, 3)]:
    write_tile(vram11, idx, solid_tile(color))
write_color(cgram11, 0, 1, 31, 0, 0)
write_color(cgram11, 0, 2, 0, 31, 0)
write_color(cgram11, 0, 3, 0, 0, 31)
for ty in range(15):
    for tx in range(20):
        write_tilemap(vram11, tx, ty, tile_index=1 + (tx + ty) % 3, palette=0)

full = render_background(vram11, cgram11, scroll_x=5, scroll_y=50)

# finestra che parte a meta' schermo, alta 40px - deve corrispondere
# esattamente alle righe [160,200) del rendering completo
window = render_background_window(vram11, cgram11, scroll_x=5, scroll_y=50,
                                   window_y_start=160, window_height=40)
check("render_background_window: dimensione buffer corretta", len(window), SCREEN_W_PX * 40 * 3)

match = True
for y in range(40):
    for x in range(0, SCREEN_W_PX, 37):  # campiono, non tutti i pixel, per velocita'
        full_off = ((160 + y) * SCREEN_W_PX + x) * 3
        win_off = (y * SCREEN_W_PX + x) * 3
        if full[full_off:full_off+3] != window[win_off:win_off+3]:
            match = False
            break
    if not match:
        break
check("render_background_window: contenuto identico alla fetta corrispondente", match, True)

# finestra minuscola (2px, il caso reale dello scroll fluido)
strip = render_background_window(vram11, cgram11, scroll_x=5, scroll_y=52,
                                  window_y_start=0, window_height=2)
check("render_background_window: finestra di 2px ha la dimensione giusta", len(strip), SCREEN_W_PX * 2 * 3)
# deve corrispondere alle righe [52,54) del mondo, cioe' righe [2,4)
# rispetto a scroll_y=50 usato sopra in 'full'... verifichiamo diversamente:
# la striscia a scroll_y=52,window_start=0 deve combaciare con la finestra
# a scroll_y=50,window_start=2 (stesso punto assoluto nel mondo)
window_equiv = render_background_window(vram11, cgram11, scroll_x=5, scroll_y=50,
                                         window_y_start=2, window_height=2)
check("render_background_window: scroll_y+offset equivalenti danno lo stesso risultato",
      bytes(strip) == bytes(window_equiv), True)

# ---------------------------------------------------------------
# Test 12: blob_cache persistente - il tile viene DECODIFICATO una
# volta sola se il chiamante passa una cache condivisa tra piu'
# chiamate, invece di ricostruirlo ad ogni chiamata - questo e' il
# fix del costo dominante trovato sulla Raspberry Pi 1 durante lo
# scroll (57ms/frame senza, vedi launcher.py)
# ---------------------------------------------------------------
import ppu as ppu_module

vram12 = new_vram()
cgram12 = new_cgram()
write_tile(vram12, 1, solid_tile(1))
write_color(cgram12, 0, 1, 20, 20, 20)
for tx in range(15):
    write_tilemap(vram12, tx, 0, tile_index=1, palette=0)
    write_tilemap(vram12, tx, 1, tile_index=1, palette=0)

original_decode_tile = ppu_module.decode_tile
call_count = [0]

def counting_decode_tile(vram, tile_index):
    call_count[0] += 1
    return original_decode_tile(vram, tile_index)

ppu_module.decode_tile = counting_decode_tile
try:
    # SENZA cache condivisa: 5 chiamate separate, ognuna ricostruisce
    call_count[0] = 0
    for _ in range(5):
        render_background_window(vram12, cgram12, 0, 0, 0, 2)
    calls_without_cache = call_count[0]

    # CON cache condivisa tra le chiamate: decodificato una volta sola
    call_count[0] = 0
    shared = {}
    for _ in range(5):
        render_background_window(vram12, cgram12, 0, 0, 0, 2, blob_cache=shared)
    calls_with_cache = call_count[0]
finally:
    ppu_module.decode_tile = original_decode_tile

check("blob_cache: senza cache condivisa, decode_tile chiamata ogni volta",
      calls_without_cache > 0, True)
check("blob_cache: CON cache condivisa, decode_tile chiamata MOLTE MENO volte",
      calls_with_cache < calls_without_cache, True)
check("blob_cache: con cache condivisa, decode_tile chiamata esattamente 1 volta (5 chiamate, 1 tile distinto)",
      calls_with_cache, 1)

print()
if fails == 0:
    print("Tutti i test passati.")
else:
    print(f"{fails} test falliti.")
