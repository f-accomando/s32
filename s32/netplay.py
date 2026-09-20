"""
netplay.py - rete P2P lockstep per S32, fino a MAX_PLAYERS giocatori
sulla stessa LAN/WiFi locale. Vedi doc_networking.md per il design
completo (perche' P2P lockstep e non host-autoritativo, alternative
scartate/rimandate) - qui c'e' SOLO l'implementazione.

Pura Python + socket standard (UDP), nessuna dipendenza esterna,
nessun riferimento a pygame/CPU - stesso principio di separazione gia'
usato per ppu.py (che non sa nulla di pygame) e cpu.py (che non sa
nulla di rete): questo modulo scambia solo byte di input, il
chiamante (launcher.py) decide come procurarli (tastiera) e cosa
farne (cpu.run()). Testabile in isolamento, vedi test_netplay.py, che
fa girare piu' "peer" nello stesso processo comunicando su
127.0.0.1.

Protocollo (una riga JSON per pacchetto UDP):
  DISCOVER  client -> host (broadcast o unicast diretto) - "cerco lobby"
  LOBBY     host -> client (risposta diretta al mittente) - "eccomi"
  JOIN      client -> host       - "voglio unirmi"
  WELCOME   host -> quel client  - "sei lo slot N, ecco chi c'e' gia'"
  PEERLIST  host -> tutti i gia' iscritti - "si e' aggiunto qualcuno,
                                             ecco la lista aggiornata"
  START     host -> tutti        - "si parte, ecco la lista finale"
  INPUT     ogni peer -> ogni altro peer - un byte di input per un
                                            numero di frame preciso

Dopo START l'host smette di avere un ruolo speciale: gli INPUT
viaggiano DIRETTAMENTE tra tutti i peer (mesh completa), non passano
mai per l'host - coerente con la scelta P2P (vedi doc_networking.md):
l'host serve solo per organizzare la lobby, non per giocare.
"""

import json
import socket
import time

MAX_PLAYERS = 4
DISCOVERY_PORT = 42042
BROADCAST_ADDR = '<broadcast>'  # valore speciale riconosciuto da
                                 # socket.sendto() con SO_BROADCAST
                                 # attivo - equivale a 255.255.255.255
DEFAULT_MAX_WAIT = 2.0  # secondi di attesa massima per l'input di un
                         # frame prima di arrendersi (vedi
                         # MatchSession.collect_frame_inputs)


class NetplayError(Exception):
    pass


class NetplayTimeout(NetplayError):
    """Un'attesa di rete (discovery, join, o l'input di un frame
    durante il lockstep) e' scaduta - tipicamente un peer disconnesso,
    un host non raggiungibile, o una rete troppo lenta."""


def _udp_socket(bind_port=0, broadcast=False):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if broadcast:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.bind(('0.0.0.0', bind_port))
    sock.setblocking(False)
    return sock


def _send(sock, addr, msg_type, **fields):
    payload = json.dumps({'type': msg_type, **fields}).encode('utf-8')
    try:
        sock.sendto(payload, tuple(addr))
    except OSError as exc:
        # il broadcast puo' essere negato da alcuni ambienti (sandbox,
        # container senza rotta di broadcast) - non deve far crashare
        # il chiamante, che puo' comunque riprovare con un IP esplicito
        raise NetplayError(f'invio a {addr} fallito: {exc}') from exc


def _recv_all(sock, bufsize=2048):
    """Legge TUTTI i pacchetti gia' in coda (non bloccante) - un solo
    poll() puo' dover processare piu' messaggi arrivati nello stesso
    istante (es. il JOIN di 3 client quasi simultanei). Pacchetti
    malformati vengono scartati silenziosamente (rete non fidata, un
    pacchetto corrotto non deve mai interrompere la partita)."""
    out = []
    while True:
        try:
            data, addr = sock.recvfrom(bufsize)
        except BlockingIOError:
            break
        try:
            msg = json.loads(data.decode('utf-8'))
        except (ValueError, UnicodeDecodeError):
            continue
        if not isinstance(msg, dict):
            continue
        out.append((msg, addr))
    return out


class LobbyHost:
    """Lato di chi crea la partita - e' sempre lo SLOT 1. poll() va
    richiamato a ripetizione (es. nel loop della schermata di lobby,
    insieme al pump degli eventi pygame) finche' non si chiama start()
    esplicitamente. Non blocca mai - a differenza di LobbyClient, che
    durante l'attesa di una risposta puo' permettersi di bloccare
    (siamo ancora prima che la partita inizi)."""

    def __init__(self, game_id, port=DISCOVERY_PORT, max_players=MAX_PLAYERS):
        if not (1 < max_players <= MAX_PLAYERS):
            raise NetplayError(f'max_players deve essere tra 2 e {MAX_PLAYERS}, ricevuto {max_players}')
        self.game_id = game_id
        self.max_players = max_players
        self.sock = _udp_socket(bind_port=port, broadcast=True)
        self.port = self.sock.getsockname()[1]
        self.peers = {1: None}  # slot -> (ip,port); lo slot 1 (l'host
                                 # stesso) non ha un indirizzo di rete
                                 # significativo verso se stesso
        self.started = False

    def slots_free(self):
        return self.max_players - len(self.peers)

    def _peers_json(self):
        return {str(slot): (list(addr) if addr else None) for slot, addr in self.peers.items()}

    def poll(self):
        """Processa i messaggi in arrivo (DISCOVER, JOIN). Ritorna
        True se in questa chiamata si e' unito un nuovo giocatore."""
        changed = False
        for msg, addr in _recv_all(self.sock):
            if msg.get('game_id') != self.game_id:
                continue  # lobby di un altro gioco sulla stessa rete/porta

            if msg.get('type') == 'DISCOVER':
                _send(self.sock, addr, 'LOBBY', game_id=self.game_id,
                      joined=len(self.peers), max_players=self.max_players)

            elif msg.get('type') == 'JOIN':
                addr_list = list(addr)
                if addr_list in self.peers.values():
                    continue  # richiesta duplicata (es. la WELCOME
                              # precedente si e' persa) - non assegnare
                              # un secondo slot allo stesso peer
                if self.slots_free() <= 0:
                    continue  # lobby piena, ignorata silenziosamente
                slot = max(self.peers) + 1
                self.peers[slot] = addr_list
                changed = True
                _send(self.sock, addr, 'WELCOME', slot=slot, peers=self._peers_json())
                for s, a in self.peers.items():
                    if s not in (1, slot) and a:
                        _send(self.sock, a, 'PEERLIST', peers=self._peers_json())
        return changed

    def start(self):
        """Chiude la lobby e avvia la partita: manda a tutti i gia'
        iscritti la lista FINALE di peer, poi ritorna la MatchSession
        per lo slot 1 (l'host e' sempre anche un giocatore, non un
        server a parte - vedi doc_networking.md)."""
        for slot, addr in self.peers.items():
            if slot != 1 and addr:
                _send(self.sock, addr, 'START', peers=self._peers_json())
        self.started = True
        peers = {slot: (tuple(addr) if addr else None) for slot, addr in self.peers.items()}
        return MatchSession(self.sock, local_slot=1, peers=peers)


class LobbyClient:
    """Lato di chi si unisce a una partita altrui. discover()/join()/
    wait_start() bloccano (con un timeout) - accettabile perche'
    succede tutto PRIMA che la partita inizi, mentre si aspetta un
    input umano ("connettiti") comunque."""

    def __init__(self, game_id, local_port=0):
        self.game_id = game_id
        self.sock = _udp_socket(bind_port=local_port, broadcast=True)
        self.slot = None
        self.peers = {}
        self.host_addr = None  # impostato da join() - vedi _parse_peers()

    def discover(self, host_addr=None, discovery_port=DISCOVERY_PORT, timeout=2.0, retry_interval=0.3):
        """Cerca lobby aperte per questo game_id. host_addr=(ip,port)
        esplicito -> chiede SOLO a quell'indirizzo (unicast diretto,
        utile quando l'IP e' gia' noto o il broadcast e' bloccato dalla
        rete/sandbox - vedi test_netplay.py). None -> broadcast sulla
        LAN. Ritorna una lista di (host_addr, info) - puo' essere vuota
        se nessuno risponde entro timeout."""
        target = tuple(host_addr) if host_addr else (BROADCAST_ADDR, discovery_port)
        found = []
        seen = set()
        deadline = time.monotonic() + timeout
        next_send = 0.0
        while time.monotonic() < deadline and not found:
            now = time.monotonic()
            if now >= next_send:
                _send(self.sock, target, 'DISCOVER', game_id=self.game_id)
                next_send = now + retry_interval
            for msg, addr in _recv_all(self.sock):
                if msg.get('type') == 'LOBBY' and msg.get('game_id') == self.game_id and addr not in seen:
                    seen.add(addr)
                    found.append((addr, msg))
            time.sleep(0.02)
        return found

    def join(self, host_addr, timeout=2.0, retry_interval=0.3):
        """Manda JOIN all'host, aspetta WELCOME. Ritorna lo slot
        assegnato. Solleva NetplayTimeout se l'host non risponde entro
        timeout (ritenta l'invio ogni retry_interval - un JOIN perso
        su UDP non deve bloccare per sempre)."""
        host_addr = tuple(host_addr)
        self.host_addr = host_addr
        deadline = time.monotonic() + timeout
        next_send = 0.0
        while time.monotonic() < deadline:
            now = time.monotonic()
            if now >= next_send:
                _send(self.sock, host_addr, 'JOIN', game_id=self.game_id)
                next_send = now + retry_interval
            for msg, addr in _recv_all(self.sock):
                if msg.get('type') == 'WELCOME':
                    self.slot = msg['slot']
                    self.peers = self._parse_peers(msg['peers'])
                    return self.slot
                if msg.get('type') == 'PEERLIST':
                    self.peers = self._parse_peers(msg['peers'])
            time.sleep(0.02)
        raise NetplayTimeout(f'Nessuna risposta di join da {host_addr} entro {timeout}s')

    def wait_start(self, timeout=30.0):
        """Aspetta il messaggio START dall'host. Ritorna la
        MatchSession pronta per il proprio slot."""
        if self.slot is None:
            raise NetplayError('wait_start() chiamato prima di join()')
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for msg, addr in _recv_all(self.sock):
                if msg.get('type') == 'PEERLIST':
                    self.peers = self._parse_peers(msg['peers'])
                elif msg.get('type') == 'START':
                    self.peers = self._parse_peers(msg['peers'])
                    return MatchSession(self.sock, local_slot=self.slot, peers=self.peers)
            time.sleep(0.02)
        raise NetplayTimeout(f'Nessun avvio partita entro {timeout}s')

    def _parse_peers(self, peers_json):
        """L'host riporta se stesso (slot 1) come indirizzo nullo -
        significativo dal SUO punto di vista (non deve mai mandare
        pacchetti a se stesso), ma un client ha invece bisogno
        dell'indirizzo REALE dell'host per potergli mandare il proprio
        input durante il lockstep - lo sostituiamo qui con quello usato
        davvero per il join (self.host_addr), l'unico che conosciamo
        per certo funzionante (ci ha appena risposto)."""
        parsed = {int(s): (tuple(a) if a else None) for s, a in peers_json.items()}
        parsed[1] = self.host_addr
        parsed[self.slot] = None  # se stesso, come per l'host in LobbyHost
        return parsed


class MatchSession:
    """Dopo START: scambio diretto (mesh, nessun relay dall'host) di UN
    byte di input a frame con ogni altro slot - il cuore del lockstep
    P2P (vedi doc_networking.md, sezione 2.3). Bufferizza gli input
    arrivati in anticipo per un frame futuro (normale su LAN: la rete
    e' quasi sempre piu' veloce del ciclo a 60fps di chi li consuma)."""

    def __init__(self, sock, local_slot, peers):
        self.sock = sock
        self.sock.setblocking(False)
        self.local_slot = local_slot
        self.peers = peers  # slot -> (ip,port) o None per se stesso
        self._pending = {}  # frame_id -> {slot: input_byte}

    def _remote_peers(self):
        return [(slot, addr) for slot, addr in self.peers.items() if addr is not None]

    def collect_frame_inputs(self, frame_id, local_input_byte, max_wait=DEFAULT_MAX_WAIT, poll_interval=0.001):
        """Manda il proprio input di questo frame a tutti gli altri
        slot, poi aspetta finche' non ha ricevuto quello di OGNI slot
        (se stesso incluso) per lo STESSO frame_id - il punto di
        sincronizzazione del lockstep: cpu.run() per questo frame non
        parte su NESSUNA macchina finche' tutte non hanno lo stesso
        set di input. Ritorna {slot: input_byte}. Solleva
        NetplayTimeout oltre max_wait (vedi doc_networking.md, "se
        manca l'input di qualcuno")."""
        bucket = self._pending.setdefault(frame_id, {})
        bucket[self.local_slot] = local_input_byte
        for slot, addr in self._remote_peers():
            _send(self.sock, addr, 'INPUT', frame=frame_id, slot=self.local_slot, input=local_input_byte)

        deadline = time.monotonic() + max_wait
        while True:
            bucket = self._pending.get(frame_id, {})
            if len(bucket) >= len(self.peers):
                break
            if time.monotonic() >= deadline:
                mancanti = sorted(set(self.peers) - set(bucket))
                raise NetplayTimeout(
                    f'Frame {frame_id}: input mancante dagli slot {mancanti} dopo {max_wait}s'
                )
            for msg, addr in _recv_all(self.sock):
                if msg.get('type') != 'INPUT':
                    continue
                self._pending.setdefault(msg['frame'], {})[msg['slot']] = msg['input']
            time.sleep(poll_interval)

        return dict(self._pending.pop(frame_id))
