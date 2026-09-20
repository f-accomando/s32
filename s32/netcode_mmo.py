"""
netcode_mmo.py - server/client per un mondo multiplayer scalabile
(decine/centinaia di giocatori), pensato per "altri progetti" - non
e' agganciato ne' pensato per la console s32 (che usa un modello a
frame fissi, lockstep - vedi netcode_lockstep.py per quello).

--------------------------------------------------------------------
PERCHE' E' UN PARADIGMA DIVERSO DAL LOCKSTEP

Il lockstep (netcode_lockstep.py) funziona perche' TUTTI i
partecipanti eseguono la STESSA simulazione completa, e per questo
ogni frame deve aspettare l'input di ognuno - con poche decine di
giocatori diventa impraticabile (basta un solo collegamento lento a
bloccare tutti, e il traffico/calcolo cresce con tutti quanti).

Un MMO usa invece un modello "client-server autoritativo":
- il SERVER e' l'unica fonte di verita': tiene lo stato vero del
  mondo (posizioni, HP, ecc.) e nessun client lo calcola per conto
  proprio
- i CLIENT mandano solo le proprie AZIONI/INTENZIONI ("vai a
  destra", "attacca") - non calcolano il risultato, lo ricevono dal
  server
- il server manda a ciascun client SOLO gli aggiornamenti che gli
  interessano (chi/cosa e' vicino a lui) - non l'intero mondo: e'
  la parte chiamata "interest management", ed e' quello che rende
  possibile scalare a molti giocatori senza che il traffico esploda

Questo file implementa uno scheletro funzionante di entrambe le
parti, con interest management a griglia (ogni entita' appartiene a
una cella; un client riceve aggiornamenti solo dalle celle vicine
alla propria). E' un punto di partenza generico, non specifico di
nessun gioco - va adattato al progetto che lo usera' (che tipo di
entita', quali azioni, ecc.).

--------------------------------------------------------------------
PROTOCOLLO (TCP, messaggi JSON con prefisso di lunghezza - scelto
apposta invece di UDP: qui la priorita' e' non perdere mai un
comando del giocatore, non la latenza minima frame-per-frame come
nel lockstep. Se in futuro serve anche un canale UDP "best effort"
per gli aggiornamenti di posizione ad alta frequenza, si puo'
aggiungere in parallelo senza toccare questo)

Client -> Server:
    {"type": "join", "name": "..."}
    {"type": "action", "action": "move", "dx": 1, "dy": 0}
    {"type": "action", "action": "...", ...}    -- azioni custom del progetto

Server -> Client:
    {"type": "welcome", "entity_id": "..."}
    {"type": "snapshot", "entities": [{"id":.., "x":.., "y":.., ...}, ...]}
--------------------------------------------------------------------
"""

import asyncio
import json
import time
import itertools


CELL_SIZE = 200          # dimensione di una cella della griglia di interesse
INTEREST_RADIUS_CELLS = 1  # quante celle di raggio intorno al giocatore vengono inviate
SNAPSHOT_HZ = 10          # quante volte al secondo il server manda aggiornamenti


def _cell_of(x, y):
    return (int(x // CELL_SIZE), int(y // CELL_SIZE))


def _cells_in_radius(cell, radius):
    cx, cy = cell
    return [
        (cx + dx, cy + dy)
        for dx in range(-radius, radius + 1)
        for dy in range(-radius, radius + 1)
    ]


class Entity:
    """Un oggetto/personaggio nel mondo. Il progetto che usa questo
    modulo probabilmente vorra' sottoclassarla o estenderne i campi
    (HP, inventario, ecc.) - qui c'e' solo il minimo per far
    funzionare interest management e movimento."""

    _ids = itertools.count(1)

    def __init__(self, x=0.0, y=0.0, kind='player'):
        self.id = str(next(Entity._ids))
        self.x = x
        self.y = y
        self.kind = kind

    def to_dict(self):
        return {'id': self.id, 'x': self.x, 'y': self.y, 'kind': self.kind}


class MmoServer:
    """Server autoritativo. Tiene lo stato di tutte le entita', apre
    una connessione TCP per client, e periodicamente manda a
    ciascuno solo le entita' nelle celle vicine alla propria
    (interest management)."""

    def __init__(self, host='0.0.0.0', port=43000):
        self.host = host
        self.port = port
        self.entities = {}          # entity_id -> Entity
        self._client_entity = {}    # writer -> entity_id
        self._writers = set()
        self._lock = asyncio.Lock()

    async def start(self):
        server = await asyncio.start_server(self._handle_client, self.host, self.port)
        asyncio.create_task(self._snapshot_loop())
        print(f'[mmo] server in ascolto su {self.host}:{self.port}')
        async with server:
            await server.serve_forever()

    # --- gestione connessioni --------------------------------------
    async def _handle_client(self, reader, writer):
        try:
            entity = Entity()
            async with self._lock:
                self.entities[entity.id] = entity
                self._client_entity[writer] = entity.id
                self._writers.add(writer)

            await self._send(writer, {'type': 'welcome', 'entity_id': entity.id})

            while True:
                line = await reader.readline()
                if not line:
                    break
                try:
                    msg = json.loads(line.decode('utf-8'))
                except (ValueError, UnicodeDecodeError):
                    continue
                await self._handle_message(entity, msg)
        except (ConnectionResetError, asyncio.IncompleteReadError):
            pass
        finally:
            async with self._lock:
                self._writers.discard(writer)
                eid = self._client_entity.pop(writer, None)
                if eid in self.entities:
                    del self.entities[eid]
            writer.close()

    async def _handle_message(self, entity, msg):
        """Punto da estendere per il progetto specifico: qui sotto
        c'e' solo un 'move' di esempio. Le azioni custom del gioco
        (attacchi, interazioni, chat, ...) vanno aggiunte come nuovi
        rami di questo if/elif, validando lato server (mai fidarsi
        del client per la logica di gioco vera - il client manda
        intenzioni, il server decide cosa succede davvero)."""
        if msg.get('type') != 'action':
            return
        action = msg.get('action')
        if action == 'move':
            dx = float(msg.get('dx', 0))
            dy = float(msg.get('dy', 0))
            async with self._lock:
                entity.x += dx
                entity.y += dy
        # elif action == '...': aggiungere qui le azioni del progetto

    # --- invio periodico degli snapshot -----------------------------
    async def _snapshot_loop(self):
        period = 1.0 / SNAPSHOT_HZ
        while True:
            t0 = time.perf_counter()
            await self._broadcast_snapshots()
            elapsed = time.perf_counter() - t0
            await asyncio.sleep(max(0.0, period - elapsed))

    async def _broadcast_snapshots(self):
        async with self._lock:
            # indicizza le entita' per cella, una volta sola per giro
            by_cell = {}
            for e in self.entities.values():
                by_cell.setdefault(_cell_of(e.x, e.y), []).append(e)

            for writer in list(self._writers):
                eid = self._client_entity.get(writer)
                entity = self.entities.get(eid)
                if entity is None:
                    continue
                nearby = []
                for cell in _cells_in_radius(_cell_of(entity.x, entity.y), INTEREST_RADIUS_CELLS):
                    nearby.extend(by_cell.get(cell, []))
                snapshot = {
                    'type': 'snapshot',
                    'entities': [e.to_dict() for e in nearby],
                }
                await self._send(writer, snapshot)

    async def _send(self, writer, msg):
        try:
            writer.write((json.dumps(msg) + '\n').encode('utf-8'))
            await writer.drain()
        except (ConnectionResetError, BrokenPipeError):
            pass


class MmoClient:
    """Client minimale: si connette, manda azioni, riceve snapshot.
    Va integrato nel game loop del progetto specifico che lo usa
    (leggere gli snapshot ricevuti e disegnarli, mandare le azioni
    in base all'input locale)."""

    def __init__(self):
        self.reader = None
        self.writer = None
        self.entity_id = None
        self.last_snapshot = {'entities': []}

    async def connect(self, host, port=43000):
        self.reader, self.writer = await asyncio.open_connection(host, port)
        welcome_line = await self.reader.readline()
        welcome = json.loads(welcome_line.decode('utf-8'))
        self.entity_id = welcome['entity_id']
        asyncio.create_task(self._recv_loop())
        return self.entity_id

    async def _recv_loop(self):
        while True:
            line = await self.reader.readline()
            if not line:
                break
            try:
                msg = json.loads(line.decode('utf-8'))
            except (ValueError, UnicodeDecodeError):
                continue
            if msg.get('type') == 'snapshot':
                self.last_snapshot = msg

    async def send_action(self, action, **fields):
        msg = {'type': 'action', 'action': action}
        msg.update(fields)
        self.writer.write((json.dumps(msg) + '\n').encode('utf-8'))
        await self.writer.drain()

    async def move(self, dx, dy):
        await self.send_action('move', dx=dx, dy=dy)

    def close(self):
        if self.writer:
            self.writer.close()


# ---------------------------------------------------------------
# Esempio d'uso minimo (non eseguito automaticamente)
# ---------------------------------------------------------------
#
# SERVER:
#     server = MmoServer(port=43000)
#     asyncio.run(server.start())
#
# CLIENT:
#     async def main():
#         client = MmoClient()
#         my_id = await client.connect('127.0.0.1', 43000)
#         await client.move(dx=1, dy=0)
#         await asyncio.sleep(1)
#         print(client.last_snapshot)   # entita' vicine a me
#     asyncio.run(main())
