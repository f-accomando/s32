"""
launcher.py - punto di ingresso unico per S32.

  python3 launcher.py                        -> mostra il menu (OS),
                                                 scopre le cartucce in
                                                 ../carts/, lancia
                                                 quella scelta
  python3 launcher.py carts/gioco/game.py    -> BYPASSA il menu,
                                                 lancia direttamente
                                                 quella cartuccia
  python3 launcher.py carts/gioco/game.asm   -> idem, assembly puro
  python3 launcher.py qualcosa.rom            -> NotImplementedError
                                                 (formato ROM ancora
                                                 da costruire, roadmap)

La logica di SCELTA (menu vs diretto, quale file, quale linguaggio)
e' separata dall'ESECUZIONE (pygame) apposta - la prima e' testata a
fondo senza bisogno di un display, la seconda no (vedi test_os_menu.py
per la prima, questo file resta un sottile collante per la seconda).
"""

import sys
import os
import importlib.util

from assembler import assemble
from lang import compile_source as compile_consolelang
from cpu import CPU
import audio
from ppu import render_frame, render_background, render_background_window, draw_sprites, iter_visible_sprite_tiles
from memory_map import (
    VRAM_SIZE, OAM_SIZE, CGRAM_SIZE, VRAM_BASE, OAM_BASE, CGRAM_BASE,
    OAM_SLOT_BYTES, TILE_SIZE_PX, SCREEN_W_PX, SCREEN_H_PX,
)
from carts_registry import discover_carts
from menu_state import MenuState

CART_LOAD_ADDR = 0x001000  # dove il programma di una cartuccia viene
                            # caricato in WRAM (lontano dagli
                            # indirizzi bassi riservati alle variabili
                            # globali di ConsoleLang, vedi lang.py)


class LauncherError(Exception):
    pass


def determine_mode(argv):
    """Pura logica di dispatch, senza effetti collaterali - ritorna
    ('menu',) oppure ('direct', percorso, tipo)."""
    if len(argv) < 2:
        return ('menu',)
    path = argv[1]
    if path.endswith('.py'):
        return ('direct', path, 'py')
    if path.endswith('.asm'):
        return ('direct', path, 'asm')
    if path.endswith('.rom'):
        return ('direct', path, 'rom')
    raise LauncherError(
        f'Estensione non riconosciuta: "{path}" (attesi .py, .asm o .rom)'
    )


def _import_module_from_path(path, module_name='cart_module_tmp'):
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_cart_rom(entry_path, kind):
    """Carica ed eventualmente compila il sorgente di una cartuccia,
    ritornando (rom_bytes, state_vars). Non tocca pygame - testabile
    da solo con una cartuccia sintetica."""
    if kind == 'asm':
        with open(entry_path, 'r') as f:
            src = f.read()
        rom = assemble(src, base_addr=CART_LOAD_ADDR)
        return rom, {}

    if kind == 'py':
        module = _import_module_from_path(entry_path)
        if not hasattr(module, 'ROM_SOURCE'):
            raise LauncherError(f'{entry_path} non espone ROM_SOURCE')
        source_lang = getattr(module, 'SOURCE_LANG', 'asm')
        if source_lang == 'consolelang':
            result = compile_consolelang(module.ROM_SOURCE)
            rom = assemble(result['asm'], base_addr=CART_LOAD_ADDR)
            return rom, result['state_vars']
        elif source_lang == 'asm':
            rom = assemble(module.ROM_SOURCE, base_addr=CART_LOAD_ADDR)
            return rom, {}
        else:
            raise LauncherError(f'SOURCE_LANG sconosciuto: "{source_lang}" (atteso "asm" o "consolelang")')

    if kind == 'rom':
        raise NotImplementedError('Formato ROM binario non ancora implementato (roadmap)')

    raise LauncherError(f'Tipo di cartuccia sconosciuto: "{kind}"')


def _load_cart_graphics(cpu, cart_dir):
    """Se la cartuccia ha un cart.py (convenzione classica) con
    build_vram/build_cgram/build_oam/build_stages, li usa per
    inizializzare la grafica. Se NON c'e' cart.py ma c'e' un game.py
    (convenzione single-file, vedi carts/barebone/), le stesse funzioni
    vengono cercate li' - una cartuccia single-file non ha un cart.py
    separato, tutto vive in game.py. Se non trova ne' l'uno ne' l'altro,
    lascia VRAM/CGRAM a zero (schermo nero, nessun crash).

    L'OAM viene SEMPRE inizializzata con tutti gli sprite NASCOSTI
    (Y=0xffff) prima di tutto - bug reale trovato profilando su
    Raspberry Pi 1: senza questo, i 512 slot OAM partono a Y=0, che
    secondo la nostra convenzione (Y>=0xfff0 = nascosto) significa
    VISIBILI - la PPU perdeva tempo a iterare tutti e 512 ogni frame
    (~70% del costo di render_frame() in questa demo), pur non
    alterando il risultato visivo (tutti trasparenti, per questo i
    test di correttezza non l'avevano preso). Stesso schema dei
    giochi retro veri: "pulisci la OAM" e' spesso il primo passo del
    boot, prima ancora di disegnare qualcosa."""
    def make_hidden_oam():
        oam = bytearray(OAM_SIZE)
        for slot in range(OAM_SIZE // OAM_SLOT_BYTES):
            base = slot * OAM_SLOT_BYTES
            oam[base + 2] = 0xff
            oam[base + 3] = 0xff  # Y = 0xffff -> nascosto
        return oam

    cpu.mem[OAM_BASE:OAM_BASE + OAM_SIZE] = make_hidden_oam()
    cpu.sound_bank = {}  # default: nessun suono - una cartuccia senza
                          # build_sound_bank() gioca muta, non crasha
                          # (stesso principio di VRAM/CGRAM a zero sopra)

    cart_py_path = os.path.join(cart_dir, 'cart.py')
    game_py_path = os.path.join(cart_dir, 'game.py')
    if os.path.isfile(cart_py_path):
        graphics_path = cart_py_path
    elif os.path.isfile(game_py_path):
        graphics_path = game_py_path
    else:
        return
    module = _import_module_from_path(graphics_path, 'cart_graphics_tmp')
    if hasattr(module, 'build_vram'):
        vram = bytearray(VRAM_SIZE)
        module.build_vram(vram)
        cpu.mem[VRAM_BASE:VRAM_BASE + VRAM_SIZE] = vram
    if hasattr(module, 'build_cgram'):
        cgram = bytearray(CGRAM_SIZE)
        module.build_cgram(cgram)
        cpu.mem[CGRAM_BASE:CGRAM_BASE + CGRAM_SIZE] = cgram
    if hasattr(module, 'build_oam'):
        oam = make_hidden_oam()  # parte gia' nascosto, il cart aggiunge sopra
        module.build_oam(oam)
        cpu.mem[OAM_BASE:OAM_BASE + OAM_SIZE] = oam
    if hasattr(module, 'build_stages'):
        cpu.stages = module.build_stages()
    if hasattr(module, 'build_sound_bank'):
        # IL BANCO SUONI E' CONTENUTO DELLA CARTUCCIA, NON DELLA
        # CONSOLE - quali suoni esistono e cosa significano (attacco,
        # ferita, ecc.) appartiene al gioco, esattamente come lo
        # spritesheet. audio.py (s32/) resta solo l'"hardware": i
        # generatori di forma d'onda (square_wave/sweep_wave/noise),
        # riusabili da QUALSIASI cartuccia. Corretto dopo che l'utente
        # ha notato che i suoni di Adventure erano finiti per errore
        # dentro il motore invece che nella cartuccia.
        cpu.sound_bank = module.build_sound_bank()


def run_direct(path, kind, show_stats=False, quit_pygame_at_end=True, renderer_mode='dirty-rects', fullscreen=False, use_audio=False, playtest=False, playtest_quick=False, netcode_session=None, local_player_index=0):
    """Bypassa il menu, carica ed esegue direttamente la cartuccia
    data - stesso comportamento immediato della v1 (python3 main.py)."""
    if not os.path.isfile(path):
        raise LauncherError(
            f'File non trovato: "{path}" (risolto come "{os.path.abspath(path)}" '
            f'dalla cartella corrente "{os.getcwd()}" - controlla di lanciare il '
            f'comando dalla cartella giusta)'
        )

    rom, state_vars = load_cart_rom(path, kind)

    cpu = CPU()
    for i, b in enumerate(rom):
        cpu.mem[CART_LOAD_ADDR + i] = b
    for name, (addr, init_val) in state_vars.items():
        cpu.write16(addr, init_val)

    cart_dir = os.path.dirname(path)
    _load_cart_graphics(cpu, cart_dir)

    _run_pygame_loop(cpu, show_stats=show_stats, quit_pygame_at_end=quit_pygame_at_end,
                      renderer_mode=renderer_mode, fullscreen=fullscreen,
                      use_audio=use_audio, playtest=playtest, playtest_quick=playtest_quick,
                      netcode_session=netcode_session, local_player_index=local_player_index)


def _init_pygame_once():
    """Inizializza pygame UNA SOLA VOLTA per tutta l'esecuzione -
    pygame.init() e' sicuro da richiamare piu' volte (pygame lo
    gestisce da solo), ma mixer.quit()/mouse.set_visible() li
    facciamo qui per essere certi che accadano una volta sola,
    indipendentemente da quante schermate (menu, poi gioco)
    useranno pygame nella stessa esecuzione. Ritorna il modulo
    pygame gia' importato, cosi' i chiamanti non devono re-importarlo."""
    import os
    os.environ.setdefault('SDL_VIDEO_WINDOW_POS', 'center')  # senza un
                                # window manager (es. Raspberry Pi OS
                                # Lite, headless) SDL piazza la finestra
                                # a (0,0) di default, angolo alto-sx -
                                # questo la centra sullo schermo fisico
    import pygame
    if not pygame.get_init():
        pygame.init()
        pygame.mixer.quit()  # vedi nota storica: niente audio, su
                              # alcune config ALSA (Raspberry Pi) il
                              # mixer attivo spamma "underrun occurred"
        pygame.mouse.set_visible(False)
    return pygame


class SurfaceRenderer:
    """Percorso di rendering ALTERNATIVO a ppu.render_frame(), usato
    SOLO nel loop di gioco vero (non nei test, che restano sul
    render_frame() puro-Python, testabile senza pygame).

    Idea: ogni tile viene costruito UNA VOLTA SOLA come pygame.Surface
    (con vera trasparenza via SRCALPHA), messo in cache, poi riusato
    con blit() - lasciando che sia SDL2 (C, potenzialmente accelerato
    dal driver video) a comporlo a schermo invece di scrivere ogni
    pixel a mano in Python ad ogni frame. Il lavoro pixel-per-pixel
    (lento) succede una volta per tile distinto, non una volta per
    frame - la differenza cresce quanto piu' a lungo gira lo stesso
    stage con pochi tile distinti (il caso tipico)."""

    def __init__(self, pygame):
        self.pygame = pygame
        self.tile_cache = {}    # (tile_index, palette) -> Surface
        self.last_stage = None  # per invalidare la cache quando cambia stage

    def invalidate(self):
        self.tile_cache.clear()

    def _tile_surface(self, vram, cgram, tile_index, palette):
        key = (tile_index, palette)
        surf = self.tile_cache.get(key)
        if surf is not None:
            return surf
        from ppu import decode_tile, decode_color
        grid = decode_tile(vram, tile_index)
        surf = self.pygame.Surface((TILE_SIZE_PX, TILE_SIZE_PX), self.pygame.SRCALPHA)
        color_cache = {}
        for y in range(TILE_SIZE_PX):
            for x in range(TILE_SIZE_PX):
                idx = grid[y][x]
                if idx == 0:
                    continue  # resta trasparente (SRCALPHA parte a (0,0,0,0))
                color = color_cache.get(idx)
                if color is None:
                    color = decode_color(cgram, palette, idx)
                    color_cache[idx] = color
                surf.set_at((x, y), color)
        self.tile_cache[key] = surf
        return surf

    def render(self, screen, vram, oam, cgram, current_stage, scroll_x=0, scroll_y=0):
        if current_stage != self.last_stage:
            self.invalidate()  # stanza cambiata: i tile potrebbero
                                # essere diversi, non fidarsi della cache
            self.last_stage = current_stage

        from ppu import read_tilemap_entry
        screen.fill((0, 0, 0))

        first_tile_col = scroll_x // TILE_SIZE_PX
        first_col_offset = scroll_x % TILE_SIZE_PX
        first_tile_row = scroll_y // TILE_SIZE_PX
        first_row_offset = scroll_y % TILE_SIZE_PX
        n_cols = (SCREEN_W_PX + first_col_offset + TILE_SIZE_PX - 1) // TILE_SIZE_PX
        n_rows = (SCREEN_H_PX + first_row_offset + TILE_SIZE_PX - 1) // TILE_SIZE_PX

        for tr in range(n_rows):
            for tc in range(n_cols):
                tile_index, palette = read_tilemap_entry(vram, first_tile_col + tc, first_tile_row + tr)
                surf = self._tile_surface(vram, cgram, tile_index, palette)
                x = tc * TILE_SIZE_PX - first_col_offset
                y = tr * TILE_SIZE_PX - first_row_offset
                screen.blit(surf, (x, y))

        n_sprites = len(oam) // OAM_SLOT_BYTES
        for i in range(n_sprites):
            base = i * OAM_SLOT_BYTES
            sx = oam[base] | (oam[base + 1] << 8)
            sy = oam[base + 2] | (oam[base + 3] << 8)
            if sy >= 0xfff0:
                continue
            tile_index = oam[base + 4] | (oam[base + 5] << 8)
            attr = oam[base + 6] | (oam[base + 7] << 8)
            size_code = attr & 0x03
            tiles_per_side = {0: 1, 1: 2, 2: 4}.get(size_code, 1)
            palette = (attr >> 2) & 0x07
            for row in range(tiles_per_side):
                for col in range(tiles_per_side):
                    idx = tile_index + row * tiles_per_side + col
                    surf = self._tile_surface(vram, cgram, idx, palette)
                    screen.blit(surf, (sx + col * TILE_SIZE_PX, sy + row * TILE_SIZE_PX))


def _sdl2_video(pygame):
    """Compatibilita' pygame-ce (nomi diretti pygame.Window/Renderer/
    Texture) vs pygame "mainline" (pygame._sdl2.video.Window/...) -
    le due versioni divergono qui. Trovato testando in questa stessa
    conversazione: Pi usa pygame mainline 2.6.1 (serve
    pygame._sdl2.video, l'API diretta non esiste li'), Windows usa
    pygame-ce 2.5.8 (dove pygame.Window esiste gia' come nome
    diretto). Ritorna un oggetto con .Window/.Renderer/.Texture,
    qualunque sia la variante installata."""
    if hasattr(pygame, 'Window') and hasattr(pygame, 'Renderer') and hasattr(pygame, 'Texture'):
        class _NS:
            pass
        ns = _NS()
        ns.Window = pygame.Window
        ns.Renderer = pygame.Renderer
        ns.Texture = pygame.Texture
        return ns
    from pygame._sdl2 import video
    return video


class GpuRenderer:
    """Quarto percorso di rendering (--gpu-renderer): usa
    pygame._sdl2.video (Renderer + Texture accelerati via GPU) invece
    della Surface classica software (quella usata da
    IncrementalRenderer, SurfaceRenderer, il percorso a buffer).

    MISURATO sulla Raspberry Pi 1 reale prima di scrivere questa
    classe (vedi test_gpu.py e README): Surface.blit()+display.flip()
    puro costa ~34ms/frame; Renderer.clear()+Texture.draw()+
    Renderer.present() equivalente costa ~2.4ms/frame - 14x piu'
    veloce. La Pi 1 ha una GPU vera (Broadcom VideoCore IV) che il
    codice precedente non stava mai usando: l'API Surface/blit di
    pygame e' SEMPRE software, indipendentemente dall'hardware sotto
    - l'accelerazione richiede questa API diversa.

    Riusa TUTTA la logica di calcolo gia' ottimizzata (blob_cache
    persistente, striscia incrementale per lo scroll fluido) - cambia
    SOLO il passo finale di presentazione: invece di
    Surface.blit()+pygame.display.flip(), Texture.update() (spinge i
    pixel calcolati in CPU dentro la texture GPU) +
    renderer.clear()+texture.draw()+renderer.present().

    Semplificazione rispetto a IncrementalRenderer: con la
    presentazione cosi' economica, non serve piu' il tracciamento dei
    "dirty rect" per gli sprite (ripristina/ridisegna solo le zone
    toccate, la parte piu' delicata di IncrementalRenderer) -
    ridisegnamo SEMPRE l'intero frame (sfondo + sprite) ogni frame, ed
    e' comunque piu' veloce del vecchio percorso parziale su Surface.

    NON ANCORA VERIFICATO end-to-end sulla Pi - solo il costo isolato
    di Renderer/Texture (test_gpu.py) e la logica qui sotto (mock di
    pygame, vedi test_launcher.py). Il prossimo passo e' l'utente che
    lo prova per davvero con --gpu-renderer."""

    ATLAS_COLS = 8         # griglia dell'atlas: 8 colonne...
    ATLAS_TILES_MAX = 64   # ...fino a 64 tile (8x8) - generoso per
                            # l'insieme di sprite di questo gioco
                            # (giocatore, nemici, boss 4 segmenti,
                            # cuori, slash, pietre, fuoco, barra vita,
                            # teschio: <20 tile distinti in totale)

    def __init__(self, pygame, renderer):
        self.pygame = pygame
        self.renderer = renderer
        self.video = _sdl2_video(pygame)
        self.bg_surface = None       # CPU-side, stesso ruolo di sempre
        self.bg_texture = None       # GPU-side, aggiornata da bg_surface
        self.bg_stage = None
        self.bg_scroll_x = None
        self.bg_scroll_y = None
        self.sprite_stage_key = None
        self.tile_blob_cache = {}    # PERSISTENTE - vedi IncrementalRenderer
        self.last_timing = None
        # -- atlas sprite: UNA texture condivisa da tutti gli sprite,
        # invece di una texture separata per ciascun tile. Richiesto
        # dall'utente dopo aver visto draw_sprites costare ~15-17ms
        # per una manciata di sprite (~2-4ms a chiamata) - il sospetto
        # e' che il costo dominante sia il CAMBIO di texture tra un
        # draw e l'altro (comune sulle GPU embedded), non il disegno
        # in se'. Con un atlas condiviso e srcrect, la GPU resta
        # "agganciata" alla stessa texture per tutti gli sprite di un
        # frame - nessun cambio, nessun ri-caricamento.
        self.sprite_atlas_surface = None   # CPU-side, cresce riempiendo slot
        self.sprite_atlas_texture = None   # GPU-side, UNA sola per tutti gli sprite
        self.sprite_atlas_slots = {}       # (tile_index, palette) -> indice slot
        self.sprite_atlas_next_slot = 0

    def _sprite_tile_srcrect(self, vram, cgram, tile_index, palette):
        """Ritorna (x,y,w,h) dentro l'atlas condiviso per questo tile -
        decodificandolo e aggiungendolo all'atlas al primo utilizzo,
        poi semplice lookup. A differenza dello sfondo (che scrolla,
        richiede spostare contenuto GIA' caricato - il bug trovato
        dall'utente), qui ogni slot resta fisso per sempre una volta
        assegnato: aggiungerne uno nuovo non tocca mai gli altri gia'
        presenti, quindi un update() parziale e' sempre sicuro."""
        key = (tile_index, palette)
        slot = self.sprite_atlas_slots.get(key)
        if slot is not None:
            col = slot % self.ATLAS_COLS
            row = slot // self.ATLAS_COLS
            return (col * TILE_SIZE_PX, row * TILE_SIZE_PX, TILE_SIZE_PX, TILE_SIZE_PX)

        from ppu import decode_tile, decode_color
        grid = decode_tile(vram, tile_index)
        tile_surf = self.pygame.Surface((TILE_SIZE_PX, TILE_SIZE_PX), self.pygame.SRCALPHA)
        color_cache = {}
        for y in range(TILE_SIZE_PX):
            for x in range(TILE_SIZE_PX):
                idx = grid[y][x]
                if idx == 0:
                    continue
                color = color_cache.get(idx)
                if color is None:
                    color = decode_color(cgram, palette, idx)
                    color_cache[idx] = color
                tile_surf.set_at((x, y), color)

        if self.sprite_atlas_surface is None:
            atlas_w = self.ATLAS_COLS * TILE_SIZE_PX
            atlas_rows = (self.ATLAS_TILES_MAX + self.ATLAS_COLS - 1) // self.ATLAS_COLS
            atlas_h = atlas_rows * TILE_SIZE_PX
            self.sprite_atlas_surface = self.pygame.Surface((atlas_w, atlas_h), self.pygame.SRCALPHA)

        slot = self.sprite_atlas_next_slot
        self.sprite_atlas_next_slot += 1
        col = slot % self.ATLAS_COLS
        row = slot // self.ATLAS_COLS
        dest_xy = (col * TILE_SIZE_PX, row * TILE_SIZE_PX)
        self.sprite_atlas_surface.blit(tile_surf, dest_xy)
        self.sprite_atlas_slots[key] = slot
        srcrect = (col * TILE_SIZE_PX, row * TILE_SIZE_PX, TILE_SIZE_PX, TILE_SIZE_PX)

        if self.sprite_atlas_texture is None:
            self.sprite_atlas_texture = self.video.Texture.from_surface(self.renderer, self.sprite_atlas_surface)
        else:
            # aggiorna SOLO lo slot nuovo - sicuro, vedi docstring
            self.sprite_atlas_texture.update(tile_surf, area=srcrect)

        return srcrect

    def render(self, vram, oam, cgram, current_stage, scroll_x=0, scroll_y=0):
        pygame = self.pygame
        import time

        self.last_timing = None

        if current_stage != self.sprite_stage_key:
            self.tile_blob_cache = {}
            self.sprite_stage_key = current_stage
            # NIENTE reset dell'atlas sprite qui (a differenza della
            # vecchia cache per-tile di IncrementalRenderer): tile_index
            # e' un identificatore stabile in tutto il cartridge (stessa
            # spritesheet caricata una volta all'avvio, mai per-stanza) -
            # cache permanente per l'intera sessione e' sicura e piu'
            # efficiente, evita di ridecodificare/ricaricare sulla GPU
            # gli stessi sprite (giocatore, cuori) rientrando in una
            # stanza gia' visitata.

        full_rebuild = self.bg_surface is None or current_stage != self.bg_stage
        bg_changed = full_rebuild
        # cosa spingere sulla texture GPU in questo frame -
        # (surface_da_caricare, area_rect_o_None). None per l'area
        # significa "l'intera texture" (Texture.update lo interpreta
        # cosi'). SEMPRE l'intero bg_surface quando qualcosa cambia
        # (rebuild o scroll incrementale) - una versione precedente
        # provava a spingere solo la striscia nuova durante lo scroll,
        # ma la texture GPU non ha un equivalente di Surface.scroll()
        # (che sposta FISICAMENTE i pixel gia' disegnati): il resto
        # del contenuto restava congelato alla vecchia posizione,
        # bug trovato dall'utente giocando davvero ("il personaggio
        # sembrava stazionario e i nemici oltrepassavano il muro" -
        # vedi il commento completo piu' sotto, nel ramo di scroll).
        dirty_update = None

        if not full_rebuild and (scroll_x != self.bg_scroll_x or scroll_y != self.bg_scroll_y):
            dx = scroll_x - self.bg_scroll_x
            dy = scroll_y - self.bg_scroll_y
            if dx == 0 and 0 < abs(dy) < SCREEN_H_PX:
                # stessa identica logica di IncrementalRenderer - vedi
                # li' per i commenti completi sul perche'
                t0 = time.perf_counter()
                self.bg_surface.scroll(0, -dy)
                t1 = time.perf_counter()
                if dy > 0:
                    strip_h = dy
                    strip_y = SCREEN_H_PX - strip_h
                else:
                    strip_h = -dy
                    strip_y = 0
                strip_buf = render_background_window(vram, cgram, scroll_x, scroll_y, strip_y, strip_h,
                                                      blob_cache=self.tile_blob_cache)
                t2 = time.perf_counter()
                strip_surf = pygame.image.frombuffer(bytes(strip_buf), (SCREEN_W_PX, strip_h), 'RGB')
                self.bg_surface.blit(strip_surf, (0, strip_y))
                t3 = time.perf_counter()
                self.bg_scroll_x = scroll_x
                self.bg_scroll_y = scroll_y
                bg_changed = True
                # BUG TROVATO DALL'UTENTE GIOCANDO DAVVERO (non nei
                # test): "il personaggio sembrava stazionario e i
                # nemici oltrepassavano il muro". Causa: la texture
                # GPU non ha un equivalente di Surface.scroll() - che
                # SPOSTA FISICAMENTE i pixel gia' disegnati dentro la
                # Surface CPU. Texture.update(area=striscia) scrive
                # SOLO quella striscia in una posizione fissa; il resto
                # del contenuto gia' caricato sulla GPU non si sposta
                # mai, restando congelato alla vecchia posizione mentre
                # gli sprite (ridisegnati ogni frame nella posizione
                # vera) continuano a muoversi - da qui lo sfondo
                # "fermo" e i nemici che sembrano attraversare i muri.
                # Fix: spingiamo l'INTERO bg_surface (che e' comunque
                # gia' corretto in CPU - scroll+patch della striscia
                # sono gia' avvenuti sopra), non solo la striscia -
                # sacrifica parte del guadagno di texture_update, ma
                # la correttezza viene prima della velocita'. Uno
                # scroll "sul serio" (shiftare anche il contenuto
                # gia' caricato sulla GPU, via render-to-texture) e'
                # possibile ma piu' complesso - non tentato ora senza
                # poterlo verificare su hardware reale.
                dirty_update = (self.bg_surface, None)
                self.last_timing = {
                    'surface_scroll': t1 - t0,
                    'strip_compute': t2 - t1,
                    'strip_blit': t3 - t2,
                }
            else:
                full_rebuild = True
                bg_changed = True

        if full_rebuild:
            bg_buf = render_background(vram, cgram, scroll_x, scroll_y, blob_cache=self.tile_blob_cache)
            # NIENTE .convert() qui (a differenza di IncrementalRenderer):
            # .convert() richiede un display "classico" attivo
            # (pygame.display.set_mode()), che in modalita' GPU non
            # esiste mai - usiamo una finestra dedicata via
            # _sdl2.video.Window. La Surface va bene cosi' com'e' per
            # Texture.from_surface()/.update(). Bug trovato testando:
            # "pygame.error: Parameter 'surface' is invalid".
            self.bg_surface = pygame.image.frombuffer(bytes(bg_buf), (SCREEN_W_PX, SCREEN_H_PX), 'RGB')
            self.bg_stage = current_stage
            self.bg_scroll_x = scroll_x
            self.bg_scroll_y = scroll_y
            dirty_update = (self.bg_surface, None)  # rebuild completo: l'intera texture

        # -- spinge SOLO la porzione cambiata dentro la texture GPU -
        # non l'intero sfondo se e' cambiata solo una striscia (vedi
        # sopra) --
        t4 = time.perf_counter()
        if self.bg_texture is None:
            self.bg_texture = self.video.Texture.from_surface(self.renderer, self.bg_surface)
        elif dirty_update is not None:
            surf_da_caricare, area = dirty_update
            self.bg_texture.update(surf_da_caricare, area=area)
        t5 = time.perf_counter()
        if self.last_timing is not None:
            self.last_timing['texture_update'] = t5 - t4

        # -- composizione: sempre l'intero frame, ogni frame. Con la
        # GPU a ~2ms per un frame pieno (misurato, vedi test_gpu.py),
        # tracciare "dirty rect" per gli sprite non vale piu' la
        # complessita' che costava su Surface software --
        self.renderer.clear()
        self.bg_texture.draw(dstrect=(0, 0, SCREEN_W_PX, SCREEN_H_PX))
        for tile_index, palette, x, y in iter_visible_sprite_tiles(oam):
            srcrect = self._sprite_tile_srcrect(vram, cgram, tile_index, palette)
            self.sprite_atlas_texture.draw(srcrect=srcrect, dstrect=(x, y, TILE_SIZE_PX, TILE_SIZE_PX))
        t6 = time.perf_counter()
        self.renderer.present()
        t7 = time.perf_counter()
        if self.last_timing is not None:
            self.last_timing['draw_sprites'] = t6 - t5
            self.last_timing['present'] = t7 - t6


class IncrementalRenderer:
    """Terzo percorso di rendering, diverso nello spirito da
    SurfaceRenderer (che sostituiva UNA blit grande con centinaia di
    piccole per lo SFONDO, e non ha aiutato - vedi sopra). Qui invece
    sfruttiamo che lo sfondo e' cachato e STATICO (vedi bg_cache nel
    loop principale): non serve ridisegnare l'intero schermo ogni
    frame, solo le zone dove c'e' DAVVERO qualcosa che cambia - gli
    sprite, in genere una manciata di pixel su 480x320.

    Meccanismo: pygame.display.update(lista_di_rettangoli) invece di
    pygame.display.flip() - aggiorna a video SOLO i rettangoli dati,
    non l'intero schermo. Ogni frame: (1) ripristina lo sfondo dove
    c'era uno sprite l'istante prima (blit di quel rettangolo dalla
    Surface di sfondo cachata), (2) disegna gli sprite nella loro
    posizione attuale, (3) update() solo sui rettangoli toccati."""

    def __init__(self, pygame):
        self.pygame = pygame
        self.bg_surface = None
        self.bg_stage = None
        self.bg_scroll_x = None
        self.bg_scroll_y = None
        self.sprite_stage_key = None  # separata dalla chiave sfondo apposta,
                                       # vedi render(): i tile sprite NON
                                       # cambiano con lo scroll, solo con lo
                                       # stage - cancellarli ad ogni frame di
                                       # scroll era uno spreco puro (bug
                                       # trovato con l'aiuto dell'utente,
                                       # misurando sulla Pi 1 vera: senza
                                       # questa separazione lo scroll era
                                       # molto piu' lento del necessario)
        self.sprite_tile_cache = {}
        self.tile_blob_cache = {}  # PERSISTENTE tra i frame - vedi
                                    # render_background_window() per
                                    # il perche' conta cosi' tanto
                                    # (57ms/frame su Pi 1 senza questo)
        self.prev_rects = []
        self.last_timing = None  # dettaglio ultima fase di scroll incrementale
                                  # (solo per diagnostica --stats, vedi render())

    def _sprite_tile_surface(self, vram, cgram, tile_index, palette):
        key = (tile_index, palette)
        surf = self.sprite_tile_cache.get(key)
        if surf is not None:
            return surf
        from ppu import decode_tile, decode_color
        grid = decode_tile(vram, tile_index)
        surf = self.pygame.Surface((TILE_SIZE_PX, TILE_SIZE_PX), self.pygame.SRCALPHA)
        color_cache = {}
        for y in range(TILE_SIZE_PX):
            for x in range(TILE_SIZE_PX):
                idx = grid[y][x]
                if idx == 0:
                    continue
                color = color_cache.get(idx)
                if color is None:
                    color = decode_color(cgram, palette, idx)
                    color_cache[idx] = color
                surf.set_at((x, y), color)
        self.sprite_tile_cache[key] = surf
        return surf

    def render(self, screen, vram, oam, cgram, current_stage, scroll_x=0, scroll_y=0):
        pygame = self.pygame
        import time

        self.last_timing = None  # popolato SOLO nel ramo di scroll
                                  # incrementale sotto - un rebuild
                                  # completo (raro: cambio stanza o
                                  # salto grande) non fa parte della
                                  # diagnostica "dettaglio scroll"

        if current_stage != self.sprite_stage_key:
            self.sprite_tile_cache = {}  # SOLO su cambio stage - i tile
                                          # sprite potrebbero davvero essere
                                          # diversi in una stanza diversa
            self.tile_blob_cache = {}  # idem per lo sfondo
            self.sprite_stage_key = current_stage

        full_rebuild = self.bg_surface is None or current_stage != self.bg_stage
        bg_changed = full_rebuild

        if not full_rebuild and (scroll_x != self.bg_scroll_x or scroll_y != self.bg_scroll_y):
            dx = scroll_x - self.bg_scroll_x
            dy = scroll_y - self.bg_scroll_y
            # SCROLL INCREMENTALE: sposta il contenuto GIA' DISEGNATO
            # di dy pixel (pygame Surface.scroll(), operazione a
            # livello C) e ricalcola SOLO la striscia nuova che entra
            # in vista (|dy| righe, non le 320 dello schermo intero) -
            # trovato necessario dopo che il movimento fluido
            # (richiesto dall'utente) ha reso lo scroll continuo:
            # prima un tile si muoveva in un salto isolato, ora la
            # telecamera si sposta di 2px per ~16 frame consecutivi -
            # ricalcolare l'intero sfondo ad OGNI frame di quei 16 e'
            # lo stesso spreco gia' risolto per la cache "sfondo
            # fermo", solo che qui lo sfondo si muove sul serio.
            if dx == 0 and 0 < abs(dy) < SCREEN_H_PX:
                t0 = time.perf_counter()
                self.bg_surface.scroll(0, -dy)
                t1 = time.perf_counter()
                if dy > 0:
                    strip_h = dy
                    strip_y = SCREEN_H_PX - strip_h
                else:
                    strip_h = -dy
                    strip_y = 0
                strip_buf = render_background_window(vram, cgram, scroll_x, scroll_y, strip_y, strip_h,
                                                      blob_cache=self.tile_blob_cache)
                t2 = time.perf_counter()
                strip_surf = pygame.image.frombuffer(bytes(strip_buf), (SCREEN_W_PX, strip_h), 'RGB')
                self.bg_surface.blit(strip_surf, (0, strip_y))
                t3 = time.perf_counter()
                self.bg_scroll_x = scroll_x
                self.bg_scroll_y = scroll_y
                bg_changed = True
                self.last_timing = {
                    'surface_scroll': t1 - t0,
                    'strip_compute': t2 - t1,
                    'strip_blit': t3 - t2,
                }
            else:
                full_rebuild = True  # salto grande o scroll orizzontale:
                                      # lo scroll incrementale presuppone
                                      # un piccolo spostamento verticale
                bg_changed = True

        if full_rebuild:
            bg_buf = render_background(vram, cgram, scroll_x, scroll_y, blob_cache=self.tile_blob_cache)
            self.bg_surface = pygame.image.frombuffer(bytes(bg_buf), (SCREEN_W_PX, SCREEN_H_PX), 'RGB').convert()
            self.bg_stage = current_stage
            self.bg_scroll_x = scroll_x
            self.bg_scroll_y = scroll_y

        if bg_changed:
            # sfondo cambiato (scroll o cambio stanza): disegniamo gli
            # sprite SOPRA il nuovo sfondo PRIMA di presentarlo, cosi'
            # background+sprite arrivano a schermo in UN'UNICA
            # presentazione (flip). PRIMA disegnavamo gli sprite DOPO
            # il flip dello sfondo, con un secondo display.update()
            # separato - per un istante lo schermo mostrava lo sfondo
            # SENZA il giocatore, visibile come flickering durante lo
            # scroll (segnalato dall'utente, non capitava da fermi
            # perche' li' non c'e' mai un flip separato dello sfondo).
            t4 = time.perf_counter()
            screen.blit(self.bg_surface, (0, 0))
            new_rects = []
            for tile_index, palette, x, y in iter_visible_sprite_tiles(oam):
                surf = self._sprite_tile_surface(vram, cgram, tile_index, palette)
                screen.blit(surf, (x, y))
                new_rects.append(pygame.Rect(x, y, TILE_SIZE_PX, TILE_SIZE_PX))
            t5 = time.perf_counter()
            pygame.display.flip()
            t6 = time.perf_counter()
            if self.last_timing is not None:
                self.last_timing['screen_blit'] = t5 - t4
                self.last_timing['flip'] = t6 - t5
            self.prev_rects = new_rects
            return

        # --- sfondo INVARIATO: percorso rapido, solo gli sprite ---
        # 1) ripristina lo sfondo dove c'era uno sprite l'istante prima
        for r in self.prev_rects:
            screen.blit(self.bg_surface, r.topleft, area=r)

        # 2) disegna gli sprite nella loro posizione ATTUALE
        new_rects = []
        for tile_index, palette, x, y in iter_visible_sprite_tiles(oam):
            surf = self._sprite_tile_surface(vram, cgram, tile_index, palette)
            screen.blit(surf, (x, y))
            new_rects.append(pygame.Rect(x, y, TILE_SIZE_PX, TILE_SIZE_PX))

        dirty = self.prev_rects + new_rects
        if dirty:
            pygame.display.update(dirty)
        self.prev_rects = new_rects


class AudioPlayer:
    """Suona gli ID accodati dalla CPU su PORT_SOUND.

    ATTIVO DI DEFAULT, disattivabile con --no-audio, e TOLLERANTE AI
    GUASTI di proposito: su Raspberry Pi con ALSA mal configurato il
    mixer di pygame puo' spammare "underrun occurred" a ogni frame e
    rallentare tutto il gioco (vedi la nota storica in
    _init_pygame_once e in audio.py) - chi incontra quel problema usa
    --no-audio. Un gioco che gira muto e' molto meglio di un gioco
    che non parte o che scatta, quindi QUALUNQUE errore qui viene
    ingoiato e disattiva solo l'audio.

    Se non abilitato, enabled resta False e play_queue() non fa nulla:
    il costo a frame e' un confronto booleano."""

    def __init__(self, pygame, enabled, sound_bank=None):
        self.pygame = pygame
        self.enabled = False
        self.sounds = {}
        if not enabled:
            print("[audio] disattivato: --no-audio sulla riga di comando")
            return
        # IL BANCO SUONI E' CONTENUTO DELLA CARTUCCIA (vedi
        # _load_cart_graphics/cpu.sound_bank), non della console -
        # AudioPlayer non lo costruisce piu' da solo, lo riceve gia'
        # pronto. Una cartuccia senza build_sound_bank() passa un
        # dict vuoto: il mixer si inizializza comunque (il gioco puo'
        # ancora emettere ID su PORT_SOUND in futuro), semplicemente
        # non c'e' nulla da suonare finche' non viene aggiunto.
        if sound_bank is None:
            sound_bank = {}
        try:
            pygame.mixer.init(frequency=audio.SAMPLE_RATE, size=-16,
                               channels=1, buffer=1024)
            # il mixer PUO' negoziare un formato diverso da quello
            # richiesto (dipende dal driver audio del sistema, es. su
            # Windows e' comune ottenere stereo anche chiedendo mono)
            # - se cosi' fosse, i campioni PCM che generiamo (16-bit
            # mono, vedi audio.py) verrebbero interpretati con il
            # formato SBAGLIATO da pygame.mixer.Sound(), risultando
            # silenziosi o distorti senza nessun errore esplicito.
            # Invece di limitarci ad avvisare, adattiamo i campioni al
            # formato REALE negoziato.
            actual = pygame.mixer.get_init()
            atteso = (audio.SAMPLE_RATE, -16, 1)
            actual_channels = actual[2] if actual else 1
            if actual != atteso:
                print(f"[audio] formato negoziato {actual} diverso dal "
                      f"richiesto {atteso} - adatto i campioni ({actual_channels} canali)")
            for sid, pcm in sound_bank.items():
                if actual_channels == 2:
                    pcm = audio.mono_to_stereo(pcm)
                self.sounds[sid] = pygame.mixer.Sound(buffer=pcm)
            self.enabled = True
            print(f"[audio] attivo - mixer inizializzato a {actual}, "
                  f"{len(self.sounds)} suoni pronti")
        except Exception as exc:
            print(f"[audio] disattivato ({exc}) - il gioco prosegue muto")
            self.enabled = False

    def play_queue(self, cpu):
        """Svuota cpu.sound_queue e suona. La coda va svuotata SEMPRE,
        anche ad audio spento: altrimenti cresce all'infinito per
        tutta la partita (una lista che nessuno legge e' comunque una
        perdita di memoria)."""
        queue = cpu.sound_queue
        if not queue:
            return
        if self.enabled:
            for sid in queue:
                snd = self.sounds.get(sid)
                if snd is not None:
                    try:
                        snd.play()
                    except Exception:
                        pass   # una riproduzione fallita non deve mai
                                # fermare il ciclo di gioco
        del queue[:]


def _playtest_sequence(quick=False):
    """Genera la sequenza di input per --playtest: una lista di
    (etichetta_fase, input_byte), un elemento per frame. Sostituisce
    la tastiera con uno "script" deterministico che attraversa
    scenari REALI di gioco - a differenza di --benchmark (sempre
    input_byte=0, il giocatore non si muove mai e lo scroll non
    scatta mai) questo esercita proprio i percorsi che abbiamo
    passato l'intera conversazione a ottimizzare: scroll continuo,
    attacco ripetuto, esplorazione con cambi di direzione.

    Deterministico (nessun modulo random importato, stesso stile del
    generatore pseudo-casuale dei nemici in game.asm) - stessa
    sequenza a ogni esecuzione, cosi' due misure sono confrontabili.

    quick=True: versione ridotta (--playtest-quick), circa 1/5 della
    durata. Segnalato dall'utente: un test completo su Pi 1 supera i
    6 minuti - abbastanza da rischiare throttling termico durante il
    test stesso (temperatura che sale sotto carico sostenuto,
    rallentando la CPU in modo incostante), che confonde la misura
    invece di chiarirla. Le prime iterazioni di ogni fase sono gia'
    rappresentative (lo stesso identico codice gira ad ogni ciclo di
    scroll/carica/sparo) - non serve ripeterle a lungo per sapere
    quanto costano."""
    UP, DOWN, LEFT, RIGHT, J = 0x01, 0x02, 0x04, 0x08, 0x10
    seq = []
    f = (lambda n: max(1, n // 5)) if quick else (lambda n: n)

    def hold(label, frames, byte):
        for _ in range(frames):
            seq.append((label, byte))

    # fase 1: fermo - baseline, il caso gia' misurato da --benchmark
    hold('1-fermo (baseline)', f(180), 0)

    # fase 2: scroll continuo in una direzione poi nell'altra - il
    # caso peggiore per il renderer, quello che ha richiesto lo
    # scroll incrementale e la cache dei blob persistente (vedi
    # README: 8fps -> 12fps -> molto meglio dopo quei due fix)
    hold('2-scroll continuo giu', f(400), DOWN)
    hold('2-scroll continuo su', f(400), UP)

    # fase 2b: scroll SOSTENUTO - a differenza della fase 2, qui il
    # giocatore rimbalza DENTRO la finestra dove la telecamera e'
    # davvero in movimento (playerY tra 160 e 608 - scroll_y =
    # clamp(playerY-160, 0, 448)), non premendo una direzione fino al
    # bordo dove la telecamera si blocca (clampata) mentre il
    # giocatore continua comunque a muoversi. Segnalato dall'utente:
    # la fase 2 diluiva il costo vero, perche' buona parte dei suoi
    # frame hanno il giocatore in movimento ma la CAMERA ferma (fuori
    # dalla finestra 160-608) - qui invece lo scroll cambia
    # letteralmente ad OGNI frame per l'intera fase, senza tratti a
    # camera statica in mezzo.
    hold('2b-scroll sostenuto', 70, DOWN)   # da 64 a ~204: entra nella finestra attiva con margine
    for _ in range(1 if quick else 6):
        hold('2b-scroll sostenuto', 175, DOWN)  # attraversa la finestra attiva (~350px)
        hold('2b-scroll sostenuto', 175, UP)      # e torna indietro, sempre dentro la finestra

    # fase 3: attacco ripetuto - J va rilasciato e ripremuto (e'
    # edge-triggered, tenerlo fermo scatta un solo attacco) per
    # esercitare davvero l'animazione slash piu' volte
    for _ in range(4 if quick else 20):
        hold('3-attacco ripetuto', 3, J)
        hold('3-attacco ripetuto', 12, 0)

    # fase 4: esplorazione mista - cambi di direzione pseudo-casuali
    # (stesso generatore lineare congruenziale usato dai nemici),
    # con J premuto ogni tanto - il caso piu' vicino a una partita
    # vera: scroll che cambia direzione, possibili incontri con
    # nemici/scale/boss lungo il cammino se il cart li prevede
    dirs = [UP, DOWN, LEFT, RIGHT]
    rng = 0x1234
    frame_i = 0
    limite = 240 if quick else 1200
    while frame_i < limite:
        rng = (rng * 1103515245 + 12345) & 0x7fffffff
        d = dirs[(rng >> 16) & 3]
        hold_frames = 20 + ((rng >> 8) & 15)
        press_j = (rng & 7) == 0
        byte = d | (J if press_j else 0)
        hold('4-esplorazione mista', hold_frames, byte)
        hold('4-esplorazione mista', 4, 0)  # rilascio breve: riabilita J
        frame_i += hold_frames + 4

    # -- rete di sicurezza: garantisce un tocco di J almeno ogni 90
    # frame in TUTTA la sequenza, non solo nella fase 3. Trovato
    # testando: se il giocatore muore (es. colpito da una pietra
    # durante la fase di scroll), il gioco passa a game over e poi
    # torna al titolo - senza un J che arrivi, il resto della
    # sequenza scorre su una schermata ferma, invalidando la
    # misura per tutte le fasi successive. Non legge la memoria del
    # gioco (l'indirizzo di "mode" e' diverso tra asm e ConsoleLang) -
    # si limita a un tocco periodico, innocuo durante il gioco
    # normale (un attacco extra ogni tanto) e risolutivo se la
    # partita e' finita nel frattempo.
    passo = 90
    per_fase = {}
    for i in range(0, len(seq), passo):
        label, byte = seq[i]
        seq[i] = (label, byte | J)
        per_fase[label] = per_fase.get(label, 0) + 1

    return seq


def _pixels_to_surface(pixels, w, h):
    """render_frame() ora ritorna gia' un buffer piatto RGB (bytearray)
    - frombuffer() lo impacchetta in una Surface con un'unica
    operazione a livello C, senza alcun loop Python. Prima di questa
    ottimizzazione (vedi ppu.py) qui serviva un doppio ciclo che
    copiava pixel per pixel da una lista di liste di tuple."""
    import pygame
    return pygame.image.frombuffer(bytes(pixels), (w, h), 'RGB')


def _run_pygame_loop(cpu, show_stats=False, quit_pygame_at_end=True, renderer_mode='dirty-rects', fullscreen=False, use_audio=False, playtest=False, playtest_quick=False, netcode_session=None, local_player_index=0):
    """Il ciclo CPU->PPU->schermo a 60fps. show_stats=True stampa in
    console fps/tempo cpu/tempo render (disegno+blit insieme, vedi
    sotto) ogni secondo, utile per misurare le prestazioni su
    hardware debole (vedi --stats).

    renderer_mode:
      'dirty-rects' (default, flag esplicito --dirty-rects se serve
        forzarlo) - IncrementalRenderer: sfrutta la cache dello
        sfondo per aggiornare a schermo SOLO i rettangoli dove sono
        gli sprite (prima e dopo), invece dell'intero schermo -
        pygame.display.update(rects) invece di flip(). VERIFICATO su
        Raspberry Pi 1 vera come il piu' veloce: ~10-12ms/frame
        contro i ~48-54ms del percorso a buffer (~60fps contro
        ~19-20fps) - un salto netto, non marginale.
      'buffer' (flag --buffer-renderer) - render_frame() + un buffer
        piatto convertito in blocco (via pygame.image.frombuffer),
        con la cache dello sfondo. Era il default prima di verificare
        dirty-rects - lasciato come via di fuga esplicita.
      'surface' (flag --surface-renderer) - SurfaceRenderer: tile
        pre-costruite come pygame.Surface cachate, disegnate con
        blit(). "Strada 1" delle opzioni discusse - MISURATO su Pi 1
        vera: PIU' LENTO del buffer (~170ms contro ~115ms/frame
        all'epoca), non piu' veloce come sperato. ~150 chiamate
        blit()/frame con overhead fisso ciascuna, e SRCALPHA ha un
        costo di compositing che SDL software non ammortizza.
        Lasciato dietro flag per chi ha un driver video accelerato.

    Perche' dirty-rects batte surface nettamente pur usando anch'esso
    blit() per gli sprite: il numero di chiamate blit()/frame e' la
    differenza chiave - surface ne faceva ~150 (un blit per OGNI tile
    di sfondo, ogni frame), dirty-rects ne fa una manciata (solo per
    lo sprite, non per lo sfondo, che resta fermo). Stesso strumento
    (blit), applicato al problema giusto invece che a quello sbagliato.

    quit_pygame_at_end: se False, NON chiude pygame all'uscita - usato
    quando questa funzione e' chiamata dal menu (run_os_menu), che ha
    gia' una sessione pygame aperta e vuole riusarla, non ricrearla."""
    import time

    pygame = _init_pygame_once()
    gpu_window = None
    gpu_sdl_renderer = None
    if renderer_mode == 'gpu':
        # Renderer accelerato: NON puo' coesistere con una Surface
        # classica (pygame.display.set_mode) sulla stessa finestra -
        # "Surface already associated with window", scoperto testando
        # (vedi test_gpu.py e README). Finestra dedicata, creata con
        # l'API _sdl2.video invece di display.set_mode().
        video = _sdl2_video(pygame)
        gpu_window = video.Window("S32", size=(SCREEN_W_PX, SCREEN_H_PX),
                                   fullscreen=fullscreen)
        gpu_sdl_renderer = video.Renderer(gpu_window, accelerated=1, vsync=False)
        screen = None  # non usato in questa modalita'
    elif fullscreen:
        screen = pygame.display.set_mode((SCREEN_W_PX, SCREEN_H_PX), pygame.FULLSCREEN | pygame.SCALED)
    else:
        screen = pygame.display.set_mode((SCREEN_W_PX, SCREEN_H_PX))
    clock = pygame.time.Clock()

    surface_renderer = SurfaceRenderer(pygame) if renderer_mode == 'surface' else None
    incremental_renderer = IncrementalRenderer(pygame) if renderer_mode == 'dirty-rects' else None
    gpu_renderer = GpuRenderer(pygame, gpu_sdl_renderer) if renderer_mode == 'gpu' else None
    audio_player = AudioPlayer(pygame, use_audio, sound_bank=getattr(cpu, 'sound_bank', None))

    # cache dello sfondo (percorso 'buffer'): ricalcolato SOLO quando
    # cambia la chiave (stage, scroll_x, scroll_y) - stage via
    # STAGE_SELECT, scroll via PORT_SCROLL_X/Y (vedi cpu.py). Trovato
    # necessario profilando una scena di gioco vera (non una title
    # screen quasi vuota): su una stanza piena al 100% di tile,
    # ricalcolare 150 posizioni ogni frame quando lo sfondo e'
    # IDENTICO a quello di un istante fa era puro spreco - su
    # Raspberry Pi 1 il costo era quasi tutto li'.
    # CON LO SCROLL ATTIVO: la chiave cambia OGNI FRAME in cui la
    # telecamera si muove (la porzione di mappa visibile e' davvero
    # diversa) - il vantaggio della cache si applica solo quando la
    # telecamera resta ferma. Non e' un limite di questa cache, e' la
    # natura dello scroll: quando entra in vista qualcosa di nuovo va
    # disegnato per forza, non c'e' scorciatoia.
    # LIMITE NOTO: se in futuro una cartuccia scrive in VRAM (tilemap)
    # con poke() mentre e' gia' in uno stage (bypassando STAGE_SELECT),
    # questa cache (e quella dentro IncrementalRenderer) NON se ne
    # accorgono e mostrano contenuto vecchio finche' la chiave non
    # cambia di nuovo. Nessuna cartuccia attuale lo fa.
    bg_cache_key = None
    bg_cache_buf = None
    tile_blob_cache = {}  # persistente tra i frame - stesso motivo di
                           # IncrementalRenderer.tile_blob_cache (vedi
                           # ppu.render_background_window)
    stats = {'cpu': 0.0, 'render': 0.0, 'frames': 0}
    stats_t0 = time.perf_counter()

    # --- --playtest: sostituisce la tastiera con una sequenza
    # scriptata (vedi _playtest_sequence) e accumula i tempi PER FASE,
    # non solo un aggregato - cosi' un rallentamento durante lo scroll
    # non si nasconde in una media con le fasi ferme. Auto-termina
    # quando la sequenza finisce, cosi' una sessione SSH senza
    # tastiera/HDMI non resta appesa in attesa di un evento QUIT che
    # non arrivera' mai. ---
    playtest_seq = _playtest_sequence(quick=playtest_quick) if playtest else None
    playtest_i = 0
    phase_stats = {}  # etichetta -> {'cpu':.., 'render':.., 'frames':..}
    playtest_t_start = time.perf_counter()

    # -- multiplayer in rete (lockstep, vedi s32/netcode_lockstep.py):
    # frame_number identifica ogni frame univocamente per host e
    # client - deve avanzare di pari passo su tutte le istanze, o i
    # frame che si scambiano non corrisponderebbero piu'. Avanza SOLO
    # quando la simulazione avanza davvero (vedi sotto: se gli input
    # non sono ancora arrivati da tutti, si salta il frame e
    # frame_number NON avanza, altrimenti si perderebbe un numero e
    # tutte le istanze andrebbero fuori sincronia). --
    frame_number = 0

    running = True
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

        current_phase = None
        if playtest_seq is not None:
            if playtest_i >= len(playtest_seq):
                running = False
                break
            current_phase, input_byte = playtest_seq[playtest_i]
            playtest_i += 1
        else:
            keys = pygame.key.get_pressed()
            input_byte = 0
            if keys[pygame.K_UP] or keys[pygame.K_w]: input_byte |= 0x01
            if keys[pygame.K_DOWN] or keys[pygame.K_s]: input_byte |= 0x02
            if keys[pygame.K_LEFT] or keys[pygame.K_a]: input_byte |= 0x04
            if keys[pygame.K_RIGHT] or keys[pygame.K_d]: input_byte |= 0x08
            if keys[pygame.K_j] or keys[pygame.K_SPACE]: input_byte |= 0x10
            if keys[pygame.K_ESCAPE]:
                running = False

        # -- multiplayer in rete: se una sessione lockstep e' attiva,
        # l'input locale (da tastiera o playtest) non va alla CPU
        # direttamente - va prima scambiato con le altre istanze, e
        # SOLO quando tutte hanno risposto per questo frame si procede,
        # tutte insieme con lo stesso identico vettore di input (vedi
        # s32/netcode_lockstep.py e doc 04 del kit di rete). Se il
        # frame non e' ancora completo (lag), si salta senza disegnare
        # nulla di non sincronizzato - meglio un frame in ritardo che
        # uno disallineato tra le istanze. --
        extra_inputs = None
        if netcode_session is not None:
            netcode_session.submit_local_input(frame_number, input_byte)
            frame_inputs = netcode_session.get_frame_inputs(frame_number, timeout=0.25)
            if frame_inputs is None:
                continue
            input_byte = frame_inputs[local_player_index]
            extra_inputs = tuple(
                v for i, v in enumerate(frame_inputs) if i != local_player_index
            )

        t0 = time.perf_counter()
        n_istruzioni = cpu.run(CART_LOAD_ADDR, input_byte=input_byte, extra_inputs=extra_inputs)
        t1 = time.perf_counter()
        frame_number += 1

        # audio PRIMA del rendering: il disegno puo' costare decine di
        # ms su hardware lento (vedi --stats), e far aspettare un
        # effetto sonoro fin dopo il disegno lo renderebbe percepibile
        # in ritardo rispetto all'azione che lo ha causato
        audio_player.play_queue(cpu)

        vram = cpu.mem[VRAM_BASE:VRAM_BASE + VRAM_SIZE]
        oam = cpu.mem[OAM_BASE:OAM_BASE + OAM_SIZE]
        cgram = cpu.mem[CGRAM_BASE:CGRAM_BASE + CGRAM_SIZE]

        if gpu_renderer is not None:
            gpu_renderer.render(vram, oam, cgram, cpu.current_stage,
                                 cpu.scroll_x, cpu.scroll_y)
            # NON chiama flip()/update(): renderer.present() e' gia'
            # dentro GpuRenderer.render()
        elif incremental_renderer is not None:
            incremental_renderer.render(screen, vram, oam, cgram, cpu.current_stage,
                                         cpu.scroll_x, cpu.scroll_y)
            # NON chiama flip() qui: IncrementalRenderer aggiorna gia'
            # da solo, in modo parziale, con pygame.display.update()
        else:
            if surface_renderer is not None:
                surface_renderer.render(screen, vram, oam, cgram, cpu.current_stage,
                                         cpu.scroll_x, cpu.scroll_y)
            else:
                cache_key = (cpu.current_stage, cpu.scroll_x, cpu.scroll_y)
                if bg_cache_key != cache_key:
                    bg_cache_buf = render_background(vram, cgram, cpu.scroll_x, cpu.scroll_y,
                                                       blob_cache=tile_blob_cache)
                    bg_cache_key = cache_key
                frame_buf = bytearray(bg_cache_buf)  # copia a livello C, non
                                                       # un ciclo Python - molto
                                                       # piu' economico che
                                                       # ricostruire lo sfondo
                draw_sprites(frame_buf, oam, cgram, vram)
                surf = _pixels_to_surface(frame_buf, SCREEN_W_PX, SCREEN_H_PX)
                screen.blit(surf, (0, 0))
            pygame.display.flip()
        t2 = time.perf_counter()

        if current_phase is not None:
            ps = phase_stats.setdefault(current_phase, {'cpu': 0.0, 'render': 0.0, 'frames': 0, 'istruzioni': 0})
            ps['cpu'] += t1 - t0
            ps['render'] += t2 - t1
            ps['frames'] += 1
            ps['istruzioni'] += n_istruzioni
            _renderer_con_timing = gpu_renderer or incremental_renderer
            if _renderer_con_timing is not None and _renderer_con_timing.last_timing is not None:
                for k, v in _renderer_con_timing.last_timing.items():
                    ps.setdefault('scroll_' + k, 0.0)
                    ps['scroll_' + k] += v
                ps['scroll_frames'] = ps.get('scroll_frames', 0) + 1

        if show_stats:
            stats['cpu'] += t1 - t0
            stats['render'] += t2 - t1
            stats['frames'] += 1
            stats['istruzioni'] = stats.get('istruzioni', 0) + n_istruzioni
            stats['istruzioni_max'] = max(stats.get('istruzioni_max', 0), n_istruzioni)
            _renderer_con_timing = gpu_renderer or incremental_renderer
            if _renderer_con_timing is not None and _renderer_con_timing.last_timing is not None:
                for k, v in _renderer_con_timing.last_timing.items():
                    stats.setdefault('scroll_' + k, 0.0)
                    stats['scroll_' + k] += v
                stats['scroll_frames'] = stats.get('scroll_frames', 0) + 1
                _renderer_con_timing.last_timing = None
            if time.perf_counter() - stats_t0 >= 1.0:
                n = stats['frames']
                label = renderer_mode.ljust(11)
                istr_medie = stats.get('istruzioni', 0) / n
                istr_max = stats.get('istruzioni_max', 0)
                print(f"[{label}] fps={n} | cpu={stats['cpu']/n*1000:.1f}ms "
                      f"render+blit={stats['render']/n*1000:.1f}ms "
                      f"totale={( stats['cpu']+stats['render'] )/n*1000:.1f}ms/frame "
                      f"| istruzioni: media={istr_medie:.0f} max={istr_max}")
                sn = stats.get('scroll_frames', 0)
                if sn:
                    parts = ' '.join(
                        f"{k.replace('scroll_', '')}={stats[k]/sn*1000:.1f}ms"
                        for k in ('scroll_surface_scroll', 'scroll_strip_compute',
                                  'scroll_strip_blit', 'scroll_screen_blit', 'scroll_flip',
                                  'scroll_texture_update', 'scroll_draw_sprites', 'scroll_present')
                        if k in stats
                    )
                    print(f"  [dettaglio scroll, {sn} frame in scroll] {parts}")
                stats = {'cpu': 0.0, 'render': 0.0, 'frames': 0}
                stats_t0 = time.perf_counter()

        clock.tick(60)

    if playtest_seq is not None:
        _print_playtest_summary(phase_stats, renderer_mode,
                                 time.perf_counter() - playtest_t_start)

    if quit_pygame_at_end:
        pygame.quit()


def _print_playtest_summary(phase_stats, renderer_mode, wall_seconds):
    """Tabella finale di --playtest, pensata per essere copiata e
    incollata cosi' com'e' - una riga per fase, piu' un totale
    generale. A differenza delle righe periodiche di --stats (una al
    secondo, tante, difficili da riassumere a mano) questo e' UN
    blocco solo, leggibile subito."""
    print()
    print(f"=== RIEPILOGO PLAYTEST ({renderer_mode}, {wall_seconds:.1f}s reali) ===")
    print(f"{'fase':<26} {'frame':>6} {'cpu ms':>8} {'render ms':>10} {'totale ms':>10} {'fps':>6} {'istr/frame':>10}")
    tot_frames = 0
    tot_cpu = 0.0
    tot_render = 0.0
    tot_istruzioni = 0
    for label in sorted(phase_stats.keys()):
        ps = phase_stats[label]
        n = ps['frames']
        if n == 0:
            continue
        cpu_ms = ps['cpu'] / n * 1000
        render_ms = ps['render'] / n * 1000
        tot_ms = cpu_ms + render_ms
        fps = 1000 / tot_ms if tot_ms > 0 else 0
        istr_medie = ps.get('istruzioni', 0) / n
        print(f"{label:<26} {n:>6} {cpu_ms:>8.2f} {render_ms:>10.2f} {tot_ms:>10.2f} {fps:>6.1f} {istr_medie:>10.0f}")
        tot_frames += n
        tot_cpu += ps['cpu']
        tot_render += ps['render']
        tot_istruzioni += ps.get('istruzioni', 0)

        sn = ps.get('scroll_frames', 0)
        if sn:
            parts = ' '.join(
                f"{k.replace('scroll_', '')}={ps[k]/sn*1000:.2f}ms"
                for k in ('scroll_surface_scroll', 'scroll_strip_compute',
                          'scroll_strip_blit', 'scroll_screen_blit', 'scroll_flip',
                          'scroll_texture_update', 'scroll_draw_sprites', 'scroll_present')
                if k in ps
            )
            print(f"  -> dettaglio scroll ({sn} frame in scroll): {parts}")

    if tot_frames:
        tot_ms = (tot_cpu + tot_render) / tot_frames * 1000
        fps = 1000 / tot_ms if tot_ms > 0 else 0
        print(f"{'-'*26} {'-'*6} {'-'*8} {'-'*10} {'-'*10} {'-'*6} {'-'*10}")
        print(f"{'TOTALE':<26} {tot_frames:>6} "
              f"{tot_cpu/tot_frames*1000:>8.2f} {tot_render/tot_frames*1000:>10.2f} "
              f"{tot_ms:>10.2f} {fps:>6.1f} {tot_istruzioni/tot_frames:>10.0f}")
    print("=== fine playtest - incolla questo blocco ===")
    print()


def run_os_menu():
    """Mostra il menu di avvio (scoperta cartucce + selezione),
    poi lancia quella scelta tramite run_direct. Si apre SEMPRE,
    anche senza cartucce trovate - mostra un messaggio invece di
    chiudersi silenziosamente in console.

    NOTA: la sessione pygame resta la STESSA dall'inizio alla fine
    (menu incluso) - passare dal menu al gioco NON chiude e riapre
    la finestra, solo la ridimensiona (pygame.display.set_mode() puo'
    essere richiamato piu' volte sulla stessa sessione). Prima
    capitava il contrario: pygame.quit() poi un pygame.init() da
    zero, costoso e visibile come un lampeggio della finestra."""
    pygame = _init_pygame_once()

    carts_dir = os.path.join(os.path.dirname(__file__), '..', 'carts')
    carts = discover_carts(carts_dir)
    menu = MenuState(carts)

    screen = pygame.display.set_mode((512, 448))
    font = pygame.font.SysFont(None, 28)
    font_small = pygame.font.SysFont(None, 20)
    clock = pygame.time.Clock()

    running = True
    chosen = None
    while running and chosen is None:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                elif not menu.is_empty():
                    if event.key in (pygame.K_UP, pygame.K_w):
                        menu.move_up()
                    elif event.key in (pygame.K_DOWN, pygame.K_s):
                        menu.move_down()
                    elif event.key in (pygame.K_RETURN, pygame.K_j, pygame.K_SPACE):
                        chosen = menu.selected()

        screen.fill((20, 20, 30))
        if menu.is_empty():
            text = font.render("NO ROM FOUND", True, (200, 90, 90))
            screen.blit(text, (40, 40))
            hint = font_small.render(f"(cercato in: {os.path.abspath(carts_dir)})", True, (140, 140, 140))
            screen.blit(hint, (40, 80))
        else:
            for i, cart in enumerate(menu.items):
                color = (255, 220, 100) if i == menu.index else (200, 200, 200)
                text = font.render(cart.title, True, color)
                screen.blit(text, (40, 40 + i * 36))
        pygame.display.flip()
        clock.tick(30)

    if chosen is not None:
        entry = chosen.entry_py() or chosen.entry_asm()
        kind = 'py' if chosen.entry_py() else 'asm'
        run_direct(entry, kind)  # riusa la stessa sessione pygame,
                                  # la chiude lui alla fine (default)
    else:
        pygame.quit()  # l'utente ha chiuso il menu senza scegliere


def run_benchmark(path, kind, n_frames=120, profile=False):
    """Misura le prestazioni SENZA aprire alcuna finestra (niente
    pygame.display) - utile per testare velocemente su una macchina
    debole/senza schermo comodo (es. una Raspberry Pi via SSH) senza
    dover configurare SDL. Stampa ms/frame medi per cpu.run() e
    render_frame(), fps stimati, e la RAM di picco usata dal processo.

    profile=True usa cProfile per mostrare il tempo speso in OGNI
    funzione (non solo il totale cpu.run()/render_frame()) - utile
    quando i numeri aggregati non spiegano da soli dove va il tempo
    su un hardware specifico (vedi caso Raspberry Pi 1 in README.md)."""
    import time
    import resource

    if not os.path.isfile(path):
        raise LauncherError(
            f'File non trovato: "{path}" (risolto come "{os.path.abspath(path)}" '
            f'dalla cartella corrente "{os.getcwd()}" - controlla di lanciare il '
            f'comando dalla cartella giusta)'
        )

    rom, state_vars = load_cart_rom(path, kind)
    cpu = CPU()
    for i, b in enumerate(rom):
        cpu.mem[CART_LOAD_ADDR + i] = b
    for name, (addr, init_val) in state_vars.items():
        cpu.write16(addr, init_val)
    _load_cart_graphics(cpu, os.path.dirname(path))

    if profile:
        import cProfile
        import pstats

        def do_frames():
            for _ in range(n_frames):
                cpu.run(CART_LOAD_ADDR, input_byte=0)
                vram = cpu.mem[VRAM_BASE:VRAM_BASE + VRAM_SIZE]
                oam = cpu.mem[OAM_BASE:OAM_BASE + OAM_SIZE]
                cgram = cpu.mem[CGRAM_BASE:CGRAM_BASE + CGRAM_SIZE]
                render_frame(vram, oam, cgram)

        profiler = cProfile.Profile()
        profiler.enable()
        do_frames()
        profiler.disable()

        print(f'--- profilo dettagliato: {path} ({n_frames} frame) ---')
        stats = pstats.Stats(profiler)
        stats.sort_stats('cumulative')
        stats.print_stats(20)  # le 20 funzioni piu' costose
        return

    cpu_total = 0.0
    render_total = 0.0
    for _ in range(n_frames):
        t0 = time.perf_counter()
        cpu.run(CART_LOAD_ADDR, input_byte=0)
        t1 = time.perf_counter()
        vram = cpu.mem[VRAM_BASE:VRAM_BASE + VRAM_SIZE]
        oam = cpu.mem[OAM_BASE:OAM_BASE + OAM_SIZE]
        cgram = cpu.mem[CGRAM_BASE:CGRAM_BASE + CGRAM_SIZE]
        render_frame(vram, oam, cgram)
        t2 = time.perf_counter()
        cpu_total += t1 - t0
        render_total += t2 - t1

    cpu_ms = cpu_total / n_frames * 1000
    render_ms = render_total / n_frames * 1000
    total_ms = cpu_ms + render_ms

    # seconda misura: stessa strategia del loop di gioco vero (vedi
    # _run_pygame_loop) - sfondo cachato (ricalcolato solo se cambia
    # stage), sprite ridisegnati sopra ogni frame. Su una scena
    # STATICA (nessuno scroll, stage invariato - il caso di questo
    # benchmark) e' il numero che rispecchia davvero cosa vivrai
    # giocando, non il caso peggiore "ricalcola tutto da zero" sopra.
    render_cached_total = 0.0
    bg_cache_key = None
    bg_cache_buf = None
    tile_blob_cache = {}
    for _ in range(n_frames):
        cpu.run(CART_LOAD_ADDR, input_byte=0)
        vram = cpu.mem[VRAM_BASE:VRAM_BASE + VRAM_SIZE]
        oam = cpu.mem[OAM_BASE:OAM_BASE + OAM_SIZE]
        cgram = cpu.mem[CGRAM_BASE:CGRAM_BASE + CGRAM_SIZE]
        t0 = time.perf_counter()
        cache_key = (cpu.current_stage, cpu.scroll_x, cpu.scroll_y)
        if bg_cache_key != cache_key:
            bg_cache_buf = render_background(vram, cgram, cpu.scroll_x, cpu.scroll_y,
                                              blob_cache=tile_blob_cache)
            bg_cache_key = cache_key
        frame_buf = bytearray(bg_cache_buf)
        draw_sprites(frame_buf, oam, cgram, vram)
        t1 = time.perf_counter()
        render_cached_total += t1 - t0
    render_cached_ms = render_cached_total / n_frames * 1000
    total_cached_ms = cpu_ms + render_cached_ms

    peak_rss_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024  # KB->MB su Linux

    print(f'--- benchmark: {path} ({n_frames} frame) ---')
    print(f'cpu.run():                {cpu_ms:.2f} ms/frame')
    print(f'render_frame() (da zero): {render_ms:.2f} ms/frame  <- caso peggiore, ricalcola tutto ogni frame')
    print(f'render con cache sfondo:  {render_cached_ms:.2f} ms/frame  <- quello che vivrai giocando (scena statica)')
    print(f'totale (da zero):         {total_ms:.2f} ms/frame  (~{1000/total_ms:.1f} fps teorici)')
    print(f'totale (con cache):       {total_cached_ms:.2f} ms/frame  (~{1000/total_cached_ms:.1f} fps teorici)')
    print(f'(entrambi SENZA il costo del blit a schermo)')
    print(f'RAM di picco:   {peak_rss_mb:.1f} MB')


def parse_flags(argv):
    """Estrae i flag di prestazioni (--stats, --benchmark, --profile,
    --surface-renderer, --buffer-renderer, --gpu-renderer, --fullscreen,
    --no-audio, --playtest, --playtest-quick, --netplay-host,
    --netplay-join) da argv, ritornando (argv_ripulito, dict_flag) -
    separato da determine_mode() apposta, per restare entrambi
    testabili singolarmente.

    L'audio e' ATTIVO DI DEFAULT (--no-audio per disattivarlo - utile
    su Raspberry Pi con ALSA mal configurato, vedi AudioPlayer).

    Il renderer predefinito e' 'dirty-rects' - VERIFICATO su Raspberry
    Pi 1 vera come il piu' veloce (~10-12ms/frame contro i ~48-54ms
    del percorso a buffer, vedi README.md). --buffer-renderer torna
    al percorso precedente se mai servisse un confronto o emergesse
    un limite non ancora visto.

    --netplay-host <porta> <num_giocatori> e --netplay-join <ip>
    <porta> abilitano il multiplayer in rete (lockstep, vedi
    s32/netcode_lockstep.py) - a differenza degli altri flag,
    consumano 2 argomenti SUCCESSIVI, non solo se stessi. Lasciati
    fuori dal kit di rete originale apposta ("meglio scriverlo voi
    seguendo lo stile esistente"), aggiunti qui."""
    flags = {'stats': False, 'benchmark': False, 'profile': False, 'renderer': 'dirty-rects', 'fullscreen': False, 'audio': True, 'playtest': False, 'playtest_quick': False,
              'netplay_host_port': None, 'netplay_host_players': None, 'netplay_join_addr': None}
    rest = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == '--stats':
            flags['stats'] = True
        elif arg == '--benchmark':
            flags['benchmark'] = True
        elif arg == '--profile':
            flags['profile'] = True
        elif arg == '--surface-renderer':
            flags['renderer'] = 'surface'
        elif arg == '--buffer-renderer':
            flags['renderer'] = 'buffer'
        elif arg == '--gpu-renderer':
            flags['renderer'] = 'gpu'
        elif arg == '--fullscreen':
            flags['fullscreen'] = True
        elif arg == '--audio':
            flags['audio'] = True
        elif arg == '--no-audio':
            flags['audio'] = False
        elif arg == '--playtest':
            flags['playtest'] = True
        elif arg == '--playtest-quick':
            flags['playtest'] = True
            flags['playtest_quick'] = True
        elif arg == '--netplay-host':
            if i + 2 >= len(argv):
                raise LauncherError('--netplay-host richiede due argomenti: <porta> <num_giocatori>')
            try:
                porta = int(argv[i+1])
                num_giocatori = int(argv[i+2])
            except ValueError:
                raise LauncherError(
                    f'--netplay-host: porta e numero giocatori devono essere numeri interi '
                    f'(ricevuto "{argv[i+1]}" "{argv[i+2]}")')
            if not (2 <= num_giocatori <= 8):
                raise LauncherError(f'--netplay-host: numero giocatori fuori range (2-8): {num_giocatori}')
            flags['netplay_host_port'] = porta
            flags['netplay_host_players'] = num_giocatori
            i += 2
        elif arg == '--netplay-join':
            if i + 2 >= len(argv):
                raise LauncherError('--netplay-join richiede due argomenti: <ip> <porta>')
            try:
                porta = int(argv[i+2])
            except ValueError:
                raise LauncherError(f'--netplay-join: porta deve essere un numero intero (ricevuto "{argv[i+2]}")')
            flags['netplay_join_addr'] = (argv[i+1], porta)
            i += 2
        else:
            rest.append(arg)
        i += 1
    return rest, flags


def main():
    argv, flags = parse_flags(sys.argv)
    mode = determine_mode(argv)
    if mode[0] == 'menu':
        run_os_menu()
    else:
        _, path, kind = mode
        if flags['benchmark'] or flags['profile']:
            run_benchmark(path, kind, profile=flags['profile'])
        else:
            netcode_session = None
            local_player_index = 0
            if flags['netplay_host_port'] is not None:
                from netcode_lockstep import LockstepHost
                porta = flags['netplay_host_port']
                num_giocatori = flags['netplay_host_players']
                print(f"[netplay] host in ascolto sulla porta {porta}, "
                      f"aspetto {num_giocatori} giocatori...")
                netcode_session = LockstepHost(num_players=num_giocatori, bind_port=porta)
                netcode_session.wait_for_players()
                local_player_index = 0  # l'host e' sempre il giocatore 0
                print("[netplay] tutti i giocatori connessi, si parte")
            elif flags['netplay_join_addr'] is not None:
                from netcode_lockstep import LockstepClient
                ip, porta = flags['netplay_join_addr']
                print(f"[netplay] mi connetto a {ip}:{porta}...")
                netcode_session = LockstepClient()
                local_player_index = netcode_session.connect(ip, host_port=porta)
                print(f"[netplay] connesso - sono il giocatore {local_player_index}")

            run_direct(path, kind, show_stats=flags['stats'], renderer_mode=flags['renderer'],
                       fullscreen=flags['fullscreen'], use_audio=flags['audio'], playtest=flags['playtest'],
                       playtest_quick=flags['playtest_quick'],
                       netcode_session=netcode_session, local_player_index=local_player_index)


if __name__ == '__main__':
    main()
