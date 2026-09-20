import threading
import time

from netplay import LobbyHost, LobbyClient, MatchSession, NetplayTimeout

fails = 0


def check(label, got, expected):
    global fails
    status = "OK  " if got == expected else "FAIL"
    if got != expected:
        fails += 1
    print(f"{status} {label}: atteso {expected!r}, ottenuto {got!r}")


def check_true(label, condition):
    check(label, bool(condition), True)


def run_host_poll_loop(host, stop_event):
    """Simula il loop di lobby del launcher: richiama poll() a
    ripetizione finche' non gli si dice di fermarsi - gira in un
    thread separato cosi' i client (che invece BLOCCANO in attesa di
    risposta, vedi netplay.py) possono essere pilotati dal thread
    principale uno alla volta, come farebbero persone reali che si
    uniscono in momenti diversi."""
    while not stop_event.is_set():
        host.poll()
        time.sleep(0.005)


# ---------------------------------------------------------------
# Test 1: un host + un client, discovery via unicast diretto (niente
# broadcast reale - piu' robusto in sandbox/CI dove il broadcast puo'
# essere bloccato, e la logica di gestione dei messaggi e' identica)
# ---------------------------------------------------------------
host = LobbyHost(game_id='test1', port=0, max_players=4)
stop = threading.Event()
t = threading.Thread(target=run_host_poll_loop, args=(host, stop), daemon=True)
t.start()

client = LobbyClient(game_id='test1', local_port=0)
found = client.discover(host_addr=('127.0.0.1', host.port), timeout=2.0)
check_true("discover: trova la lobby", len(found) == 1)
if found:
    check("discover: game_id corretto nella risposta", found[0][1].get('game_id'), 'test1')

slot = client.join(('127.0.0.1', host.port), timeout=2.0)
check("join: primo client riceve slot 2", slot, 2)
check("host: dopo il join, 2 peer noti", len(host.peers), 2)

stop.set()
t.join(timeout=1.0)

# ---------------------------------------------------------------
# Test 2: 4 giocatori (host + 3 client) si uniscono in sequenza -
# verifica assegnazione slot 1..4 e che la lista peer converga per
# tutti (ognuno finisce per conoscere l'indirizzo di tutti gli altri)
# ---------------------------------------------------------------
host2 = LobbyHost(game_id='test2', port=0, max_players=4)
stop2 = threading.Event()
t2 = threading.Thread(target=run_host_poll_loop, args=(host2, stop2), daemon=True)
t2.start()

clients = []
for i in range(3):
    c = LobbyClient(game_id='test2', local_port=0)
    s = c.join(('127.0.0.1', host2.port), timeout=2.0)
    clients.append(c)
    check(f"join sequenziale: client {i+1} riceve slot {i+2}", s, i + 2)

check("host: 4 slot occupati dopo 3 join", len(host2.peers), 4)
check("host: lobby piena, slots_free=0", host2.slots_free(), 0)

# un quinto tentativo (lobby piena) va ignorato - il client va in timeout
late_client = LobbyClient(game_id='test2', local_port=0)
try:
    late_client.join(('127.0.0.1', host2.port), timeout=0.3, retry_interval=0.1)
    check("join su lobby piena: solleva NetplayTimeout", "nessun errore", "NetplayTimeout")
except NetplayTimeout:
    check("join su lobby piena: solleva NetplayTimeout", "NetplayTimeout", "NetplayTimeout")

# la lista che il TERZO client si porta dietro (dalla propria WELCOME +
# eventuali PEERLIST successive) deve includere tutti e 4 gli slot
check("client 3: conosce tutti e 4 gli slot dopo il suo WELCOME",
      sorted(clients[2].peers.keys()), [1, 2, 3, 4])

host_session = host2.start()
sessions = [host_session]
for c in clients:
    sessions.append(c.wait_start(timeout=2.0))

check("start: 4 MatchSession create (1 host + 3 client)", len(sessions), 4)
for s in sessions:
    check(f"MatchSession slot {s.local_slot}: conosce tutti e 4 gli slot",
          sorted(s.peers.keys()), [1, 2, 3, 4])

stop2.set()
t2.join(timeout=1.0)

# ---------------------------------------------------------------
# Test 3: lockstep vero - ogni peer manda un input deterministico
# diverso per frame/slot, tutti devono convergere sullo STESSO
# dizionario {slot: input} per ogni frame - questo e' il cuore della
# sincronizzazione P2P (vedi doc_networking.md)
# ---------------------------------------------------------------
N_FRAMES = 20
results = {s.local_slot: [] for s in sessions}
errors = []


def play(session):
    try:
        for frame_id in range(N_FRAMES):
            local_input = (frame_id + session.local_slot) % 256
            got = session.collect_frame_inputs(frame_id, local_input, max_wait=5.0)
            results[session.local_slot].append(got)
    except Exception as exc:
        errors.append((session.local_slot, exc))


threads = [threading.Thread(target=play, args=(s,)) for s in sessions]
for th in threads:
    th.start()
for th in threads:
    th.join(timeout=10.0)

check("lockstep: nessun errore/timeout durante lo scambio", errors, [])

expected_by_frame = [
    {slot: (frame_id + slot) % 256 for slot in (1, 2, 3, 4)}
    for frame_id in range(N_FRAMES)
]
all_agree = all(
    results[slot] == expected_by_frame
    for slot in (1, 2, 3, 4)
)
check_true(f"lockstep: tutti e 4 i peer concordano su tutti i {N_FRAMES} frame", all_agree)

# ---------------------------------------------------------------
# Test 4: se un peer non manda mai il suo input, collect_frame_inputs
# deve arrendersi con NetplayTimeout (non restare bloccato per sempre)
# ---------------------------------------------------------------
lonely_session = MatchSession(
    sock=__import__('netplay')._udp_socket(bind_port=0),
    local_slot=1,
    peers={1: None, 2: ('127.0.0.1', 1)},  # slot 2 non rispondera' mai
)
try:
    lonely_session.collect_frame_inputs(0, local_input_byte=42, max_wait=0.2)
    check("collect_frame_inputs: peer muto -> NetplayTimeout", "nessun errore", "NetplayTimeout")
except NetplayTimeout as exc:
    check("collect_frame_inputs: peer muto -> NetplayTimeout", "NetplayTimeout", "NetplayTimeout")
    check_true("collect_frame_inputs: il messaggio nomina lo slot mancante", "[2]" in str(exc))

print()
if fails:
    print(f"{fails} test falliti.")
    raise SystemExit(1)
print("Tutti i test passati.")
