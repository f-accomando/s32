"""
ppu.py - PPU di S32.

Differenze principali rispetto alla PPU della v1:
- 8bpp: un pixel = UN byte = l'indice colore diretto (0-255). Niente
  piu' codifica a piani di bit (2bpp in v1 impacchettava 4 pixel
  logici nei bit di 2 byte per riga) - qui e' semplicemente
  vram[tile_base + row*8 + col].
- CGRAM vera: i colori si leggono da memoria (formato RGB555, 2
  byte/colore, come il vero SNES), non da una lista Python fissa.
- Palette PER TILE nello sfondo (3 bit nella tilemap, 8 palette
  disponibili) - in v1 il cambio palette era globale per tutto lo
  schermo (BG_PALETTE).
- Scroll in ENTRAMBE le direzioni (la tilemap e' 128x128 tile, molto
  piu' grande dello schermo in entrambi gli assi - in v1 la larghezza
  tilemap coincideva con quella schermo, zero scroll orizzontale
  possibile).

Come in v1: la PPU non sa nulla di CPU/registri - riceve solo array
di byte (vram, oam, cgram) e numeri (scroll), non ha mai un
riferimento alla CPU stessa.
"""

from memory_map import (
    TILE_SIZE_PX, TILE_BYTES, TILEMAP_W, TILEMAP_H, TILEMAP_ENTRY_BYTES,
    TILEMAP_VRAM_OFFSET, TILE_GRAPHICS_VRAM_OFFSET,
    SCREEN_W_PX, SCREEN_H_PX, SCREEN_TILES_W, SCREEN_TILES_H,
    COLORS_PER_PALETTE, CGRAM_COLOR_BYTES,
    OAM_SLOT_BYTES,
)


def decode_tile(vram, tile_index):
    """Ritorna una griglia 8x8 di indici colore (0-255) per il tile
    all'indice dato. A 8bpp un pixel e' un byte intero: nessuna
    decodifica bit a bit necessaria, solo un offset."""
    base = TILE_GRAPHICS_VRAM_OFFSET + tile_index * TILE_BYTES
    grid = []
    for row in range(TILE_SIZE_PX):
        row_base = base + row * TILE_SIZE_PX
        grid.append(list(vram[row_base:row_base + TILE_SIZE_PX]))
    return grid


def decode_color(cgram, palette_index, color_index):
    """Legge un colore da CGRAM in formato RGB555 (2 byte, 5 bit per
    canale) e lo scala a 0-255 per canale. color_index=0 e' sempre
    trasparente (mai letto qui - vedi render_frame)."""
    offset = (palette_index * COLORS_PER_PALETTE + color_index) * CGRAM_COLOR_BYTES
    raw = cgram[offset] | (cgram[offset + 1] << 8)
    r5 = raw & 0x1f
    g5 = (raw >> 5) & 0x1f
    b5 = (raw >> 10) & 0x1f
    # scala 5 bit (0-31) a 8 bit (0-255)
    scale = lambda v: (v * 255) // 31
    return (scale(r5), scale(g5), scale(b5))


def read_tilemap_entry(vram, tx, ty):
    """Legge una cella della tilemap: ritorna (tile_index, palette).
    tx,ty in TILE (non pixel), con wraparound se fuori [0,TILEMAP_W/H)
    - il mondo e' "infinito" per avvolgimento, non ha bordi rigidi
    a livello di PPU (i limiti di gioco li impone il programma)."""
    tx %= TILEMAP_W
    ty %= TILEMAP_H
    offset = TILEMAP_VRAM_OFFSET + (ty * TILEMAP_W + tx) * TILEMAP_ENTRY_BYTES
    raw = vram[offset] | (vram[offset + 1] << 8)
    tile_index = raw & 0x0fff        # 12 bit
    palette = (raw >> 12) & 0x07     # 3 bit
    return tile_index, palette


def get_pixel(buf, x, y):
    """Legge un pixel (r,g,b) dal buffer piatto ritornato da
    render_frame() - comodo per i test, non usato nel percorso caldo."""
    off = (y * SCREEN_W_PX + x) * 3
    return (buf[off], buf[off + 1], buf[off + 2])


def render_background(vram, cgram, scroll_x=0, scroll_y=0, blob_cache=None):
    """Disegna SOLO lo sfondo (tilemap), ritorna un buffer piatto
    nuovo. Separata da render_frame() apposta: se lo sfondo non
    cambia da un frame all'altro (nessuno scroll in corso), il
    chiamante puo' CACHARE questo risultato e riusarlo, invece di
    ricalcolare centinaia di posizioni tile ogni singolo frame -
    trovato necessario profilando una scena di gioco vera (non una
    title screen quasi vuota): con lo schermo pieno al 100% di
    tile (pavimento+muri, nessuno "vuoto" da saltare), il costo
    dello sfondo domina ed e' IDENTICO ad ogni frame finche' non ci
    si muove nel mondo - ricalcolarlo e' puro spreco. Vedi
    _run_pygame_loop in launcher.py per la cache vera.

    blob_cache: dict opzionale, persistente tra le chiamate - vedi
    render_background_window() per il perche' conta cosi' tanto.

    Caso speciale di render_background_window() (finestra = tutto lo
    schermo) - vedi quella per lo scroll incrementale."""
    return render_background_window(vram, cgram, scroll_x, scroll_y, 0, SCREEN_H_PX, blob_cache=blob_cache)


def render_background_window(vram, cgram, scroll_x, scroll_y, window_y_start, window_height, blob_cache=None):
    """Come render_background(), ma disegna SOLO una fascia
    orizzontale dello schermo - righe [window_y_start,
    window_y_start+window_height), non tutte le SCREEN_H_PX. Ritorna
    un buffer di window_height righe (non l'intero schermo).

    Usata per lo SCROLL INCREMENTALE: durante uno scorrimento fluido
    (2px/frame, vedi adventure_asm/game.asm), ricalcolare l'INTERO
    sfondo ogni frame e' spreco puro - il 99% del contenuto e'
    semplicemente quello di un istante fa, spostato di 2px. Il
    chiamante (IncrementalRenderer in launcher.py) sposta il
    contenuto gia' disegnato e usa questa funzione SOLO per la
    striscia di pixel nuova che entra in vista (2px alti, non 320).

    blob_cache: dict opzionale {(tile_index,palette): blob}. Se non
    passato, ne viene creato uno NUOVO e SCARTATO alla fine di questa
    chiamata (comportamento originale, giusto per un uso isolato tipo
    test/benchmark). PROBLEMA TROVATO MISURANDO SU RASPBERRY PI 1
    VERA: durante lo scroll, questa funzione viene chiamata OGNI
    FRAME - senza un blob_cache persistente, ogni chiamata ricostruiva
    da zero il blob COMPLETO di un tile (tutti e 1024 pixel, incluso
    il costo di decodifica colore) anche se la finestra chiedeva solo
    2 righe di quel tile - 57ms/frame SOLO per questo su Pi 1, il
    costo dominante misurato. Il chiamante (IncrementalRenderer) ora
    passa un blob_cache PERSISTENTE tra i frame, cosi' il pavimento e
    il muro (2 blob distinti in questa demo) si costruiscono una
    volta sola per l'intera durata di uno stage, non ad ogni frame di
    scroll."""
    buf = bytearray(SCREEN_W_PX * window_height * 3)

    tile_cache = {}

    def get_tile(idx):
        if idx not in tile_cache:
            tile_cache[idx] = decode_tile(vram, idx)
        return tile_cache[idx]

    color_cache = {}

    def get_color(palette, color_index):
        key = (palette, color_index)
        color = color_cache.get(key)
        if color is None:
            color = decode_color(cgram, palette, color_index)
            color_cache[key] = color
        return color

    # tile PRE-RENDERIZZATI come blocco di byte RGB, con i pixel
    # trasparenti (indice 0) sostituiti dal nero di sfondo - cosi' un
    # intero tile diventa un blocco opaco copiabile in blocco, niente
    # controllo di trasparenza pixel per pixel. Se il tile e'
    # COMPLETAMENTE trasparente (es. un tile "vuoto"), il valore in
    # cache e' None - il buffer parte gia' tutto nero (bytearray
    # azzerato), quindi copiare un blocco tutto-nero sopra e' spreco
    # puro: lo saltiamo del tutto (vedi uso sotto). blob_cache e'
    # ESTERNO (passato dal chiamante) quando serve farlo sopravvivere
    # tra i frame - vedi docstring sopra.
    if blob_cache is None:
        blob_cache = {}

    def get_tile_blob(tile_index, palette):
        key = (tile_index, palette)
        if key in blob_cache:
            return blob_cache[key]
        grid = get_tile(tile_index)
        has_content = False
        for row in grid:
            for color_index in row:
                if color_index != 0:
                    has_content = True
                    break
            if has_content:
                break
        if not has_content:
            blob_cache[key] = None
            return None
        blob = bytearray(TILE_SIZE_PX * TILE_SIZE_PX * 3)
        i = 0
        for row in grid:
            for color_index in row:
                if color_index != 0:
                    r, g, b = get_color(palette, color_index)
                    blob[i] = r
                    blob[i + 1] = g
                    blob[i + 2] = b
                i += 3
        blob_cache[key] = blob
        return blob

    # --- sfondo: copia OGNI RIGA di un tile visibile con una sola
    # slice assignment (fino a 24 byte in un colpo), non 8 assegnazioni
    # pixel per pixel - ma solo le righe dentro la FINESTRA richiesta ---
    window_y_end = window_y_start + window_height
    abs_scroll_y = scroll_y + window_y_start  # la finestra e' scroll_y+offset,
                                                # non scroll_y stesso - permette
                                                # di chiedere "la striscia che
                                                # sta 2px sotto quella attuale"
    first_tile_row = abs_scroll_y // TILE_SIZE_PX
    first_row_offset = abs_scroll_y % TILE_SIZE_PX
    first_tile_col = scroll_x // TILE_SIZE_PX
    first_col_offset = scroll_x % TILE_SIZE_PX

    n_tile_rows = (window_height + first_row_offset + TILE_SIZE_PX - 1) // TILE_SIZE_PX
    n_tile_cols = (SCREEN_W_PX + first_col_offset + TILE_SIZE_PX - 1) // TILE_SIZE_PX

    for tr in range(n_tile_rows):
        map_row = first_tile_row + tr
        window_y_base = tr * TILE_SIZE_PX - first_row_offset
        for tc in range(n_tile_cols):
            map_col = first_tile_col + tc
            tile_index, palette = read_tilemap_entry(vram, map_col, map_row)
            blob = get_tile_blob(tile_index, palette)
            if blob is None:
                continue  # tile vuoto: il buffer e' gia' nero qui, niente da fare
            screen_x_base = tc * TILE_SIZE_PX - first_col_offset

            # taglia il tile ai bordi schermo (tile parzialmente
            # visibile, es. a causa dello scroll fine)
            src_x_start = max(0, -screen_x_base)
            dst_x_start = screen_x_base + src_x_start
            src_x_end = min(TILE_SIZE_PX, SCREEN_W_PX - screen_x_base)
            if src_x_end <= src_x_start:
                continue
            n_bytes = (src_x_end - src_x_start) * 3

            for ry in range(TILE_SIZE_PX):
                py = window_y_base + ry
                if py < 0 or py >= window_height:
                    continue
                blob_off = ry * TILE_SIZE_PX * 3 + src_x_start * 3
                dst_off = (py * SCREEN_W_PX + dst_x_start) * 3
                buf[dst_off:dst_off + n_bytes] = blob[blob_off:blob_off + n_bytes]

    return buf


def iter_visible_sprite_tiles(oam):
    """Analizza la OAM e produce, per ogni sotto-tile di ogni sprite
    VISIBILE (Y < 0xfff0) E DAVVERO DENTRO LO SCHERMO, una tupla
    (tile_index, palette, x, y) - x,y in pixel schermo, gia' calcolati
    per sprite grandi (griglia 2x2/4x4). Estratta da draw_sprites()
    apposta: la stessa enumerazione serve anche al rendering
    incrementale (vedi launcher.py, IncrementalRenderer) - un solo
    posto che sa come interpretare gli 8 byte OAM, testabile senza
    bisogno di pygame.

    BUG TROVATO (segnalato dall'utente su Pi vera): prima si
    controllava solo "sy >= 0xfff0" (nascosto esplicitamente), non se
    la posizione calcolata cadesse davvero nei 480x320 dello schermo.
    Un nemico che vaga lontano dalla telecamera ha una posizione
    schermo (mondo - scroll) che puo' finire ben fuori quel
    rettangolo - veniva comunque disegnato li'. Nel percorso veloce di
    IncrementalRenderer, il ripristino dello sfondo per il frame
    successivo usa quell'area come "area" sorgente da bg_surface (che
    e' grande ESATTAMENTE 480x320) - un'area fuori da quei limiti non
    esiste nella sorgente, quindi il ripristino non cancellava nulla:
    lo sprite restava visibile, una "scia" ad ogni frame di
    movimento. Ora si scarta un sotto-tile la cui area 32x32 non
    intersechi affatto lo schermo - stesso identico effetto visivo
    (comunque invisibile), ma senza sprecare un blit ne' lasciare un
    dirty-rect fantasma da (tentare di) ripristinare."""
    n_sprites = len(oam) // OAM_SLOT_BYTES
    for i in range(n_sprites):
        base = i * OAM_SLOT_BYTES
        sx = oam[base] | (oam[base + 1] << 8)
        sy = oam[base + 2] | (oam[base + 3] << 8)
        if sy >= 0xfff0:
            continue
        tile_index = oam[base + 4] | (oam[base + 5] << 8)
        attr = oam[base + 6] | (oam[base + 7] << 8)
        size_code = attr & 0x03
        tiles_per_side = {0: 1, 1: 2, 2: 4}.get(size_code, 1)
        palette = (attr >> 2) & 0x07
        for row in range(tiles_per_side):
            for col in range(tiles_per_side):
                tx = sx + col * TILE_SIZE_PX
                ty = sy + row * TILE_SIZE_PX
                # sy e' senza segno (0-65535) - uno sprite con
                # coordinate "negative" nel senso normale arriva qui
                # come un numero enorme (es. -5 -> 65531), che questo
                # controllo scarta comunque correttamente (ben oltre
                # SCREEN_H_PX) senza bisogno di gestire segni.
                if tx + TILE_SIZE_PX <= 0 or tx >= SCREEN_W_PX:
                    continue
                if ty + TILE_SIZE_PX <= 0 or ty >= SCREEN_H_PX:
                    continue
                idx = tile_index + row * tiles_per_side + col
                yield (idx, palette, tx, ty)


def render_frame(vram, oam, cgram, scroll_x=0, scroll_y=0):
    """Ritorna un buffer PIATTO (bytearray, SCREEN_W_PX*SCREEN_H_PX*3
    byte, RGB riga per riga). Composizione di render_background() +
    disegno sprite - vedi quelle due per i dettagli. Usata da
    --benchmark/--profile (percorso puro-Python, portabile,
    testabile senza pygame) e da tutti i test PPU. Il loop di gioco
    vero (_run_pygame_loop) NON la chiama direttamente ogni frame -
    usa render_background() con una cache, vedi launcher.py."""
    buf = render_background(vram, cgram, scroll_x, scroll_y)
    draw_sprites(buf, oam, cgram, vram)
    return buf


def draw_sprites(buf, oam, cgram, vram):
    """Disegna gli sprite SOPRA un buffer esistente (lo modifica sul
    posto - buf deve essere un bytearray gia' della dimensione giusta,
    tipicamente l'output di render_background(), cachato o fresco).
    Separata da render_background() apposta: gli sprite SI muovono
    ogni frame anche quando lo sfondo resta fermo, quindi vanno
    ridisegnati sempre - ma sono pochi (tipicamente una manciata),
    molto piu' economico che rifare anche lo sfondo. vram serve per
    decodificare i tile degli sprite (stesso spazio grafico dello
    sfondo, indici diversi)."""
    color_cache = {}

    def get_color(palette, color_index):
        key = (palette, color_index)
        color = color_cache.get(key)
        if color is None:
            color = decode_color(cgram, palette, color_index)
            color_cache[key] = color
        return color

    tile_cache = {}

    def get_tile(idx):
        if idx not in tile_cache:
            tile_cache[idx] = decode_tile(vram, idx)
        return tile_cache[idx]

    for tile_index, palette, ox, oy in iter_visible_sprite_tiles(oam):
        grid = get_tile(tile_index)
        for ry in range(TILE_SIZE_PX):
            py = oy + ry
            if py < 0 or py >= SCREEN_H_PX:
                continue
            row = grid[ry]
            for rx in range(TILE_SIZE_PX):
                color_index = row[rx]
                if color_index == 0:
                    continue
                px = ox + rx
                if 0 <= px < SCREEN_W_PX:
                    r, g, b = get_color(palette, color_index)
                    off = (py * SCREEN_W_PX + px) * 3
                    buf[off] = r
                    buf[off + 1] = g
                    buf[off + 2] = b
