import os
import tempfile
import shutil

from carts_registry import discover_carts
from menu_state import MenuState

fails = 0

def check(label, got, expected):
    global fails
    status = "OK  " if got == expected else "FAIL"
    if got != expected:
        fails += 1
    print(f"{status} {label}: atteso {expected!r}, ottenuto {got!r}")

def make_cart(base, name, has_py=False, has_asm=False, title=None):
    path = os.path.join(base, name)
    os.makedirs(path, exist_ok=True)
    if has_py:
        with open(os.path.join(path, 'game.py'), 'w') as f:
            f.write('ROM_SOURCE = ""\n')
    if has_asm:
        with open(os.path.join(path, 'game.asm'), 'w') as f:
            f.write('HALT\n')
    if title:
        with open(os.path.join(path, 'cart_info.py'), 'w') as f:
            f.write(f'TITLE = {title!r}\n')
    return path

tmpdir = tempfile.mkdtemp(prefix='s32_carts_test_')
try:
    # ---------------------------------------------------------------
    # Test 1: cartuccia valida con game.py viene trovata
    # ---------------------------------------------------------------
    make_cart(tmpdir, 'adventure_demo', has_py=True)
    carts = discover_carts(tmpdir)
    check("cartuccia con game.py trovata", len(carts), 1)
    check("titolo derivato dal nome cartella (default)", carts[0].title, "Adventure Demo")
    check("has_py=True", carts[0].has_py, True)
    check("has_asm=False", carts[0].has_asm, False)

    # ---------------------------------------------------------------
    # Test 2: cartella SENZA game.py/game.asm viene ignorata
    # ---------------------------------------------------------------
    os.makedirs(os.path.join(tmpdir, 'non_una_cartuccia'), exist_ok=True)
    with open(os.path.join(tmpdir, 'non_una_cartuccia', 'appunti.txt'), 'w') as f:
        f.write('solo un file a caso')
    carts2 = discover_carts(tmpdir)
    check("cartella senza game.py/asm ignorata (ancora solo 1 cartuccia)", len(carts2), 1)

    # ---------------------------------------------------------------
    # Test 3: cartuccia con game.asm (non .py) viene trovata
    # ---------------------------------------------------------------
    make_cart(tmpdir, 'platform_test', has_asm=True)
    carts3 = discover_carts(tmpdir)
    check("cartuccia con solo game.asm trovata", len(carts3), 2)
    asm_cart = [c for c in carts3 if c.name == 'platform_test'][0]
    check("has_asm=True per cartuccia asm", asm_cart.has_asm, True)
    check("has_py=False per cartuccia asm", asm_cart.has_py, False)

    # ---------------------------------------------------------------
    # Test 4: titolo personalizzato da cart_info.py ha precedenza
    # ---------------------------------------------------------------
    make_cart(tmpdir, 'rpg_prototype', has_py=True, title="Il Mio RPG")
    carts4 = discover_carts(tmpdir)
    custom = [c for c in carts4 if c.name == 'rpg_prototype'][0]
    check("titolo personalizzato da cart_info.py", custom.title, "Il Mio RPG")

    # ---------------------------------------------------------------
    # Test 5: la lista e' ordinata per titolo
    # ---------------------------------------------------------------
    carts5 = discover_carts(tmpdir)
    titles = [c.title for c in carts5]
    check("lista ordinata alfabeticamente per titolo", titles, sorted(titles, key=str.lower))

    # ---------------------------------------------------------------
    # Test 6: cartella carts/ inesistente -> lista vuota, non errore
    # ---------------------------------------------------------------
    carts6 = discover_carts('/percorso/che/non/esiste/di/sicuro')
    check("cartella carts/ inesistente: lista vuota, nessun crash", carts6, [])

finally:
    shutil.rmtree(tmpdir)

# ---------------------------------------------------------------
# Test 7-11: navigazione del menu (MenuState)
# ---------------------------------------------------------------
class FakeCart:
    def __init__(self, title):
        self.title = title

items = [FakeCart("Alpha"), FakeCart("Beta"), FakeCart("Gamma")]
m = MenuState(items)
check("indice iniziale = 0", m.index, 0)
check("selected() ritorna il primo elemento", m.selected().title, "Alpha")

m.move_down()
check("move_down: indice avanza", m.index, 1)
check("selected() dopo move_down", m.selected().title, "Beta")

m.move_down()
m.move_down()
check("move_down oltre l'ultimo: si avvolge al primo", m.index, 0)

m.move_up()
check("move_up dal primo: si avvolge all'ultimo", m.index, 2)
check("selected() dopo wraparound verso l'alto", m.selected().title, "Gamma")

empty_menu = MenuState([])
check("menu vuoto: is_empty()", empty_menu.is_empty(), True)
check("menu vuoto: selected() ritorna None, non crash", empty_menu.selected(), None)
empty_menu.move_down()  # non deve sollevare eccezioni
check("menu vuoto: move_down() non crasha", empty_menu.index, 0)

# ---------------------------------------------------------------
# Test 12: MenuState a griglia (columns>1) - aggiunta per la griglia
# di icone del menu OS. Con columns=1 (default, gia' verificato sopra)
# si comporta esattamente come la vecchia lista verticale.
# ---------------------------------------------------------------
grid_items = [FakeCart(n) for n in ["A", "B", "C", "D", "E", "F"]]  # griglia 3x2
g = MenuState(grid_items, columns=3)
check("griglia: indice iniziale = 0", g.index, 0)

g.move_right()
check("griglia: move_right avanza di 1", g.index, 1)
g.move_left()
g.move_left()
check("griglia: move_left si avvolge all'ultimo elemento", g.index, 5)

g.index = 0
g.move_down()
check("griglia: move_down avanza di 'columns' (salta alla riga sotto)", g.index, 3)
g.move_up()
check("griglia: move_up torna alla riga sopra", g.index, 0)
g.move_up()
check("griglia: move_up dalla prima riga si avvolge all'ultima", g.index, 3)

# ---------------------------------------------------------------
# Test 13: icona della cartuccia (carts_registry) - icon.png opzionale
# ---------------------------------------------------------------
from carts_registry import ICON_FILENAME

tmpdir2 = tempfile.mkdtemp(prefix='s32_icon_test_')
try:
    make_cart(tmpdir2, 'senza_icona', has_py=True)
    con_icona_path = make_cart(tmpdir2, 'con_icona', has_py=True)
    with open(os.path.join(con_icona_path, ICON_FILENAME), 'wb') as f:
        f.write(b'\x89PNG\r\n\x1a\n')  # contenuto finto, basta che il file esista

    carts_icon = discover_carts(tmpdir2)
    senza = [c for c in carts_icon if c.name == 'senza_icona'][0]
    con = [c for c in carts_icon if c.name == 'con_icona'][0]
    check("cartuccia senza icon.png: has_icon=False", senza.has_icon, False)
    check("cartuccia senza icon.png: icon_path()=None", senza.icon_path(), None)
    check("cartuccia con icon.png: has_icon=True", con.has_icon, True)
    check("cartuccia con icon.png: icon_path() punta al file giusto",
          con.icon_path(), os.path.join(con_icona_path, ICON_FILENAME))
finally:
    shutil.rmtree(tmpdir2)

# ---------------------------------------------------------------
# Test 14: os_menu - layout griglia (pura, senza pygame) e TextField
# ---------------------------------------------------------------
import os_menu

pos = os_menu._grid_positions(6, 3, 100, 120, 20, 40, origin_x=10, origin_y=50)
check("_grid_positions: 6 elementi, 3 colonne -> 6 posizioni", len(pos), 6)
check("_grid_positions: primo elemento all'origine", pos[0], (10, 50))
check("_grid_positions: secondo elemento sulla stessa riga (x avanza)", pos[1], (10 + 120, 50))
check("_grid_positions: quarto elemento va a capo (nuova riga)", pos[3], (10, 50 + 160))

tf = os_menu.TextField('', max_len=5, allowed=os_menu.DIGITS)
tf.add_char('4'); tf.add_char('2'); tf.add_char('x')  # 'x' rifiutato (non e' una cifra)
check("TextField: accetta solo caratteri in 'allowed'", tf.value, "42")
tf.backspace()
check("TextField: backspace rimuove l'ultimo carattere", tf.value, "4")
tf2 = os_menu.TextField('', max_len=3)
for ch in "12345":
    tf2.add_char(ch)
check("TextField: rispetta max_len", tf2.value, "123")

# ---------------------------------------------------------------
# Test 15: run_os_menu() end-to-end con pygame finto - verifica il
# FLUSSO (non il disegno): selezione cartuccia -> modalita' -> lancio,
# ritorno al menu DOPO la partita con lo stesso indice selezionato
# (non azzerato), e distinzione tra "ESC in game" (torna al menu) e
# "finestra chiusa in game" (chiude tutto). Stessa tecnica di mock di
# pygame gia' usata in test_launcher.py (sys.modules['pygame'] finto).
# ---------------------------------------------------------------
import sys as _sys_om
import types as _types_om
from unittest.mock import MagicMock as _MagicMock_om

class _FakeSurfaceOm:
    def __init__(self, *a, **k): pass
    def fill(self, *a, **k): pass
    def blit(self, *a, **k): pass
    def get_rect(self, *a, **k): return (0, 0, 10, 10)
    def get_width(self): return 40

class _FakeFontOm:
    def render(self, text, aa, color):
        return _FakeSurfaceOm()

class _FakeClockOm:
    def tick(self, fps): pass

class _FakeEventOm:
    def __init__(self, type_, key=None, unicode=''):
        self.type = type_
        self.key = key
        self.unicode = unicode

_pygame_om = _types_om.ModuleType('pygame_os_menu_fake')
_pygame_om.QUIT = 1
_pygame_om.KEYDOWN = 2
for _i, _name in enumerate(['K_ESCAPE', 'K_UP', 'K_DOWN', 'K_LEFT', 'K_RIGHT',
                             'K_w', 'K_a', 'K_s', 'K_d', 'K_RETURN', 'K_j',
                             'K_SPACE', 'K_TAB', 'K_BACKSPACE'], start=10):
    setattr(_pygame_om, _name, _i)

_pygame_om.init = _MagicMock_om()
_pygame_om.get_init = _MagicMock_om(return_value=False)
_pygame_om.quit = _MagicMock_om()
_pygame_om.mixer = _MagicMock_om()
_pygame_om.mouse = _MagicMock_om()
_pygame_om.display = _MagicMock_om()
_pygame_om.display.set_mode = _MagicMock_om(return_value=_FakeSurfaceOm())
_pygame_om.display.flip = _MagicMock_om()
_pygame_om.font = _MagicMock_om()
_pygame_om.font.SysFont = _MagicMock_om(return_value=_FakeFontOm())
_pygame_om.time = _MagicMock_om()
_pygame_om.time.Clock = _MagicMock_om(return_value=_FakeClockOm())
_pygame_om.draw = _MagicMock_om()
_pygame_om.Surface = _FakeSurfaceOm

_eventi_in_coda = []

def _prossimi_eventi():
    if _eventi_in_coda:
        return _eventi_in_coda.pop(0)
    return []

_pygame_om.event = _MagicMock_om()
_pygame_om.event.get = _MagicMock_om(side_effect=_prossimi_eventi)

_sys_om.modules['pygame'] = _pygame_om
import importlib as _importlib_om
import launcher as _launcher_om
_importlib_om.reload(_launcher_om)

class FakeMenuCart:
    def __init__(self, name):
        self.name = name
        self.title = name
    def entry_py(self):
        return f"/fake/{self.name}/game.py"
    def entry_asm(self):
        return None
    def icon_path(self):
        return None

_fake_carts_om = [FakeMenuCart('aaa'), FakeMenuCart('bbb')]

import os_menu as _os_menu_om
_importlib_om.reload(_os_menu_om)
_os_menu_om.discover_carts = lambda carts_dir: _fake_carts_om

_run_direct_calls = []
_run_direct_returns = []

def _fake_run_direct(path, kind, **kwargs):
    _run_direct_calls.append((path, kind, kwargs.get('netcode_session'), kwargs.get('local_player_index')))
    return _run_direct_returns.pop(0)

_orig_run_direct_om = _launcher_om.run_direct
_launcher_om.run_direct = _fake_run_direct
try:
    # scenario 1: sposta la selezione a destra (indice 1, cartuccia
    # "bbb"), sceglie "Locale", la partita finisce con ESC (run_direct
    # ritorna False) -> deve tornare al menu MANTENENDO l'indice 1 (non
    # azzerato a 0) - poi rigioca la STESSA cartuccia, stavolta la
    # partita finisce con la finestra chiusa (run_direct ritorna True)
    # -> il menu deve chiudersi del tutto (pygame.quit chiamato).
    _eventi_in_coda.extend([
        [_FakeEventOm(_pygame_om.KEYDOWN, key=_pygame_om.K_RIGHT)],      # grid: -> indice 1 ("bbb")
        [_FakeEventOm(_pygame_om.KEYDOWN, key=_pygame_om.K_RETURN)],     # grid: scegli "bbb" -> stato 'mode'
        [_FakeEventOm(_pygame_om.KEYDOWN, key=_pygame_om.K_RETURN)],     # mode: "Locale" (indice 0 di default)
        [_FakeEventOm(_pygame_om.KEYDOWN, key=_pygame_om.K_RETURN)],     # (di nuovo) grid: scegli - deve essere ANCORA "bbb"
        [_FakeEventOm(_pygame_om.KEYDOWN, key=_pygame_om.K_RETURN)],     # mode: "Locale" di nuovo
    ])
    _run_direct_returns.extend([False, True])

    _os_menu_om.run_os_menu()

    check("run_os_menu: run_direct chiamato esattamente 2 volte", len(_run_direct_calls), 2)
    check("run_os_menu: prima partita lanciata sulla cartuccia selezionata (indice 1, 'bbb')",
          _run_direct_calls[0][0], "/fake/bbb/game.py")
    check("run_os_menu: NESSUN netcode_session per 'Locale'", _run_direct_calls[0][2], None)
    check("run_os_menu: dopo ESC in game (False), il menu RIAPRE la STESSA cartuccia (indice preservato)",
          _run_direct_calls[1][0], _run_direct_calls[0][0])
    check("run_os_menu: chiusura finestra in game (True) -> pygame.quit() chiamato",
          _pygame_om.quit.called, True)
finally:
    _launcher_om.run_direct = _orig_run_direct_om

# scenario 2: ESC direttamente sulla griglia -> chiude subito, MAI
# chiamato run_direct
_pygame_om.quit.reset_mock()
_run_direct_calls.clear()
_launcher_om.run_direct = _fake_run_direct
try:
    _eventi_in_coda.append([_FakeEventOm(_pygame_om.KEYDOWN, key=_pygame_om.K_ESCAPE)])
    _os_menu_om.run_os_menu()
    check("run_os_menu: ESC sulla griglia chiude subito (pygame.quit chiamato)", _pygame_om.quit.called, True)
    check("run_os_menu: ESC sulla griglia non lancia mai una partita", len(_run_direct_calls), 0)
finally:
    _launcher_om.run_direct = _orig_run_direct_om

# scenario 3: "Ospita partita in rete" con i valori DI DEFAULT del
# form (porta 42420, 2 giocatori, invio subito) - verifica che
# start_netcode_host() venga davvero chiamato con quei valori e che
# la sessione venga chiusa (session.close()) dopo la partita.
class _FakeNetSession:
    def __init__(self):
        self.closed = False
    def close(self):
        self.closed = True

_host_calls = []
_fake_session_om = _FakeNetSession()

def _fake_start_netcode_host(port, num_players):
    _host_calls.append((port, num_players))
    return _fake_session_om, 0

_pygame_om.quit.reset_mock()
_run_direct_calls.clear()
_launcher_om.run_direct = _fake_run_direct
_orig_start_host_om = _launcher_om.start_netcode_host
_launcher_om.start_netcode_host = _fake_start_netcode_host
try:
    _eventi_in_coda.extend([
        [_FakeEventOm(_pygame_om.KEYDOWN, key=_pygame_om.K_RETURN)],   # grid: scegli "aaa" -> 'mode'
        [_FakeEventOm(_pygame_om.KEYDOWN, key=_pygame_om.K_DOWN)],     # mode: -> "Ospita partita in rete"
        [_FakeEventOm(_pygame_om.KEYDOWN, key=_pygame_om.K_RETURN)],   # mode: conferma -> 'host', campi di default
        [_FakeEventOm(_pygame_om.KEYDOWN, key=_pygame_om.K_RETURN)],   # host: conferma con i default
        [_FakeEventOm(_pygame_om.KEYDOWN, key=_pygame_om.K_ESCAPE)],  # torna al menu (False) poi esci subito
    ])
    _run_direct_returns.append(False)

    _os_menu_om.run_os_menu()

    check("run_os_menu 'Ospita': start_netcode_host chiamato con i valori di default del form",
          _host_calls, [(42420, 2)])
    check("run_os_menu 'Ospita': run_direct riceve la sessione di rete creata",
          _run_direct_calls[0][2] is _fake_session_om, True)
    check("run_os_menu 'Ospita': la sessione viene chiusa dopo la partita", _fake_session_om.closed, True)
finally:
    _launcher_om.run_direct = _orig_run_direct_om
    _launcher_om.start_netcode_host = _orig_start_host_om

# scenario 4: "Unisciti a partita in rete" - la scansione LAN trova UN
# host -> schermata 'join_pick', selezionandolo si collega DIRETTAMENTE
# (niente IP da digitare a mano). Risponde alla domanda dell'utente
# "come faccio a sapere l'IP dell'host?" - risposta: nella maggior
# parte dei casi non serve, il menu lo trova da solo.
_discover_queue = []

def _fake_discover_netcode_hosts(duration_s=2.0):
    return _discover_queue.pop(0)

_client_calls = []
_fake_session_client_om = _FakeNetSession()

def _fake_start_netcode_client(ip, port):
    _client_calls.append((ip, port))
    return _fake_session_client_om, 1

_pygame_om.quit.reset_mock()
_run_direct_calls.clear()
_launcher_om.run_direct = _fake_run_direct
_orig_discover_om = _launcher_om.discover_netcode_hosts
_orig_start_client_om = _launcher_om.start_netcode_client
_launcher_om.discover_netcode_hosts = _fake_discover_netcode_hosts
_launcher_om.start_netcode_client = _fake_start_netcode_client
try:
    _discover_queue.append([{'ip': '192.168.1.50', 'name': 'S32', 'port': 42420}])
    _eventi_in_coda.extend([
        [_FakeEventOm(_pygame_om.KEYDOWN, key=_pygame_om.K_RETURN)],               # grid: scegli "aaa" -> 'mode'
        [_FakeEventOm(_pygame_om.KEYDOWN, key=_pygame_om.K_DOWN)],
        [_FakeEventOm(_pygame_om.KEYDOWN, key=_pygame_om.K_DOWN)],                  # mode: -> "Unisciti a partita in rete"
        [_FakeEventOm(_pygame_om.KEYDOWN, key=_pygame_om.K_RETURN)],               # mode: conferma -> scansione -> 'join_pick'
        [_FakeEventOm(_pygame_om.KEYDOWN, key=_pygame_om.K_RETURN)],               # join_pick: sceglie l'unico host trovato
        [_FakeEventOm(_pygame_om.KEYDOWN, key=_pygame_om.K_ESCAPE)],               # torna al menu poi esci
    ])
    _run_direct_returns.append(False)

    _os_menu_om.run_os_menu()

    check("run_os_menu 'Unisciti' (host trovato): NON chiede l'IP a mano, si collega subito",
          _client_calls, [('192.168.1.50', 42420)])
    check("run_os_menu 'Unisciti' (host trovato): run_direct riceve la sessione creata",
          _run_direct_calls[0][2] is _fake_session_client_om, True)
finally:
    _launcher_om.run_direct = _orig_run_direct_om
    _launcher_om.discover_netcode_hosts = _orig_discover_om
    _launcher_om.start_netcode_client = _orig_start_client_om

# scenario 5: la scansione LAN non trova NESSUN host -> si ripiega
# SUBITO sul form manuale (nessun vicolo cieco)
_client_calls.clear()
_pygame_om.quit.reset_mock()
_run_direct_calls.clear()
_launcher_om.run_direct = _fake_run_direct
_launcher_om.discover_netcode_hosts = _fake_discover_netcode_hosts
_launcher_om.start_netcode_client = _fake_start_netcode_client
try:
    _discover_queue.append([])  # nessun host trovato
    _eventi_in_coda.extend([
        [_FakeEventOm(_pygame_om.KEYDOWN, key=_pygame_om.K_RETURN)],               # grid: scegli "aaa" -> 'mode'
        [_FakeEventOm(_pygame_om.KEYDOWN, key=_pygame_om.K_DOWN)],
        [_FakeEventOm(_pygame_om.KEYDOWN, key=_pygame_om.K_DOWN)],                  # mode: -> "Unisciti a partita in rete"
        [_FakeEventOm(_pygame_om.KEYDOWN, key=_pygame_om.K_RETURN)],               # mode: conferma -> scansione vuota -> form manuale 'join'
        [_FakeEventOm(_pygame_om.KEYDOWN, key=_pygame_om.K_RETURN)],               # join: conferma SENZA digitare nulla (usa il default precompilato)
        [_FakeEventOm(_pygame_om.KEYDOWN, key=_pygame_om.K_ESCAPE)],               # torna al menu poi esci
    ])
    _run_direct_returns.append(False)

    _os_menu_om.run_os_menu()

    check("run_os_menu 'Unisciti' (nessun host trovato): il form manuale e' precompilato con 127.0.0.1 (stesso PC)",
          _client_calls, [('127.0.0.1', 42420)])
finally:
    _launcher_om.run_direct = _orig_run_direct_om
    _launcher_om.discover_netcode_hosts = _orig_discover_om
    _launcher_om.start_netcode_client = _orig_start_client_om

print()
if fails == 0:
    print("Tutti i test passati.")
else:
    print(f"{fails} test falliti.")
