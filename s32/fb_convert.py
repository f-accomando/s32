"""fb_convert.py - conversione RGB888 (formato interno di
render_background()/draw_sprites() in ppu.py) -> RGB565 (formato
nativo di molti LCD SPI/GPIO - vedi FramebufferRenderer in
launcher.py, --fbdev-renderer, e `fbset -fb /dev/fbN` per verificare
il formato del proprio schermo).

Isolata in un modulo a se' (invece di restare inline dentro
FramebufferRenderer in launcher.py) apposta per poter essere
compilata con Cython come cpu.py/ppu.py (vedi build_cython.py e
fb_convert.pxd accanto a questo file): launcher.py e' pieno di codice
pygame/SDL complesso, un pessimo candidato per Cython, mentre questo
loop e' puro calcolo su byte - esattamente il tipo di codice che
beneficia della tipizzazione statica.

MISURATO su Raspberry Pi 1 vero: ~4 SECONDI/frame in Python puro
(153.600 pixel/frame a 480x320) - completamente inutilizzabile senza
compilare questo modulo. Il fallback naturale a Python puro resta
corretto (stesso risultato), solo troppo lento per girare in tempo
reale su questo hardware."""


def rgb888_to_rgb565(frame_buf):
    """frame_buf: bytearray/bytes RGB888 piatto (3 byte/pixel, output
    di render_background()+draw_sprites()). Ritorna un NUOVO
    bytearray RGB565 (2 byte/pixel, little-endian - byte basso poi
    byte alto), stesso bit-packing gia' verificato su un LCD reale
    con uno script indipendente dell'utente."""
    n = len(frame_buf)
    out = bytearray(n // 3 * 2)
    j = 0
    for i in range(0, n, 3):
        r = frame_buf[i]
        g = frame_buf[i + 1]
        b = frame_buf[i + 2]
        p = ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)
        out[j] = p & 0xff
        out[j + 1] = (p >> 8) & 0xff
        j += 2
    return out
