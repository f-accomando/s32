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
import mmap
import importlib.util

# --screen-mode va intercettato QUI, PRIMA di qualunque import che
# porti a "from memory_map import SCREEN_W_PX/H_PX" (lang.py e cpu.py
# sotto lo fanno gia', indirettamente anche ppu.py) - quella sintassi
# COPIA il valore al momento dell'import, troppo presto per un flag
# letto dentro parse_flags()/main(). Vedi memory_map.py per il
# perche' di una variabile d'ambiente invece di un parametro normale.
# Se il valore manca, non solleviamo nulla qui: parse_flags() (piu'
# sotto in questo file) vede comunque '--screen-mode' in argv e
# solleva il consueto LauncherError con un messaggio chiaro - questo
# blocco al massimo lascia attiva la risoluzione di default per
# l'istante prima che il programma si fermi comunque su quell'errore.
if '--screen-mode' in sys.argv:
    _i = sys.argv.index('--screen-mode')
    if _i + 1 < len(sys.argv):
        os.environ['S32_SCREEN_MODE'] = sys.argv[_i + 1]

from assembler import assemble
from lang import compile_source as compile_consolelang
from cpu import CPU
import audio
from ppu import render_frame, render_background, render_background_window, draw_sprites, iter_visible_sprite_tiles
from fb_convert import rgb888_to_rgb565
from memory_map import (
    VRAM_SIZE, OAM_SIZE, CGRAM_SIZE, VRAM_BASE, OAM_BASE, CGRAM_BASE,
    OAM_SLOT_BYTES, TILE_SIZE_PX, SCREEN_W_PX, SCREEN_H_PX,
)

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


def run_direct(path, kind, show_stats=False, quit_pygame_at_end=True, renderer_mode='dirty-rects', fullscreen=False, use_audio=False, playtest=False, playtest_quick=False, netcode_session=None, local_player_index=0, fbdev_path=None):
    """Bypassa il menu, carica ed esegue direttamente la cartuccia
    data - stesso comportamento immediato della v1 (python3 main.py).

    Ritorna True se l'utente ha chiuso la FINESTRA (pygame.QUIT)
    durante la partita, False se il loop si e' fermato per un altro
    motivo (ESC, fine sequenza --playtest) - os_menu.py lo usa per
    decidere se tornare al menu o chiudere tutto il programma."""
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

    return _run_pygame_loop(cpu, show_stats=show_stats, quit_pygame_at_end=quit_pygame_at_end,
                             renderer_mode=renderer_mode, fullscreen=fullscreen,
                             use_audio=use_audio, playtest=playtest, playtest_quick=playtest_quick,
                             netcode_session=netcode_session, local_player_index=local_player_index,
                             fbdev_path=fbdev_path)


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
        self.bg_texture = None       # GPU-side, l'unica sorgente di verita' -
                                      # niente piu' una Surface CPU parallela
                                      # da tenere sincronizzata (vedi render())
        self.bg_texture_scratch = None  # seconda texture "target", usata a
                                         # turno con bg_texture per lo scroll
                                         # GPU-side (ping-pong, vedi render())
        self.bg_strip_texture = None    # texture riutilizzata ogni frame di
                                         # scroll per caricare SOLO la striscia
                                         # nuova (poche righe, non l'intero
                                         # schermo) - vedi render()
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

        full_rebuild = self.bg_texture is None or current_stage != self.bg_stage
        gpu_shift = None            # (dy, strip_surf, strip_y, strip_h): scroll GPU-side
        full_update_surface = None  # Surface COMPLETA da caricare (primo frame / rebuild)

        if not full_rebuild and (scroll_x != self.bg_scroll_x or scroll_y != self.bg_scroll_y):
            dx = scroll_x - self.bg_scroll_x
            dy = scroll_y - self.bg_scroll_y
            if dx == 0 and 0 < abs(dy) < SCREEN_H_PX:
                # SCROLL GPU-SIDE VERO (issue #10): la strada scartata
                # in precedenza per mancanza di modo di verificarla su
                # hardware reale. Storia completa:
                #
                # v1: si aggiornava sulla texture SOLO l'area della
                # striscia nuova (Texture.update(area=striscia),
                # ~1.5ms) - veloce ma visivamente rotto: una texture
                # GPU non ha un equivalente di Surface.scroll() (che
                # SPOSTA FISICAMENTE i pixel gia' disegnati in una
                # Surface CPU) - il resto del contenuto gia' caricato
                # restava congelato alla vecchia posizione mentre gli
                # sprite si muovevano. BUG TROVATO DALL'UTENTE GIOCANDO
                # DAVVERO: "il personaggio sembrava stazionario e i
                # nemici oltrepassavano il muro".
                #
                # v2 (fix precedente): si spingeva sempre l'INTERO
                # bg_surface (480x320) sulla texture ad ogni frame di
                # scroll - corretto, ma il costo di un caricamento
                # pieno CPU->GPU ad ogni frame (~36ms misurato su Pi 1
                # reale) mangiava quasi tutto il guadagno che la GPU
                # avrebbe dato altrove.
                #
                # v3 (questa versione): la STESSA correttezza di v2
                # (nessuna area che resta congelata: lo shift copre
                # l'intera texture, la striscia nuova copre esattamente
                # l'area che lo shift rivela, insieme le due coprono il
                # 100% - identica matematica di
                # self.bg_surface.scroll(0,-dy)+blit() gia' usata da
                # IncrementalRenderer) MA senza il suo costo: invece di
                # ricaricare tutto da una Surface CPU, spostiamo il
                # contenuto GIA' in VRAM con un render-to-texture
                # (disegnare la vecchia texture, shiftata, dentro una
                # texture "target" - un'operazione GPU->GPU, mai un
                # giro per la RAM) e carichiamo dalla CPU SOLO la
                # striscia nuova (poche righe, non l'intero schermo -
                # vedi bg_strip_texture piu' sotto).
                t0 = time.perf_counter()
                if dy > 0:
                    strip_h = dy
                    strip_y = SCREEN_H_PX - strip_h
                else:
                    strip_h = -dy
                    strip_y = 0
                strip_buf = render_background_window(vram, cgram, scroll_x, scroll_y, strip_y, strip_h,
                                                      blob_cache=self.tile_blob_cache)
                t1 = time.perf_counter()
                strip_surf = pygame.image.frombuffer(bytes(strip_buf), (SCREEN_W_PX, strip_h), 'RGB')
                t2 = time.perf_counter()
                gpu_shift = (dy, strip_surf, strip_y, strip_h)
                self.bg_scroll_x = scroll_x
                self.bg_scroll_y = scroll_y
                self.last_timing = {
                    'strip_compute': t1 - t0,
                    'strip_surface': t2 - t1,
                }
            else:
                full_rebuild = True

        if full_rebuild:
            bg_buf = render_background(vram, cgram, scroll_x, scroll_y, blob_cache=self.tile_blob_cache)
            # NIENTE .convert() qui (a differenza di IncrementalRenderer):
            # .convert() richiede un display "classico" attivo
            # (pygame.display.set_mode()), che in modalita' GPU non
            # esiste mai - usiamo una finestra dedicata via
            # _sdl2.video.Window. La Surface va bene cosi' com'e' per
            # Texture(...).update(). Bug trovato testando:
            # "pygame.error: Parameter 'surface' is invalid".
            full_update_surface = pygame.image.frombuffer(bytes(bg_buf), (SCREEN_W_PX, SCREEN_H_PX), 'RGB')
            self.bg_stage = current_stage
            self.bg_scroll_x = scroll_x
            self.bg_scroll_y = scroll_y

        t3 = time.perf_counter()
        if gpu_shift is not None:
            dy, strip_surf, strip_y, strip_h = gpu_shift
            # bg_texture_scratch e bg_strip_texture sono create UNA
            # SOLA VOLTA (al primo scroll) e riusate per sempre - la
            # stessa filosofia gia' usata per l'atlas sprite: creare
            # una texture GPU non e' gratis, quindi mai farlo ogni
            # frame quando si puo' riusare la stessa. bg_texture_scratch
            # DEVE essere creata con target=True fin dall'inizio (mai
            # da Texture.from_surface(), che non garantisce una
            # texture utilizzabile come target) - vedi anche
            # bg_texture stesso, creato con target=True qui sotto per
            # lo stesso motivo: nello scambio ping-pong ogni frame
            # l'una prende il posto dell'altra, quindi ENTRAMBE devono
            # poter fare da target in un frame di scroll futuro.
            if self.bg_texture_scratch is None:
                self.bg_texture_scratch = self.video.Texture(self.renderer, (SCREEN_W_PX, SCREEN_H_PX), target=True)
            if self.bg_strip_texture is None:
                self.bg_strip_texture = self.video.Texture(self.renderer, (SCREEN_W_PX, SCREEN_H_PX))
            self.renderer.target = self.bg_texture_scratch
            # 1) sposta il contenuto GIA' in VRAM (GPU->GPU, la vecchia
            # texture per intero ma shiftata) - stessa direzione di
            # Surface.scroll(0, -dy)
            self.bg_texture.draw(dstrect=(0, -dy, SCREEN_W_PX, SCREEN_H_PX))
            # 2) carica SOLO la striscia nuova (CPU->GPU, ma piccola -
            # questo e' l'UNICO upload rimasto, proporzionale a
            # strip_h non a SCREEN_H_PX) e disegnala esattamente
            # nell'area che lo shift sopra ha lasciato scoperta
            self.bg_strip_texture.update(strip_surf, area=(0, 0, SCREEN_W_PX, strip_h))
            self.bg_strip_texture.draw(srcrect=(0, 0, SCREEN_W_PX, strip_h),
                                        dstrect=(0, strip_y, SCREEN_W_PX, strip_h))
            self.renderer.target = None
            # ping-pong: la texture appena disegnata diventa quella
            # "corrente", la vecchia corrente diventa lo scratch per
            # il prossimo frame di scroll
            self.bg_texture, self.bg_texture_scratch = self.bg_texture_scratch, self.bg_texture
        elif self.bg_texture is None:
            self.bg_texture = self.video.Texture(self.renderer, (SCREEN_W_PX, SCREEN_H_PX), target=True)
            self.bg_texture.update(full_update_surface)
        elif full_update_surface is not None:
            self.bg_texture.update(full_update_surface)
        t4 = time.perf_counter()
        if self.last_timing is not None:
            self.last_timing['gpu_shift'] = t4 - t3

        # -- composizione: sempre l'intero frame, ogni frame. Con la
        # GPU a ~2ms per un frame pieno (misurato, vedi test_launcher.py),
        # tracciare "dirty rect" per gli sprite non vale piu' la
        # complessita' che costava su Surface software.
        #
        # QUI SOTTO ERA UN SOLO 'draw_sprites' che includeva clear() +
        # il draw dello SFONDO INTERO (480x320, non un piccolo tile
        # 32x32!) + il loop degli sprite - un'etichetta fuorviante
        # trovata analizzando issue #24 (draw_sprites misurato a
        # ~12-14ms su Pi 1 reale): un benchmark isolato di soli draw()
        # 32x32 (bench_gpu_draw.py) costava una FRAZIONE di quel
        # tempo, mostrando che il vero sospettato non erano gli sprite
        # (solo 3-7 per frame durante lo scroll) ma quasi certamente
        # il draw() dello sfondo a schermo intero, nascosto dentro la
        # stessa etichetta. Separato in tre timing distinti apposta -
        # senza questo dettaglio non si può distinguere "il problema è
        # lo sfondo" da "il problema sono gli sprite". --
        t4b = time.perf_counter()
        self.renderer.clear()
        t4c = time.perf_counter()
        self.bg_texture.draw(dstrect=(0, 0, SCREEN_W_PX, SCREEN_H_PX))
        t4d = time.perf_counter()
        for tile_index, palette, x, y in iter_visible_sprite_tiles(oam):
            srcrect = self._sprite_tile_srcrect(vram, cgram, tile_index, palette)
            self.sprite_atlas_texture.draw(srcrect=srcrect, dstrect=(x, y, TILE_SIZE_PX, TILE_SIZE_PX))
        t6 = time.perf_counter()
        self.renderer.present()
        t7 = time.perf_counter()
        if self.last_timing is not None:
            self.last_timing['clear'] = t4c - t4b
            self.last_timing['bg_draw'] = t4d - t4c
            self.last_timing['sprite_draws'] = t6 - t4d
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


def _ticks_to_catch_up(accumulator, tick_dt, max_ticks):
    """Timestep fisso per il loop di gioco locale interattivo (vedi
    _run_pygame_loop): quanti tick di simulazione da tick_dt secondi
    servono per "consumare" l'accumulatore di tempo reale trascorso,
    con un tetto max_ticks - oltre quel tetto si accetta di perdere
    tempo simulato invece di provare a recuperarlo tutto insieme
    (evita una "spirale della morte" se il rendering si e' bloccato a
    lungo, es. il primissimo frame). Funzione pura, separata dal
    resto del loop apposta per essere testabile senza pygame/hardware.

    Ritorna (numero_di_tick, accumulatore_residuo)."""
    n = 0
    while accumulator >= tick_dt and n < max_ticks:
        accumulator -= tick_dt
        n += 1
    return n, accumulator


def _write_changed_rows(dst, out, prev, row_bytes, n_rows, dst_row_stride=None, dst_row_offset=0):
    """Scrive in dst (supporta slice assignment - un mmap o un
    bytearray normale, usato cosi' nei test senza bisogno di un vero
    framebuffer) solo le righe di `out` diverse dalla riga
    corrispondente in `prev`. out/prev hanno lo stesso layout
    (row_bytes*n_rows byte totali, riga per riga). Se prev e' None
    (primo frame, niente da confrontare), scrive tutto.

    dst_row_stride/dst_row_offset: per quando dst e' un framebuffer
    FISICO piu' largo del contenuto logico (bordo nero ai lati/sopra-
    sotto, vedi FramebufferRenderer con --screen-mode) - dst_row_stride
    e' quanti byte separano l'inizio di una riga fisica dalla prossima
    (se diverso da row_bytes), dst_row_offset e' il byte di partenza
    della prima riga logica dentro il framebuffer fisico (l'angolo in
    alto a sinistra dell'area di gioco). Di default (entrambi None/0)
    dst ha lo stesso layout di out/prev, nessun bordo - comportamento
    identico a prima.

    Ritorna il numero di righe effettivamente riscritte - usato dai
    test per verificare che le righe invariate vengano davvero
    saltate, non solo che il risultato finale sia corretto.

    MISURATO su Raspberry Pi 1 vero: la prima versione di questa
    funzione confrontava le righe con `out[start:end] != prev[start:end]`
    - ogni slice su un bytearray/bytes CREA UNA COPIA nuova (960 byte
    qui), quindi 320 confronti = 320 allocazioni+copie A OGNI FRAME,
    anche quando NESSUNA riga era cambiata. Su questo hardware
    lentissimo, quel costo fisso da solo valeva gia' ~200ms/frame -
    identico che scrivessimo 0 righe o 26, il "risparmio" del
    dirty-diff veniva mangiato dal costo del confronto stesso.
    Corretto con due passaggi:
    1) un confronto dell'INTERO buffer prima di tutto (out == prev,
       un solo memcmp a livello C su 307KB) - se il frame e' identico
       al precedente, si esce subito senza toccare le 320 righe (questo
       confronto e' sul contenuto LOGICO, quindi vale a prescindere dal
       bordo - un bordo non tocca mai out/prev, solo dove finiscono in dst);
    2) per il confronto riga per riga (frame DIVERSO da quello
       precedente), si usano memoryview invece di slice dirette:
       affettare un memoryview NON copia i dati (crea solo una vista
       sullo stesso buffer), a differenza di affettare un bytearray."""
    if dst_row_stride is None:
        dst_row_stride = row_bytes
    no_border = dst_row_stride == row_bytes and dst_row_offset == 0
    if prev is None:
        if no_border:
            dst[0:len(out)] = out
        else:
            for y in range(n_rows):
                s = y * row_bytes
                d = y * dst_row_stride + dst_row_offset
                dst[d:d + row_bytes] = out[s:s + row_bytes]
        return n_rows
    if out == prev:
        return 0
    out_mv = memoryview(out)
    prev_mv = memoryview(prev)
    written = 0
    for y in range(n_rows):
        start = y * row_bytes
        end = start + row_bytes
        if out_mv[start:end] != prev_mv[start:end]:
            d = y * dst_row_stride + dst_row_offset
            dst[d:d + row_bytes] = out_mv[start:end]
            written += 1
    return written


class FramebufferRenderer:
    """Quinto percorso di rendering (--fbdev-renderer): scrive
    render_background()+draw_sprites() DIRETTAMENTE su un framebuffer
    Linux (es. /dev/fb1, un LCD collegato via GPIO), bypassando SDL
    per l'OUTPUT VIDEO. Nato perche' su Raspberry Pi 1 con Pi OS Lite
    headless nessun driver SDL2 reale e' disponibile: KMSDRM richiede
    /dev/dri (il kernel di questo modello non lo espone - niente
    supporto DRM/KMS), x11/wayland richiedono un server grafico in
    esecuzione (nessuno, headless), fbcon/directfb non sono compilati
    nelle build recenti di SDL2 (rimossi dal sorgente stesso, non solo
    disabilitati). Risultato: SDL2 cade silenziosamente sul driver
    'offscreen', che non disegna da nessuna parte - ne' su HDMI ne'
    sull'LCD, senza nessun errore evidente.

    pygame/SDL restano usati per audio (funziona anche col driver
    'offscreen') e per l'input SOLO in modalita' --playtest (una
    sequenza scriptata, non tastiera vera). Per il gioco interattivo
    VERO, pygame.key.get_pressed() NON funziona qui: senza una
    finestra SDL reale non c'e' mai focus, i tasti finiscono altrove
    (es. il terminale SSH da cui e' stato lanciato il gioco) -
    scoperto testando su hardware reale. Vedi EvdevKeyboard poco
    sotto per come viene letta la tastiera in quel caso.

    Conversione RGB888->RGB565 (formato nativo di questo LCD, vedi
    `fbset -fb /dev/fb1`) in fb_convert.py, compilato con Cython come
    cpu.py/ppu.py (vedi quel modulo) - MISURATO su Raspberry Pi 1
    vero in Python puro: ~4 SECONDI/frame (153.600 pixel/frame),
    completamente inutilizzabile senza compilarlo.

    SCRITTURA VIA mmap: il driver (fb_ili9486, famiglia 'fbtft',
    identificato con l'utente via dmesg - SPI a 16MHz, deferred I/O)
    traccia le pagine "sporche" della memoria mappata per decidere
    cosa spedire sul bus SPI. MISURATO pero' che passare da write() a
    mmap() da solo NON riduce il tempo bloccante (restava ~200-500ms/
    frame in entrambi i casi, anche dopo aver alzato la frequenza SPI
    a 24MHz senza risultati e con artefatti visivi - tentativo
    scartato) - il vincolo reale non e' la velocita' del canale ma il
    NUMERO DI BYTE scritti ogni frame: un frame RGB565 intero sono
    307.200 byte, e va spedito per intero anche quando lo sfondo non
    e' cambiato affatto (tipico: solo pochi sprite si muovono).

    DIFF RIGA PER RIGA (vedi render()): confronta il nuovo frame con
    l'ultimo scritto e riscrive nel framebuffer SOLO le righe diverse
    - se lo sfondo e' fermo e si muovono solo un paio di sprite, la
    stragrande maggioranza delle 320 righe risultano identiche e
    vengono saltate, riducendo proporzionalmente sia il lavoro fatto
    qui sia (si spera, dato che il driver traccia le pagine toccate)
    il traffico SPI reale. Durante lo scroll (quasi tutte le righe
    cambiano comunque) il guadagno si riduce, ma non peggiora mai
    rispetto a riscrivere sempre tutto.

    --screen-mode ('4:3'/'16:9', vedi memory_map.py) rende la
    risoluzione LOGICA della console (SCREEN_W_PX/H_PX) piu' piccola
    di questo LCD fisico (480x320, LCD_PHYSICAL_W/H sotto - specifico
    di questo pannello, non ricavabile da SCREEN_W_PX/H_PX una volta
    che quelle possono valere meno). L'immagine di gioco viene
    centrata nel framebuffer fisico, con un bordo NERO intorno -
    NESSUNO scaling (deciso apposta con l'utente: scalare per
    riempire il pannello annullerebbe il beneficio principale di una
    risoluzione piu' bassa, che e' spedire MENO byte sull'SPI, non
    solo comporre meno pixel). Il bordo si scrive una volta sola
    all'avvio (resta nero per tutta la sessione, non tocca mai i byte
    fuori dall'area di gioco); ogni frame successivo aggiorna solo il
    rettangolo attivo, con lo stesso dirty-diff riga per riga di
    sempre (vedi _write_changed_rows)."""

    LCD_PHYSICAL_W = 480  # dimensione REALE di questo pannello - fissa,
    LCD_PHYSICAL_H = 320  # indipendente dalla risoluzione scelta per la console

    def __init__(self, fb_path="/dev/fb1"):
        self.fb_path = fb_path
        self.fb = open(fb_path, "r+b")
        self._phys_w = self.LCD_PHYSICAL_W
        self._phys_h = self.LCD_PHYSICAL_H
        self._fb_size = self._phys_w * self._phys_h * 2  # RGB565, 2 byte/pixel
        self._mmap = mmap.mmap(self.fb.fileno(), self._fb_size)
        self._prev_rgb565 = None  # ultimo frame scritto - None al primo
                                   # frame, forza la scrittura intera
        self.last_rows_written = 0  # diagnostica --stats: quante righe (su
                                     # SCREEN_H_PX) sono state davvero
                                     # riscritte nell'ultimo render()

        off_x = (self._phys_w - SCREEN_W_PX) // 2
        off_y = (self._phys_h - SCREEN_H_PX) // 2
        self._dst_row_stride = self._phys_w * 2
        self._dst_row_offset = off_y * self._dst_row_stride + off_x * 2
        self._has_border = off_x != 0 or off_y != 0
        if self._has_border:
            self._mmap[0:self._fb_size] = bytes(self._fb_size)  # nero (0x0000
                                                                   # in RGB565) -
                                                                   # una volta
                                                                   # sola, resta
                                                                   # cosi' per
                                                                   # tutta la
                                                                   # sessione

    def render(self, frame_buf):
        out = rgb888_to_rgb565(frame_buf)
        row_bytes = SCREEN_W_PX * 2
        self.last_rows_written = _write_changed_rows(
            self._mmap, out, self._prev_rgb565, row_bytes, SCREEN_H_PX,
            dst_row_stride=self._dst_row_stride, dst_row_offset=self._dst_row_offset,
        )
        self._prev_rgb565 = out

    def close(self):
        self._mmap.close()
        self.fb.close()


class EvdevKeyboard:
    """Lettura tastiera diretta da /dev/input/eventX (libreria
    'evdev'), usata SOLO con --fbdev-renderer in modalita'
    INTERATTIVA (non --playtest/--playtest-quick, che usano una
    sequenza scriptata e non hanno bisogno di una tastiera vera).

    Perche' non pygame.key.get_pressed(): senza una finestra SDL reale
    (vedi FramebufferRenderer) non c'e' mai focus, quindi SDL non
    riceve mai gli eventi tastiera - scoperto testando su hardware
    reale (i tasti finivano nel terminale SSH da cui era stato
    lanciato il gioco). Stesso principio gia' applicato al video:
    bypassare SDL dove SDL non funziona su questo hardware.

    device.grab() prende il device in ESCLUSIVA: come effetto
    collaterale utile, impedisce ANCHE che i tasti finiscano nel
    terminale (risolve il sintomo originale, non solo la causa) - se
    il processo termina in modo anomalo il grab si rilascia comunque
    da solo (e' legato al file descriptor, chiuso automaticamente
    dal kernel all'uscita del processo)."""

    def __init__(self):
        try:
            import evdev
        except ImportError:
            raise LauncherError(
                "--fbdev-renderer in modalita' interattiva richiede la libreria 'evdev' per "
                "leggere la tastiera senza una finestra SDL vera (pip3 install evdev "
                "--break-system-packages), oppure usa --playtest/--playtest-quick che non "
                "ha bisogno di una tastiera reale."
            )
        self._evdev = evdev
        device_path = None
        for path in evdev.list_devices():
            dev = evdev.InputDevice(path)
            caps = dev.capabilities().get(evdev.ecodes.EV_KEY, [])
            if evdev.ecodes.KEY_A in caps:  # trucco comune per distinguere
                                              # una tastiera vera da un
                                              # mouse/joystick (niente tasti
                                              # lettera tra le sue capability)
                device_path = path
                break
            dev.close()
        if device_path is None:
            raise LauncherError(
                "--fbdev-renderer in modalita' interattiva: nessuna tastiera trovata tra i "
                "device /dev/input/event* - collega una tastiera USB, oppure usa "
                "--playtest/--playtest-quick che non ha bisogno di una tastiera reale."
            )
        self.device = evdev.InputDevice(device_path)
        self.device.grab()
        self._pressed = set()

    def poll(self):
        """Da chiamare una volta per frame: svuota (senza bloccare) la
        coda di eventi pendenti e aggiorna l'insieme dei tasti premuti
        in questo istante."""
        ecodes = self._evdev.ecodes
        try:
            for event in self.device.read():
                if event.type == ecodes.EV_KEY:
                    if event.value == 1:      # tasto premuto
                        self._pressed.add(event.code)
                    elif event.value == 0:    # tasto rilasciato
                        self._pressed.discard(event.code)
        except BlockingIOError:
            pass  # nessun evento pendente in questo frame, normale

    def input_byte(self):
        """Stessa mappatura di tasti/bit di _run_pygame_loop per
        pygame.key.get_pressed() (frecce o WASD, J o SPAZIO)."""
        ecodes = self._evdev.ecodes
        b = 0
        if ecodes.KEY_UP in self._pressed or ecodes.KEY_W in self._pressed: b |= 0x01
        if ecodes.KEY_DOWN in self._pressed or ecodes.KEY_S in self._pressed: b |= 0x02
        if ecodes.KEY_LEFT in self._pressed or ecodes.KEY_A in self._pressed: b |= 0x04
        if ecodes.KEY_RIGHT in self._pressed or ecodes.KEY_D in self._pressed: b |= 0x08
        if ecodes.KEY_J in self._pressed or ecodes.KEY_SPACE in self._pressed: b |= 0x10
        return b

    def should_quit(self):
        return self._evdev.ecodes.KEY_ESC in self._pressed

    def close(self):
        try:
            self.device.ungrab()
        except OSError:
            pass  # gia' rilasciato o device sparito - non fatale in chiusura
        self.device.close()


def _pixels_to_surface(pixels, w, h):
    """render_frame() ora ritorna gia' un buffer piatto RGB (bytearray)
    - frombuffer() lo impacchetta in una Surface con un'unica
    operazione a livello C, senza alcun loop Python. Prima di questa
    ottimizzazione (vedi ppu.py) qui serviva un doppio ciclo che
    copiava pixel per pixel da una lista di liste di tuple."""
    import pygame
    return pygame.image.frombuffer(bytes(pixels), (w, h), 'RGB')


def _run_pygame_loop(cpu, show_stats=False, quit_pygame_at_end=True, renderer_mode='dirty-rects', fullscreen=False, use_audio=False, playtest=False, playtest_quick=False, netcode_session=None, local_player_index=0, fbdev_path=None):
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
      'fbdev' (flag --fbdev-renderer, opzionale --fbdev-path) -
        FramebufferRenderer: scrive direttamente su un framebuffer
        Linux (default /dev/fb1), bypassando SDL per l'output video -
        vedi quella classe per il perche' (nessun driver SDL2 reale
        disponibile su alcuni Raspberry Pi headless).

    Perche' dirty-rects batte surface nettamente pur usando anch'esso
    blit() per gli sprite: il numero di chiamate blit()/frame e' la
    differenza chiave - surface ne faceva ~150 (un blit per OGNI tile
    di sfondo, ogni frame), dirty-rects ne fa una manciata (solo per
    lo sprite, non per lo sfondo, che resta fermo). Stesso strumento
    (blit), applicato al problema giusto invece che a quello sbagliato.

    quit_pygame_at_end: se False, NON chiude pygame all'uscita - usato
    quando questa funzione e' chiamata dal menu (run_os_menu), che ha
    gia' una sessione pygame aperta e vuole riusarla, non ricrearla.

    local_player_index: NON viene piu' usato per rimappare le porte
    di input della CPU (bug corretto - vedi il commento sopra
    l'assegnazione di input_byte/extra_inputs piu' in basso: le porte
    seguono sempre l'indice ASSOLUTO di frame_inputs, uguale su ogni
    istanza). Resta nella firma solo per un eventuale uso futuro
    (es. evidenziare "sei tu" nella UI), oggi non serve al loop."""
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
    fbdev_renderer = FramebufferRenderer(fbdev_path or "/dev/fb1") if renderer_mode == 'fbdev' else None
    # EvdevKeyboard SOLO in modalita' interattiva (non --playtest, che
    # ha gia' la propria sequenza scriptata e non tocca mai la
    # tastiera vera) - vedi quella classe per il perche' serve qui.
    evdev_keyboard = EvdevKeyboard() if (renderer_mode == 'fbdev' and not playtest) else None
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

    # -- TIMESTEP FISSO per il gioco locale interattivo (non
    # --playtest, non in rete - vedi il condizionale piu' sotto dove
    # viene usato per il perche' di questa esclusione): senza questo,
    # un rendering lento (segnalato dall'utente su --fbdev-renderer,
    # ma il problema esiste per qualunque renderer) fa chiamare
    # cpu.run() meno spesso, rallentando anche la LOGICA di gioco
    # (il personaggio si muove piu' lento in tempo REALE, non solo
    # in modo meno fluido) - la velocita' di gioco non deve dipendere
    # da quanto ci mette il disegno a schermo. Ogni iterazione reale
    # del loop misura quanto tempo e' passato e "recupera" quel tempo
    # a passi fissi di TICK_DT, eseguendo cpu.run() una volta per
    # passo prima del prossimo disegno - se il rendering e' stato
    # lento, si eseguono piu' passi di fila. MAX_CATCHUP_TICKS evita
    # una "spirale della morte" se il rendering si blocca a lungo
    # (es. il primissimo frame): oltre quel tetto si accetta di
    # perdere tempo simulato invece di provare a recuperarlo tutto
    # insieme, cosa che rallenterebbe ulteriormente il frame
    # successivo in un circolo vizioso.
    TICK_DT = 1.0 / 60
    MAX_CATCHUP_TICKS = 5
    sim_accumulator = 0.0
    sim_last_time = time.perf_counter()

    running = True
    quit_requested = False  # True SOLO se l'utente ha chiuso la finestra
                             # (pygame.QUIT) - ESC/fine partita fermano
                             # questo loop ma NON devono chiudere il
                             # processo quando chi chiama e' il menu OS
                             # (vedi os_menu.py: torna al menu su ESC,
                             # chiude tutto solo su QUIT vero)
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
                quit_requested = True

        current_phase = None
        if playtest_seq is not None:
            if playtest_i >= len(playtest_seq):
                running = False
                break
            current_phase, input_byte = playtest_seq[playtest_i]
            playtest_i += 1
        elif evdev_keyboard is not None:
            evdev_keyboard.poll()
            input_byte = evdev_keyboard.input_byte()
            if evdev_keyboard.should_quit():
                running = False
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
            try:
                netcode_session.submit_local_input(frame_number, input_byte)
                frame_inputs = netcode_session.get_frame_inputs(frame_number, timeout=0.25)
            except OSError as exc:
                # una sessione di rete puo' fallire A META' PARTITA
                # (non solo al momento di connettersi, gia' gestito da
                # os_menu.py) - un socket che va in errore (rete
                # caduta, host irraggiungibile) sollevava OSError qui
                # SENZA che nessuno lo catturasse, facendo crashare
                # l'intera applicazione con un traceback grezzo -
                # segnalato dall'utente giocando davvero tra due reti
                # diverse (molto piu' soggette a blip di rete di una
                # LAN locale). Trattata come se l'utente avesse
                # premuto ESC (quit_requested resta False): si torna
                # al menu invece di chiudere tutto, vedi run_os_menu.
                print(f"[netplay] connessione di rete persa ({exc}) - torno al menu")
                running = False
                continue
            if frame_inputs is None:
                clock.tick(60)  # mai saltare il limitatore di framerate,
                                 # nemmeno quando il frame viene scartato
                continue
            # BUG segnalato dall'utente in un test reale ("l'host si
            # vede come giocatore 1 ma muove il giocatore 2 sul
            # guest"): qui si rimappava frame_inputs mettendo SEMPRE
            # il proprio input in porta 0 (input(0)) e gli altri a
            # seguire - ogni istanza vedeva quindi se stessa come
            # "input(0)" e l'altra come "input(1)". Ma la simulazione
            # e' deterministica proprio perche' OGNI istanza esegue
            # la stessa ROM con lo STESSO vettore di input sulle
            # STESSE porte (vedi netcode_lockstep.py) - frame_inputs[i]
            # e' gia' il valore del giocatore di indice ASSOLUTO i
            # (0 = host, 1 = primo client, ecc., assegnato una volta
            # sola da LockstepHost/LockstepClient.connect()), uguale
            # su tutte le macchine. Rimappare per local_player_index
            # faceva scrivere sulla PORTA 0 valori diversi a seconda
            # di chi era locale, cioe' facendo divergere lo stato
            # della CPU (p1x/p1y ecc.) tra host e client invece di
            # farli girare sulla stessa simulazione condivisa.
            input_byte = frame_inputs[0]
            extra_inputs = frame_inputs[1:]

        t0 = time.perf_counter()
        if playtest_seq is None and netcode_session is None:
            # locale interattivo: timestep fisso (vedi commento sopra
            # TICK_DT). --playtest resta un tick per iterazione ESATTAMENTE
            # come prima apposta - deve restare un benchmark del throughput
            # reale del motore, non della velocita' "corretta" di gioco. La
            # rete ha gia' la sua pacatura (get_frame_inputs/timeout) e un
            # proprio vincolo di sincronia tra istanze - un recupero locale
            # di tick qui rischierebbe di disallinearle, va lasciata invariata.
            now = time.perf_counter()
            frame_time = min(now - sim_last_time, TICK_DT * MAX_CATCHUP_TICKS)
            sim_last_time = now
            sim_accumulator += frame_time
            ticks_done, sim_accumulator = _ticks_to_catch_up(sim_accumulator, TICK_DT, MAX_CATCHUP_TICKS)
            n_istruzioni = 0
            for _ in range(ticks_done):
                n_istruzioni += cpu.run(CART_LOAD_ADDR, input_byte=input_byte, extra_inputs=extra_inputs)
                frame_number += 1
        else:
            n_istruzioni = cpu.run(CART_LOAD_ADDR, input_byte=input_byte, extra_inputs=extra_inputs)
            frame_number += 1
        t1 = time.perf_counter()

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
        elif fbdev_renderer is not None:
            cache_key = (cpu.current_stage, cpu.scroll_x, cpu.scroll_y)
            if bg_cache_key != cache_key:
                bg_cache_buf = render_background(vram, cgram, cpu.scroll_x, cpu.scroll_y,
                                                   blob_cache=tile_blob_cache)
                bg_cache_key = cache_key
            frame_buf = bytearray(bg_cache_buf)
            draw_sprites(frame_buf, oam, cgram, vram)
            fbdev_renderer.render(frame_buf)
            # NON chiama pygame.display.flip(): l'output va al
            # framebuffer del device, non alla finestra SDL (che qui
            # non disegna comunque nulla di visibile, vedi
            # FramebufferRenderer)
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
                righe_info = ""
                if fbdev_renderer is not None:
                    righe_info = f" | righe riscritte: {fbdev_renderer.last_rows_written}/{SCREEN_H_PX}"
                print(f"[{label}] fps={n} | cpu={stats['cpu']/n*1000:.1f}ms "
                      f"render+blit={stats['render']/n*1000:.1f}ms "
                      f"totale={( stats['cpu']+stats['render'] )/n*1000:.1f}ms/frame "
                      f"| istruzioni: media={istr_medie:.0f} max={istr_max}{righe_info}")
                sn = stats.get('scroll_frames', 0)
                if sn:
                    parts = ' '.join(
                        f"{k.replace('scroll_', '')}={stats[k]/sn*1000:.1f}ms"
                        for k in ('scroll_surface_scroll', 'scroll_strip_compute',
                                  'scroll_strip_surface', 'scroll_strip_blit',
                                  'scroll_screen_blit', 'scroll_flip',
                                  'scroll_texture_update', 'scroll_gpu_shift',
                                  'scroll_clear', 'scroll_bg_draw', 'scroll_sprite_draws',
                                  'scroll_present')
                        if k in stats
                    )
                    print(f"  [dettaglio scroll, {sn} frame in scroll] {parts}")
                stats = {'cpu': 0.0, 'render': 0.0, 'frames': 0}
                stats_t0 = time.perf_counter()

        clock.tick(60)

    if playtest_seq is not None:
        _print_playtest_summary(phase_stats, renderer_mode,
                                 time.perf_counter() - playtest_t_start)

    if fbdev_renderer is not None:
        fbdev_renderer.close()

    if evdev_keyboard is not None:
        evdev_keyboard.close()

    if quit_pygame_at_end:
        pygame.quit()

    return quit_requested


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
                          'scroll_strip_surface', 'scroll_strip_blit',
                          'scroll_screen_blit', 'scroll_flip',
                          'scroll_texture_update', 'scroll_gpu_shift',
                          'scroll_clear', 'scroll_bg_draw', 'scroll_sprite_draws',
                          'scroll_present')
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


def start_netcode_host(port, num_players, host_name='S32', avatar=0):
    """Costruisce e avvia un LockstepHost (vedi netcode_lockstep.py),
    bloccando finche' non si sono connessi tutti i giocatori. Estratta
    da main() apposta: la usano sia il flag CLI --netplay-host sia la
    schermata "Ospita partita" del menu OS (os_menu.py) - stessa
    identica logica, un solo posto da mantenere.

    host_name/avatar: identita' mostrata a chi cerca partite (vedi
    profile.py) - di default 'S32'/0 per la CLI, che non ha un
    profilo. Il menu OS passa il nickname/avatar scelto dall'utente.

    Annuncia la lobby sulla LAN per tutta l'attesa (LanAnnouncer, vedi
    discover_netcode_hosts()) - cosi' chi si unisce dal menu OS non
    deve conoscere a memoria l'IP dell'host, lo trova nella lista.
    Smette di annunciare appena la partita parte (nessun nuovo
    giocatore puo' comunque piu' unirsi una volta partiti)."""
    from netcode_lockstep import LockstepHost, LanAnnouncer
    print(f"[netplay] host in ascolto sulla porta {port}, "
          f"aspetto {num_players} giocatori...")
    announcer = LanAnnouncer(game_name=host_name, connect_port=port, avatar=avatar)
    announcer.start()
    try:
        session = LockstepHost(num_players=num_players, bind_port=port)
        session.wait_for_players()
    finally:
        announcer.stop()
    print("[netplay] tutti i giocatori connessi, si parte")
    return session, 0  # l'host e' sempre il giocatore 0


def discover_netcode_hosts(duration_s=2.0):
    """Ascolta gli annunci LAN (LanAnnouncer, vedi start_netcode_host)
    per duration_s secondi, ritorna la lista degli host trovati
    ({'ip','name','port'}) - usata dalla schermata "Unisciti a
    partita" del menu OS per evitare di dover digitare un IP a mano
    quando l'host e' sulla stessa rete locale. Lista vuota se nessuno
    risponde (rete che blocca il broadcast, host non ancora in
    attesa, o host su un'altra rete) - il chiamante ripiega
    sull'inserimento manuale dell'IP, non e' un errore."""
    from netcode_lockstep import LanBrowser
    browser = LanBrowser()
    try:
        return browser.scan(duration_s=duration_s)
    finally:
        browser.close()


def start_netcode_client(ip, port):
    """Costruisce e avvia un LockstepClient, bloccando finche' l'host
    non conferma la connessione. Estratta per lo stesso motivo di
    start_netcode_host() - vedi li'."""
    from netcode_lockstep import LockstepClient
    print(f"[netplay] mi connetto a {ip}:{port}...")
    session = LockstepClient()
    local_player_index = session.connect(ip, host_port=port)
    print(f"[netplay] connesso - sono il giocatore {local_player_index}")
    return session, local_player_index


def run_benchmark(path, kind, n_frames=120, profile=False):
    """Misura le prestazioni SENZA aprire alcuna finestra (niente
    pygame.display) - utile per testare velocemente su una macchina
    debole/senza schermo comodo (es. una Raspberry Pi via SSH) senza
    dover configurare SDL. Stampa ms/frame medi per cpu.run() e
    render_frame(), fps stimati, e la RAM di picco usata dal processo.

    profile=True usa cProfile per mostrare il tempo speso in OGNI
    funzione (non solo il totale cpu.run()/render_frame()) - utile
    quando i numeri aggregati non spiegano da soli dove va il tempo
    su un hardware specifico (vedi caso Raspberry Pi 1 in README.md).

    ATTENZIONE: chiama cpu.run() con input_byte=0 SEMPRE (nessun input
    scriptato) - se la cartuccia resta su una schermata "a riposo"
    (es. titolo) senza input, il profilo misura QUELLA fase, non il
    gameplay vero (movimento/scroll/collisioni), che spesso esegue
    molte piu' istruzioni/frame. Per profilare il gameplay vero serve
    combinare --profile con --playtest (vedi main(): in quel caso il
    profiling avvolge l'intero loop interattivo/scriptato invece di
    passare da qui)."""
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
    """Estrae i flag di prestazioni (--stats, --benchmark,
    --benchmark-frames, --profile, --surface-renderer,
    --buffer-renderer, --gpu-renderer, --fbdev-renderer, --fbdev-path,
    --screen-mode, --fullscreen, --no-audio, --playtest,
    --playtest-quick, --netplay-host, --netplay-join) da argv,
    ritornando (argv_ripulito, dict_flag) - separato da
    determine_mode() apposta, per restare entrambi testabili
    singolarmente.

    --fbdev-renderer scrive direttamente su un framebuffer Linux
    invece di usare SDL per l'output video (vedi FramebufferRenderer) -
    utile quando nessun driver SDL2 reale e' disponibile (es. Pi 1
    headless senza /dev/dri). --fbdev-path <path> cambia il device di
    default (/dev/fb1).

    --screen-mode '4:3'/'16:9' riduce la risoluzione logica della
    console (vedi memory_map.py) - il suo VALORE va gia' letto e
    applicato PRIMA di questa funzione (blocco in cima a questo file,
    prima degli import pesanti), qui viene solo tolto da argv e
    validato di nuovo per dare un errore chiaro a chi chiama
    parse_flags() direttamente (es. i test) senza passare da quel
    blocco iniziale.

    --benchmark-frames <N> cambia quanti frame misura --benchmark
    (default 120, vedi run_benchmark()) - serve per confrontare
    CPython/PyPy: con solo 120 frame il JIT di PyPy non fa in tempo a
    "scaldarsi" (compila il ciclo caldo in codice nativo solo dopo
    averlo visto girare abbastanza) e puo' risultare PIU' LENTO di
    CPython sullo stesso identico benchmark - segnalato dall'utente
    testando davvero su Pi 1 (cpu.run(): 2.33ms/frame con PyPy contro
    0.48ms/frame con CPython, a 120 frame). Con molti piu' frame il
    costo di riscaldamento si ammortizza su un numero maggiore di
    iterazioni, avvicinandosi al caso reale di una partita giocata per
    minuti, non per 2 secondi.

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
    flags = {'stats': False, 'benchmark': False, 'benchmark_frames': None, 'profile': False, 'renderer': 'dirty-rects', 'fullscreen': False, 'audio': True, 'playtest': False, 'playtest_quick': False,
              'fbdev_path': None,
              'netplay_host_port': None, 'netplay_host_players': None, 'netplay_join_addr': None}
    rest = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == '--stats':
            flags['stats'] = True
        elif arg == '--benchmark':
            flags['benchmark'] = True
        elif arg == '--benchmark-frames':
            if i + 1 >= len(argv):
                raise LauncherError('--benchmark-frames richiede un argomento: <N>')
            try:
                n = int(argv[i+1])
            except ValueError:
                raise LauncherError(f'--benchmark-frames: deve essere un numero intero (ricevuto "{argv[i+1]}")')
            if n <= 0:
                raise LauncherError(f'--benchmark-frames: deve essere positivo (ricevuto {n})')
            flags['benchmark_frames'] = n
            i += 1
        elif arg == '--profile':
            flags['profile'] = True
        elif arg == '--surface-renderer':
            flags['renderer'] = 'surface'
        elif arg == '--buffer-renderer':
            flags['renderer'] = 'buffer'
        elif arg == '--gpu-renderer':
            flags['renderer'] = 'gpu'
        elif arg == '--fbdev-renderer':
            flags['renderer'] = 'fbdev'
        elif arg == '--fbdev-path':
            if i + 1 >= len(argv):
                raise LauncherError('--fbdev-path richiede un argomento: <path>, es. /dev/fb1')
            flags['fbdev_path'] = argv[i+1]
            i += 1
        elif arg == '--screen-mode':
            # il VALORE e' gia' stato applicato (variabile d'ambiente
            # S32_SCREEN_MODE) PRIMA degli import in cima a questo file -
            # vedi li' per il perche'. Qui lo consumiamo solo per
            # toglierlo da argv (altrimenti finirebbe scambiato per un
            # percorso di cartuccia da determine_mode()) e per dare un
            # errore chiaro se il valore non e' uno dei due riconosciuti.
            if i + 1 >= len(argv):
                raise LauncherError("--screen-mode richiede un argomento: '4:3' o '16:9'")
            if argv[i+1] not in ('4:3', '16:9'):
                raise LauncherError(f"--screen-mode: valore non riconosciuto \"{argv[i+1]}\" (usa '4:3' o '16:9')")
            i += 1
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
        from os_menu import run_os_menu
        run_os_menu()
    else:
        _, path, kind = mode
        # --profile SENZA --playtest usa il benchmark sintetico (vedi
        # run_benchmark - niente rendering vero, input_byte=0 sempre,
        # quindi resta su una fase "a riposo"). --profile CON --playtest
        # invece avvolge l'intero loop interattivo/scriptato vero (con
        # il renderer scelto, es. --fbdev-renderer) in cProfile, perche'
        # e' l'UNICO modo di catturare il costo reale di cpu.run() sotto
        # il carico vero (movimento/scroll/collisioni) che la fase "a
        # riposo" non esercita mai - richiesto dopo aver visto su
        # Raspberry Pi 1 vero cpu=80-110ms/frame durante il gameplay
        # scriptato, contro numeri molto piu' bassi attesi dal benchmark
        # sintetico su una scena statica.
        if flags['benchmark'] or (flags['profile'] and not flags['playtest']):
            run_benchmark(path, kind, n_frames=flags['benchmark_frames'] or 120, profile=flags['profile'])
        else:
            netcode_session = None
            local_player_index = 0
            try:
                if flags['netplay_host_port'] is not None:
                    netcode_session, local_player_index = start_netcode_host(
                        flags['netplay_host_port'], flags['netplay_host_players'])
                elif flags['netplay_join_addr'] is not None:
                    ip, porta = flags['netplay_join_addr']
                    netcode_session, local_player_index = start_netcode_client(ip, porta)
            except (ValueError, TimeoutError, OSError) as exc:
                # es. "getaddrinfo failed"/gaierror per un IP non valido
                # o non risolvibile, porta gia' occupata, timeout di
                # connessione - un messaggio chiaro invece di un
                # traceback grezzo (os_menu.py gestisce lo stesso caso
                # allo stesso modo, vedi run_os_menu)
                print(f"[netplay] impossibile avviare la partita in rete: {exc}")
                sys.exit(1)

            if flags['profile']:
                import cProfile
                import pstats

                profiler = cProfile.Profile()
                profiler.enable()
                run_direct(path, kind, show_stats=flags['stats'], renderer_mode=flags['renderer'],
                           fullscreen=flags['fullscreen'], use_audio=flags['audio'], playtest=flags['playtest'],
                           playtest_quick=flags['playtest_quick'],
                           netcode_session=netcode_session, local_player_index=local_player_index,
                           fbdev_path=flags['fbdev_path'])
                profiler.disable()

                print(f"--- profilo dettagliato (playtest): {path} ---")
                stats = pstats.Stats(profiler)
                stats.sort_stats('cumulative')
                stats.print_stats(30)
            else:
                run_direct(path, kind, show_stats=flags['stats'], renderer_mode=flags['renderer'],
                           fullscreen=flags['fullscreen'], use_audio=flags['audio'], playtest=flags['playtest'],
                           playtest_quick=flags['playtest_quick'],
                           netcode_session=netcode_session, local_player_index=local_player_index,
                           fbdev_path=flags['fbdev_path'])


if __name__ == '__main__':
    try:
        main()
    except LauncherError as exc:
        print(f"Errore: {exc}")
        sys.exit(1)
