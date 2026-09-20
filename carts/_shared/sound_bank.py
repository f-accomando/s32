"""
sound_bank.py - il banco suoni di Adventure.

QUESTO E' CONTENUTO DELLA CARTUCCIA, NON DELLA CONSOLE - quali suoni
esistono e cosa significano (attacco, ferita, boss sconfitto, ecc.)
appartiene al gioco, esattamente come lo spritesheet in graphics.py.
La console fornisce solo l'"hardware": i generatori di forma d'onda
generici (square_wave/sweep_wave/noise) in s32/audio.py, riusabili
da QUALUNQUE cartuccia con il proprio banco suoni diverso.

Corretto dopo che l'utente ha notato che questi suoni erano finiti
per errore dentro il motore (s32/audio.py) invece che qui.

Condiviso tra adventure_asm e adventure_cl (stesso gioco, stessi
suoni) - importato dal cart.py di entrambi, stesso schema di
graphics.py.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 's32'))

from audio import square_wave, sweep_wave, noise, silence  # noqa: F401 (square_wave/silence disponibili per usi futuri)

# ---- ID dei suoni: sono i numeri che la cartuccia scrive su
# PORT_SOUND (0x042004). Tenuti bassi e stabili: fanno parte
# dell'interfaccia della cartuccia col motore, come gli indici dei
# tile per la grafica. ----
SND_ATTACK    = 1   # fendente del giocatore
SND_HURT      = 2   # il giocatore incassa un colpo
SND_ENEMY_HIT = 3   # un nemico viene distrutto
SND_SHOOT     = 4   # nemico/boss spara
SND_STAIRS    = 5   # cambio stanza
SND_GATE      = 6   # la grata si apre
SND_BOSS_HIT  = 7   # il boss incassa un colpo
SND_BOSS_DIE  = 8   # il boss viene sconfitto
SND_DEFEAT    = 9   # il giocatore esaurisce i cuori (game over)


def build_sound_bank():
    """Costruisce TUTTI i suoni di Adventure una volta sola, all'avvio
    (chiamata da _load_cart_graphics nel launcher). Ritorna {id: bytes
    PCM}. Generarli a ogni riproduzione costerebbe millisecondi in
    mezzo al ciclo di gioco - esattamente lo stesso errore gia'
    corretto per i tile (vedi blob_cache in ppu.py)."""
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
