# Networking: multiplayer locale per S32

Documento di riferimento sul multiplayer di S32: cosa è **realmente
implementato**, come si usa, e cosa resta aperto per il futuro. Per il
resoconto completo (dettagli di integrazione, bug trovati e corretti)
vedi `README.md`, sezione "Kit di rete integrato".

Obiettivo originale: un gioco (a partire da `carts/barebone_p2p/`)
giocabile fino a più persone in locale sulla stessa rete WiFi/LAN.

---

## 1. Come siamo arrivati qui (storia breve)

Questo progetto ha avuto **due tentativi paralleli** di implementare
il multiplayer, nati in due sessioni di lavoro diverse senza
coordinamento diretto:

1. Un primo tentativo (questa sessione) ha progettato e implementato
   un networking **peer-to-peer a maglia piena** (ogni giocatore manda
   il proprio input a TUTTI gli altri, nessun hub centrale).
2. In parallelo, l'utente ha caricato un **kit di rete già pronto**
   (`networking_kit.zip`) con un'architettura diversa - **host-relay a
   stella** (un giocatore fa da hub, riceve tutti gli input e
   ridistribuisce il vettore completo) - verificato e integrato da
   un'altra sessione direttamente su `main`.

Le due soluzioni si sovrapponevano quasi completamente (stessa
funzione, API incompatibili). Alla fusione dei branch, **si è scelto
di adottare il kit già integrato e verificato** (più maturo: fino a 8
giocatori, discovery LAN, rilevamento disallineamento via checksum) e
scartare il tentativo P2P a maglia piena. Questo documento descrive
SOLO la soluzione adottata.

---

## 2. Architettura adottata: lockstep host-relay

**Perché deterministico basta lo scambio di input**: la CPU di S32
(`cpu.py`) è pura Python, senza numeri in virgola mobile, senza timer
di sistema letti dentro la simulazione, senza `random` del sistema
operativo (il generatore "casuale" dei nemici in `adventure_cl`/
`adventure_asm` è un LCG scritto nel programma stesso). Stessa ROM +
stessa sequenza di input per ogni frame → stesso identico risultato su
qualunque macchina. Per questo il multiplayer non deve mai trasmettere
lo stato del gioco (VRAM/OAM/WRAM): basta che ogni copia riceva, per
ogni frame, l'input di TUTTI i giocatori.

**Topologia: host-relay (a stella), non P2P a maglia piena.** Un
giocatore (sempre l'indice 0) fa anche da hub: riceve l'input di tutti
i client, lo aggrega in un vettore (un byte per giocatore) e lo
ridistribuisce a tutti, host compreso. Scelta deliberata: con N
giocatori il traffico resta O(N) invece di O(N²) di un P2P a maglia
piena, e la logica "aspetta tutti" vive in un punto solo.

**Limite intrinseco**: si va veloci quanto il giocatore più lento a
rispondere - su LAN con pochi giocatori è quasi sempre un
non-problema.

**Testare host e client sullo STESSO PC**: usa sempre `127.0.0.1`
(loopback) come IP - funziona SEMPRE, a differenza della scoperta
automatica via broadcast (sezione 3) che su una singola macchina può
essere bloccata da firewall/VPN pur essendo tecnicamente sullo stesso
host. Il form "Unisciti a partita" del menu OS precompila già
`127.0.0.1` per questo motivo.

---

## 3. Cosa è implementato

### `s32/netcode_lockstep.py`

- `LockstepHost(num_players, bind_port)` - `wait_for_players()`
  blocca finché non si sono connessi tutti i client, poi
  `submit_local_input(frame, value)` + `get_frame_inputs(frame,
  timeout)` per lo scambio ad ogni frame (ritorna `None` se il vettore
  non è ancora completo - il chiamante decide se aspettare o saltare).
- `LockstepClient()` - `connect(host_ip, host_port)` per l'handshake
  (riceve il proprio `player_index` dall'host), stessa coppia
  `submit_local_input`/`get_frame_inputs` lato client.
- `LanAnnouncer`/`LanBrowser` - discovery via broadcast UDP.
  **Collegata** (vedi `s32/launcher.py` sotto e `os_menu.py`): l'host
  annuncia la lobby per tutta l'attesa, chi si unisce dal menu OS la
  trova in automatico senza dover conoscere l'IP - il form manuale
  resta come ripiego (rete che blocca il broadcast, o IP/porta gia'
  noti). Da riga di comando (`--netplay-join`) l'IP va ancora dato a
  mano - la scoperta automatica e' cablata solo nel menu OS per ora.
  Un IP non valido/non risolvibile (`socket.gaierror`, tipicamente
  "getaddrinfo failed") non fa piu' crashare ne' il menu ne' la CLI -
  entrambi mostrano un messaggio chiaro invece di un traceback grezzo
  (`main()` in `launcher.py` e `run_os_menu()` in `os_menu.py`
  catturano `(ValueError, TimeoutError, OSError)` attorno a
  `start_netcode_host`/`start_netcode_client`).

### `s32/cpu.py`

- `EXTRA_INPUT_PORTS` (7 porte, `0x042010`-`0x042016`, giocatori 2-8)
  + `ALL_INPUT_PORTS`. `PORT_INPUT` (giocatore 1/indice 0) resta
  invariato.
- `CPU.run(start_pc, input_byte=0, extra_inputs=None, max_steps=...)`
  - `extra_inputs` è opzionale (default `None`, ogni chiamata
  esistente continua a funzionare invariata).
- `CPU.state_checksum()` - CRC32 della WRAM, da confrontare tra le
  istanze in rete per scoprire un disallineamento (bug non
  deterministico o input perso) invece di vederlo come un bug di
  gioco "misterioso" molto più tardi.

### `s32/lang.py` (ConsoleLang)

- `input(N)`, N opzionale 0-7 (default 0 - `input()` resta identico a
  prima). Vedi `doc_cl.md`, sezione 7bis.

### `s32/launcher.py`

- `_run_pygame_loop()`/`run_direct()` accettano `netcode_session`/
  `local_player_index` opzionali. Con una sessione attiva: l'input
  locale viene inviato, poi si aspetta il vettore completo - se non
  ancora arrivato, il frame viene **saltato** (non disegna nulla di
  non sincronizzato), il contatore di frame non avanza finché non
  arriva una risposta valida.
- Flag CLI:
  ```
  --netplay-host <porta> <num_giocatori>
  --netplay-join <ip> <porta>
  ```
- `start_netcode_host(port, num_players)` / `start_netcode_client(ip,
  port)`: costruiscono LockstepHost/LockstepClient - riusate sia dai
  flag CLI sia dal menu OS (`os_menu.py`), un solo posto da mantenere.
  `start_netcode_host` avvia anche un `LanAnnouncer` per tutta
  l'attesa (fermato non appena i giocatori sono connessi).
- `discover_netcode_hosts(duration_s=2.0)`: usa `LanBrowser` per
  cercare host annunciati sulla LAN - usata dal menu OS prima di
  chiedere un IP a mano (vedi sotto, `os_menu.py`).

### `s32/os_menu.py`

Il menu di avvio: scelta cartuccia -> Locale/Ospita/Unisciti. Per
"Unisciti a partita in rete", cerca prima automaticamente sulla LAN
(`discover_netcode_hosts`, ~2s) e mostra la lista degli host trovati -
selezionandone uno ci si collega direttamente, **senza dover sapere
l'IP a mano**. Se la scansione non trova nulla (rete che blocca il
broadcast, host su un'altra rete), ripiega sul form manuale
(IP/porta). Vedi `README.md`, sezione sul mini-OS, per i dettagli.

### `carts/barebone_p2p/`

Cartuccia single-file (stessa convenzione di `carts/barebone/`) con 4
avatar (`p,q,r,s`), uno per slot, ognuno mosso da `input(0)`..`input(3)`.
Per giocarci in rete:

```
host:   python3 launcher.py carts/barebone_p2p/game.py --netplay-host 42420 2
client: python3 launcher.py carts/barebone_p2p/game.py --netplay-join <ip host> 42420
```

### `s32/netcode_mmo.py`

Scheletro client-server autoritativo generico (interest management a
griglia), pensato per progetti diversi da S32 - **presente ma NON
agganciato** al game loop: architettura diversa (asincrona, non
lockstep), nessuna integrazione richiesta finora.

---

## 4. Cosa NON è ancora fatto

- **Mai verificato su due macchine fisiche diverse** - solo
  host+client sulla stessa macchina via loopback.
- **La schermata "Ospita partita" resta bloccata e statica** durante
  `wait_for_players()` - mostra "in attesa di N giocatori..." ma non
  aggiorna la lista via via che qualcuno si unisce (nessun evento
  pygame elaborato in quella fase, stessa limitazione gia' presente
  nei flag CLI). Idem nessun HUD DURANTE la partita per lo stato della
  connessione (latenza, frame persi).
- **`netcode_mmo.py` non integrato** - disponibile per un progetto
  futuro che ne avesse bisogno.
- **Gestione disconnessione a partita in corso** non specificata -
  oggi un client che sparisce blocca `get_frame_inputs()` fino al
  timeout, senza una strategia di recovery (continua senza di lui?
  pausa?).

---

## 5. Sviluppi futuri (idee, non decise)

- **Rollback netcode (stile GGPO)**: se il lockstep con timeout fisso
  risultasse troppo "scattoso" su WiFi reale (jitter alto),
  l'alternativa è predizione locale + rollback quando arriva un input
  diverso da quello previsto - molto più complesso, non necessario per
  un prototipo LAN.
- **Migrazione parziale verso `netcode_mmo.py`**: se in futuro
  servisse un gioco con MOLTI giocatori (decine+) invece di una
  manciata, il modello lockstep smette di scalare (basta un client
  lento a bloccare tutti) - a quel punto lo scheletro client-server
  autoritativo già presente in `netcode_mmo.py` è il punto di
  partenza naturale, non il lockstep.
- **UI di lobby "viva"**: la schermata "Ospita partita" del menu OS
  (`os_menu.py`) esiste già, ma resta statica durante l'attesa (vedi
  sezione 4) - aggiornarla in tempo reale (chi si è connesso finora)
  richiederebbe rendere `wait_for_players()` non bloccante o pollarla
  a pezzi dal loop di disegno.
- **Replay/salvataggi**: essendo la simulazione deterministica,
  registrare la sola sequenza di input di tutti gli slot (frame per
  frame) basta a riprodurre l'intera partita - stesso principio già
  usato da `_playtest_sequence` in `launcher.py`.
- **Migrazione host**: oggi se l'host (indice 0) si disconnette la
  partita finisce - un host-relay puro non ha un modo nativo di
  "promuovere" un client a nuovo host senza riprogettare
  l'handshake.

---

## 6. Collegamenti

- `README.md`, sezione "Kit di rete integrato" - il resoconto completo
  dell'integrazione (bug trovati, test eseguiti, numeri esatti).
- `doc_cl.md`, sezione 7bis - `input(N)` lato ConsoleLang.
- `carts/barebone_p2p/game.py` - l'esempio funzionante.
- Punto aperto e indipendente (non di rete): dimensione tile/sprite
  oggi fissa a 32x32 per l'intera console (`memory_map.py`,
  `TILE_SIZE_PX`) - tenuto da parte come possibile lavoro futuro, non
  necessario per il multiplayer.
