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

print()
if fails == 0:
    print("Tutti i test passati.")
else:
    print(f"{fails} test falliti.")
