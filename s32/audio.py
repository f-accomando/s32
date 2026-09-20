"""
audio.py - generazione delle forme d'onda della console S32.

QUESTO E' L'"HARDWARE" AUDIO: solo i generatori di forma d'onda
generici (onda quadra, sweep, rumore) - il "chip sonoro" della
console, riusabile da QUALUNQUE cartuccia. Quali suoni esistono,
cosa significano (attacco, ferita, ecc.) e come si combinano e'
CONTENUTO della cartuccia, non della console - esattamente come lo
spritesheet non sta in ppu.py. Vedi carts/_shared/sound_bank.py per
il banco suoni di Adventure, costruito con questi stessi generatori.
Corretto dopo che l'utente ha notato che i suoni di Adventure erano
finiti per errore qui invece che nella cartuccia.

DELIBERATAMENTE SENZA PYGAME: qui si producono solo BYTE (campioni
PCM 16-bit mono), esattamente come ppu.py produce solo byte RGB. Chi
li manda alla scheda audio e' il launcher. Cosi' questo modulo resta
testabile in un ambiente senza scheda audio (e senza pygame), come
tutto il resto del motore.

Perche' onde quadre e rumore e non campioni registrati: e' la stessa
scelta delle console 8/16 bit vere - un generatore di toni costa
pochi byte di parametri invece di megabyte di audio, e lo stile
sonoro che ne esce e' coerente con la grafica a tile.

NOTA STORICA IMPORTANTE (vedi launcher._init_pygame_once): su
Raspberry Pi il mixer di pygame, se lasciato attivo con ALSA mal
configurato, spamma "underrun occurred" a ogni frame e rallenta
tutto. Per questo l'audio qui e' OPT-IN (flag --no-audio per
disattivarlo) e ogni errore di inizializzazione viene ingoiato: il
gioco deve continuare a girare muto, mai crashare, se la scheda
audio non collabora.
"""

import struct

SAMPLE_RATE = 22050   # meta' della qualita' CD: basta per onde quadre
                       # e dimezza i campioni da generare su hardware
                       # lento (la Pi 1 e' il bersaglio, vedi README)
AMPLITUDE = 9000      # ben sotto il massimo di un int16 (32767):
                       # lascia margine se piu' suoni si sovrappongono


def square_wave(freq, duration_s, duty=0.5, volume=1.0):
    """Onda quadra: il suono piu' tipico dei chip 8-bit. `duty`
    sposta il rapporto alto/basso - 0.5 e' il timbro pieno classico,
    valori piu' bassi danno un suono piu' nasale/sottile."""
    n = int(SAMPLE_RATE * duration_s)
    amp = int(AMPLITUDE * volume)
    out = bytearray()
    period = SAMPLE_RATE / freq if freq > 0 else 1
    for i in range(n):
        phase = (i % period) / period
        v = amp if phase < duty else -amp
        out += struct.pack('<h', v)
    return bytes(out)


def sweep_wave(f_start, f_end, duration_s, duty=0.5, volume=1.0):
    """Onda quadra che scivola da una frequenza a un'altra. In salita
    suona come "raccolto/aperto", in discesa come "colpito/perso" -
    e' il trucco piu' economico per dare un'intenzione a un suono
    senza inviluppi complicati."""
    n = int(SAMPLE_RATE * duration_s)
    amp = int(AMPLITUDE * volume)
    out = bytearray()
    phase = 0.0
    for i in range(n):
        t = i / n if n else 0
        freq = f_start + (f_end - f_start) * t
        phase += freq / SAMPLE_RATE
        v = amp if (phase % 1.0) < duty else -amp
        out += struct.pack('<h', v)
    return bytes(out)


def noise(duration_s, volume=1.0, decay=True):
    """Rumore pseudo-casuale: percussioni, esplosioni, impatti.
    Generatore deterministico (nessun random importato) - stesso
    seme, stesso rumore, cosi' i test possono verificarlo."""
    n = int(SAMPLE_RATE * duration_s)
    amp = int(AMPLITUDE * volume)
    out = bytearray()
    state = 0x7f3a
    for i in range(n):
        state = ((state * 1103515245) + 12345) & 0x7fffffff
        bit = 1 if (state >> 16) & 1 else -1
        env = (1.0 - i / n) if (decay and n) else 1.0
        out += struct.pack('<h', int(amp * bit * env))
    return bytes(out)


def silence(duration_s):
    return b'\x00\x00' * int(SAMPLE_RATE * duration_s)


def mono_to_stereo(pcm_mono):
    """Duplica ogni campione mono sui due canali (L=R), per quando il
    mixer negozia stereo nonostante la richiesta esplicita di canale
    singolo (capita su alcuni sistemi, in particolare Windows) -
    senza questo, pygame.mixer.Sound() interpreterebbe i byte mono
    come se fossero gia' interleaved L/R, risultando distorto o
    silenzioso senza nessun errore esplicito."""
    n = len(pcm_mono) // 2  # numero di campioni (2 byte ciascuno)
    out = bytearray(len(pcm_mono) * 2)
    for i in range(n):
        sample = pcm_mono[i*2:i*2+2]
        out[i*4:i*4+2] = sample
        out[i*4+2:i*4+4] = sample
    return bytes(out)
