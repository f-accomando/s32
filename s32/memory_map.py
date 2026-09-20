"""
memory_map.py - specifica di S32 (motore 16-bit, bus a 24-bit flat).

Questo file e' la SINGOLA fonte di verita' per la mappa indirizzi.
CPU, PPU, assembler e ConsoleLang devono importare le costanti da
qui, non ridefinirle - se in futuro un indirizzo deve cambiare,
cambia in un punto solo.

--------------------------------------------------------------------
PERCHE' QUESTI NUMERI (deciso insieme all'utente, non arbitrario)
--------------------------------------------------------------------

BUS: 24-bit, FLAT (16MB indirizzabili, NESSUN banking). Il vero
SNES usa 24 bit CON banking perche' il suo 65816 indirizza nativamente
solo 16 bit per istruzione (eredita' del 6502) - per noi non c'e'
questo vincolo di silicio, quindi prendiamo lo stesso spazio totale
(16MB) SENZA la complessita' del banking che ci ha gia' causato bug
reali quando abbiamo scritto la ROM SNES vera in un'altra parte di
questo progetto.

REGISTRI: A, X, Y tutti a 16 bit (0-65535). Un vero registro FLAG
(Zero, Negative, Carry, Overflow) abilita un CMP che non distrugge
l'accumulatore - risolve il limite che in ConsoleLang (v1, 8-bit) ci
ha costretto a vietare "<" come valore generico, permettendolo solo
dentro if/ternario. Uno STACK HARDWARE vero (non solo la pila interna
per JSR/RTS che avevamo in v1) abilita PUSH/POP veri.

WRAM/VRAM/OAM/CGRAM: generosi deliberatamente, con margine ampio
sopra al vero SNES - la scelta esplicita dell'utente e' stata "meglio
essere generosi e semplici, non vorrei ricreare l'architettura da
capo per limiti imprevisti". Costano pochissimo in piu' per noi
(niente e' vincolato dal silicio), quindi il margine e' quasi gratis.

COLORI: 8bpp (256 colori per tile: 1 trasparente + 255 veri) - pari
o sopra il vero SNES nelle sue modalita' piu' ricche.

TUTTO LO SPAZIO NON ASSEGNATO RESTA DELIBERATAMENTE LIBERO (~15,5MB):
non e' spreco, e' la garanzia di non dover mai "traslocare" la mappa
per fare posto a qualcosa che non avevamo previsto (es. i coprocessori
del punto 1 della roadmap, ancora non implementati per scelta).
"""

# ---------------------------------------------------------------
# BUS
# ---------------------------------------------------------------
ADDRESS_BITS = 24
ADDRESS_SPACE = 1 << ADDRESS_BITS  # 16.777.216 byte (16MB)

# ---------------------------------------------------------------
# REGISTRI
# ---------------------------------------------------------------
REGISTER_BITS = 16
REGISTER_MAX = (1 << REGISTER_BITS) - 1  # 65535

# nomi dei bit del registro FLAG (non ancora implementato il core -
# questa e' la specifica che cpu.py dovra' rispettare)
FLAG_ZERO = 0x01
FLAG_NEGATIVE = 0x02
FLAG_CARRY = 0x04
FLAG_OVERFLOW = 0x08

# ---------------------------------------------------------------
# MAPPA INDIRIZZI
# ---------------------------------------------------------------
WRAM_BASE = 0x000000
WRAM_SIZE = 128 * 1024  # 128KB, pari al vero SNES
WRAM_END = WRAM_BASE + WRAM_SIZE  # 0x020000 (esclusivo)

VRAM_BASE = 0x020000
VRAM_SIZE = 128 * 1024  # 128KB, IL DOPPIO del vero SNES (64KB)
VRAM_END = VRAM_BASE + VRAM_SIZE  # 0x040000 (esclusivo)

OAM_BASE = 0x040000
OAM_SLOT_BYTES = 8   # x(2) + y(2) + tile(2) + attr(2) - a 16 bit, non 8
OAM_MAX_SPRITES = 512  # 4x il vero SNES (128 sprite)
OAM_SIZE = OAM_SLOT_BYTES * OAM_MAX_SPRITES  # 4096 byte (4KB)
OAM_END = OAM_BASE + OAM_SIZE  # 0x041000 (esclusivo)

CGRAM_BASE = 0x041000
CGRAM_SIZE = 4 * 1024  # 4KB - tante palette, non piu' 2 fisse come in v1
CGRAM_END = CGRAM_BASE + CGRAM_SIZE  # 0x042000 (esclusivo)

PORTS_BASE = 0x042000
PORTS_SIZE = 256
PORTS_END = PORTS_BASE + PORTS_SIZE  # 0x042100 (esclusivo)

COPROCESSOR_BASE = 0x042100
COPROCESSOR_SIZE = 0x04FFFF - COPROCESSOR_BASE + 1  # ~57KB riservati,
                                                      # NESSUN coprocessore
                                                      # implementato ancora
                                                      # (roadmap punto 1)
COPROCESSOR_END = 0x050000  # (esclusivo)

FREE_BASE = 0x050000
FREE_END = ADDRESS_SPACE  # ~15,5MB deliberatamente non assegnati

# ---------------------------------------------------------------
# GRAFICA
# ---------------------------------------------------------------
BITS_PER_PIXEL = 8
COLORS_PER_TILE = 256  # 1 trasparente (indice 0) + 255 veri
TILE_SIZE_PX = 32  # FISSA per l'intera console, non selezionabile per
                    # cartuccia (deciso con l'utente): ogni cambio qui
                    # e' un cambio hardware globale, non di un singolo
                    # gioco. Renderla variabile per-cart (es. 8x8/16x16
                    # per barebone, 32x32 per adventure, nella stessa
                    # sessione) e' un'idea tenuta da parte per il
                    # futuro - richiederebbe portare questa costante da
                    # globale a un parametro registrato per cartuccia,
                    # toccando PPU/CPU/assembler. Non fatto ora.
                    # UNIFICATO tra sfondo e sprite (era 8) - "strada B":
                    # coerenza totale invece di due scale diverse, e
                    # un bonus prestazioni concreto: lo sfondo passa
                    # da 2400 posizioni-tile a schermo a 150 (il costo
                    # scala col NUMERO di posizioni controllate, non
                    # solo con quanto c'e' disegnato - vedi README.md)
TILE_BYTES = (TILE_SIZE_PX * TILE_SIZE_PX * BITS_PER_PIXEL) // 8  # 1024 byte/tile

# --- risoluzione schermo: stessa dei modi piu' comuni del vero SNES ---
SCREEN_W_PX = 480
SCREEN_H_PX = 320
SCREEN_TILES_W = SCREEN_W_PX // TILE_SIZE_PX  # 15
SCREEN_TILES_H = SCREEN_H_PX // TILE_SIZE_PX  # 10

# --- tilemap: molto piu' grande dello schermo (mondo scrollabile in
# entrambe le direzioni, non solo in verticale come in v1) ---
TILEMAP_W = 128  # tile (4096px a 32px/tile)
TILEMAP_H = 128  # tile (4096px a 32px/tile)
TILEMAP_ENTRY_BYTES = 2  # tile_index(12 bit) + palette(3 bit) + 1 bit riservato
TILEMAP_BYTES = TILEMAP_W * TILEMAP_H * TILEMAP_ENTRY_BYTES  # 32.768 (32KB)

# la tilemap vive all'inizio della VRAM, i tile grafici veri subito dopo
TILEMAP_VRAM_OFFSET = 0
TILE_GRAPHICS_VRAM_OFFSET = TILEMAP_BYTES
TILE_GRAPHICS_BYTES = VRAM_SIZE - TILEMAP_BYTES  # ~96KB
MAX_TILES = TILE_GRAPHICS_BYTES // TILE_BYTES  # 96 tile indirizzabili
                                                 # (era ~1536 a 8x8 -
                                                 # tetto molto piu' basso,
                                                 # ma ancora abbondante:
                                                 # oggi ne usiamo 12)

# --- CGRAM: colori in RGB555 (2 byte/colore, stesso formato del
# vero SNES: 5 bit per canale) - 8 palette da 256 colori ciascuna ---
CGRAM_COLOR_BYTES = 2
COLORS_PER_PALETTE = 256
PALETTE_COUNT = CGRAM_SIZE // (COLORS_PER_PALETTE * CGRAM_COLOR_BYTES)  # 8


def describe_map():
    """Stampa la mappa indirizzi in forma leggibile - utile per
    verificare a colpo d'occhio che tutto torni."""
    regions = [
        ("WRAM", WRAM_BASE, WRAM_END),
        ("VRAM", VRAM_BASE, VRAM_END),
        ("OAM", OAM_BASE, OAM_END),
        ("CGRAM", CGRAM_BASE, CGRAM_END),
        ("Porte", PORTS_BASE, PORTS_END),
        ("Coprocessori (riservato)", COPROCESSOR_BASE, COPROCESSOR_END),
        ("Libero", FREE_BASE, FREE_END),
    ]
    for name, start, end in regions:
        size = end - start
        print(f"0x{start:06X} - 0x{end - 1:06X}   {name:<28} ({size:,} byte)")


if __name__ == "__main__":
    describe_map()
