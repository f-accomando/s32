"""
audio.py - generazione delle forme d'onda della console S32.

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
tutto. Per questo l'audio qui e' OPT-IN (flag --audio) e ogni errore
di inizializzazione viene ingoiato: il gioco deve continuare a
girare muto, mai crashare, se la scheda audio non collabora.
"""

import math
import struct

SAMPLE_RATE = 22050   # meta' della qualita' CD: basta per onde quadre
                       # e dimezza i campioni da generare su hardware
                       # lento (la Pi 1 e' il bersaglio, vedi README)
AMPLITUDE = 9000      # ben sotto il massimo di un int16 (32767):
                       # lascia margine se piu' suoni si sovrappongono

# ---- ID dei suoni: sono i numeri che una cartuccia scrive su
# PORT_SOUND. Tenuti bassi e stabili: fanno parte dell'"hardware"
# dal punto di vista del gioco, come gli indici dei tile. ----
SND_ATTACK   = 1   # fendente del giocatore
SND_HURT     = 2   # il giocatore incassa un colpo
SND_ENEMY_HIT = 3  # un nemico viene distrutto
SND_SHOOT    = 4   # nemico/boss spara
SND_STAIRS   = 5   # cambio stanza
SND_GATE     = 6   # la grata si apre
SND_BOSS_HIT = 7   # il boss incassa un colpo
SND_BOSS_DIE = 8   # il boss viene sconfitto
SND_DEFEAT   = 9   # il giocatore esaurisce i cuori (game over)


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


def build_sound_bank():
    """Costruisce TUTTI i suoni una volta sola, all'avvio. Ritorna
    {id: bytes PCM}. Generarli a ogni riproduzione costerebbe
    millisecondi in mezzo al ciclo di gioco - esattamente lo stesso
    errore gia' corretto per i tile (vedi blob_cache in ppu.py)."""
    return {
        # fendente: breve sibilo discendente
        SND_ATTACK: sweep_wave(900, 380, 0.07, duty=0.25, volume=0.55),
        # ferita: discesa marcata, il classico "ahi" a due toni
        SND_HURT: sweep_wave(520, 130, 0.22, duty=0.5, volume=0.85),
        # nemico distrutto: rumore che sfuma
        SND_ENEMY_HIT: noise(0.20, volume=0.7),
        # sparo: colpo secco e sottile
        SND_SHOOT: sweep_wave(260, 660, 0.06, duty=0.15, volume=0.5),
        # scale: salita ariosa
        SND_STAIRS: sweep_wave(320, 820, 0.18, duty=0.5, volume=0.6),
        # grata che si apre: rumore lungo e grave, come pietra che scorre
        SND_GATE: noise(0.45, volume=0.55),
        # boss colpito: tonfo basso e corto
        SND_BOSS_HIT: sweep_wave(220, 90, 0.14, duty=0.5, volume=0.9),
        # boss sconfitto: rumore lungo + coda discendente
        SND_BOSS_DIE: noise(0.5, volume=0.9) + sweep_wave(300, 60, 0.5, volume=0.8),
        # sconfitta del giocatore: discesa lunga e cupa, distinta dal
        # tonfo breve della ferita - l'ultimo suono di una partita
        SND_DEFEAT: sweep_wave(400, 50, 0.9, duty=0.5, volume=0.85),
    }
