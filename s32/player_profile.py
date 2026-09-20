"""
player_profile.py - profilo LOCALE del giocatore (nickname + avatar)
per il menu OS - vedi os_menu.py, schermata "profilo" (tasto P dalla
griglia).

NOME NON "profile.py" DI PROPOSITO: collide con il modulo della
libreria standard di Python `profile` (usato da `cProfile`, quindi da
--profile/run_benchmark) - con "profile.py" nella stessa cartella,
`import profile` dentro cProfile.py prendeva QUESTO file invece dello
stdlib, rompendo --profile con un AttributeError oscuro. Trovato
scrivendo i test.

Persistito in player_profile.json accanto a questo file: e' stato
PERSONALE della macchina/installazione, non del progetto - stesso
principio di un file di salvataggio, per questo e' in .gitignore (non
va mai committato: il nickname di chi gioca non e' contenuto del
motore ne' di una cartuccia).

Nessuna dipendenza da pygame - pura logica, testabile senza display
(stesso principio di menu_state.py/carts_registry.py).
"""

import json
import os

PROFILE_PATH = os.path.join(os.path.dirname(__file__), 'player_profile.json')
AVATARS_DIR = os.path.join(os.path.dirname(__file__), 'avatars')

DEFAULT_NICKNAME = 'Player'
DEFAULT_AVATAR = 0
AVATAR_COUNT = 4
MAX_NICKNAME_LEN = 16

# caratteri ammessi nel nickname - stampabili, niente spazi ai bordi
# ne' caratteri che romperebbero il protocollo JSON (in realta' json
# gestirebbe qualunque stringa, il limite e' sulla leggibilita' a
# schermo: niente a capo, niente caratteri di controllo)
NICKNAME_CHARS = set(
    'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_- '
)


def _sanitize(nickname, avatar):
    nickname = (nickname or '').strip()[:MAX_NICKNAME_LEN]
    if not nickname:
        nickname = DEFAULT_NICKNAME
    if not isinstance(avatar, int) or not (0 <= avatar < AVATAR_COUNT):
        avatar = DEFAULT_AVATAR
    return nickname, avatar


def load_profile():
    """Ritorna {'nickname':.., 'avatar':..} - un default sensato se
    il file non esiste ancora o e' corrotto (MAI un crash del menu
    per un profilo illeggibile, stesso principio di icon_path()
    mancante in carts_registry.py)."""
    if os.path.isfile(PROFILE_PATH):
        try:
            with open(PROFILE_PATH, 'r') as f:
                data = json.load(f)
            nickname, avatar = _sanitize(data.get('nickname'), data.get('avatar'))
            return {'nickname': nickname, 'avatar': avatar}
        except (ValueError, OSError, AttributeError):
            pass  # file corrotto/illeggibile - ripiega sul default sotto
    return {'nickname': DEFAULT_NICKNAME, 'avatar': DEFAULT_AVATAR}


def save_profile(nickname, avatar):
    """Salva e ritorna il profilo (gia' sanificato - il chiamante non
    deve validare prima)."""
    nickname, avatar = _sanitize(nickname, avatar)
    with open(PROFILE_PATH, 'w') as f:
        json.dump({'nickname': nickname, 'avatar': avatar}, f)
    return {'nickname': nickname, 'avatar': avatar}


def avatar_path(index):
    """Percorso assoluto di avatars/avatar_N.png - non verifica che
    esista, os_menu.py ripiega su un placeholder se il caricamento
    fallisce (stesso schema di carts_registry.icon_path())."""
    _, index = _sanitize('', index)
    return os.path.join(AVATARS_DIR, f'avatar_{index}.png')
