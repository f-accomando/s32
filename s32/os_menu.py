"""
os_menu.py - il mini-OS di avvio di S32: griglia di icone per
scegliere una cartuccia, poi locale/ospita/unisciti in rete.

Separato da launcher.py (che resta l'ESECUZIONE: caricare una ROM e
far girare il loop CPU->PPU->schermo) - qui c'e' solo la SCELTA:
scoperta cartucce (carts_registry), navigazione (menu_state, pura
logica testabile senza pygame) e il disegno con pygame. Stessa
separazione logica/esecuzione gia' documentata in launcher.py.

Non importa pygame a livello di modulo apposta (come launcher.py) -
lo riceve gia' pronto da launcher._init_pygame_once(), cosi' questo
file resta importabile anche in un ambiente senza pygame installato
(solo run_os_menu() lo usa davvero).

FLUSSO (stati di run_os_menu, un semplice automa a stati):
  grid      -> scegli una cartuccia (griglia di icone, navigazione 2D)
  mode      -> "locale" / "ospita partita" / "unisciti a partita"
  host      -> form (porta, numero giocatori) prima di ospitare -
               annuncia la lobby sulla LAN (LanAnnouncer, vedi
               launcher.start_netcode_host) per tutta l'attesa
  join_pick -> lista degli host trovati in automatico sulla rete
               locale (LanBrowser, ~2s di scansione) + "inserisci IP
               manualmente" - saltata a favore del form manuale se la
               scansione non trova nessuno
  join      -> form manuale (ip, porta) prima di unirsi - usato solo
               se scelto esplicitamente da join_pick, o se la
               scansione automatica non ha trovato nulla
Da qualunque form, ESC torna allo stato precedente (non chiude il
programma) - solo ESC/chiusura finestra dallo stato 'grid' chiude
tutto. Dopo una partita (locale o in rete), si torna SEMPRE allo
stato 'grid' con la stessa MenuState di prima (stesso indice
selezionato) - MAI ricreata a ogni giro, altrimenti "riprendi da dove
eri rimasto" non funzionerebbe. Fa eccezione la chiusura della
FINESTRA durante la partita (run_direct ritorna True in quel caso):
li' si chiude tutto il programma, coerente con l'aver chiuso la
finestra.
"""

import os

from carts_registry import discover_carts, ICON_WIDTH_PX, ICON_HEIGHT_PX
from menu_state import MenuState

GRID_COLUMNS = 4
ICON_SCALE = 3  # icona sorgente 32x40 (vedi carts_registry.py),
                 # disegnata a schermo 3x piu' grande - troppo piccola
                 # altrimenti per navigarla comodamente

ICON_DRAW_W = ICON_WIDTH_PX * ICON_SCALE
ICON_DRAW_H = ICON_HEIGHT_PX * ICON_SCALE
CELL_GAP_X = 24
CELL_GAP_Y = 44  # spazio extra sotto l'icona per l'etichetta col titolo
GRID_ORIGIN_X = 32
GRID_ORIGIN_Y = 90

WINDOW_W = GRID_ORIGIN_X * 2 + GRID_COLUMNS * ICON_DRAW_W + (GRID_COLUMNS - 1) * CELL_GAP_X
WINDOW_H = 520

DIGITS = set('0123456789')
IP_CHARS = set('0123456789.')


def _grid_positions(n, columns, cell_w, cell_h, gap_x, gap_y, origin_x=0, origin_y=0):
    """Pura, senza pygame: posizione (x,y) in pixel dell'angolo in
    alto a sinistra della cella i-esima di una griglia riga per riga.
    Separata apposta per essere testabile senza un display (vedi
    test_os_menu.py)."""
    positions = []
    for i in range(n):
        row, col = divmod(i, columns)
        x = origin_x + col * (cell_w + gap_x)
        y = origin_y + row * (cell_h + gap_y)
        positions.append((x, y))
    return positions


class TextField:
    """Un campo di testo minimale (porta, IP, numero giocatori) - pura
    logica, senza pygame: riceve caratteri gia' estratti da
    event.unicode, non un evento pygame intero. Testabile da sola."""

    def __init__(self, initial='', max_len=32, allowed=None):
        self.value = initial
        self.max_len = max_len
        self.allowed = allowed  # None = qualunque carattere stampabile

    def add_char(self, ch):
        if not ch or not ch.isprintable():
            return
        if self.allowed is not None and ch not in self.allowed:
            return
        if len(self.value) >= self.max_len:
            return
        self.value += ch

    def backspace(self):
        self.value = self.value[:-1]


def _load_icon_surface(pygame, cart):
    """Carica e ridimensiona icon.png se la cartuccia ne ha una,
    altrimenti un riquadro grigio di default - MAI un crash del menu
    per colpa di un asset mancante o illeggibile in una cartuccia."""
    icon_path = cart.icon_path()
    if icon_path:
        try:
            raw = pygame.image.load(icon_path).convert_alpha()
            return pygame.transform.scale(raw, (ICON_DRAW_W, ICON_DRAW_H))
        except Exception:
            pass  # icona presente ma illeggibile/corrotta: ripiega sotto
    surf = pygame.Surface((ICON_DRAW_W, ICON_DRAW_H))
    surf.fill((90, 90, 100))
    pygame.draw.rect(surf, (140, 140, 150), surf.get_rect(), width=2)
    return surf


def _entry_and_kind(cart):
    entry = cart.entry_py() or cart.entry_asm()
    kind = 'py' if cart.entry_py() else 'asm'
    return entry, kind


def _friendly_netcode_error(exc, port):
    """Messaggio d'errore piu' utile del solo testo tecnico
    dell'eccezione - segnalato dall'utente testando su due PC reali:
    un timeout di connessione (host trovato dalla scoperta LAN ma la
    connessione vera cade) sembrava "tornare indietro senza motivo"
    perche' l'errore non veniva nemmeno mostrato a schermo (bug a
    parte, vedi _draw_list_screen). La causa piu' comune di un
    TimeoutError/OSError qui e' il firewall che blocca la porta di
    gioco (diversa dalla porta di SCOPERTA, 42421 - avere trovato
    l'host non garantisce che la connessione vera passi), non un bug -
    lo diciamo esplicitamente invece di lasciare solo il testo tecnico
    ("Timeout connessione a ..."), che non suggerisce cosa controllare."""
    base = str(exc)
    if isinstance(exc, (TimeoutError, OSError)):
        return f"{base} - controlla il firewall sulla porta {port}/UDP su ENTRAMBI i PC"
    return base


def _draw_grid_screen(screen, pygame, fonts, carts_dir, grid, icon_cache):
    font, font_small, font_title = fonts
    title = font_title.render("S32", True, (230, 230, 240))
    screen.blit(title, (GRID_ORIGIN_X, 24))

    if grid.is_empty():
        text = font.render("NO ROM FOUND", True, (200, 90, 90))
        screen.blit(text, (GRID_ORIGIN_X, GRID_ORIGIN_Y))
        hint = font_small.render(f"(cercato in: {os.path.abspath(carts_dir)})", True, (140, 140, 140))
        screen.blit(hint, (GRID_ORIGIN_X, GRID_ORIGIN_Y + 32))
        return

    positions = _grid_positions(len(grid.items), grid.columns, ICON_DRAW_W, ICON_DRAW_H,
                                 CELL_GAP_X, CELL_GAP_Y, GRID_ORIGIN_X, GRID_ORIGIN_Y)
    for i, (cart, (x, y)) in enumerate(zip(grid.items, positions)):
        if cart.name not in icon_cache:
            icon_cache[cart.name] = _load_icon_surface(pygame, cart)
        icon = icon_cache[cart.name]
        selected = (i == grid.index)
        if selected:
            pygame.draw.rect(screen, (255, 220, 100),
                              (x - 4, y - 4, ICON_DRAW_W + 8, ICON_DRAW_H + 8), width=3)
        screen.blit(icon, (x, y))
        color = (255, 220, 100) if selected else (200, 200, 200)
        label = font_small.render(cart.title, True, color)
        label_x = x + (ICON_DRAW_W - label.get_width()) // 2
        screen.blit(label, (label_x, y + ICON_DRAW_H + 6))

    hint = font_small.render("frecce: muovi   invio/J: scegli   esc: esci", True, (120, 120, 130))
    screen.blit(hint, (GRID_ORIGIN_X, WINDOW_H - 30))


def _draw_list_screen(screen, font, font_title, heading, list_menu, font_small=None, error_message=None):
    title = font_title.render(heading, True, (230, 230, 240))
    screen.blit(title, (GRID_ORIGIN_X, 40))
    y = 100
    for i, label in enumerate(list_menu.items):
        color = (255, 220, 100) if i == list_menu.index else (200, 200, 200)
        text = font.render(label, True, color)
        screen.blit(text, (GRID_ORIGIN_X, y))
        y += 40
    if error_message and font_small is not None:
        err = font_small.render(error_message, True, (220, 90, 90))
        screen.blit(err, (GRID_ORIGIN_X, y + 10))


def _draw_form_screen(screen, font, font_title, font_small, heading, fields, focus_name, error_message):
    """fields: lista di (etichetta, nome_campo, TextField)."""
    title = font_title.render(heading, True, (230, 230, 240))
    screen.blit(title, (GRID_ORIGIN_X, 40))
    y = 110
    for label, name, field in fields:
        is_focus = (name == focus_name)
        label_color = (255, 220, 100) if is_focus else (180, 180, 190)
        text = font.render(f"{label}: {field.value}{'_' if is_focus else ''}", True, label_color)
        screen.blit(text, (GRID_ORIGIN_X, y))
        y += 44
    if error_message:
        err = font_small.render(error_message, True, (220, 90, 90))
        screen.blit(err, (GRID_ORIGIN_X, y + 10))
    hint = font_small.render("tab: cambia campo   invio: conferma   esc: indietro", True, (120, 120, 130))
    screen.blit(hint, (GRID_ORIGIN_X, WINDOW_H - 30))


def run_os_menu():
    """Mostra il menu di avvio, gestisce la scelta cartuccia +
    modalita' (locale/ospita/unisciti), lancia la partita, e AL SUO
    TERMINE torna qui (stessa MenuState, stesso indice) finche'
    l'utente non chiude davvero la finestra. Si apre SEMPRE, anche
    senza cartucce trovate."""
    from launcher import (_init_pygame_once, run_direct, start_netcode_host,
                          start_netcode_client, discover_netcode_hosts)
    pygame = _init_pygame_once()

    carts_dir = os.path.join(os.path.dirname(__file__), '..', 'carts')
    carts = discover_carts(carts_dir)
    grid = MenuState(carts, columns=GRID_COLUMNS)  # creata UNA volta sola:
                                                     # deve sopravvivere a
                                                     # ogni partita giocata
                                                     # e tornare qui invariata

    screen = pygame.display.set_mode((WINDOW_W, WINDOW_H))
    fonts = (pygame.font.SysFont(None, 26), pygame.font.SysFont(None, 18), pygame.font.SysFont(None, 40))
    clock = pygame.time.Clock()
    icon_cache = {}

    state = 'grid'
    chosen_cart = None
    mode_menu = None
    host_fields = None
    host_focus = None
    join_fields = None
    join_focus = None
    join_pick_menu = None
    join_scan_results = []
    error_message = None

    while True:
        action = None  # 'launch_local' | 'launch_host' | 'scan_join' |
                        # 'launch_join' | 'launch_join_direct' | None

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                return
            if event.type != pygame.KEYDOWN:
                continue

            if state == 'grid':
                if event.key == pygame.K_ESCAPE:
                    pygame.quit()
                    return
                if grid.is_empty():
                    continue
                if event.key in (pygame.K_UP, pygame.K_w):
                    grid.move_up()
                elif event.key in (pygame.K_DOWN, pygame.K_s):
                    grid.move_down()
                elif event.key in (pygame.K_LEFT, pygame.K_a):
                    grid.move_left()
                elif event.key in (pygame.K_RIGHT, pygame.K_d):
                    grid.move_right()
                elif event.key in (pygame.K_RETURN, pygame.K_j, pygame.K_SPACE):
                    chosen_cart = grid.selected()
                    mode_menu = MenuState(['Locale (1 giocatore)', 'Ospita partita in rete', 'Unisciti a partita in rete'])
                    error_message = None
                    state = 'mode'

            elif state == 'mode':
                if event.key == pygame.K_ESCAPE:
                    state = 'grid'
                elif event.key in (pygame.K_UP, pygame.K_w):
                    mode_menu.move_up()
                elif event.key in (pygame.K_DOWN, pygame.K_s):
                    mode_menu.move_down()
                elif event.key in (pygame.K_RETURN, pygame.K_j, pygame.K_SPACE):
                    choice = mode_menu.index
                    if choice == 0:
                        action = 'launch_local'
                        break
                    elif choice == 1:
                        host_fields = {'porta': TextField('42420', max_len=5, allowed=DIGITS),
                                       'giocatori': TextField('2', max_len=1, allowed=DIGITS)}
                        host_focus = 'porta'
                        error_message = None
                        state = 'host'
                    else:
                        action = 'scan_join'
                        break

            elif state == 'join_pick':
                if event.key == pygame.K_ESCAPE:
                    state = 'mode'
                elif event.key in (pygame.K_UP, pygame.K_w):
                    join_pick_menu.move_up()
                elif event.key in (pygame.K_DOWN, pygame.K_s):
                    join_pick_menu.move_down()
                elif event.key in (pygame.K_RETURN, pygame.K_j, pygame.K_SPACE):
                    if join_pick_menu.index == len(join_scan_results):
                        # ultima voce: "inserisci IP manualmente" - IP
                        # precompilato a 127.0.0.1 (loopback): funziona
                        # SEMPRE quando host e client girano sulla
                        # stessa macchina (test/sviluppo), a differenza
                        # della scansione automatica che puo' essere
                        # bloccata da firewall/VPN pur essendo entrambi
                        # sullo stesso PC
                        join_fields = {'ip': TextField('127.0.0.1', max_len=15, allowed=IP_CHARS),
                                       'porta': TextField('42420', max_len=5, allowed=DIGITS)}
                        join_focus = 'ip'
                        error_message = None
                        state = 'join'
                    else:
                        action = 'launch_join_direct'
                        break

            elif state == 'host':
                if event.key == pygame.K_ESCAPE:
                    state = 'mode'
                elif event.key == pygame.K_TAB:
                    host_focus = 'giocatori' if host_focus == 'porta' else 'porta'
                elif event.key == pygame.K_BACKSPACE:
                    host_fields[host_focus].backspace()
                elif event.key == pygame.K_RETURN:
                    action = 'launch_host'
                    break
                else:
                    host_fields[host_focus].add_char(event.unicode)

            elif state == 'join':
                if event.key == pygame.K_ESCAPE:
                    state = 'mode'
                elif event.key == pygame.K_TAB:
                    join_focus = 'porta' if join_focus == 'ip' else 'ip'
                elif event.key == pygame.K_BACKSPACE:
                    join_fields[join_focus].backspace()
                elif event.key == pygame.K_RETURN:
                    action = 'launch_join'
                    break
                else:
                    join_fields[join_focus].add_char(event.unicode)

        # -- azioni che lanciano davvero una partita: FUORI dal ciclo
        # "for event" apposta - run_direct ha il proprio pygame.event.get()
        # interno, chiamarlo da dentro quello esterno perderebbe eventi
        # accodati nel frattempo (e li leggerebbe due volte in generale) --
        if action == 'launch_local':
            entry, kind = _entry_and_kind(chosen_cart)
            quit_requested = run_direct(entry, kind, quit_pygame_at_end=False)
            screen = pygame.display.set_mode((WINDOW_W, WINDOW_H))
            if quit_requested:
                pygame.quit()
                return
            state = 'grid'
            continue

        if action == 'launch_host':
            try:
                porta = int(host_fields['porta'].value)
                num_giocatori = int(host_fields['giocatori'].value)
            except ValueError:
                error_message = "Porta e numero giocatori devono essere numeri"
                state = 'host'
                continue
            screen.fill((18, 18, 26))
            _draw_form_screen(screen, fonts[0], fonts[2], fonts[1], "Ospita partita",
                               [('Porta', 'porta', host_fields['porta']),
                                ('Numero giocatori', 'giocatori', host_fields['giocatori'])],
                               None, f"In attesa di {num_giocatori} giocatori...")
            pygame.display.flip()
            try:
                netcode_session, local_idx = start_netcode_host(porta, num_giocatori)
            except (ValueError, TimeoutError, OSError) as exc:
                error_message = _friendly_netcode_error(exc, porta)
                state = 'host'
                continue
            entry, kind = _entry_and_kind(chosen_cart)
            quit_requested = run_direct(entry, kind, quit_pygame_at_end=False,
                                         netcode_session=netcode_session, local_player_index=local_idx)
            netcode_session.close()
            screen = pygame.display.set_mode((WINDOW_W, WINDOW_H))
            if quit_requested:
                pygame.quit()
                return
            state = 'grid'
            continue

        if action == 'scan_join':
            screen.fill((18, 18, 26))
            _draw_list_screen(screen, fonts[0], fonts[2], "Cerco partite sulla rete locale...", MenuState([]))
            pygame.display.flip()
            join_scan_results = discover_netcode_hosts(duration_s=2.0)
            if join_scan_results:
                labels = [f"{h.get('name', '?')}  ({h['ip']}:{h['port']})" for h in join_scan_results]
                labels.append("Inserisci IP manualmente...")
                join_pick_menu = MenuState(labels)
                error_message = None
                state = 'join_pick'
            else:
                # nessun host trovato (rete che blocca il broadcast, host
                # su un'altra rete, o nessuno ancora in ascolto) - si
                # ripiega SUBITO sull'inserimento manuale, non e' un
                # vicolo cieco. IP precompilato a 127.0.0.1: se host e
                # client sono sulla STESSA macchina (caso comune in
                # sviluppo/test) funziona SEMPRE, anche quando il
                # broadcast e' bloccato da firewall/VPN.
                join_fields = {'ip': TextField('127.0.0.1', max_len=15, allowed=IP_CHARS),
                               'porta': TextField('42420', max_len=5, allowed=DIGITS)}
                join_focus = 'ip'
                error_message = "Nessuna partita trovata in automatico - inserisci l'IP a mano (127.0.0.1 se e' la stessa macchina)"
                state = 'join'
            continue

        if action == 'launch_join':
            ip = join_fields['ip'].value
            try:
                porta = int(join_fields['porta'].value)
            except ValueError:
                error_message = "La porta deve essere un numero"
                state = 'join'
                continue
            if not ip:
                error_message = "Inserisci l'indirizzo IP dell'host"
                state = 'join'
                continue
            screen.fill((18, 18, 26))
            _draw_form_screen(screen, fonts[0], fonts[2], fonts[1], "Unisciti a partita",
                               [('IP host', 'ip', join_fields['ip']),
                                ('Porta', 'porta', join_fields['porta'])],
                               None, f"Mi connetto a {ip}:{porta}...")
            pygame.display.flip()
            try:
                netcode_session, local_idx = start_netcode_client(ip, porta)
            except (ValueError, TimeoutError, OSError) as exc:
                error_message = _friendly_netcode_error(exc, porta)
                state = 'join'
                continue
            entry, kind = _entry_and_kind(chosen_cart)
            quit_requested = run_direct(entry, kind, quit_pygame_at_end=False,
                                         netcode_session=netcode_session, local_player_index=local_idx)
            netcode_session.close()
            screen = pygame.display.set_mode((WINDOW_W, WINDOW_H))
            if quit_requested:
                pygame.quit()
                return
            state = 'grid'
            continue

        if action == 'launch_join_direct':
            host = join_scan_results[join_pick_menu.index]
            ip, porta = host['ip'], host['port']
            screen.fill((18, 18, 26))
            _draw_list_screen(screen, fonts[0], fonts[2], f"Mi connetto a {ip}:{porta}...", MenuState([]))
            pygame.display.flip()
            try:
                netcode_session, local_idx = start_netcode_client(ip, porta)
            except (ValueError, TimeoutError, OSError) as exc:
                error_message = _friendly_netcode_error(exc, porta)
                state = 'join_pick'
                continue
            entry, kind = _entry_and_kind(chosen_cart)
            quit_requested = run_direct(entry, kind, quit_pygame_at_end=False,
                                         netcode_session=netcode_session, local_player_index=local_idx)
            netcode_session.close()
            screen = pygame.display.set_mode((WINDOW_W, WINDOW_H))
            if quit_requested:
                pygame.quit()
                return
            state = 'grid'
            continue

        # -- disegno --
        screen.fill((18, 18, 26))
        if state == 'grid':
            _draw_grid_screen(screen, pygame, fonts, carts_dir, grid, icon_cache)
        elif state == 'mode':
            _draw_list_screen(screen, fonts[0], fonts[2], f'Come vuoi giocare a "{chosen_cart.title}"?', mode_menu)
        elif state == 'host':
            _draw_form_screen(screen, fonts[0], fonts[2], fonts[1], "Ospita partita",
                               [('Porta', 'porta', host_fields['porta']),
                                ('Numero giocatori', 'giocatori', host_fields['giocatori'])],
                               host_focus, error_message)
        elif state == 'join_pick':
            _draw_list_screen(screen, fonts[0], fonts[2], "Partite trovate sulla rete locale:",
                               join_pick_menu, font_small=fonts[1], error_message=error_message)
        elif state == 'join':
            _draw_form_screen(screen, fonts[0], fonts[2], fonts[1], "Unisciti a partita",
                               [('IP host', 'ip', join_fields['ip']),
                                ('Porta', 'porta', join_fields['porta'])],
                               join_focus, error_message)
        pygame.display.flip()
        clock.tick(30)
