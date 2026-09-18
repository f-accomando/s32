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
                       build_oam(oam) per il contenuto grafico iniziale
  graphics/*.png      <- risorse grafiche vere (png_tool, da riportare
                       da v1 quando servirà)
```

`game.py` deve esporre:
  `ROM_SOURCE`   - il codice sorgente (stringa)
  `SOURCE_LANG`  - `'asm'` oppure `'consolelang'`

`game.asm` è invece SEMPRE assembly puro (l'estensione lo dice già).

## Avvio

- `python3 s32/launcher.py` (nessun argomento) -> mostra il menu,
  scopre le cartucce qui dentro, le elenca, lancia quella scelta
- `python3 s32/launcher.py carts/nome_gioco/game.py` -> BYPASSA il
  menu, lancia direttamente quella cartuccia (stesso comportamento
  diretto della v1: `python3 main.py`)
