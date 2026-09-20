# carts/ - contenuto (giochi), separato dal motore

Ogni sottocartella è un gioco indipendente. Il motore (`../s32/`) non
sa nulla di cosa c'è qui dentro - legge solo un file `.asm`/`.py`/
`.rom` che gli viene passato, esattamente come una console vera non
sa nulla del gioco finché non inserisci la cartuccia.

## Convenzione per una cartuccia valida (letta da `carts_registry.py`)

```
carts/nome_gioco/
  game.py          <- ALMENO uno tra game.py e game.asm è richiesto
  game.asm
  cart_info.py      <- opzionale: TITLE = "Nome mostrato nel menu"
                       (senza, si usa il nome della cartella)
  cart.py            <- opzionale: build_vram(vram), build_cgram(cgram),
                       build_oam(oam), build_stages(dict) per il
                       contenuto grafico iniziale
  icon.png            <- opzionale: icona nella griglia del menu OS,
                       32x40px esatti (vedi os_menu.py) - senza,
                       il menu disegna un riquadro grigio col titolo.
                       Convenzione INDIPENDENTE dagli spritesheet di
                       gioco (mai caricata in VRAM, la disegna
                       direttamente pygame nel menu)
  *.png               <- spritesheet (uno o più), tile_size x tile_size
                       per cella - vedi spritesheet_tool.py
```

`game.py` deve esporre:
  `ROM_SOURCE`   - il codice sorgente (stringa)
  `SOURCE_LANG`  - `'asm'` oppure `'consolelang'`

`game.asm` è invece SEMPRE assembly puro (l'estensione lo dice già).

### Convenzione single-file (nuova, vedi `carts/barebone/`)

Una cartuccia può essere **un solo file `game.py`** (più gli eventuali
spritesheet `.png`) - niente `cart.py` né `cart_info.py` separati:

```
carts/nome_gioco/
  game.py       <- ROM_SOURCE + SOURCE_LANG + (opzionale) TITLE,
                   build_vram/build_cgram/build_oam/build_stages
  font.png      <- spritesheet, unico asset non-Python ammesso
```

Il motore cerca `cart.py`/`cart_info.py` per primi (retro-compatibilità
con `adventure_cl`/`adventure_asm`); se assenti, cerca le stesse cose
dentro `game.py`. Nessuna cartella `_shared/`: ogni cartuccia è
autosufficiente, tutte le risorse (incluse quelle grafiche) stanno
nella sua cartella.

## Avvio

- `python3 s32/launcher.py` (nessun argomento) -> mostra il menu OS
  (griglia di icone, vedi `os_menu.py`), scopre le cartucce qui
  dentro. Scelta una cartuccia, chiede la modalità: **Locale**,
  **Ospita partita in rete** o **Unisciti a partita in rete** (fino a
  8 giocatori, vedi `doc_networking.md`) - dopo la partita si torna al
  menu, stesso indice di prima, finché non si chiude davvero la
  finestra.
- `python3 s32/launcher.py carts/nome_gioco/game.py` -> BYPASSA il
  menu, lancia direttamente quella cartuccia (stesso comportamento
  diretto della v1: `python3 main.py`). Aggiungendo
  `--netplay-host <porta> <num_giocatori>` o `--netplay-join <ip>
  <porta>` si salta anche il form del menu.
