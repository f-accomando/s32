"""ppu.pxd - dichiarazioni di tipo per Cython (vedi cpu.pxd per la
spiegazione del meccanismo generale - stesso principio, applicato qui
al percorso di rendering invece che all'emulazione della CPU).

Le funzioni qui sotto sono a livello di MODULO, non metodi di una
classe (la PPU non ha stato proprio - riceve vram/cgram/oam a ogni
chiamata, vedi il docstring in cima a ppu.py): basta dichiararle con
cpdef, senza bisogno di una cdef class come in cpu.pxd.

NON tipizzate le cache (tile_cache/color_cache/blob_cache, tutte
dict semplici): restano la struttura dati con cui il resto del
progetto (launcher.py, i renderer, i test) gia' le crea e passa -
blob_cache in particolare e' persistente tra i frame nel loop di
gioco vero (vedi IncrementalRenderer in launcher.py) e cambiare la
sua rappresentazione tocca quei punti di chiamata, un intervento
volutamente separato da questo. Qui l'obiettivo e' il lavoro
ARITMETICO per-pixel/per-tile (decode_tile/decode_color/il loop di
get_tile_blob), che il profilo su Raspberry Pi 1 vera indica come
il costo dominante (~64% del tempo per frame, issue prestazioni)."""

cpdef decode_tile(object vram, long tile_index)
cpdef decode_color(object cgram, long palette_index, long color_index)
cpdef read_tilemap_entry(object vram, long tx, long ty)
cpdef get_tile(object vram, dict tile_cache, long tile_index)
cpdef get_color(object cgram, dict color_cache, long palette, long color_index)
cpdef get_tile_blob(object vram, object cgram, dict tile_cache, dict color_cache,
                     dict blob_cache, long tile_index, long palette)
