# Networking: multiplayer locale WiFi per S32

Documento di **design**, non di implementazione — qui teniamo traccia
delle decisioni prese, del perché, e delle strade alternative scartate
o rimandate, così non le ridiscutiamo da zero ogni volta. Nessun
codice di rete esiste ancora nel motore: questo file è il punto di
partenza per quando lo scriveremo.

Obiettivo: un gioco (a partire da `carts/barebone/`) giocabile fino a
**4 persone in locale sulla stessa rete WiFi/LAN** — non su internet.

---

## 1. Decisione presa: peer-to-peer lockstep

Scartata l'alternativa host-autoritativo (client-server) per questo
caso d'uso. Motivazione:

| | Host-autoritativo | Peer-to-peer lockstep |
|---|---|---|
| Chi calcola la simulazione | Solo l'host, gli altri sono "muti" (mandano input, ricevono stato) | OGNI copia calcola la stessa simulazione in autonomia |
| Punto singolo di fallimento | Sì — se l'host lagga o cade, la partita si blocca per tutti | No — ogni peer è alla pari |
| Adatto a | Internet, tanti giocatori, server dedicato | LAN/WiFi locale, pochi giocatori, bassa latenza |
| Requisito sulla simulazione | Nessuno particolare | Deve essere **deterministica al bit** (stesso input -> stesso risultato su ogni macchina) |

Per 4 giocatori sulla stessa rete locale, senza un server dedicato, il
P2P lockstep è la scelta più semplice e naturale — nessun ruolo
speciale da gestire, nessuna migrazione host da progettare.

**Requisito chiave già soddisfatto da S32**: la CPU (`cpu.py`) è pura
Python, senza numeri in virgola mobile, senza timer di sistema letti
dentro la simulazione, senza `random` del sistema operativo — il
generatore "casuale" dei nemici in `adventure_cl`/`adventure_asm`
(`e1rng`, `e2rng`) è un LCG scritto nel programma stesso, quindi
deterministico e riproducibile identico su ogni macchina a parità di
input. Lo stesso principio già sfrutta `--playtest` (`launcher.py`):
una sequenza di input fissa produce sempre lo stesso risultato. Il
lockstep P2P si appoggia esattamente su questa proprietà.

---

## 2. Come funzionerebbe (bozza)

### 2.1 Discovery

Broadcast UDP sulla subnet locale: ogni copia in attesa di giocatori
manda/ascolta un pacchetto periodico tipo `S32_DISCOVER` sulla stessa
porta; chi risponde entra in una lobby con lo stesso game id. Niente
di più sofisticato per ora (mDNS/Zeroconf è un'alternativa più
robusta se in futuro servisse attraversare subnet diverse — vedi
sezione 4).

### 2.2 Sessione

- Un giocatore crea la partita, gli altri (fino a 3) la trovano e si
  uniscono - ognuno riceve uno **slot** (1-4).
- Si parte solo quando tutti gli slot occupati hanno segnalato
  "pronto" - evita di far partire il lockstep con un peer a metà
  handshake.

### 2.3 Il loop lockstep

Per ogni frame `N`:

1. Ogni peer legge il proprio input locale (tastiera/pad) e lo manda
   agli altri 3, taggato con il numero di frame `N`.
2. Ogni peer aspetta di avere ricevuto l'input di frame `N` da TUTTI
   e 4 gli slot (compreso il proprio) prima di chiamare `cpu.run()`
   per quel frame.
3. Se manca l'input di qualcuno, si aspetta - eventualmente con un
   **input delay** fisso (es. 2-3 frame, tecnica standard nei giochi
   in lockstep su LAN) per assorbire il jitter di rete senza dover
   implementare rollback.

Pacchetto UDP minimo per frame: `frame_id (4 byte) + slot (1 byte) +
input_byte (1 byte)` - pochissimi byte, tenendo la latenza il più
bassa possibile.

### 2.4 Impatto sul motore attuale

Oggi `input()` in ConsoleLang legge **un solo byte** da `PORT_INPUT`
(`cpu.py`) - un solo giocatore locale. Per 4 giocatori serve:

- un modo per la CPU di leggere l'input di **ognuno dei 4 slot**
  separatamente (es. 4 porte `PORT_INPUT_P1`..`PORT_INPUT_P4`, o un
  blocco WRAM dedicato scritto dal launcher prima di ogni
  `cpu.run()`) - decisione da prendere quando iniziamo l'implementazione
- una funzione ConsoleLang per leggerli (`input()` per il giocatore
  1, qualcosa come `input(2)`/`input_p2()` per gli altri - sintassi
  da decidere, vedi `lang.py`)
- il loop (`_run_pygame_loop` in `launcher.py`) deve inserire la fase
  di rete (invio/attesa pacchetti) PRIMA di `cpu.run()`, non dopo

Nessuna di queste modifiche è ancora stata fatta.

---

## 3. Stato attuale

**0% implementato.** Nessun modulo di rete esiste nel codice (verificato:
nessun uso di `socket`/`asyncio` in `s32/` o `carts/`). Questo
documento è il riferimento per quando affronteremo l'implementazione,
uno step alla volta come da roadmap generale del progetto.

---

## 4. Sviluppi e alternative future (non decise, solo annotate)

- **Migrazione a host-autoritativo**: se in futuro si volesse
  supportare il gioco via internet (latenza alta, variabile), il
  lockstep puro diventa scomodo (tutti aspettano il peer più lento) -
  a quel punto conviene un host autoritativo con client-side
  prediction, o un modello ibrido.
- **Rollback netcode (stile GGPO)**: se il lockstep con input delay
  fisso risultasse troppo "scattoso" su WiFi reale (jitter alto),
  l'alternativa è predizione locale + rollback quando arriva un input
  diverso da quello previsto - molto più complesso, non necessario per
  un primo prototipo LAN.
- **Spettatori**: un quinto client che riceve tutti gli input ma non
  ne manda mai (nessuno slot) - banale da aggiungere sopra il
  protocollo di cui sopra, dato che la simulazione è la stessa per
  tutti.
- **Replay/salvataggi**: essendo la simulazione deterministica,
  registrare la sola sequenza di input di tutti gli slot (frame per
  frame) basta a riprodurre l'intera partita — stesso principio già
  usato da `_playtest_sequence` in `launcher.py`. Utile sia per debug
  di disallineamenti di rete, sia come feature per i giocatori.
- **Discovery via mDNS/Zeroconf**: più robusto del semplice broadcast
  UDP se in futuro serve funzionare su reti WiFi che isolano i client
  tra loro (AP isolation) o su subnet diverse - non necessario per il
  primo prototipo.
- **Rilevamento disallineamento (desync)**: un lockstep P2P senza
  controlli può silenziosamente divergere (es. un bug di
  arrotondamento su una macchina) - un modo economico per accorgersene
  è scambiarsi periodicamente un hash dello stato (WRAM+VRAM+OAM) e
  segnalare un warning se non combacia tra i peer. Non necessario al
  primo prototipo, utile appena si superano le demo semplici.

---

## 5. Collegamenti

- Punto aperto e indipendente (non di rete): dimensione tile/sprite
  oggi fissa a 32x32 per l'intera console (`memory_map.py`,
  `TILE_SIZE_PX`) - tenuto da parte come possibile lavoro futuro, non
  necessario per il multiplayer.
- `doc_asm.md` / `doc_cl.md` - riferimento per come si scrive un
  programma S32 (necessario comunque prima di scrivere la demo
  multiplayer sopra `carts/barebone/`).
