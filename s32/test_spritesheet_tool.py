from spritesheet_tool import (
    load_spritesheet, SpritesheetError,
    write_tiles_to_vram, write_palette_to_cgram,
)
from memory_map import TILE_GRAPHICS_VRAM_OFFSET, TILE_BYTES, VRAM_SIZE, CGRAM_SIZE

fails = 0

def check(label, got, expected):
    global fails
    status = "OK  " if got == expected else "FAIL"
    if got != expected:
        fails += 1
    print(f"{status} {label}: atteso {expected!r}, ottenuto {got!r}")

# ---------------------------------------------------------------
# Test 1: griglia 2x2 valida - slicing, ordine, conteggio colori
# ---------------------------------------------------------------
r1 = load_spritesheet("test_assets/sheet_2x2.png", tile_size=32)
check("griglia: colonne", r1['cols'], 2)
check("griglia: righe", r1['rows'], 2)
check("griglia: numero tile totali", len(r1['tiles']), 4)
check("ogni tile ha 32*32 byte", len(r1['tiles'][0]), 1024)
check("4 colori distinti trovati (uno per tile)", len(r1['palette']), 4)

# il tile 0 (alto-sx) deve essere rosso -> indice colore corrisponde
# al primo colore incontrato
idx_center = 16 * 32 + 16  # pixel centrale del tile 0
check("tile 0 (alto-sx): pixel centrale opaco", r1['tiles'][0][idx_center] != 0, True)
idx_corner = 0  # angolo (0,0) del tile, fuori dal quadrato colorato -> trasparente
check("tile 0: angolo trasparente (indice 0)", r1['tiles'][0][idx_corner], 0)

# ---------------------------------------------------------------
# Test 2: dimensioni non multiple del tile -> errore chiaro
# ---------------------------------------------------------------
try:
    load_spritesheet("test_assets/sheet_dimensioni_sbagliate.png", tile_size=32)
    check("dimensioni sbagliate: solleva errore", "nessun errore", "SpritesheetError")
except SpritesheetError:
    check("dimensioni sbagliate: solleva errore", "SpritesheetError", "SpritesheetError")

# ---------------------------------------------------------------
# Test 3: troppi colori senza quantize -> errore chiaro
# ---------------------------------------------------------------
try:
    load_spritesheet("test_assets/sheet_troppi_colori.png", tile_size=32)
    check("troppi colori: solleva errore", "nessun errore", "SpritesheetError")
except SpritesheetError:
    check("troppi colori: solleva errore", "SpritesheetError", "SpritesheetError")

# ---------------------------------------------------------------
# Test 4: troppi colori CON quantize=True -> funziona
# ---------------------------------------------------------------
r4 = load_spritesheet("test_assets/sheet_troppi_colori.png", tile_size=32, max_colors=8, quantize=True)
check("quantize: riduce entro il limite richiesto", len(r4['palette']) <= 8, True)
check("quantize: produce comunque 1 tile", len(r4['tiles']), 1)

# ---------------------------------------------------------------
# Test 5: scrittura in VRAM - i byte finiscono nel punto giusto
# ---------------------------------------------------------------
vram = bytearray(VRAM_SIZE)
tile_bytes_32 = 32 * 32  # dimensione esplicita per questo test (8bpp:
                          # 1 byte/pixel), indipendente dalla costante
                          # globale TILE_BYTES che riflette ancora la
                          # vecchia dimensione 8x8 finche' non cambiamo
                          # TILE_SIZE_PX nel prossimo passo
write_tiles_to_vram(vram, TILE_GRAPHICS_VRAM_OFFSET, tile_bytes_32, start_index=5, tiles=r1['tiles'])
base5 = TILE_GRAPHICS_VRAM_OFFSET + 5 * tile_bytes_32
check("scrittura VRAM: tile 0 finisce all'indice 5 richiesto",
      vram[base5:base5 + tile_bytes_32] == r1['tiles'][0], True)
base6 = TILE_GRAPHICS_VRAM_OFFSET + 6 * tile_bytes_32
check("scrittura VRAM: tile 1 finisce all'indice 6 (successivo)",
      vram[base6:base6 + tile_bytes_32] == r1['tiles'][1], True)

# ---------------------------------------------------------------
# Test 6: scrittura in CGRAM - RGB888 -> RGB555, indice 0 mai toccato
# ---------------------------------------------------------------
cgram = bytearray(CGRAM_SIZE)
write_palette_to_cgram(cgram, palette_index=3, palette=[(255, 0, 0), (0, 255, 0)])
# indice colore 0 (trasparente) non deve mai essere scritto
check("CGRAM: indice 0 (trasparente) resta a zero", cgram[3*256*2] == 0 and cgram[3*256*2+1] == 0, True)
# indice colore 1 (primo della palette, rosso) -> RGB555 (31,0,0)
off1 = (3*256 + 1) * 2
raw1 = cgram[off1] | (cgram[off1+1] << 8)
check("CGRAM: rosso pieno -> R5=31", raw1 & 0x1f, 31)
check("CGRAM: rosso pieno -> G5=0", (raw1 >> 5) & 0x1f, 0)

print()
if fails == 0:
    print("Tutti i test passati.")
else:
    print(f"{fails} test falliti.")
