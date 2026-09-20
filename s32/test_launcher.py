import os
import tempfile
import shutil

from launcher import determine_mode, load_cart_rom, LauncherError, _load_cart_graphics
from cpu import CPU

fails = 0

def check(label, got, expected):
    global fails
    status = "OK  " if got == expected else "FAIL"
    if got != expected:
        fails += 1
    print(f"{status} {label}: atteso {expected!r}, ottenuto {got!r}")

# ---------------------------------------------------------------
# Test 1: determine_mode - nessun argomento -> menu
# ---------------------------------------------------------------
check("nessun argomento -> menu", determine_mode(['launcher.py']), ('menu',))

# ---------------------------------------------------------------
# Test 2: determine_mode - con un file -> diretto, tipo corretto
# ---------------------------------------------------------------
check("file .py -> diretto/py", determine_mode(['launcher.py', 'carts/x/game.py']), ('direct', 'carts/x/game.py', 'py'))
check("file .asm -> diretto/asm", determine_mode(['launcher.py', 'carts/x/game.asm']), ('direct', 'carts/x/game.asm', 'asm'))
check("file .rom -> diretto/rom", determine_mode(['launcher.py', 'gioco.rom']), ('direct', 'gioco.rom', 'rom'))

# ---------------------------------------------------------------
# Test 3: determine_mode - estensione sconosciuta -> errore chiaro
# ---------------------------------------------------------------
try:
    determine_mode(['launcher.py', 'qualcosa.txt'])
    check("estensione sconosciuta: solleva errore", "nessun errore", "LauncherError")
except LauncherError:
    check("estensione sconosciuta: solleva errore", "LauncherError", "LauncherError")

# ---------------------------------------------------------------
# Test 4: load_cart_rom - cartuccia .asm pura
# ---------------------------------------------------------------
tmpdir = tempfile.mkdtemp(prefix='s32_launcher_test_')
try:
    asm_path = os.path.join(tmpdir, 'game.asm')
    with open(asm_path, 'w') as f:
        f.write('LDA #123\nSTA 0x3000\nHALT\n')
    rom, state_vars = load_cart_rom(asm_path, 'asm')
    check("cartuccia .asm: compila senza errori", len(rom) > 0, True)
    check("cartuccia .asm: nessuna state_vars (solo asm puro)", state_vars, {})

    # eseguo davvero il ROM caricato per confermare che sia corretto
    from launcher import CART_LOAD_ADDR
    c = CPU()
    for i, b in enumerate(rom):
        c.mem[CART_LOAD_ADDR + i] = b
    c.run(CART_LOAD_ADDR)
    check("cartuccia .asm: il ROM prodotto funziona davvero", c.read16(0x3000), 123)

    # ---------------------------------------------------------------
    # Test 4b: la OAM parte con TUTTI gli sprite nascosti di default
    # (Y=0xffff) - previene la regressione del bug dei "512 sprite
    # fantasma" trovato profilando su Raspberry Pi 1 (ogni slot mai
    # scritto aveva Y=0, quindi VISIBILE secondo la nostra convenzione,
    # costando tempo di rendering pur restando invisibile a schermo)
    # ---------------------------------------------------------------
    from memory_map import OAM_SIZE, OAM_SLOT_BYTES, OAM_BASE
    _load_cart_graphics(c, tmpdir)
    n_slots = OAM_SIZE // OAM_SLOT_BYTES
    all_hidden = True
    for slot in range(n_slots):
        base = OAM_BASE + slot * OAM_SLOT_BYTES
        y = c.mem[base + 2] | (c.mem[base + 3] << 8)
        if y < 0xfff0:
            all_hidden = False
            break
    check(f"OAM: tutti i {n_slots} slot partono nascosti di default", all_hidden, True)

    # ---------------------------------------------------------------
    # Test 5: load_cart_rom - cartuccia .py con SOURCE_LANG='asm'
    # ---------------------------------------------------------------
    py_asm_path = os.path.join(tmpdir, 'game_asm.py')
    with open(py_asm_path, 'w') as f:
        f.write('ROM_SOURCE = "LDA #77\\nSTA 0x3000\\nHALT\\n"\nSOURCE_LANG = "asm"\n')
    rom5, sv5 = load_cart_rom(py_asm_path, 'py')
    c5 = CPU()
    for i, b in enumerate(rom5):
        c5.mem[CART_LOAD_ADDR + i] = b
    c5.run(CART_LOAD_ADDR)
    check("cartuccia .py con SOURCE_LANG=asm funziona", c5.read16(0x3000), 77)

    # ---------------------------------------------------------------
    # Test 6: load_cart_rom - cartuccia .py con SOURCE_LANG='consolelang'
    # ---------------------------------------------------------------
    py_cl_path = os.path.join(tmpdir, 'game_cl.py')
    with open(py_cl_path, 'w') as f:
        f.write(
            'ROM_SOURCE = """\n'
            'var x = 55\n'
            'x = x + 1\n'
            'write_oam(0, x, 0, 0, 0)\n'
            '"""\n'
            'SOURCE_LANG = "consolelang"\n'
        )
    rom6, sv6 = load_cart_rom(py_cl_path, 'py')
    from memory_map import OAM_BASE
    c6 = CPU()
    for i, b in enumerate(rom6):
        c6.mem[CART_LOAD_ADDR + i] = b
    c6.run(CART_LOAD_ADDR)
    check("cartuccia .py con SOURCE_LANG=consolelang funziona", c6.read16(OAM_BASE), 56)

    # ---------------------------------------------------------------
    # Test 7: cartuccia .py senza ROM_SOURCE -> errore chiaro
    # ---------------------------------------------------------------
    bad_path = os.path.join(tmpdir, 'game_bad.py')
    with open(bad_path, 'w') as f:
        f.write('QUALCOSA_ALTRO = 1\n')
    try:
        load_cart_rom(bad_path, 'py')
        check("cartuccia senza ROM_SOURCE: solleva errore", "nessun errore", "LauncherError")
    except LauncherError:
        check("cartuccia senza ROM_SOURCE: solleva errore", "LauncherError", "LauncherError")

    # ---------------------------------------------------------------
    # Test 8: SOURCE_LANG sconosciuto -> errore chiaro
    # ---------------------------------------------------------------
    bad2_path = os.path.join(tmpdir, 'game_bad2.py')
    with open(bad2_path, 'w') as f:
        f.write('ROM_SOURCE = "HALT\\n"\nSOURCE_LANG = "cobol"\n')
    try:
        load_cart_rom(bad2_path, 'py')
        check("SOURCE_LANG sconosciuto: solleva errore", "nessun errore", "LauncherError")
    except LauncherError:
        check("SOURCE_LANG sconosciuto: solleva errore", "LauncherError", "LauncherError")

finally:
    shutil.rmtree(tmpdir)

# ---------------------------------------------------------------
# Test 9: formato .rom -> NotImplementedError esplicito (non un
# crash generico), coerente con la roadmap
# ---------------------------------------------------------------
try:
    load_cart_rom('qualcosa.rom', 'rom')
    check(".rom: solleva NotImplementedError", "nessun errore", "NotImplementedError")
except NotImplementedError:
    check(".rom: solleva NotImplementedError", "NotImplementedError", "NotImplementedError")

# ---------------------------------------------------------------
# Test 10: parse_flags - estrae --stats/--benchmark, lascia il resto
# ---------------------------------------------------------------
from launcher import parse_flags, run_benchmark
import io
import contextlib

rest1, flags1 = parse_flags(['launcher.py', 'gioco.py'])
check("nessun flag: dict tutto False (renderer='dirty-rects', ora default)", flags1, {'stats': False, 'benchmark': False, 'profile': False, 'renderer': 'dirty-rects', 'fullscreen': False, 'audio': True, 'playtest': False, 'playtest_quick': False, 'netplay_host_port': None, 'netplay_host_players': None, 'netplay_join_addr': None})
check("nessun flag: argv invariato", rest1, ['launcher.py', 'gioco.py'])

rest2, flags2 = parse_flags(['launcher.py', 'gioco.py', '--stats'])
check("--stats: rilevato", flags2['stats'], True)
check("--stats: rimosso da argv", rest2, ['launcher.py', 'gioco.py'])

rest3, flags3 = parse_flags(['launcher.py', '--benchmark', 'gioco.py'])
check("--benchmark: rilevato indipendentemente dalla posizione", flags3['benchmark'], True)
check("--benchmark: rimosso, resta solo il file", rest3, ['launcher.py', 'gioco.py'])

rest4, flags4 = parse_flags(['launcher.py', 'gioco.py', '--stats', '--benchmark'])
check("entrambi i flag insieme", flags4['stats'] and flags4['benchmark'], True)

rest4b, flags4b = parse_flags(['launcher.py', 'gioco.py', '--profile'])
check("--profile: rilevato", flags4b['profile'], True)
check("--profile: rimosso da argv", rest4b, ['launcher.py', 'gioco.py'])

rest4c, flags4c = parse_flags(['launcher.py', 'gioco.py', '--surface-renderer'])
check("--surface-renderer: imposta renderer='surface'", flags4c['renderer'], 'surface')
check("--surface-renderer: rimosso da argv", rest4c, ['launcher.py', 'gioco.py'])

rest4d, flags4d = parse_flags(['launcher.py', 'gioco.py', '--buffer-renderer'])
check("--buffer-renderer: imposta renderer='buffer'", flags4d['renderer'], 'buffer')
check("--buffer-renderer: rimosso da argv", rest4d, ['launcher.py', 'gioco.py'])

rest4e, flags4e = parse_flags(['launcher.py', 'gioco.py', '--fullscreen'])
check("--fullscreen: rilevato", flags4e['fullscreen'], True)
check("--fullscreen: rimosso da argv", rest4e, ['launcher.py', 'gioco.py'])

# L'audio e' ATTIVO DI DEFAULT - --no-audio per disattivarlo (utile
# su Raspberry Pi con ALSA mal configurato, vedi audio.py e
# AudioPlayer in launcher.py)
rest4f, flags4f = parse_flags(['launcher.py', 'gioco.py'])
check("audio: ATTIVO di default", flags4f['audio'], True)
rest4g, flags4g = parse_flags(['launcher.py', 'gioco.py', '--no-audio'])
check("--no-audio: disattiva quando richiesto", flags4g['audio'], False)
check("--no-audio: rimosso da argv", rest4g, ['launcher.py', 'gioco.py'])
rest4g2, flags4g2 = parse_flags(['launcher.py', 'gioco.py', '--audio'])
check("--audio: resta valido esplicitamente (ridondante ma non un errore)", flags4g2['audio'], True)
check("--audio: rimosso da argv", rest4g2, ['launcher.py', 'gioco.py'])

rest4h, flags4h = parse_flags(['launcher.py', 'gioco.py'])
check("--playtest: spento di DEFAULT", flags4h['playtest'], False)
rest4i, flags4i = parse_flags(['launcher.py', 'gioco.py', '--playtest'])
check("--playtest: rilevato quando richiesto", flags4i['playtest'], True)
check("--playtest: rimosso da argv", rest4i, ['launcher.py', 'gioco.py'])
check("--playtest (senza -quick): playtest_quick resta False", flags4i['playtest_quick'], False)

rest4j, flags4j = parse_flags(['launcher.py', 'gioco.py', '--playtest-quick'])
check("--playtest-quick: attiva sia playtest che playtest_quick", (flags4j['playtest'], flags4j['playtest_quick']), (True, True))
check("--playtest-quick: rimosso da argv", rest4j, ['launcher.py', 'gioco.py'])

rest4k, flags4k = parse_flags(['launcher.py', 'gioco.py', '--gpu-renderer'])
check("--gpu-renderer: imposta renderer='gpu'", flags4k['renderer'], 'gpu')
check("--gpu-renderer: rimosso da argv", rest4k, ['launcher.py', 'gioco.py'])

# ---------------------------------------------------------------
# --netplay-host / --netplay-join: consumano 2 argomenti SUCCESSIVI
# (porta+num_giocatori, o ip+porta) - a differenza di tutti gli
# altri flag, che sono semplici booleani. Lasciati fuori dal kit di
# rete originale apposta ("meglio scriverlo voi seguendo lo stile
# esistente"), aggiunti qui.
# ---------------------------------------------------------------
rest4l, flags4l = parse_flags(['launcher.py', 'gioco.py', '--netplay-host', '5555', '3'])
check("--netplay-host: porta interpretata correttamente", flags4l['netplay_host_port'], 5555)
check("--netplay-host: numero giocatori interpretato correttamente", flags4l['netplay_host_players'], 3)
check("--netplay-host: consuma i suoi 2 argomenti, non li lascia in argv", rest4l, ['launcher.py', 'gioco.py'])
check("--netplay-host: netplay_join_addr resta None", flags4l['netplay_join_addr'], None)

rest4m, flags4m = parse_flags(['launcher.py', 'gioco.py', '--netplay-join', '192.168.1.5', '5555'])
check("--netplay-join: (ip, porta) interpretati correttamente", flags4m['netplay_join_addr'], ('192.168.1.5', 5555))
check("--netplay-join: consuma i suoi 2 argomenti", rest4m, ['launcher.py', 'gioco.py'])
check("--netplay-join: netplay_host_port resta None", flags4m['netplay_host_port'], None)

# argomenti mancanti - deve fallire in modo chiaro, non con un
# IndexError o silenziosamente
try:
    parse_flags(['launcher.py', 'gioco.py', '--netplay-host'])
    check("--netplay-host senza argomenti: doveva sollevare LauncherError", False, True)
except LauncherError:
    check("--netplay-host senza argomenti: solleva LauncherError come atteso", True, True)

try:
    parse_flags(['launcher.py', 'gioco.py', '--netplay-host', '5555'])
    check("--netplay-host con un solo argomento: doveva sollevare LauncherError", False, True)
except LauncherError:
    check("--netplay-host con un solo argomento: solleva LauncherError come atteso", True, True)

# valori non numerici dove serve un numero
try:
    parse_flags(['launcher.py', 'gioco.py', '--netplay-host', 'abc', '2'])
    check("--netplay-host con porta non numerica: doveva sollevare LauncherError", False, True)
except LauncherError:
    check("--netplay-host con porta non numerica: solleva LauncherError come atteso", True, True)

try:
    parse_flags(['launcher.py', 'gioco.py', '--netplay-join', '192.168.1.5', 'abc'])
    check("--netplay-join con porta non numerica: doveva sollevare LauncherError", False, True)
except LauncherError:
    check("--netplay-join con porta non numerica: solleva LauncherError come atteso", True, True)

# numero giocatori fuori dal range valido (2-8: sotto 2 non e'
# multiplayer, EXTRA_INPUT_PORTS in cpu.py copre al massimo 8 in
# totale)
for _n_non_valido in (0, 1, 9, 99):
    try:
        parse_flags(['launcher.py', 'gioco.py', '--netplay-host', '5555', str(_n_non_valido)])
        check(f"--netplay-host con {_n_non_valido} giocatori (fuori range 2-8): doveva sollevare LauncherError", False, True)
    except LauncherError:
        check(f"--netplay-host con {_n_non_valido} giocatori (fuori range 2-8): solleva LauncherError come atteso", True, True)

# nessun flag di rete -> tutti None, nessuna interferenza con gli
# altri flag esistenti
rest4n, flags4n = parse_flags(['launcher.py', 'gioco.py', '--stats', '--fullscreen'])
check("nessun flag di rete: i tre campi netplay restano None",
      (flags4n['netplay_host_port'], flags4n['netplay_host_players'], flags4n['netplay_join_addr']),
      (None, None, None))
check("nessun flag di rete: gli altri flag continuano a funzionare normalmente",
      (flags4n['stats'], flags4n['fullscreen']), (True, True))

# ---------------------------------------------------------------
# _sdl2_video(): compatibilita' pygame-ce (nomi diretti) vs pygame
# mainline (pygame._sdl2.video) - le due varianti divergono qui,
# trovato testando Pi (mainline) e Windows (pygame-ce) nella stessa
# conversazione
# ---------------------------------------------------------------
import types as _types
from launcher import _sdl2_video

_pg_ce = _types.ModuleType('pygame_ce_fake')
_pg_ce.Window = 'W'
_pg_ce.Renderer = 'R'
_pg_ce.Texture = 'T'
_ns = _sdl2_video(_pg_ce)
check("_sdl2_video: usa i nomi diretti quando disponibili (pygame-ce)",
      (_ns.Window, _ns.Renderer, _ns.Texture), ('W', 'R', 'T'))

_pg_mainline = _types.ModuleType('pygame_mainline_fake')
_sdl2_pkg = _types.ModuleType('pygame._sdl2')
_video_pkg = _types.ModuleType('pygame._sdl2.video')
_video_pkg.Window = 'W2'
_video_pkg.Renderer = 'R2'
_video_pkg.Texture = 'T2'
import sys as _sys
_sys.modules['pygame._sdl2'] = _sdl2_pkg
_sys.modules['pygame._sdl2.video'] = _video_pkg
_ns2 = _sdl2_video(_pg_mainline)
check("_sdl2_video: ripiega su pygame._sdl2.video quando i nomi diretti mancano (mainline)",
      (_ns2.Window, _ns2.Renderer, _ns2.Texture), ('W2', 'R2', 'T2'))

# ---------------------------------------------------------------
# GpuRenderer: stessa logica di IncrementalRenderer (rebuild
# completo/incrementale, cache sprite) ma con Renderer+Texture al
# posto di Surface/blit - verificato con un mock completo
# ---------------------------------------------------------------
from launcher import GpuRenderer

_chiamate = []

class _FakeSurfaceGR:
    def __init__(self, size=None, *a, **k):
        self.size = size
    def scroll(self, dx, dy): pass
    def blit(self, *a, **k): pass
    def convert(self):
        # pygame vero: .convert() richiede un display "classico" attivo
        # (pygame.display.set_mode()) - in modalita' GPU non esiste mai
        # (finestra dedicata via _sdl2.video.Window). Un mock che
        # accettasse sempre .convert() (come "return self") avrebbe
        # MASCHERATO il bug reale trovato dall'utente su Pi
        # ("pygame.error: Parameter 'surface' is invalid") - qui invece
        # fallisce, cosi' GpuRenderer deve DAVVERO evitare di chiamarlo.
        raise RuntimeError("Parameter 'surface' is invalid (nessun display classico attivo)")
    def set_at(self, *a, **k): pass
    def fill(self, *a, **k): pass

class _FakeTextureGR:
    def __init__(self, renderer, surface):
        _chiamate.append('texture_creata')
    def update(self, surface, area=None):
        _chiamate.append(('texture_update', getattr(surface, 'size', None), area))
    def draw(self, dstrect=None, **k):
        _chiamate.append(('texture_draw', dstrect))
    @classmethod
    def from_surface(cls, renderer, surface):
        _chiamate.append('from_surface')
        return cls(renderer, surface)

class _FakeRendererGR:
    def clear(self):
        _chiamate.append('clear')
    def present(self):
        _chiamate.append('present')

_video_pkg.Texture = _FakeTextureGR
_video_pkg.Renderer = _FakeRendererGR

_pygame_gr = _types.ModuleType('pygame_gr_fake')
_pygame_gr.SRCALPHA = 4
_pygame_gr.Surface = _FakeSurfaceGR
_pygame_gr.image = _types.SimpleNamespace(frombuffer=lambda data, size, fmt: _FakeSurfaceGR(size))

_gr = GpuRenderer(_pygame_gr, _FakeRendererGR())

_vram_gr = bytearray(200000)
_cgram_gr = bytearray(10000)
_oam_gr = bytearray(512)
def _write_slot_gr(oam, slot, x, y, tile, attr=0):
    b = slot * 8
    oam[b] = x & 0xff; oam[b+1] = (x >> 8) & 0xff
    oam[b+2] = y & 0xff; oam[b+3] = (y >> 8) & 0xff
    oam[b+4] = tile & 0xff; oam[b+5] = (tile >> 8) & 0xff
    oam[b+6] = attr & 0xff; oam[b+7] = (attr >> 8) & 0xff
for _s in range(64):
    _write_slot_gr(_oam_gr, _s, 0, 0xFFFF, 0)
_write_slot_gr(_oam_gr, 0, 200, 150, 16)

_chiamate.clear()
_gr.render(_vram_gr, _oam_gr, _cgram_gr, current_stage=1, scroll_x=0, scroll_y=0)
check("GpuRenderer: primo frame chiama clear()", 'clear' in _chiamate, True)
check("GpuRenderer: primo frame chiama present()", 'present' in _chiamate, True)
_draws = [c for c in _chiamate if isinstance(c, tuple) and c[0] == 'texture_draw']
check("GpuRenderer: primo frame disegna sfondo + 1 sprite (2 texture_draw)", len(_draws), 2)
check("GpuRenderer: primo frame crea le texture (bg_texture era None)",
      _chiamate.count('from_surface'), 2)  # sfondo + 1 sprite

_chiamate.clear()
_gr.render(_vram_gr, _oam_gr, _cgram_gr, current_stage=1, scroll_x=0, scroll_y=0)
_updates_vuoto = [c for c in _chiamate if isinstance(c, tuple) and c[0] == 'texture_update']
check("GpuRenderer: frame successivo SENZA cambiamenti non ricrea/aggiorna texture",
      'from_surface' in _chiamate or len(_updates_vuoto) > 0, False)

# -- il fix corretto (dopo che il primo tentativo - aggiornare solo
# la striscia - si e' rivelato un bug di correttezza, trovato
# dall'utente GIOCANDO DAVVERO: "il personaggio sembrava stazionario
# e i nemici oltrepassavano il muro". La texture GPU non ha un
# equivalente di Surface.scroll() (che sposta FISICAMENTE i pixel
# gia' disegnati nella Surface CPU) - update(area=striscia) scrive
# SOLO quella striscia, lasciando il resto della texture congelato
# alla vecchia posizione. Quindi: anche durante uno scroll piccolo,
# va spinto l'INTERO bg_surface (gia' corretto in CPU), area=None --
from memory_map import SCREEN_W_PX as _SW, SCREEN_H_PX as _SH

_chiamate.clear()
_gr.render(_vram_gr, _oam_gr, _cgram_gr, current_stage=1, scroll_x=0, scroll_y=10)
_updates = [c for c in _chiamate if isinstance(c, tuple) and c[0] == 'texture_update']
check("GpuRenderer: scroll cambiato -> update() la texture esistente", len(_updates) == 1, True)
if _updates:
    _surf_size, _area = _updates[0][1], _updates[0][2]
    check("GpuRenderer: scroll piccolo -> la surface passata e' l'INTERO sfondo (480,320), non solo la striscia",
          _surf_size, (_SW, _SH))
    check("GpuRenderer: scroll piccolo -> area=None (texture GPU non sa 'scrollare' il contenuto gia' caricato)",
          _area, None)
check("GpuRenderer: scroll cambiato -> NON ricrea la texture da zero",
      'from_surface' in _chiamate, False)

# -- controllo simmetrico: un rebuild completo (cambio stanza) DEVE
# ancora aggiornare l'INTERA texture (area=None) - il fix riguarda
# solo lo scroll incrementale, non deve rompere il caso normale.
# bg_texture esiste gia' dal primo frame, quindi qui si aggiorna
# quella esistente con l'intero nuovo sfondo, non se ne ricrea una --
_chiamate.clear()
_gr.render(_vram_gr, _oam_gr, _cgram_gr, current_stage=2, scroll_x=0, scroll_y=0)
_updates_rebuild = [c for c in _chiamate if isinstance(c, tuple) and c[0] == 'texture_update']
check("GpuRenderer: cambio stanza -> UN SOLO update() con l'intera texture",
      len(_updates_rebuild), 1)
if _updates_rebuild:
    check("GpuRenderer: cambio stanza -> area=None (intera texture, non una striscia)",
          _updates_rebuild[0][2], None)
# l'atlas sprite NON si svuota al cambio stanza (tile_index e' un
# identificatore stabile in tutto il cartridge - vedi GpuRenderer) -
# il tile gia' in cache resta tale, nessun from_surface/update extra
# per lo sprite qui: l'unico update() visto sopra e' quello dello
# SFONDO (il rebuild completo della stanza), non dello sprite
check("GpuRenderer: cambio stanza -> l'atlas sprite gia' cachato NON si ricrea",
      'from_surface' in _chiamate, False)

# -- proprieta' chiave dell'atlas condiviso: uno sprite con un tile
# MAI VISTO PRIMA deve aggiungersi all'atlas ESISTENTE (update() su
# uno slot nuovo), non creare una texture separata - questo e' il
# punto di tutta l'ottimizzazione, richiesta dall'utente dopo aver
# visto draw_sprites costare ~15-17ms: il sospetto e' che il costo
# dominante fosse il CAMBIO di texture tra uno sprite e l'altro --
_write_slot_gr(_oam_gr, 1, 250, 180, 20)  # tile diverso (20), mai visto prima
_chiamate.clear()
_gr.render(_vram_gr, _oam_gr, _cgram_gr, current_stage=2, scroll_x=0, scroll_y=0)
_draws_due_sprite = [c for c in _chiamate if isinstance(c, tuple) and c[0] == 'texture_draw']
check("GpuRenderer: due sprite (tile diversi) -> ancora sfondo + 2 texture_draw",
      len(_draws_due_sprite), 3)  # sfondo + 2 sprite
check("GpuRenderer: tile nuovo -> aggiunto all'atlas ESISTENTE (update, non from_surface)",
      'from_surface' in _chiamate, False)
_updates_nuovo_tile = [c for c in _chiamate if isinstance(c, tuple) and c[0] == 'texture_update']
check("GpuRenderer: tile nuovo -> esattamente un update() (il nuovo slot nell'atlas)",
      len(_updates_nuovo_tile), 1)

# ---------------------------------------------------------------
# _playtest_sequence(): la sequenza scriptata usata da --playtest
# per guidare il gioco senza tastiera (vedi README) - deterministica,
# copre piu' fasi, e include davvero movimento/scroll/attacco
# ---------------------------------------------------------------
from launcher import _playtest_sequence

seq_a = _playtest_sequence()
seq_b = _playtest_sequence()
check("_playtest_sequence: deterministica (stessa sequenza ogni volta)",
      seq_a == seq_b, True)
check("_playtest_sequence: non vuota", len(seq_a) > 1000, True)

etichette = {label for label, _ in seq_a}
check("_playtest_sequence: copre tutte e 5 le fasi attese",
      etichette, {'1-fermo (baseline)', '2-scroll continuo giu',
                   '2-scroll continuo su', '2b-scroll sostenuto',
                   '3-attacco ripetuto', '4-esplorazione mista'})

byte_usati = {byte for _, byte in seq_a}
check("_playtest_sequence: usa piu' input diversi da zero (non solo fermo)",
      len(byte_usati - {0}) > 1, True)

# --playtest-quick: richiesto dall'utente - un test completo su Pi 1
# supera i 6 minuti, abbastanza da rischiare throttling termico che
# confonde la misura. La versione quick copre le stesse 6 fasi in
# una frazione del tempo.
seq_quick = _playtest_sequence(quick=True)
check("_playtest_sequence(quick=True): sensibilmente piu' corta (almeno 3x)",
      len(seq_a) > len(seq_quick) * 3, True)
etichette_quick = {label for label, _ in seq_quick}
check("_playtest_sequence(quick=True): copre comunque tutte e 6 le fasi",
      etichette_quick, etichette)
check("_playtest_sequence(quick=True): deterministica",
      _playtest_sequence(quick=True) == seq_quick, True)

fase3 = [byte for label, byte in seq_a if label == '3-attacco ripetuto']
check("_playtest_sequence: la fase attacco alterna J premuto/rilasciato",
      0x10 in fase3 and 0 in fase3, True)

# ---------------------------------------------------------------
# I due test seguenti eseguono la sequenza contro il motore VERO
# (non solo ispezionano la lista) - servono a verificare proprieta'
# che dipendono dal comportamento del gioco, non solo dalla sequenza
# di byte in se'.
# ---------------------------------------------------------------
import sys as _sys
_sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'carts', 'adventure_asm'))
_rom, _ = load_cart_rom(
    os.path.join(os.path.dirname(__file__), '..', 'carts', 'adventure_asm', 'game.asm'), 'asm')
_c = CPU()
for _i, _b in enumerate(_rom):
    _c.mem[CART_LOAD_ADDR + _i] = _b
_load_cart_graphics(_c, os.path.join(os.path.dirname(__file__), '..', 'carts', 'adventure_asm'))
_c.run(CART_LOAD_ADDR, input_byte=0)
_c.run(CART_LOAD_ADDR, input_byte=16)

_fase_target = '2b-scroll sostenuto'
_scroll_cambiato = 0
_scroll_fermo = 0
_prev_scroll = None
for _label, _byte in seq_a:
    _c.run(CART_LOAD_ADDR, input_byte=_byte)
    if _label == _fase_target and _c.read16(0x000100) == 1:  # solo mentre si gioca
        _s = _c.scroll_y
        if _prev_scroll is not None:
            if _s != _prev_scroll:
                _scroll_cambiato += 1
            else:
                _scroll_fermo += 1
        _prev_scroll = _s
_pct_attivo = _scroll_cambiato / (_scroll_cambiato + _scroll_fermo) * 100
# soglia onesta, non 90%: la fase attraversa un ingresso nella
# finestra attiva (frame sotto soglia per costruzione) e puo'
# incontrare i nemici (morte + game-over reali, gia' verificati dal
# test della rete di sicurezza sopra) - qui verifichiamo solo che
# resti un campione utile di scroll attivo, non un valore ideale
# irraggiungibile
check("_playtest_sequence: fase 2b produce un campione utile di scroll attivo (>20%)",
      _pct_attivo > 20, True)

# rete di sicurezza: se il giocatore muore durante il playtest, deve
# sempre tornare a giocare (mai restare bloccato fino alla fine)
_c2 = CPU()
for _i, _b in enumerate(_rom):
    _c2.mem[CART_LOAD_ADDR + _i] = _b
_load_cart_graphics(_c2, os.path.join(os.path.dirname(__file__), '..', 'carts', 'adventure_asm'))
_c2.run(CART_LOAD_ADDR, input_byte=0)
_c2.run(CART_LOAD_ADDR, input_byte=16)
_morti = 0
_riavvii = 0
_prev_mode = 1
for _label, _byte in seq_a:
    _c2.run(CART_LOAD_ADDR, input_byte=_byte)
    _mode = _c2.read16(0x000100)
    if _mode == 2 and _prev_mode != 2:
        _morti += 1
    if _mode == 1 and _prev_mode == 0:
        _riavvii += 1
    _prev_mode = _mode
check("_playtest_sequence: rete di sicurezza - ogni morte durante il playtest si riavvia da sola",
      _riavvii, _morti)

# ---------------------------------------------------------------
# Test 11: run_benchmark - gira davvero, senza aprire alcuna finestra
# ---------------------------------------------------------------
tmpdir2 = tempfile.mkdtemp(prefix='s32_benchmark_test_')
try:
    bench_asm = os.path.join(tmpdir2, 'game.asm')
    with open(bench_asm, 'w') as f:
        f.write('HALT\n')
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        run_benchmark(bench_asm, 'asm', n_frames=5)
    text = output.getvalue()
    check("run_benchmark: stampa 'cpu.run()'", 'cpu.run()' in text, True)
    check("run_benchmark: stampa 'render_frame()'", 'render_frame()' in text, True)
    check("run_benchmark: stampa la RAM di picco", 'RAM di picco' in text, True)

    output2 = io.StringIO()
    with contextlib.redirect_stdout(output2):
        run_benchmark(bench_asm, 'asm', n_frames=5, profile=True)
    text2 = output2.getvalue()
    check("run_benchmark(profile=True): stampa il profilo dettagliato", 'profilo dettagliato' in text2, True)
    check("run_benchmark(profile=True): elenca le funzioni (cumulative)", 'cumulative' in text2, True)
finally:
    shutil.rmtree(tmpdir2)

# ---------------------------------------------------------------
# Test 12: AudioPlayer riceve il banco suoni DALL'ESTERNO (dalla
# cartuccia, via cpu.sound_bank) - non lo costruisce piu' da solo.
# Corretto dopo che l'utente ha notato che i suoni di Adventure
# erano finiti per errore nel motore invece che nella cartuccia.
# ---------------------------------------------------------------
from launcher import AudioPlayer
import types as _types_audio

_pygame_audio = _types_audio.ModuleType('pygame_audio_fake')
_pygame_audio.mixer = _types_audio.SimpleNamespace(
    init=lambda **k: None,
    get_init=lambda: (22050, -16, 1),
    Sound=lambda buffer: _types_audio.SimpleNamespace(play=lambda: None),
)

_ap_vuoto = AudioPlayer(_pygame_audio, enabled=True, sound_bank=None)
check("AudioPlayer: sound_bank=None -> nessun suono caricato ma mixer attivo",
      (_ap_vuoto.enabled, len(_ap_vuoto.sounds)), (True, 0))

_banco_finto = {1: b'\x00\x00' * 10, 2: b'\x00\x00' * 10}
_ap_pieno = AudioPlayer(_pygame_audio, enabled=True, sound_bank=_banco_finto)
check("AudioPlayer: carica esattamente i suoni ricevuti dal banco passato",
      set(_ap_pieno.sounds.keys()), {1, 2})

_ap_off = AudioPlayer(_pygame_audio, enabled=False, sound_bank=_banco_finto)
check("AudioPlayer: enabled=False -> non carica nulla anche con un banco valido",
      (_ap_off.enabled, len(_ap_off.sounds)), (False, 0))

# -- verifica end-to-end: _load_cart_graphics carica DAVVERO il
# banco suoni della cartuccia in cpu.sound_bank (non un mock - il
# vero cart.py/sound_bank.py di Adventure) --
from launcher import CART_LOAD_ADDR
_rom_audio, _ = load_cart_rom(
    os.path.join(os.path.dirname(__file__), '..', 'carts', 'adventure_asm', 'game.asm'), 'asm')
_c_audio = CPU()
for _i, _b in enumerate(_rom_audio):
    _c_audio.mem[CART_LOAD_ADDR + _i] = _b
_load_cart_graphics(_c_audio, os.path.join(os.path.dirname(__file__), '..', 'carts', 'adventure_asm'))
check("_load_cart_graphics: popola cpu.sound_bank con i 9 suoni di Adventure",
      sorted(_c_audio.sound_bank.keys()), list(range(1, 10)))

_c_senza_cart = CPU()
_load_cart_graphics(_c_senza_cart, tempfile.mkdtemp(prefix='s32_no_cart_'))
check("_load_cart_graphics: senza cart.py, sound_bank resta vuoto (nessun crash)",
      _c_senza_cart.sound_bank, {})

# ---------------------------------------------------------------
# Test 13: aggancio netcode nel game loop (_run_pygame_loop) -
# verifica che una sessione di rete (host o client di
# netcode_lockstep.py) venga davvero usata: input locale inviato ad
# ogni frame, un frame "in lag" (risposta non ancora arrivata)
# ririchiesto SENZA far avanzare la simulazione, poi ripresa normale
# una volta risolto. Mock completo di pygame, non solo GpuRenderer -
# qui serve l'intero _run_pygame_loop.
# ---------------------------------------------------------------
import types as _types_net, io as _io_net, contextlib as _ctx_net
from unittest.mock import MagicMock as _MagicMock_net

_pygame_net = _types_net.ModuleType('pygame_netcode_fake')
_pygame_net.QUIT = 1
_pygame_net.SRCALPHA = 4

class _FakeSurfaceNet:
    def __init__(self, *a, **k): pass
    def scroll(self, dx, dy): pass
    def blit(self, *a, **k): pass
    def convert(self): return self
    def set_at(self, *a, **k): pass
    def fill(self, *a, **k): pass

class _FakeClockNet:
    def tick(self, fps): pass

_pygame_net.init = _MagicMock_net()
_pygame_net.get_init = _MagicMock_net(return_value=False)
_pygame_net.mixer = _MagicMock_net()
_pygame_net.mouse = _MagicMock_net()
_pygame_net.display = _MagicMock_net()
_pygame_net.display.set_mode = _MagicMock_net(return_value=_FakeSurfaceNet())
_pygame_net.display.flip = _MagicMock_net()
_pygame_net.display.update = _MagicMock_net()
_pygame_net.event = _MagicMock_net()
_pygame_net.event.get = _MagicMock_net(return_value=[])
_pygame_net.key = _MagicMock_net()
_pygame_net.key.get_pressed = _MagicMock_net(return_value={})
_pygame_net.time = _MagicMock_net()
_pygame_net.time.Clock = _MagicMock_net(return_value=_FakeClockNet())
_pygame_net.Surface = _FakeSurfaceNet
_pygame_net.Rect = lambda x, y, w, h: _types_net.SimpleNamespace(x=x, y=y, w=w, h=h, topleft=(x, y))
_pygame_net.image = _MagicMock_net()
_pygame_net.image.frombuffer = _MagicMock_net(return_value=_FakeSurfaceNet())

class _FintaSessioneNetcode:
    """Finge una LockstepHost/LockstepClient: per i primi N tentativi
    di un dato frame risponde None (input non ancora arrivato da
    tutti - simula lag), poi risponde con un vettore a 2 giocatori."""
    def __init__(self, frame_saltati_prima_di_rispondere=3):
        self.invii = []
        self.richieste = []
        self.frame_saltati_prima_di_rispondere = frame_saltati_prima_di_rispondere
        self._tentativi_per_frame = {}
        self._ultimo_input_locale = 0

    def submit_local_input(self, frame_number, input_byte):
        self._ultimo_input_locale = input_byte
        self.invii.append((frame_number, input_byte))

    def get_frame_inputs(self, frame_number, timeout=0.25):
        self.richieste.append(frame_number)
        tentativi = self._tentativi_per_frame.get(frame_number, 0)
        self._tentativi_per_frame[frame_number] = tentativi + 1
        if tentativi < self.frame_saltati_prima_di_rispondere:
            return None
        return (self._ultimo_input_locale, 0x07)  # giocatore locale + un secondo finto

_sys.modules['pygame'] = _pygame_net
import importlib
import launcher
importlib.reload(launcher)

_sessione_netcode = _FintaSessioneNetcode(frame_saltati_prima_di_rispondere=3)
_buf_net = _io_net.StringIO()
with _ctx_net.redirect_stdout(_buf_net):
    launcher.run_direct(
        os.path.join(os.path.dirname(__file__), '..', 'carts', 'adventure_asm', 'game.asm'), 'asm',
        show_stats=False, quit_pygame_at_end=False, renderer_mode='dirty-rects',
        playtest=True, playtest_quick=True,
        netcode_session=_sessione_netcode, local_player_index=0)

check("netcode: l'input locale viene DAVVERO inviato alla sessione ad ogni frame",
      len(_sessione_netcode.invii) > 0, True)
check("netcode: un frame in lag viene ririchiesto esattamente (tentativi_lag + 1) volte",
      _sessione_netcode.richieste.count(0), _sessione_netcode.frame_saltati_prima_di_rispondere + 1)
check("netcode: dopo il lag simulato, la sessione arriva a richiedere frame successivi (la simulazione riprende)",
      max(_sessione_netcode.richieste) > 0, True)

# ---------------------------------------------------------------
# Test 13bis: un errore di rete A META' PARTITA (non solo al momento
# di connettersi, gia' gestito da os_menu.py) non deve crashare
# l'intera applicazione - segnalato dall'utente giocando davvero tra
# due reti diverse (casa/lavoro), molto piu' soggette a blip di rete
# di una singola LAN locale. run_direct() deve tornare normalmente
# (quit_requested=False, si torna al menu), non propagare l'OSError.
# ---------------------------------------------------------------
class _SessioneCheCadeAMetaPartita:
    def __init__(self, fallisce_al_frame=3):
        self.fallisce_al_frame = fallisce_al_frame
        self.invii = 0
    def submit_local_input(self, frame_number, input_byte):
        self.invii += 1
        if self.invii >= self.fallisce_al_frame:
            raise OSError("Network is unreachable")
    def get_frame_inputs(self, frame_number, timeout=0.25):
        return (0, 0)  # mai raggiunto: submit_local_input fallisce prima

_sessione_cade = _SessioneCheCadeAMetaPartita(fallisce_al_frame=3)
_buf_crash = _io_net.StringIO()
with _ctx_net.redirect_stdout(_buf_crash):
    _quit_richiesto = launcher.run_direct(
        os.path.join(os.path.dirname(__file__), '..', 'carts', 'adventure_asm', 'game.asm'), 'asm',
        show_stats=False, quit_pygame_at_end=False, renderer_mode='dirty-rects',
        playtest=True, playtest_quick=True,
        netcode_session=_sessione_cade, local_player_index=0)

check("un OSError a meta' partita NON crasha - run_direct() ritorna normalmente", _quit_richiesto, False)
check("un OSError a meta' partita: il tentativo che fallisce viene registrato", _sessione_cade.invii >= 3, True)

# ---------------------------------------------------------------
# Test 14: start_netcode_host() annuncia sulla LAN (LanAnnouncer) per
# tutta l'attesa - aggiunto dopo che l'utente ha chiesto "come faccio
# a sapere l'IP dell'host per unirmi?": la risposta e' che l'host lo
# annuncia da solo in broadcast, vedi anche discover_netcode_hosts()
# e os_menu.py (schermata "Unisciti a partita").
# ---------------------------------------------------------------
import netcode_lockstep as _ncl

class _FakeAnnouncer:
    instances = []
    def __init__(self, game_name, connect_port, avatar=0):
        self.game_name = game_name
        self.connect_port = connect_port
        self.avatar = avatar
        self.started = False
        self.stopped = False
        _FakeAnnouncer.instances.append(self)
    def start(self):
        self.started = True
    def stop(self):
        self.stopped = True

class _FakeHostSession:
    def __init__(self, num_players, bind_port):
        self.num_players = num_players
        self.bind_port = bind_port
    def wait_for_players(self):
        pass

_orig_LockstepHost = _ncl.LockstepHost
_orig_LanAnnouncer = _ncl.LanAnnouncer
_ncl.LockstepHost = _FakeHostSession
_ncl.LanAnnouncer = _FakeAnnouncer
try:
    _FakeAnnouncer.instances.clear()
    _sessione_host, _idx_host = launcher.start_netcode_host(12345, 3)
    check("start_netcode_host: ritorna sempre local_player_index=0 (l'host)", _idx_host, 0)
    check("start_netcode_host: crea UN LanAnnouncer con la porta giusta",
          (len(_FakeAnnouncer.instances), _FakeAnnouncer.instances[0].connect_port), (1, 12345))
    check("start_netcode_host: annuncia PRIMA/DURANTE l'attesa (start chiamato)",
          _FakeAnnouncer.instances[0].started, True)
    check("start_netcode_host: smette di annunciare una volta partiti (stop chiamato)",
          _FakeAnnouncer.instances[0].stopped, True)
    check("start_netcode_host: senza host_name/avatar, usa i default ('S32', 0)",
          (_FakeAnnouncer.instances[0].game_name, _FakeAnnouncer.instances[0].avatar), ('S32', 0))
finally:
    _ncl.LockstepHost = _orig_LockstepHost
    _ncl.LanAnnouncer = _orig_LanAnnouncer

# host_name/avatar (dal profilo, vedi profile.py/os_menu.py) devono
# arrivare fino a LanAnnouncer - chi cerca partite deve vedere
# l'identita' scelta dall'utente, non sempre "S32"
_ncl.LockstepHost = _FakeHostSession
_ncl.LanAnnouncer = _FakeAnnouncer
try:
    _FakeAnnouncer.instances.clear()
    launcher.start_netcode_host(12345, 2, host_name='Mario', avatar=2)
    check("start_netcode_host: propaga host_name/avatar a LanAnnouncer",
          (_FakeAnnouncer.instances[0].game_name, _FakeAnnouncer.instances[0].avatar), ('Mario', 2))
finally:
    _ncl.LockstepHost = _orig_LockstepHost
    _ncl.LanAnnouncer = _orig_LanAnnouncer

# l'annuncio va fermato ANCHE se wait_for_players() fallisce - mai
# lasciare un annuncio "fantasma" in broadcast se qualcosa va storto
class _FakeHostSessionCheFallisce(_FakeHostSession):
    def wait_for_players(self):
        raise TimeoutError("nessuno si e' unito in tempo")

_ncl.LockstepHost = _FakeHostSessionCheFallisce
_ncl.LanAnnouncer = _FakeAnnouncer
try:
    _FakeAnnouncer.instances.clear()
    try:
        launcher.start_netcode_host(12345, 2)
        check("start_netcode_host: propaga l'eccezione di wait_for_players", "nessun errore", "TimeoutError")
    except TimeoutError:
        check("start_netcode_host: propaga l'eccezione di wait_for_players", "TimeoutError", "TimeoutError")
    check("start_netcode_host: annuncio fermato ANCHE se wait_for_players fallisce",
          _FakeAnnouncer.instances[0].stopped, True)
finally:
    _ncl.LockstepHost = _orig_LockstepHost
    _ncl.LanAnnouncer = _orig_LanAnnouncer

# ---------------------------------------------------------------
# Test 15: discover_netcode_hosts() - scansione LAN lato client
# ---------------------------------------------------------------
class _FakeBrowser:
    instances = []
    def __init__(self):
        self.closed = False
        _FakeBrowser.instances.append(self)
    def scan(self, duration_s):
        self.scanned_for = duration_s
        return [{'ip': '192.168.1.50', 'name': 'S32', 'port': 42420}]
    def close(self):
        self.closed = True

_orig_LanBrowser = _ncl.LanBrowser
_ncl.LanBrowser = _FakeBrowser
try:
    _FakeBrowser.instances.clear()
    _risultati_scan = launcher.discover_netcode_hosts(duration_s=1.5)
    check("discover_netcode_hosts: ritorna gli host trovati da LanBrowser.scan()",
          _risultati_scan, [{'ip': '192.168.1.50', 'name': 'S32', 'port': 42420}])
    check("discover_netcode_hosts: passa duration_s a scan()", _FakeBrowser.instances[0].scanned_for, 1.5)
    check("discover_netcode_hosts: chiude sempre il browser dopo", _FakeBrowser.instances[0].closed, True)
finally:
    _ncl.LanBrowser = _orig_LanBrowser

# ---------------------------------------------------------------
# Test 16: main() non crasha con un traceback grezzo se la
# connessione di rete fallisce (es. "getaddrinfo failed" per un IP
# non valido/non risolvibile con --netplay-join) - segnalato
# dall'utente testando host e client sullo stesso PC. Un errore di
# rete termina con un messaggio chiaro (SystemExit(1)), MAI
# arrivando a run_direct().
# ---------------------------------------------------------------
import sys as _sys_main

_orig_argv_main = _sys_main.argv
_orig_start_client_main = launcher.start_netcode_client
_orig_run_direct_main = launcher.run_direct

def _fake_start_client_che_fallisce(ip, port):
    raise OSError("[Errno -2] Name or service not known")

_run_direct_mai_chiamato = []

def _run_direct_non_dovrebbe_essere_chiamato(*a, **k):
    _run_direct_mai_chiamato.append((a, k))
    return False

_sys_main.argv = ['launcher.py', 'carts/fake/game.py', '--netplay-join', 'indirizzo.non.valido', '42420']
launcher.start_netcode_client = _fake_start_client_che_fallisce
launcher.run_direct = _run_direct_non_dovrebbe_essere_chiamato
try:
    try:
        launcher.main()
        check("main(): un errore di rete termina con SystemExit", "nessun errore", "SystemExit")
    except SystemExit as exc:
        check("main(): un errore di rete termina con SystemExit(1)", exc.code, 1)
    check("main(): run_direct MAI chiamato se la connessione fallisce", _run_direct_mai_chiamato, [])
finally:
    _sys_main.argv = _orig_argv_main
    launcher.start_netcode_client = _orig_start_client_main
    launcher.run_direct = _orig_run_direct_main

print()
if fails == 0:
    print("Tutti i test passati.")
else:
    print(f"{fails} test falliti.")
