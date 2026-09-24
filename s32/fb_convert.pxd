"""fb_convert.pxd - dichiarazioni di tipo per Cython (vedi cpu.pxd per
la spiegazione del meccanismo generale).

frame_buf e' dichiarato come memoryview tipizzato (unsigned char[:])
invece di semplice object: a differenza di cpu.py/ppu.py (dove mem
resta un bytearray Python normale, vedi cpu.pxd), qui l'accesso in
LETTURA a frame_buf e' l'unica cosa che conta per le prestazioni (un
loop stretto su 150.000+ elementi/frame) - un memoryview tipizzato
elimina l'overhead di __getitem__ Python a ogni pixel, non solo
l'overhead sui singoli interi come infer_types da solo farebbe.

Il bytearray di output (out, locale alla funzione) resta non
tipizzato - .pxd puo' dichiarare solo parametri/attributi, non
variabili locali; il grosso del costo era comunque nella lettura di
frame_buf e nell'aritmetica di bit, non nella scrittura del risultato."""

cpdef rgb888_to_rgb565(const unsigned char[:] frame_buf)
