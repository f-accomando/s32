"""
spritesheet_tool.py - carica uno spritesheet PNG (griglia di tile)
per S32.

A differenza dello strumento equivalente in v1 (limitato a 3 colori
per tile-set, formato 2bpp), qui a 8bpp abbiamo fino a 255 colori
VERI per palette - molto piu' margine, la quantizzazione serve solo
per immagini davvero ricche (foto, sfumature), non per la pixel art
tipica di sprite/tile.

FORMATO ATTESO: un PNG le cui dimensioni sono multipli esatti di
tile_size x tile_size (default 32x32, vedi TILE_SIZE_PX in
memory_map.py) - ogni cella della griglia e' un tile, numerati riga
per riga da sinistra a destra, partendo dall'alto (indice 0 in alto
a sinistra).
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from PIL import Image

from memory_map import TILE_SIZE_PX, COLORS_PER_PALETTE


class SpritesheetError(Exception):
    pass


def load_spritesheet(png_path, tile_size=None, max_colors=None, quantize=False):
    """Legge uno spritesheet PNG, ritorna un dict:
      'tiles':  lista di bytearray, uno per tile (tile_size*tile_size
                byte, indice colore diretto 0-(N-1), 0=trasparente)
      'palette': lista di tuple (r,g,b), indice colore 1 in poi
                 (indice 0 e' sempre trasparente, non in questa lista)
      'cols', 'rows': dimensioni della griglia in tile

    Se l'immagine ha piu' colori distinti di max_colors, solleva
    SpritesheetError (con la lista dei colori trovati) A MENO CHE
    quantize=True, che riduce automaticamente ai colori piu'
    rappresentativi (stesso approccio di png_tool.py in v1, utile
    per bozze rapide - per un risultato pulito conviene preparare
    l'immagine gia' entro il limite di colori)."""
    tile_size = tile_size or TILE_SIZE_PX
    max_colors = max_colors or (COLORS_PER_PALETTE - 1)  # -1: indice 0 riservato al trasparente

    img = Image.open(png_path).convert("RGBA")
    w, h = img.size
    if w % tile_size != 0 or h % tile_size != 0:
        raise SpritesheetError(
            f'Lo spritesheet e\' {w}x{h}px - le dimensioni devono essere '
            f'multiple di {tile_size} (ogni tile e\' {tile_size}x{tile_size}px).'
        )

    cols, rows = w // tile_size, h // tile_size
    px = img.load()

    if quantize:
        index_grid, palette = _quantize_image(img, w, h, max_colors)
    else:
        index_grid, palette = _index_image_exact(img, w, h, max_colors)

    tiles = []
    for ty in range(rows):
        for tx in range(cols):
            tile = bytearray(tile_size * tile_size)
            for ry in range(tile_size):
                for rx in range(tile_size):
                    tile[ry * tile_size + rx] = index_grid[ty * tile_size + ry][tx * tile_size + rx]
            tiles.append(tile)

    return {'tiles': tiles, 'palette': palette, 'cols': cols, 'rows': rows}


def _index_image_exact(img, w, h, max_colors):
    px = img.load()
    colors_seen = []
    grid = [[0] * w for _ in range(h)]
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a < 128:
                grid[y][x] = 0
                continue
            rgb = (r, g, b)
            if rgb not in colors_seen:
                colors_seen.append(rgb)
            grid[y][x] = colors_seen.index(rgb) + 1

    if len(colors_seen) > max_colors:
        raise SpritesheetError(
            f'Lo spritesheet ha {len(colors_seen)} colori distinti (oltre alla '
            f'trasparenza), il massimo e\' {max_colors}. Riduci i colori '
            f'nell\'editor, oppure richiama con quantize=True.'
        )
    return grid, colors_seen


def _quantize_image(img, w, h, max_colors):
    px = img.load()
    opaque_pixels = [px[x, y][:3] for y in range(h) for x in range(w) if px[x, y][3] >= 128]
    if not opaque_pixels:
        raise SpritesheetError('Lo spritesheet e\' completamente trasparente')

    side = 1
    while side * side < len(opaque_pixels):
        side += 1
    quant_src = Image.new("RGB", (side, side), (0, 0, 0))
    quant_src.putdata(opaque_pixels + [(0, 0, 0)] * (side * side - len(opaque_pixels)))
    quant = quant_src.quantize(colors=max_colors, method=Image.MEDIANCUT)
    palette_bytes = quant.getpalette()[:max_colors * 3]
    palette = [tuple(palette_bytes[i:i + 3]) for i in range(0, len(palette_bytes), 3)]

    def closest(rgb):
        best, best_d = 0, None
        for idx, c in enumerate(palette):
            d = sum((a - b) ** 2 for a, b in zip(rgb, c))
            if best_d is None or d < best_d:
                best, best_d = idx, d
        return best + 1

    grid = [[0] * w for _ in range(h)]
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a >= 128:
                grid[y][x] = closest((r, g, b))
    return grid, palette


def write_tiles_to_vram(vram, tile_graphics_offset, tile_bytes_size, start_index, tiles):
    """Scrive una lista di tile (da load_spritesheet) in VRAM a
    partire da start_index."""
    for i, tile in enumerate(tiles):
        base = tile_graphics_offset + (start_index + i) * tile_bytes_size
        vram[base:base + len(tile)] = tile


def write_palette_to_cgram(cgram, palette_index, palette, colors_per_palette=None):
    """Scrive una palette (lista di (r,g,b) 0-255) in CGRAM, convertendo
    da RGB888 a RGB555 (5 bit/canale, formato nativo CGRAM) - indice
    colore 1 in poi (indice 0 resta il trasparente, mai scritto)."""
    colors_per_palette = colors_per_palette or COLORS_PER_PALETTE
    for i, (r, g, b) in enumerate(palette):
        color_index = i + 1
        if color_index >= colors_per_palette:
            break
        r5, g5, b5 = r >> 3, g >> 3, b >> 3  # 8 bit -> 5 bit per canale
        raw = (r5 & 0x1f) | ((g5 & 0x1f) << 5) | ((b5 & 0x1f) << 10)
        offset = (palette_index * colors_per_palette + color_index) * 2
        cgram[offset] = raw & 0xff
        cgram[offset + 1] = (raw >> 8) & 0xff
