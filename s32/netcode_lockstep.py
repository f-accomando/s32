"""
netcode_lockstep.py - multiplayer sincrono (lockstep deterministico)
per la console s32, da 2 a 8 giocatori, via LAN o Internet.

NON ANCORA AGGANCIATO al resto del progetto - vedi i file in docs/
per dove e come collegarlo (cpu.py, lang.py, launcher.py).

--------------------------------------------------------------------
COME FUNZIONA (in breve)

La CPU della console e' completamente deterministica: stessa ROM +
stessa sequenza di input per ogni frame = stesso identico output su
qualunque macchina (nessun random, nessuna sorgente di tempo reale
dentro la simulazione). Per questo il multiplayer sincrono non ha
bisogno di trasmettere lo stato del gioco (VRAM/OAM/WRAM) - basta
che ogni copia della console riceva, per ogni frame, l'input di
TUTTI i giocatori, ed eseguano tutte lo stesso identico frame.

Topologia: "host-relay" (a stella). Un giocatore (l'host) fa anche
da hub: riceve l'input di tutti i client connessi, li impacchetta
in un unico "vettore" (un byte per giocatore, indice 0..7) e lo
ridistribuisce a tutti - host compreso. Scelta deliberata invece di
un P2P a maglia piena: con N giocatori il traffico resta O(N)
invece di O(N^2), e la logica di sincronizzazione (aspettare tutti)
vive in un punto solo (l'host) invece di essere duplicata ovunque.

Limite intrinseco del lockstep: si va veloci quanto il giocatore
piu' lento a rispondere. Con 2-4 giocatori su LAN e' quasi sempre
un non-problema (latenza sub-millisecondo); su Internet, o con piu'
giocatori, conviene alzare INPUT_DELAY_FRAMES per assorbire il
jitter (vedi sotto) - il prezzo e' percepire i propri comandi con
qualche frame di ritardo fisso, ma costante e prevedibile invece
che a scatti.

--------------------------------------------------------------------
PROTOCOLLO (UDP, pacchetti JSON - semplice da leggere/debuggare;
se in futuro serve piu' velocita' si puo' sostituire con un formato
binario a struct, l'interfaccia pubblica delle classi non cambia)

Handshake:
    client -> host   {"type": "hello", "name": "..."}
    host   -> client {"type": "welcome", "player_index": N,
                       "num_players": N, "players": {...}}

Ogni frame:
    client -> host   {"type": "input", "frame": F, "player": idx,
                       "value": byte, "checksum": crc_or_null}
    host   -> tutti  {"type": "frame", "frame": F,
                       "inputs": [b0, b1, ..., bN-1]}

Discovery LAN (facoltativa, solo per trovare host automaticamente
sulla stessa rete invece di digitare un IP a mano):
    host   -> broadcast  {"type": "announce", "name": "...",
                           "port": 12345, "players": "2/4"}
--------------------------------------------------------------------
"""

import json
import socket
import threading
import time
import zlib
import queue


DEFAULT_PORT = 42420
DISCOVERY_PORT = 42421
DISCOVERY_INTERVAL_S = 1.0
MAX_PLAYERS = 8

# Quanti frame di ritardo fisso applicare all'input locale prima di
# usarlo, per dare tempo alla rete di consegnare quello degli altri
# senza dover "saltare" frame in caso di jitter. 0 = nessun ritardo
# (va bene su LAN), 2-4 e' ragionevole su Internet.
INPUT_DELAY_FRAMES = 0


def crc32_of(data: bytes) -> int:
    """Utility per confrontare un checksum di stato (vedi doc
    01_porte_input_multiplayer_cpu.txt, CPU.state_checksum())."""
    return zlib.crc32(data)


class _UdpEndpoint:
    """Base comune: socket UDP + thread di ricezione che infila i
    pacchetti in una coda, cosi' il game loop non si blocca mai in
    attesa di rete - chiama solo get_frame_inputs()/poll() con un
    timeout breve, un frame alla volta."""

    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(('', 0))  # porta assegnata dal SO, sovrascritta da chi eredita se serve
        self._recv_queue = queue.Queue()
        self._running = True
        self._thread = threading.Thread(target=self._recv_loop, daemon=True)

    def _start(self):
        self._thread.start()

    def _recv_loop(self):
        self.sock.settimeout(0.5)
        while self._running:
            try:
                data, addr = self.sock.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                msg = json.loads(data.decode('utf-8'))
            except (ValueError, UnicodeDecodeError):
                continue
            self._recv_queue.put((msg, addr))

    def _send(self, msg: dict, addr):
        self.sock.sendto(json.dumps(msg).encode('utf-8'), addr)

    def close(self):
        self._running = False
        self.sock.close()


class LockstepHost(_UdpEndpoint):
    """Il giocatore che ospita la partita. E' sempre il giocatore di
    indice 0. Riceve gli input degli altri, li aggrega e ridistribuisce
    il "vettore input" completo di ogni frame a tutti (se' compreso,
    per simmetria con il client)."""

    def __init__(self, num_players, bind_port=DEFAULT_PORT):
        super().__init__()
        if not (2 <= num_players <= MAX_PLAYERS):
            raise ValueError(f'num_players deve essere tra 2 e {MAX_PLAYERS}')
        self.sock.close()
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(('', bind_port))
        self.num_players = num_players
        self.local_player_index = 0
        self._client_addrs = {}       # player_index -> (ip, porta)
        self._pending_by_frame = {}   # frame -> {player_index: value}
        self._lock = threading.Lock()
        self._start()

    # --- fase di attesa connessioni --------------------------------
    def wait_for_players(self, timeout_s=120):
        """Blocca finche' non si sono connessi num_players-1 client
        (l'host stesso conta come giocatore 0). Ritorna quando la
        partita puo' iniziare."""
        deadline = time.time() + timeout_s
        next_index = 1
        while len(self._client_addrs) < self.num_players - 1:
            if time.time() > deadline:
                raise TimeoutError('Timeout in attesa dei giocatori')
            try:
                msg, addr = self._recv_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if msg.get('type') == 'hello' and addr not in self._client_addrs.values():
                self._client_addrs[next_index] = addr
                self._send({
                    'type': 'welcome',
                    'player_index': next_index,
                    'num_players': self.num_players,
                }, addr)
                next_index += 1

    # --- loop di gioco -----------------------------------------------
    def submit_local_input(self, frame, value):
        with self._lock:
            self._pending_by_frame.setdefault(frame, {})[0] = value & 0xff

    def _drain_incoming(self):
        while True:
            try:
                msg, addr = self._recv_queue.get_nowait()
            except queue.Empty:
                break
            if msg.get('type') == 'input':
                with self._lock:
                    self._pending_by_frame.setdefault(msg['frame'], {})[msg['player']] = msg['value'] & 0xff
            elif msg.get('type') == 'hello':
                # riconnessione tardiva: ignorata qui, gestita in wait_for_players
                continue

    def get_frame_inputs(self, frame, timeout=0.25):
        """Ritorna una tupla di num_players byte per questo frame,
        oppure None se non sono ancora arrivati tutti entro il
        timeout (il chiamante decide se aspettare ancora o saltare
        il frame - vedi doc 03)."""
        deadline = time.time() + timeout
        while True:
            self._drain_incoming()
            with self._lock:
                got = self._pending_by_frame.get(frame, {})
                if len(got) >= self.num_players:
                    inputs = tuple(got[i] for i in range(self.num_players))
                    del self._pending_by_frame[frame]
                    break
            if time.time() > deadline:
                return None
            time.sleep(0.002)

        for addr in self._client_addrs.values():
            self._send({'type': 'frame', 'frame': frame, 'inputs': list(inputs)}, addr)
        return inputs


class LockstepClient(_UdpEndpoint):
    """Un giocatore che si unisce a una partita ospitata da qualcun
    altro. local_player_index viene assegnato dall'host durante
    connect()."""

    def __init__(self):
        super().__init__()
        self.local_player_index = None
        self.num_players = None
        self.host_addr = None
        self._frames = {}   # frame -> tupla di input
        self._lock = threading.Lock()
        self._start()

    def connect(self, host_ip, host_port=DEFAULT_PORT, name='player', timeout=10):
        self.host_addr = (host_ip, host_port)
        deadline = time.time() + timeout
        self._send({'type': 'hello', 'name': name}, self.host_addr)
        while time.time() < deadline:
            try:
                msg, addr = self._recv_queue.get(timeout=0.5)
            except queue.Empty:
                self._send({'type': 'hello', 'name': name}, self.host_addr)  # ritenta
                continue
            if msg.get('type') == 'welcome':
                self.local_player_index = msg['player_index']
                self.num_players = msg['num_players']
                return self.local_player_index
        raise TimeoutError('Timeout connessione a %s:%s' % self.host_addr)

    def submit_local_input(self, frame, value):
        self._send({
            'type': 'input',
            'frame': frame,
            'player': self.local_player_index,
            'value': value & 0xff,
        }, self.host_addr)

    def _drain_incoming(self):
        while True:
            try:
                msg, _addr = self._recv_queue.get_nowait()
            except queue.Empty:
                break
            if msg.get('type') == 'frame':
                with self._lock:
                    self._frames[msg['frame']] = tuple(msg['inputs'])

    def get_frame_inputs(self, frame, timeout=0.25):
        deadline = time.time() + timeout
        while True:
            self._drain_incoming()
            with self._lock:
                if frame in self._frames:
                    return self._frames.pop(frame)
            if time.time() > deadline:
                return None
            time.sleep(0.002)


# ---------------------------------------------------------------
# Discovery LAN - facoltativa: serve solo a trovare automaticamente
# un host sulla stessa rete locale invece di scrivere un IP a mano.
# Su Internet non serve (si usa IP pubblico/porta inoltrata a mano
# con LockstepClient.connect()).
# ---------------------------------------------------------------

class LanAnnouncer:
    """Da far girare lato host: annuncia periodicamente la partita
    in broadcast sulla rete locale.

    avatar: indice dell'avatar del profilo locale dell'host (vedi
    profile.py/os_menu.py) - facoltativo, di default 0. Incluso
    nell'annuncio cosi' chi cerca partite (LanBrowser.scan()) vede
    l'avatar dell'host PRIMA di connettersi, non solo il nome."""

    def __init__(self, game_name, connect_port=DEFAULT_PORT, avatar=0):
        self.game_name = game_name
        self.connect_port = connect_port
        self.avatar = avatar
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self._running = False
        self._thread = None

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self):
        msg = json.dumps({
            'type': 'announce',
            'name': self.game_name,
            'port': self.connect_port,
            'avatar': self.avatar,
        }).encode('utf-8')
        while self._running:
            try:
                self.sock.sendto(msg, ('<broadcast>', DISCOVERY_PORT))
            except OSError:
                pass
            time.sleep(DISCOVERY_INTERVAL_S)

    def stop(self):
        self._running = False
        self.sock.close()


class LanBrowser:
    """Da far girare lato client: ascolta gli annunci e restituisce
    la lista di host trovati sulla rete locale (ip, nome, porta)."""

    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(('', DISCOVERY_PORT))
        self.sock.settimeout(0.5)

    def scan(self, duration_s=2.0):
        found = {}
        deadline = time.time() + duration_s
        while time.time() < deadline:
            try:
                data, addr = self.sock.recvfrom(2048)
            except socket.timeout:
                continue
            try:
                msg = json.loads(data.decode('utf-8'))
            except (ValueError, UnicodeDecodeError):
                continue
            if msg.get('type') == 'announce':
                found[addr[0]] = {
                    'ip': addr[0],
                    'name': msg.get('name', '?'),
                    'port': msg.get('port', DEFAULT_PORT),
                    'avatar': msg.get('avatar', 0),
                }
        return list(found.values())

    def close(self):
        self.sock.close()


# ---------------------------------------------------------------
# Esempio d'uso minimo (non eseguito automaticamente)
# ---------------------------------------------------------------
#
# LATO HOST (2 giocatori):
#     host = LockstepHost(num_players=2, bind_port=42420)
#     host.wait_for_players()
#     frame = 0
#     while playing:
#         host.submit_local_input(frame, local_input_byte)
#         inputs = host.get_frame_inputs(frame)   # None se non pronto
#         if inputs is not None:
#             cpu.run(CART_LOAD_ADDR, input_byte=inputs[0], extra_inputs=inputs[1:])
#             frame += 1
#
# LATO CLIENT:
#     client = LockstepClient()
#     my_index = client.connect('192.168.1.10', 42420, name='giocatore2')
#     frame = 0
#     while playing:
#         client.submit_local_input(frame, local_input_byte)
#         inputs = client.get_frame_inputs(frame)
#         if inputs is not None:
#             cpu.run(CART_LOAD_ADDR, input_byte=inputs[0], extra_inputs=inputs[1:])
#             frame += 1
