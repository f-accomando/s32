# S32 - motore 16-bit (bus 24-bit flat)

Successore di `console_v2` (8-bit, congelata in `console_v1_frozen/`
e non più modificata). Le specifiche complete e il *perché* di ogni
numero sono in `memory_map.py` - leggilo prima di scrivere codice
qui dentro, è la fonte di verità.

## Stato attuale

- [x] Specifica della mappa indirizzi (`memory_map.py`), verificata
      senza buchi né sovrapposizioni
- [x] Nucleo CPU (`cpu.py`) - registri a 16 bit, bus 24-bit flat,
      registro flag (Z/N/C/V), stack hardware vero. 44 test
      (`test_cpu.py`), tutti passati.
- [x] PPU (`ppu.py`) - VRAM/OAM/CGRAM alle nuove dimensioni, tile
      8bpp, palette per-tile (8 palette), scroll in entrambe le
      direzioni, sprite 8x8/16x16 con palette selezionabile. 25 test
      (`test_ppu.py`), tutti passati.
- [x] Assemblatore (`assembler.py`) - operandi a 16 bit (immediati)
      e 24 bit (indirizzi), due passaggi con etichette avanti/
      indietro. 17 test (`test_assembler.py`), tutti passati -
      inclusa l'esecuzione VERA su CPU dei programmi assemblati.
- [x] Backend ConsoleLang (`lang.py`) - stessa SINTASSI di v1
      (lexer/parser identici), nuovo generatore di codice per S32.
      Migliora due limiti noti di v1: il confronto "<" ora usa CMP
      (non distrugge A) invece di una SUB distruttiva, e un "return"
      anticipato dentro una func ora ripristina X/Y correttamente
      (stack hardware vero) - in v1 questo era un limite documentato
      e irrisolto. 14 test (`test_lang.py`), tutti passati.
      NON ancora portato: select_room/set_bg_palette (S32 non ha
      ancora un meccanismo di cambio stanza - da progettare).

## Motore base COMPLETO (100 test: 44 CPU + 25 PPU + 17 assembler + 14 lang)

- [x] Mini-OS (`carts_registry.py` + `menu_state.py` + `launcher.py`)
      - scoperta automatica delle cartucce in `../carts/` per
        convenzione (game.py o game.asm richiesti)
      - `python3 launcher.py` (nessun argomento) -> mostra il menu
      - `python3 launcher.py carts/gioco/game.py` -> BYPASSA il menu,
        lancio diretto (stesso comportamento immediato della v1)
      - logica di scelta/scoperta separata dal loop pygame apposta,
        per restare testabile senza display: 34 test
        (`test_os_menu.py` + `test_launcher.py`), tutti passati -
        inclusa la compilazione/esecuzione vera di cartucce
        sintetiche sia in assembly che in ConsoleLang

## Totale attuale: 265 test, tutti passati (54 CPU + 48 PPU + 17 assembler + 21 lang + 21 menu + 66 launcher + 16 spritesheet + 22 audio)

## Prestazioni (rilevante per hardware debole, es. Raspberry Pi 1)

Storia reale di questo debug (utile documentarla, non solo il
risultato finale): due giri di ottimizzazione su `render_frame()`
(iterazione per blocco di tile + cache colori, poi buffer piatto con
copie a blocco via slice assignment) avevano dato 20ms -> 4ms -> 3.8ms
su macchina di sviluppo - ma sulla Raspberry Pi 1 vera il tempo
restava fermo a ~335-390ms, IDENTICO a prima di ogni ottimizzazione.
Invece di continuare a ottimizzare alla cieca, abbiamo profilato con
`--profile` (cProfile) DIRETTAMENTE sulla Pi 1, e il numero non
tornava: `get_tile()` chiamata 62.520 volte per una title screen con
solo 2 tile distinti.

IL BUG VERO (non specifico della Pi - un difetto reale, la Pi l'ha
solo reso visibile): la OAM ha 512 slot sprite. Uno slot mai scritto
resta a zero, quindi Y=0 - che secondo la nostra convenzione
(Y>=0xfff0 = nascosto) vuol dire VISIBILE! La PPU iterava tutti e
512 gli sprite fantasma ogni frame (completamente trasparenti, quindi
invisibili a schermo - per questo i test di correttezza non l'avevano
mai preso, controllavano il risultato visivo, non il lavoro sprecato
per ottenerlo). Fix: `_load_cart_graphics()` ora inizializza SEMPRE
la OAM con tutti gli sprite nascosti (Y=0xffff) prima di caricare
qualunque cartuccia - stesso schema dei giochi retro veri, dove
"pulisci la OAM" e' spesso il primo passo del boot.

Lezione generale: un profilo con numeri di chiamata "strani" (troppe
chiamate per quello che il programma dovrebbe fare) e' un segnale piu'
affidabile di quanto sembri - vale la pena controllarlo PRIMA di
continuare a ottimizzare il codice "giusto" per il sintomo sbagliato.

Tre flag per misurare le prestazioni sulla propria macchina:

  `python3 launcher.py carts/gioco/game.py --stats`
      gira normalmente (finestra aperta) e stampa in console, ogni
      secondo, fps + tempo medio di cpu.run()/render_frame()/blit

  `python3 launcher.py carts/gioco/game.py --benchmark`
      NESSUNA finestra aperta - misura pura di cpu.run()+render_frame()
      su 120 frame, utile per testare velocemente (anche via SSH,
      senza dover configurare un display)

  `python3 launcher.py carts/gioco/game.py --profile`
      come --benchmark ma con cProfile: stampa le 20 funzioni piu'
      costose per tempo cumulativo - usare quando i numeri aggregati
      non spiegano da soli dove va il tempo (esattamente il caso che
      ha portato a trovare il bug OAM sopra)

TERZO GIRO (dopo il fix OAM): il profilo su Pi 1 mostrava ancora il
67% del tempo nel corpo proprio di render_frame() (non nelle
sotto-funzioni) - il ciclo che scorre le 896 posizioni di tile, 8
righe ciascuna. Per una title screen, il 98% di quelle posizioni sono
"vuote" (tile trasparente) - e il buffer parte gia' tutto nero
(bytearray azzerato), quindi copiare un blocco tutto-zero sopra
un'area gia' tutta zero e' spreco puro. Fix: get_tile_blob() rileva i
tile completamente trasparenti e li salta del tutto (nessun blit).
Su macchina di sviluppo: 2.7ms -> 0.5ms, 5.5x - il guadagno piu'
grande di tutti i giri fatti finora, perche' elimina ITERAZIONI
intere invece di renderle piu' economiche. Non ancora confermato sulla
Pi 1 vera.

## Risoluzione

**480x320** (60x40 tile) - risoluzione nativa per lo schermo Raspberry
Pi reale dell'utente, cambiata da 256x224 (32x28 tile). Il cambio e'
solo nelle costanti di `memory_map.py`: tutto il resto (PPU, test,
cartucce) si adatta di conseguenza, tranne le coordinate VRAM
hardcoded per il testo della title screen (ricalcolate in entrambe
le cartucce - dipendono dalla posizione dello schermo, non sono
generiche). `scale` nel launcher e' tornato a 1 (nessun
raddoppiamento) dato che 480x320 e' gia' la risoluzione attesa a
schermo, non serve piu' ingrandire.

Impatto misurato su macchina di sviluppo: render_frame() passa da
0.487ms a 1.308ms (~2.68x, combacia quasi esattamente col rapporto
di pixel 153.600/57.344=2.68) - conferma che il costo del "controllo
se il tile e' vuoto" scala con il NUMERO DI POSIZIONI tile, non con
quanto c'e' effettivamente disegnato. Non ancora misurato sulla Pi 1
vera - il guadagno di aver tolto lo scale=2 (niente piu'
pygame.transform.scale) potrebbe compensare in parte l'aumento.

## Roadmap (deciso, non ancora implementato)

- **Coprocessori virtuali** (punto 1 della lista originale): 3D/
  matematica in virgola mobile, compressione asset, layer bitmap a
  colore pieno. Pattern comune: parametri scritti in porte dedicate,
  calcolo lato host, risultato letto da altre porte - stesso schema
  di `ROOM_SELECT`/`BG_PALETTE` in v1.
- **Audio/musica**: un coprocessore sonoro autonomo (canali pulse/
  triangolare/rumore/campioni, ispirato ai sound chip storici reali,
  NON allo SPC700 dello SNES 1:1) che gira sul lato host in
  parallelo alla CPU principale, non bloccato dal suo ciclo - a
  differenza degli altri coprocessori (calcolo puntuale, chiamato e
  messo in pausa), l'audio deve continuare mentre la CPU fa altro.
  Riproduzione vera affidata a libreria nativa per piattaforma
  (`pygame.mixer` su desktop/Python, Web Audio nelle demo browser).
  Deliberatamente NON basato su Strudel: ottimo per live coding
  interattivo ma browser-only (Web Audio), pensato per essere
  scritto da un umano in tempo reale, non per essere pilotato riga
  per riga da un programma - romperebbe la portabilita' Python del
  motore. La sua notazione compatta per i pattern resta pero' una
  buona ispirazione per come ConsoleLang potrebbe un giorno esporre
  sequenze musicali brevi, senza dipendere dallo strumento stesso.

## Struttura

```
s32/                  <- questo motore, riusabile per qualunque gioco
  memory_map.py        <- specifica indirizzi
  cpu.py                <- nucleo CPU (registri 16bit, bus 24bit, flag, stack)
  ppu.py                <- PPU (tile 8bpp, palette, scroll, sprite)
  assembler.py           <- testo assembly -> byte
  lang.py                <- ConsoleLang (stessa sintassi di v1, nuovo backend)
  coprocessors/           <- vuoto, pronto per il futuro (roadmap sopra)

../carts/              <- IL CONTENUTO (un gioco = una cartella),
                          separato dal motore
```

## Come lanciare

- `python3 launcher.py` (nessun argomento) -> mostra il menu (mini-OS),
  scopre le cartucce in `../carts/`, le elenca; se non ne trova
  nessuna mostra "NO ROM FOUND" invece di chiudersi in silenzio
- `python3 launcher.py carts/gioco/game.py` -> BYPASSA il menu,
  lancio diretto (stesso comportamento immediato della v1)
- `python3 launcher.py carts/gioco/game.asm` -> idem, assembly puro
- aggiungi `--stats` o `--benchmark` a uno qualunque dei comandi
  sopra per misurare le prestazioni (vedi sezione Prestazioni)

## Cartucce demo e tutorial

`carts/adventure_asm/` e `carts/adventure_cl/` - stessa title screen,
stesso comportamento, una in assembly puro e una in ConsoleLang
(quest'ultima usa la nuova `poke()`, vedi sotto). Le guide passo-passo
sono in `../docs/doc_asm.md` e `../docs/doc_cl.md` - coprono registri,
memoria, risorse grafiche, primo programma, input, fino alla title
screen funzionante. Prossimo capitolo (non ancora scritto): sprite e
movimento.

## Finestra menu/gioco condivisa

`run_os_menu()` e `run_direct()` ora condividono la STESSA sessione
pygame (un solo `pygame.init()`, la finestra viene ridimensionata
con `pygame.display.set_mode()`, non distrutta e ricreata) - prima
passare dal menu al gioco chiudeva e riapriva la finestra da zero
(`pygame.quit()` poi un nuovo `pygame.init()`), costoso e visibile
come un lampeggio.

## Sprite fino a 32x32 (CAMBIO CODIFICA ATTRIBUTI)

Il byte attributi OAM ora usa 2 bit per la dimensione (prima 1):
bit0-1 = dimensione (00=8x8, 01=16x16, 10=32x32 - 16 tile, griglia
4x4 sequenziale), bit2-4 = palette (spostata di una posizione).
CAMBIO INCOMPATIBILE con l'encoding precedente: un vecchio attr=4
(palette 2, 8x8) ora significa palette 1 - le cartucce esistenti
sono state aggiornate (attr=8 per palette 2, 8x8).

## IncrementalRenderer - VERIFICATO su Pi 1: il piu' veloce finora, ora default

Terzo percorso di rendering, diverso nello spirito da SurfaceRenderer
(che sostituiva un blit grande con centinaia di piccoli per lo
SFONDO - non ha aiutato). Qui invece si sfrutta che la cache dello
sfondo lo rende STATICO frame dopo frame: non serve ridisegnare
l'intero schermo (`pygame.display.flip()`), solo i rettangoli dove
sono gli sprite - `pygame.display.update(rects)`. Ogni frame: (1)
ripristina lo sfondo dov'era lo sprite l'istante prima (blit di quel
solo rettangolo dalla Surface di sfondo cachata), (2) disegna gli
sprite nella posizione attuale, (3) update() solo sui rettangoli
toccati.

Riusa `iter_visible_sprite_tiles()` (estratta da `draw_sprites()`
apposta, con test dedicati) per decidere cosa disegnare - stessa
logica di analisi OAM in un solo posto.

MISURATO su Raspberry Pi 1 vera: **~10-12ms/frame (~56-63fps)**
contro i ~48-54ms (~19-20fps) del percorso a buffer - un salto netto,
non marginale. E' ora il renderer PREDEFINITO (`--buffer-renderer`
torna al precedente se mai servisse). Perche' batte "Strada 1"
nettamente pur usando anch'esso blit() per gli sprite: il numero di
chiamate blit()/frame e' la differenza chiave - surface ne faceva
~150 (un blit per OGNI tile di sfondo, ogni frame), dirty-rects ne fa
una manciata (solo per lo sprite, lo sfondo resta fermo). Stesso
strumento (blit), applicato al problema giusto invece che a quello
sbagliato.

## Percorso completo di ottimizzazione (Raspberry Pi 1, scena di gioco reale)

| Passo | ms/frame | fps |
|---|---|---|
| Partenza | 335 | 1-2 |
| Fix OAM (512 sprite fantasma) | 260 | ~3 |
| Salto tile vuoti | ~118 | ~8 |
| Cambio risoluzione 480x320 | ~123 | ~8 |
| Tentativo SurfaceRenderer ("Strada 1") | 170-180 | peggio - scartato come default |
| Cache dello sfondo (percorso a buffer) | ~48-54 | ~19-20 |
| **IncrementalRenderer (dirty-rects)** | **~10-12** | **~56-63** |

Da 1-2fps a ~60fps: ~150x. Lezione ricorrente in questo percorso:
alcune ipotesi hanno retto (fix OAM, cache sfondo, dirty-rects),
altre no (SurfaceRenderer) - verificare sempre sui dati reali della
Pi prima di rendere un cambiamento il default, mai fidarsi solo del
ragionamento teorico o delle misure sulla macchina di sviluppo.

## Cache dello sfondo (background caching) - il vero rimedio ai 10fps

Trovato dopo aver capito perche' "Strada 1" non aiutava: sulla title
screen (quasi vuota) l'ottimizzazione "salta i tile vuoti" bastava.
Su una scena di gioco vera - stanza piena al 100% di pavimento/muri,
NESSUN tile vuoto da saltare - quell'ottimizzazione non aiuta per
niente, e il costo di ricalcolare ~150 posizioni tile OGNI FRAME
dominava (misurato: ~100-118ms/frame sulla Pi 1, ~10fps).

La leva vera: senza scroll implementato, lo sfondo e' IDENTICO da un
frame all'altro finche' non cambia stage. `ppu.py` e' stato separato
in `render_background()` (solo lo sfondo, cachabile) e
`draw_sprites()` (disegna sopra un buffer esistente - va rifatto ogni
frame, gli sprite si muovono, ma sono pochi). `render_frame()` resta
la loro composizione, comportamento IDENTICO di prima (32 test PPU
invariati + 3 nuovi che verificano l'equivalenza).

Il loop di gioco (`_run_pygame_loop`) e il benchmark (`run_benchmark`,
ora stampa ENTRAMBI i numeri: "da zero" e "con cache") ricalcolano lo
sfondo SOLO quando cambia `cpu.current_stage`; ogni frame copiano il
buffer cachato (una singola operazione a livello C, non un ciclo
Python) e disegnano gli sprite sopra. Su macchina di sviluppo, scena
piena: 2.33ms -> 0.39ms, 5.9x. Non ancora confermato sulla Pi 1 vera.

LIMITE NOTO: se una cartuccia scrive in VRAM (tilemap) con `poke()`
mentre e' gia' in uno stage, bypassando STAGE_SELECT, la cache non se
ne accorge - mostra contenuto vecchio finche' lo stage non cambia di
nuovo. Nessuna cartuccia attuale lo fa. Se/quando implementeremo lo
scroll, la chiave della cache dovra' includere anche scroll_x/y, non
solo lo stage.

## Tile unificati a 32x32 ("strada B")

TILE_SIZE_PX passa da 8 a 32 - stessa dimensione per sfondo E sprite
(prima erano disaccoppiati: tile sfondo 8x8, sprite componibili fino
a 32x32 a blocchi di tile da 8). Cambio a cascata: TILE_BYTES
1024 (era 64), MAX_TILES 96 (era ~1536 - tetto molto piu' basso ma
ancora abbondante, oggi ne usiamo 12), SCREEN_TILES_W/H 15x10 (era
60x40). Uno sprite di UN tile e' gia' 32x32 - i size_code 1/2
nell'attributo OAM ora producono 64x64/128x128 (griglie 2x2/4x4),
non piu' 16x16/32x32.

CONSEGUENZA IMPORTANTE: lo schermo e' largo solo 15 tile a 32px -
"PRESS J TO START" (16 caratteri) non ci stava piu', accorciato in
"PRESS J START" (13).

## Spritesheet PNG (spritesheet_tool.py) - NUOVA DIPENDENZA: Pillow

Le risorse grafiche non sono piu' disegnate a codice (liste di
stringhe ASCII) - si caricano da un vero file PNG a griglia
(`carts/_shared/adventure_spritesheet.png`, 4x3 tile), con palette
automatica (fino a 255 colori per tile-set, quantizzazione opzionale
per immagini piu' ricche del limite). Vedi `spritesheet_tool.py`
(16 test, `test_spritesheet_tool.py`) per il formato e le funzioni
di caricamento in VRAM/CGRAM.

IMPORTANTE: questo introduce Pillow (PIL) come dipendenza runtime
del MOTORE (non solo di sviluppo) - se non e' gia' installata sulla
Raspberry Pi: `pip install Pillow --break-system-packages`.

## SurfaceRenderer - "Strada 1" (MISURATA su Pi 1 vera: PIU' LENTA, non e' il default)

Percorso di rendering alternativo: ogni tile diventa una
pygame.Surface costruita UNA VOLTA SOLA (cache), poi riusata con
blit() invece che un buffer piatto scritto pixel per pixel in
Python. L'ipotesi era che lasciare il compositing a SDL2 (C) fosse
piu' veloce - VERIFICATO FALSO su Raspberry Pi 1: ~170-180ms/frame
contro i ~113-118ms/frame del percorso a buffer (render_frame() +
pygame.image.frombuffer), quindi PIU' LENTO, non piu' veloce.

Cause probabili (non confermate con un profilo dedicato, solo
ipotesi plausibili): ~150 chiamate blit()/frame hanno un costo fisso
ciascuna che qui supera il guadagno; le Surface con SRCALPHA
richiedono compositing alpha per-pixel anche in blit, costoso senza
accelerazione GPU; questa Pi probabilmente usa un renderer SDL
software (nessun driver video accelerato configurato di default su
Pi OS Lite headless).

NON e' il default (render_frame()+buffer lo e' ancora) - resta
disponibile dietro il flag `--surface-renderer` per chi vuole
riprovare su hardware con accelerazione GPU vera configurata, o per
investigare ulteriormente. Lezione: un'ipotesi di ottimizzazione va
sempre verificata sui dati reali prima di diventare il default -
esattamente per questo era dietro un flag invece che una sostituzione
diretta.

## Totale attuale: 196 test, tutti passati (54 CPU + 36 PPU + 17 assembler + 20 lang + 21 menu + 32 launcher + 16 spritesheet)

## Velocità ridotte: nemici, pietre, boss, fuoco

Richiesto dall'utente. Tutte le velocità dimezzate, stesso rapporto
ovunque per coerenza:
- nemici che vagano: 4px/frame -> 2px/frame
- pietre (proiettili nemici): 6px/frame -> 3px/frame
- movimento del boss: 2px/frame -> 1px/frame
- fuoco del boss: velocita' iniziale 13 -> 6 (cala di 1/frame come
  prima). La distanza totale percorsa scende di conseguenza (91px
  circa 3 tile -> 21px circa 2/3 di tile) - non era stato chiesto di
  preservare quella distanza, solo di ridurre la velocita', quindi
  non ho aggiunto complessita' per mantenerla invariata.

Verificato con misure dirette (spostamento in un frame) per tutte e
4 le velocita', in entrambe le versioni, con risultati identici.

### Falso allarme nel playthrough di verifica
Il primo test end-to-end post-modifica sembrava mostrare il boss
"immune" ai colpi dopo il secondo. Causa reale: il test teneva il
giocatore incollato al corpo del boss per OGNI frame, incluse le
attese tra un colpo e l'altro - danno da contatto ripetuto uccideva
il giocatore a meta' test (mode passa a game over, che ferma
l'aggiornamento del boss, dando l'impressione di un boss "congelato").
Non un bug nel gioco: corretto il test forzando l'invincibilita' del
giocatore per isolare la verifica sul boss. Lezione per il futuro:
un test che manipola lo stato direttamente deve isolare la variabile
che vuole verificare, o rischia di innescare altre meccaniche (qui,
danno da contatto) che confondono il risultato.

## Game over: teschio, testo, suono, reset al titolo

Richiesto dall'utente: quando i cuori finiscono, l'animazione del
giocatore cambia in un teschio, appare "GAME OVER", suona la
sconfitta, e dopo 3 secondi il gioco resetta tornando al titolo.

### Un problema strutturale scoperto per primo
La scritta "PRESS J START" veniva scritta nella tilemap UNA VOLTA
SOLA, all'avvio, da codice host-side Python (build_title_vram) -
mai dalla CPU. Una volta che STAGE_SELECT sovrascrive la tilemap
con una stanza vera, quel testo e' perso per sempre: non c'era modo
di "tornare al titolo" a runtime. Risolto rendendo la title screen
uno STAGE VERO: `build_title_tilemap()` estratta come funzione
standalone (stesso schema di _make_room), registrata come stage 0
in build_stages(). Ora `select_stage(0)` la ricarica in qualunque
momento, esattamente come le altre stanze.

### Nuovi sprite
Spritesheet esteso a 4x8 (32 tile): teschio (27) e le lettere G, M,
V (28,29,30) - mancavano per poter scrivere "GAME OVER" (avevamo
solo P,R,E,S,J,T,O,A dal font della title screen).

### La sequenza
1. HP=0 controllato PRIMA di ogni altra logica, all'inizio del
   frame - non ad ogni singolo punto che riduce HP (pietra, fuoco,
   contatto nemico/boss sono tutti fonti diverse).
2. Alla transizione: mode=2, timer=180 frame (3s), suono ID 9
   (nuovo: discesa lunga e cupa, distinta dal tonfo breve della
   ferita), e "GAME OVER" scritto nella tilemap UNA VOLTA SOLA (non
   ad ogni frame - e' sfondo, non OAM) via scrittura diretta VRAM
   (STA in asm, poke() in ConsoleLang - stessi indirizzi esatti).
3. Ogni frame successivo: teschio disegnato sopra il testo (non
   sovrapposto - aggiustato dopo la prima prova), tutto il resto
   (cuori, slash, nemici, pietre, boss, fuoco, barra vita) nascosto.
4. A timer=0: select_stage(0) ricarica "PRESS J START", mode=0.

Verificato con un test end-to-end completo in ENTRAMBE le versioni:
titolo -> uccisione nemici -> grata -> attraverso la notte -> morte
per mano del boss -> game over -> reset -> riavvio pulito (HP=3,
room=1) - non solo la funzionalita' isolata.

**237 test**, invariati (il game over e' contenuto di gioco, non
motore).

## Rischio noto, NON ancora affrontato: --gpu-renderer + --fullscreen

video.Window(fullscreen=True) potrebbe tentare un cambio modalita'
ESCLUSIVO a 480x320 - una risoluzione che lo schermo del Pi non
supporta nativamente via HDMI (raspi-config non la offre nemmeno,
vedi sezione sulla risoluzione minima 640x480). L'equivalente
accelerato di pygame.SCALED esiste in SDL2 (SDL_RenderSetLogicalSize
- scala il rendering a una risoluzione logica fissa indipendente da
quella fisica, con letterbox automatico), ma non ho trovato con
certezza il nome esatto della proprieta' che pygame gli da'
(probabilmente Renderer.logical_size, non verificato). Deliberatamente
NON toccato: abbiamo gia' sbagliato l'API esatta due volte in questo
stesso file (pygame.Window mancante, poi Surface/Renderer in
conflitto sulla stessa finestra) - un terzo tentativo su base
indovinata rischia di introdurre un bug invece di prevenirlo. Per
ora: testare --gpu-renderer SENZA --fullscreen.

## Bug di correttezza trovato dall'utente GIOCANDO DAVVERO: sfondo congelato durante lo scroll

Dopo il fix del dispatch CPU, l'utente ha giocato per davvero (non
solo playtest) e ha notato: "il personaggio sembrava stazionario e i
nemici oltrepassavano il muro". Non un problema di prestazioni - un
bug di correttezza introdotto dall'ottimizzazione precedente di
`texture_update`.

Causa: l'ottimizzazione spingeva sulla texture GPU SOLO la striscia
nuova durante lo scroll (`Texture.update(strip_surf, area=striscia)`),
basandosi sul fatto che lato CPU `Surface.scroll()` sposta
FISICAMENTE i pixel gia' disegnati prima di disegnare la striscia
nuova sopra. Ma la texture GPU non ha un equivalente di
`Surface.scroll()` - `Texture.update(area=X)` scrive SOLO i pixel
nuovi in quella regione; il resto del contenuto gia' caricato sulla
GPU non si sposta mai, restando congelato alla vecchia posizione.
Gli sprite (ridisegnati ogni frame nella posizione vera, mai
dipendenti dalla texture di sfondo) continuavano a muoversi
correttamente - da qui lo sfondo "fermo" mentre tutto il resto si
muoveva, e i nemici che sembravano attraversare muri ormai
disallineati dalla loro posizione visiva originale.

Corretto: si spinge sempre l'INTERO `bg_surface` (che e' comunque
gia' corretto lato CPU - scroll+patch della striscia sono gia'
avvenuti) con `area=None`, sia al rebuild completo sia durante lo
scroll incrementale. Sacrifica parte del guadagno di velocita' di
quell'ottimizzazione, ma la correttezza viene prima. Una versione
che scrolla DAVVERO anche il contenuto gia' caricato sulla GPU
(via render-to-texture, doppio buffering di texture) resterebbe
possibile in futuro, ma e' piu' complessa e non tentata ora senza
poterla verificare su hardware reale.

2 test in test_launcher.py corretti (verificavano il comportamento
BACATO come fosse quello giusto - li' stava il problema: un mock che
controlla "e' stata chiamata la funzione giusta con gli argomenti
giusti" non basta a verificare che il risultato VISIVO sia corretto,
serve pensare alla semantica reale, non solo alla forma della
chiamata).

**269 test**, tutti passati. Non ancora riverificato sulla Pi reale.

## Il fix del dispatch CPU invece ha funzionato: confermato dai dati

Confronto diretto, stesso identico scenario (--playtest-quick
--gpu-renderer), prima e dopo il fix del dispatch:
- PRIMA: cpu=38.61ms totale=70.68ms fps=14.1
- DOPO:  cpu=24.98ms totale=53.32ms fps=18.8

Un miglioramento reale e confermato sull'hardware vero, indipendente
dal bug di correttezza sopra (che riguarda solo `render`, non `cpu`).

## Kit di rete integrato (lockstep multiplayer), da networking_kit.zip caricato dall'utente

L'utente ha caricato un kit di rete auto-contenuto (3 documenti di
patch, 2 documenti di architettura, `netcode_lockstep.py`,
`netcode_mmo.py`) con un README che dichiarava tutto "testato". Non
mi sono fidato della dicitura - ho verificato io stesso ogni pezzo
prima di integrare, con lo stesso rigore usato per tutto il resto
del motore: eseguito davvero `netcode_lockstep.py` (host+client
locali, 5 frame di input diversi, verificato che ricevano lo stesso
identico vettore) e `netcode_mmo.py` (connessione, movimento,
interest management a griglia - un giocatore lontano non vede
quello vicino), non solo letto il codice.

### Cosa e' stato applicato

**cpu.py** (doc 01): `EXTRA_INPUT_PORTS` (7 porte, 0x042010-0x042016,
giocatori 2-8) + `ALL_INPUT_PORTS`. `read_mem()` riconosce tutte le
porte input, non solo `PORT_INPUT`. `run()` accetta `extra_inputs`
opzionale (default `None`, retrocompatibile con ogni chiamata
esistente) - scrive `input_byte` su `PORT_INPUT` e ogni valore di
`extra_inputs` sulla porta del giocatore corrispondente. Nuovo
`state_checksum()` (CRC32 della WRAM) per rilevare disallineamenti
tra istanze in rete. 23 nuovi test.

**lang.py** (doc 02): `input(N)` in ConsoleLang, N opzionale 0-7
(default 0, quindi `input()` resta identico a prima - NOTA: ora
compila in `LDA <porta>` invece del vecchio opcode dedicato `IN`,
comportamentalmente equivalente ma bytecode diverso; nessun test
esistente controllava il bytecode esatto, solo il comportamento, e
tutti sono passati invariati). Range validato con `SyntaxError`
chiaro se fuori 0-7. 7 nuovi test.

**launcher.py** (doc 03): `_run_pygame_loop()`/`run_direct()`
accettano `netcode_session`/`local_player_index` opzionali (default
`None`/`0`). Quando una sessione e' attiva: l'input locale viene
inviato (`submit_local_input`), poi si aspetta il vettore completo
(`get_frame_inputs`) - se non ancora arrivato (lag), il frame viene
SALTATO senza disegnare nulla di non sincronizzato, `frame_number`
non avanza finche' non arriva una risposta valida. `run_benchmark()`
resta invariato, sempre single-player. 3 nuovi test (con una sessione
finta che simula lag di rete, verificando che il frame venga
ririchiesto senza avanzare, poi ripreso normalmente).

### Cosa e' stato aggiunto oltre al kit

Il kit lasciava DELIBERATAMENTE fuori i flag CLI ("meglio scriverlo
voi seguendo lo stile esistente"). Aggiunti:

```
--netplay-host <porta> <num_giocatori>
--netplay-join <ip> <porta>
```

A differenza di tutti gli altri flag (booleani semplici),
consumano 2 argomenti successivi - `parse_flags()` e' passato da un
ciclo `for` a un ciclo a indice per poterli leggere. Validazione con
`LauncherError` (coerente col resto del file): argomenti mancanti,
non numerici, numero giocatori fuori range 2-8. `main()` costruisce
davvero `LockstepHost`/`LockstepClient` in base al flag e li passa a
`run_direct()` - l'host e' sempre il giocatore 0, il client riceve
il proprio indice dall'handshake di `connect()`.

`netcode_lockstep.py` e `netcode_mmo.py` copiati in `s32/`.
`netcode_mmo.py` e' disponibile ma NON agganciato al game loop -
nessuno dei documenti del kit ne descriveva l'integrazione (e'
un'architettura diversa, client-server asincrona, non lockstep) -
lasciato per un'eventuale integrazione futura con un design dedicato.

### Tre errori trovati durante la verifica pratica (miei, non del kit)

Scrivendo un piccolo cart di prova con `input(0)`/`input(1)` (due
giocatori, stato persistente, mosse da porte diverse su piu' frame,
incluso input simultaneo in direzioni opposte) ho trovato e corretto
tre miei errori, non del kit:
1. Chiamavo `run()` senza passare `input_byte`/`extra_inputs` dopo
   aver scritto le porte a mano - `run()` le sovrascrive comunque
   con i propri parametri (default 0).
2. Il programma di prova viveva allo stesso indirizzo (0x1000) usato
   anche come destinazione dei `poke()` di output - il programma
   sovrascriveva se stesso dal secondo frame in poi.
3. Dimenticata l'inizializzazione dei valori iniziali di `state`
   (`compile_source()` li ritorna separatamente in `state_vars`, va
   l'host a scriverli in memoria prima del primo `run()` - lo fa
   sempre `load_cart_rom`, ma non lo facevo nel test isolato).

Tutti e tre isolati e risolti prima di proseguire con l'integrazione
vera - il codice del kit non ha mai avuto bisogno di modifiche.

**330 test**, tutti passati. Playthrough completo (nemici -> grata
-> boss sconfitto) verificato invariato in entrambe le versioni
(assembly e ConsoleLang) dopo l'integrazione.

### Non ancora fatto

- Non verificato su due macchine reali diverse (solo host+client
  locali sulla stessa macchina, via loopback)
- `netcode_mmo.py` presente ma non agganciato a nulla
- Nessuna UI/HUD per mostrare lo stato della connessione durante il
  gioco (solo messaggi in console all'avvio)

## Separazione audio console/cartuccia, richiesta dall'utente

Segnalazione dell'utente: i suoni di Adventure erano finiti per
errore in `s32/audio.py` (il motore/console) invece che nella
cartuccia - esattamente come se avessimo messo lo spritesheet di
Adventure dentro `ppu.py` invece che in `carts/_shared/graphics.py`.

Corretto seguendo lo STESSO schema gia' in uso per la grafica:

- **`s32/audio.py`** (console, "hardware"): resta SOLO i generatori
  di forma d'onda generici - `square_wave`, `sweep_wave`, `noise`,
  `silence`, `mono_to_stereo`, `SAMPLE_RATE`, `AMPLITUDE`. Riusabili
  da QUALUNQUE cartuccia futura.
- **`carts/_shared/sound_bank.py`** (cartuccia, nuovo file):
  contiene gli ID suono di Adventure (`SND_ATTACK`, `SND_HURT`,
  ecc.) e `build_sound_bank()` - quali suoni esistono e cosa
  significano, costruiti usando i generatori della console.
  Condiviso tra adventure_asm e adventure_cl (stesso gioco, stessi
  suoni), stesso schema di `graphics.py`.
- **`cart.py`** di entrambe le cartucce: importa ed espone
  `build_sound_bank` esattamente come gia' faceva con
  `build_stages`.
- **`_load_cart_graphics()`** nel launcher: ora cerca anche
  `build_sound_bank` nel `cart.py` della cartuccia (stesso
  meccanismo `hasattr()` gia' usato per vram/cgram/oam/stages),
  popolando `cpu.sound_bank` - vuoto di default se la cartuccia non
  lo espone (nessun crash, il gioco resta muto).
- **`AudioPlayer`**: non costruisce piu' il banco suoni da solo
  chiamando `audio.build_sound_bank()` - lo riceve come parametro
  (`sound_bank=cpu.sound_bank`), passato dal launcher dopo aver
  caricato la cartuccia.

Verificato con 7 nuovi test: `audio.py` non ha piu' gli ID/la
funzione di Adventure, `sound_bank.py` li contiene tutti,
`AudioPlayer` carica esattamente il banco che riceve (incluso il
caso `sound_bank=None`/cartuccia senza audio - nessun crash),
`_load_cart_graphics` popola `cpu.sound_bank` correttamente dal vero
`cart.py` di Adventure. Verificato anche end-to-end con un mock
completo di pygame: `run_direct` con `--audio` carica davvero tutti
e 9 i suoni nel mixer, catena intera cartuccia -> sound_bank ->
AudioPlayer -> mixer.

**280 test**, tutti passati.

## Atlas sprite condiviso: da N texture separate a una sola, richiesto dall'utente

Prima di implementare, calcolo onesto fatto insieme all'utente: anche
azzerando COMPLETAMENTE `draw_sprites` (non solo -10ms, tutto), il
totale sarebbe rimasto a ~50ms da fermo e ~82ms in scroll sui dati
Pi reali - lontano dal target di 30fps/33ms. Non e' un'ottimizzazione
che risolve da sola il problema, ma vale comunque la pena farla:
aiuta le fasi senza scroll, e non richiede API mai testate prima
(a differenza del render-to-texture per lo scroll, scartato per
troppa incertezza sull'API esatta dopo tre correzioni gia' necessarie
in quest'area).

Prima: ogni sprite (giocatore, nemici, cuori, ecc.) aveva una
`Texture` GPU SEPARATA, creata una per ciascun (tile_index, palette)
distinto. Ogni `draw()` di uno sprite diverso costringeva la GPU a
CAMBIARE texture attiva - un'operazione con un costo fisso non
trascurabile sulle GPU embedded come la VideoCore IV, probabile causa
dei ~15-17ms misurati per una manciata di sprite (~2-4ms a chiamata).

Corretto: un ATLAS condiviso - una sola Surface/Texture che contiene
tutti i tile sprite distinti (griglia 8x8, fino a 64 slot - il gioco
ne usa meno di 20), con `srcrect` a selezionare la porzione giusta
ad ogni `draw()`. La GPU resta "agganciata" alla stessa texture per
tutti gli sprite di un frame.

A differenza dello sfondo (che scrolla, richiede SPOSTARE contenuto
gia' caricato - il bug di correttezza trovato prima), ogni slot
dell'atlas resta fisso una volta assegnato: aggiungerne uno nuovo
(`Texture.update(area=slot)`) non tocca mai gli altri gia' presenti,
quindi non c'e' equivalente del problema di scroll - sicuro per
costruzione, non solo per fortuna.

Bonus scoperto strada facendo: l'atlas non si svuota piu' al cambio
stanza (a differenza della vecchia cache per-tile). `tile_index` e'
un identificatore stabile in tutto il cartridge (stessa spritesheet
caricata una volta all'avvio, mai per-stanza) - cache permanente per
tutta la sessione e' sicura e piu' efficiente, evita di
ridecodificare/ricaricare gli stessi sprite (giocatore, cuori)
rientrando in una stanza gia' visitata.

Verificato con 4 nuovi test: due sprite con tile diversi usano
`update()` sulla STESSA texture (non `from_surface()` per ognuno),
un tile gia' in cache non genera ne' update ne' from_surface,
il cambio stanza non svuota piu' l'atlas.

**273 test**, tutti passati. Non ancora verificato sulla Pi reale -
e ricordare: anche in caso di successo, NON basta da sola per
raggiungere 30fps (vedi calcolo sopra) - serve ancora affrontare
`texture_update` durante lo scroll o il costo base della CPU.

## Segnalazione aperta, non ancora indagata: scia parzialmente residua

L'utente ha notato che il fix precedente per gli sprite fuori
schermo (vedi sezione sopra nel changelog) sembra parzialmente
efficace in modalita' GPU: i nemici entrerebbero nella zona nera
circa 1 tile prima del previsto. Non ancora indagato - serve capire
se succede anche con --gpu-renderer assente (per isolare se e'
specifico del percorso GPU o un problema piu' generale), e se
possibile un confronto visivo piu' preciso (screenshot, o la
posizione esatta mondo/schermo nel momento dell'artefatto) prima di
tentare un'altra correzione - specialmente dopo che gia' 3
correzioni in quest'area (`.convert()`, conflitto Surface/Renderer,
scroll congelato) sono state necessarie per problemi non previsti
inizialmente.

## Dispatch della CPU riscritto: da if/elif a tabella - il vero collo di bottiglia residuo

Dopo il fix di texture_update, il playtest su Pi mostrava ancora
~70-90ms/frame (14fps), con `cpu` a 35-45ms **anche da fermo, con
sole ~300 istruzioni** (verificate identiche al conteggio atteso -
non e' un problema di "troppo lavoro"). 300 istruzioni in 40ms sono
~130 microsecondi CIASCUNA - troppo anche per un ARM11 senza JIT.

Causa trovata: `step()` decodificava ogni istruzione con una catena
if/elif di 55 rami. Le istruzioni piu' usate in QUALSIASI programma
reale - i salti condizionali JZ/JNZ/JLT/JGE (ogni `if` di
ConsoleLang ne genera uno) - cadevano in posizione 39-42 su 55:
Python doveva controllare 38-41 condizioni PRIMA di arrivare a
quella giusta, ad OGNI singola istruzione eseguita.

Corretto: tabella di dispatch (`dict {opcode: metodo}`), costruita
UNA volta nel costruttore, non ad ogni istruzione - dispatch O(1)
invece di O(n), stesso costo qualunque sia l'istruzione. Ogni
`_op_XX` ha ESATTAMENTE lo stesso corpo del ramo elif corrispondente
- nessuna logica cambiata, solo il MECCANISMO di scelta.

Verificato: tutti i 54 test CPU passano invariati (comportamento
identico), un playthrough completo (nemici -> grata -> boss
sconfitto) in entrambe le versioni da' lo stesso risultato di prima.
Misurato sul mio ambiente: **~2.8x piu' veloce** (0.19ms -> 0.067ms
per lo stesso scenario) - la Pi, piu' lenta e senza branch
prediction efficiente, dovrebbe beneficiarne almeno altrettanto.

**269 test**, tutti passati. Non ancora riverificato sulla Pi reale -
prossimo passo dell'utente.

## Bug trovato dai dati reali: texture_update costante a 38ms, indipendente dallo scroll

Playtest reale su Pi: `texture_update=38ms` **costante** in ogni
frame di scroll, che lo scroll fosse di 2px o di 20px. Causa:
`Texture.update(self.bg_surface)` veniva chiamato SENZA l'area -
questo ricarica l'INTERA texture 480x320 sulla GPU ad ogni singolo
frame di scroll, anche se in CPU calcoliamo (con blob_cache e
striscia incrementale) solo le poche righe che cambiano davvero.
Lo stesso principio gia' applicato al calcolo CPU non era mai
arrivato al passo di caricamento sulla GPU.

Corretto: `Texture.update()` accetta un secondo argomento `area` -
durante lo scroll incrementale ora si passa SOLO `strip_surf` (la
striscia gia' calcolata, poche righe) con l'area che dice alla
texture DOVE piazzarla, non l'intero sfondo. Un rebuild completo
(cambio stanza) continua ad aggiornare l'intera texture (area=None) -
corretto cosi', non e' un caso da ottimizzare ulteriormente (succede
raramente).

Verificato con un mock che traccia le DIMENSIONI reali della surface
passata a update(): durante uno scroll di 10px, la surface e'
esattamente (480, 10) - la striscia - non (480, 320) - l'intero
sfondo. 4 nuovi test in test_launcher.py, incluso il caso simmetrico
(cambio stanza -> un solo update con area=None sulla texture
ESISTENTE, non una ricreazione).

**269 test**, tutti passati. Non ancora riverificato sulla Pi reale -
prossimo passo dell'utente.

## Bug trovato dall'utente al primo avvio reale di --gpu-renderer

```
pygame.error: Parameter 'surface' is invalid
```

su `pygame.image.frombuffer(...).convert()`. Causa: `.convert()`
richiede un display "classico" attivo (`pygame.display.set_mode()`)
per sapere a quale formato convertire - in modalita' GPU questo non
esiste MAI (finestra dedicata via `_sdl2.video.Window`, mai
`display.set_mode()`). Riga copiata da IncrementalRenderer (dove e'
corretta, quel percorso usa davvero `display.set_mode()`) senza
notare che il presupposto non vale in GpuRenderer. Rimossa - la
Surface va bene cosi' com'e' per `Texture.from_surface()`/`.update()`.

**Lezione sul mio stesso testing**: il mock usato per "verificare"
GpuRenderer prima di consegnarlo aveva `convert(self): return self`
- sempre valido, MAI come il vincolo vero di pygame. Questo ha
mascherato il bug: il test passava, il codice vero no. Corretto il
mock per fallire come pygame vero (nessun display classico -> errore),
cosi' la stessa classe di bug verrebbe intercettata la prossima
volta, non solo scoperta sull'hardware reale.

## --gpu-renderer: rendering accelerato via GPU (Renderer+Texture) - 14x piu' veloce, misurato

Scoperta chiave: la Pi 1 ha una GPU vera (Broadcom VideoCore IV), ma
tutto il codice fin qui (IncrementalRenderer, SurfaceRenderer, il
percorso a buffer) usa l'API CLASSICA di pygame
(pygame.display.set_mode() + Surface.blit() + pygame.display.flip())
- che e' SEMPRE software, indipendentemente dall'hardware sotto.
L'accelerazione vera richiede un'API diversa: pygame.Renderer +
pygame.Texture (in SDL2 puro: SDL_RENDERER_ACCELERATED).

**Verificato con test_gpu.py** (script isolato, non parte del
motore) sulla Pi 1 reale, prima di scrivere qualunque codice del
motore:
```
1) Surface.blit() + display.flip() (percorso ATTUALE, software):
   34.18 ms/frame  (~29.3 fps teorici)
2) Renderer + Texture accelerati (GPU, se disponibile):
   2.38 ms/frame  (~419.5 fps teorici)
-> 14.1x piu' veloce
```

### GpuRenderer

Riusa TUTTA la logica di calcolo gia' ottimizzata (blob_cache
persistente, striscia incrementale per lo scroll fluido, identica a
IncrementalRenderer) - cambia SOLO il passo finale di presentazione:
`Texture.update()` (spinge i pixel calcolati in CPU dentro la texture
GPU, solo quando lo sfondo e' davvero cambiato) + `renderer.clear()`
+ `texture.draw()` per sfondo e ogni sprite + `renderer.present()`.

Semplificazione rispetto a IncrementalRenderer: con la presentazione
cosi' economica, non serve piu' il tracciamento dei "dirty rect" per
gli sprite - si ridisegna SEMPRE l'intero frame, ogni frame, ed e'
comunque piu' veloce del vecchio percorso parziale su Surface.

### Compatibilita' pygame-ce / pygame mainline

Le due varianti divergono: pygame-ce (usata su Windows in questa
conversazione) espone `pygame.Window/Renderer/Texture` come nomi
diretti; pygame "mainline" (sulla Pi) li tiene sotto
`pygame._sdl2.video` - `_sdl2_video()` rileva quale delle due e' in
uso e ritorna l'oggetto giusto, stessa interfaccia in entrambi i
casi.

### Un'insidia trovata testando lo script diagnostico

SDL non permette che la STESSA finestra abbia sia una Surface
classica sia un Renderer accelerato ("Surface already associated
with window") - GpuRenderer quindi crea una finestra DEDICATA
(`_sdl2_video().Window(...)`), mai `pygame.display.set_mode()`,
quando `renderer_mode == 'gpu'`.

### Uso

```
python3 s32/launcher.py carts/adventure_asm/game.asm --gpu-renderer --stats
```

**NON ANCORA VERIFICATO end-to-end** con il gioco vero sulla Pi -
solo il costo isolato (test_gpu.py) e la logica di GpuRenderer
(mock di pygame, 11 nuovi test in test_launcher.py). Il prossimo
passo e' l'utente che lo prova per davvero.

**265 test**, tutti passati.

## --playtest-quick: versione ridotta, richiesta dall'utente

Un playtest completo su Raspberry Pi 1 reale ha impiegato **387
secondi** (6.5 minuti) - abbastanza a lungo da rischiare di
introdurre throttling termico durante il test stesso (un Pi 1 senza
dissipatore, sotto carico Python sostenuto, puo' scaldarsi e
rallentare la CPU in modo incostante), confondendo la misura invece
di chiarirla. L'utente ha giustamente osservato che le prime
iterazioni di ogni fase sono gia' rappresentative - non serve
ripeterle decine di volte per sapere quanto costano.

`--playtest-quick` copre le stesse identiche 6 fasi con frame ridotti
(~1/5 - fase 1 e 2 tagliate a 1/5, fase 2b a 1 solo ciclo di
rimbalzo invece di 6, fase 3 a 4 ripetizioni invece di 20, fase 4 a
240 frame invece di 1200):

```
python3 s32/launcher.py carts/adventure_asm/game.asm --playtest-quick --stats
```

Verificato: entrambe le versioni (`quick=True/False`) sono
deterministiche, coprono le stesse 6 fasi, e --playtest-quick e'
sempre almeno 3x piu' corta (di fatto ~5x, 938 frame contro 4671).

## Scoperta importante dal primo confronto Windows/Pi

Windows: **~1ms/frame medio** su tutte le fasi, incluso lo scroll
sostenuto - nessun problema di prestazioni li'.

Pi: la fase "1-fermo (baseline)" da SOLA (fermo, zero scroll, zero
combattimento) ha mostrato cpu=37.85ms, render=45.58ms - un costo
enorme per lo scenario piu' semplice possibile, con fps che
saltavano in modo erratico tra 8 e 38 senza una relazione chiara col
carico effettivo. Ipotesi principale (non ancora confermata): il
test da 6+ minuti puo' aver fatto scaldare il Pi abbastanza da
attivare il throttling termico (`vcgencmd get_throttled` per
verificare) - un fattore ambientale, non un problema nel codice.
--playtest-quick esiste anche per poter testare senza questo rischio.

## --playtest: pilota automatico per test via SSH senza HDMI/tastiera

Richiesto dall'utente: vedere risultati di prestazioni via SSH senza
dover collegare HDMI e tastiera fisicamente alla Pi. `--benchmark`
esisteva gia' ma usa SEMPRE input_byte=0 - il giocatore non si
muove mai, lo scroll non scatta mai: manca esattamente cio' che
abbiamo passato la conversazione a ottimizzare.

`--playtest` usa invece il rendering VERO (pygame reale,
IncrementalRenderer, flip()/update() reali) ma sostituisce la
tastiera con una sequenza scriptata deterministica
(`_playtest_sequence()` in launcher.py): fermo (baseline), scroll
continuo giu poi su, attacco ripetuto (J alternato premuto/rilasciato,
e' edge-triggered), esplorazione mista con cambi di direzione
pseudo-casuali (stesso generatore lineare congruenziale dei nemici)
e J occasionale. ~2500 frame, ~42 secondi simulati.

Si autotermina quando la sequenza finisce (niente attesa di un
evento QUIT che non puo' arrivare senza tastiera), e stampa un
riepilogo finale UNA tabella sola, per fase, pensata per essere
copiata e incollata cosi' com'e' - non le righe periodiche di
--stats (una al secondo, tante, da riassumere a mano).

Uso:
```
python3 s32/launcher.py carts/adventure_asm/game.asm --playtest
```

Combinabile con --stats (dettaglio in tempo reale oltre al
riepilogo), --no-audio, e qualunque renderer.

### Niente HDMI collegato? SDL_VIDEODRIVER=kmsdrm resta rappresentativo

Verificato in questa stessa conversazione (turno sul debug
offscreen/KMSDRM): forzare il driver KMSDRM via SSH SENZA monitor
collegato da' comunque numeri realistici (i drop misurati
combaciavano con quelli visti con HDMI attaccato) - il sottosistema
DRM lavora sul serio anche senza un pannello fisico a valle.

```
SDL_VIDEODRIVER=kmsdrm python3 s32/launcher.py carts/adventure_asm/game.asm --playtest
```

Senza questa variabile, con HDMI scollegato SDL sceglie "offscreen"
(un driver nullo, pensato per test automatizzati - non misura il
costo vero del driver grafico).

Verificato con un test che esegue DAVVERO run_direct attraverso un
mock di pygame (non solo lettura del codice) - tutte e 5 le fasi
presenti nell'output, playtest+stats insieme, playtest col renderer
'buffer', playtest con la cartuccia ConsoleLang: nessun crash in
nessuna combinazione. 10 nuovi test in test_launcher.py verificano
il parsing del flag e le proprieta' della sequenza (deterministica,
copre tutte le fasi, l'attacco alterna davvero premuto/rilasciato).

## Bug trovato nel playthrough completo end-to-end

Prima di dichiarare concluso il gioco, un test end-to-end reale
(titolo -> 2 nemici -> grata -> attraverso la stanza notturna ->
boss sconfitto, in ENTRAMBE le versioni, con la coda suoni
verificata ad ogni frame) ha rivelato un buco: il suono di ferita
(ID 2) mancava nel blocco di contatto DIRETTO col corpo del boss, in
assembly - era collegato correttamente a pietre e fuoco, ma non a
quello. ConsoleLang ce l'aveva gia' (un pattern di sostituzione piu'
generico l'aveva coperto per caso). Corretto e riverificato.

## Nota aperta: nessun game-over

Lo stesso playthrough ha mostrato che l'HP puo' arrivare davvero a 0
durante una partita normale (contro il boss) - e a quel punto il
gioco continua a girare indefinitamente, senza game over ne'
respawn: il giocatore resta semplicemente a 0 cuori, di fatto
invincibile (i controlli "playerHP < 1: non scendere sotto zero"
impediscono il crash, ma non gestiscono la sconfitta). Non era stato
chiesto esplicitamente, quindi non l'ho aggiunto di mia iniziativa -
segnalato qui invece di lasciarlo silenzioso.

## Boss e sistema audio (completamento del gioco)

### Boss 64x64
Un SOLO slot OAM con attributo dimensione 01 (griglia 2x2): il PPU
compone da solo i 4 tile consecutivi 20-23. Disegnato come immagine
unica 64x64 e poi tagliata, non quattro pezzi separati.
Due fasi alternate: movimento orizzontale a passi (2 passi, inverte
ai bordi) e sparo del fuoco. Barra vita di 4 tile (slot OAM 11-14,
segmento pieno=25 / vuoto=26), presente SOLO nella stanza del boss.
4 colpi la svuotano; il contatto col corpo ruba un cuore.

**Fuoco che rallenta**: velocita' parte da 13, cala di 1 al frame, e
il fuoco avanza DI quella velocita' ogni frame -> 13+12+...+1 = 91px
= quasi esattamente 3 tile. Sparisce dopo 120 frame (2.02s misurati).

### Due bug trovati testando (non leggendo il codice)
1. **Fuoco che non percorreva la distanza giusta**: muoveva di 2px
   FISSI mentre la velocita' calava - il valore scendeva
   regolarmente (sembrava corretto) ma percorreva solo 24px invece
   di ~96. Visibile solo misurando la distanza in un test.
2. **Boss invisibile**: `boss_y - scrollY` va sotto zero quando la
   telecamera sta piu' in basso del boss; registri SENZA SEGNO ->
   si avvolge a >= 0xFFF0, che e' il codice "sprite nascosto".
   Stessa insidia gia' vista per la telecamera. Protetto con
   CMP/JLT prima della sottrazione, anche per il fuoco.

Corretto anche il posizionamento: il boss era in cima alla stanza,
ma "a fine schermo" significa in FONDO - dove il giocatore arriva
dopo aver attraversato la stanza notturna.

### Audio (nuovo: audio.py, PORT_SOUND, play_sound())
NON esisteva alcun audio prima: il mixer era deliberatamente spento
per gli underrun ALSA su Pi. Ora c'e' un sistema completo che
mantiene la stessa separazione del video:
- `cpu.py`: scrivere su PORT_SOUND (0x042004) ACCODA un ID in
  `cpu.sound_queue`. La CPU non produce suono, come non disegna
  pixel - resta pura e testabile senza scheda audio.
- `audio.py`: genera solo BYTE PCM (square_wave / sweep_wave /
  noise), nessuna dipendenza da pygame. Banco di 8 suoni costruito
  UNA volta sola all'avvio (stesso principio del blob_cache).
- `launcher.py`: `AudioPlayer` svuota la coda a ogni frame, PRIMA
  del rendering (il disegno puo' costare decine di ms su Pi, e
  ritardare il suono lo renderebbe percepibile in ritardo).
- `lang.py`: nuova istruzione `play_sound(expr)`.

**ATTIVO DI DEFAULT** (aggiornato in un turno successivo - prima era
opt-in con --audio, l'utente ha chiesto il contrario), disattivabile
con --no-audio, e tollerante ai guasti: ogni errore di
inizializzazione viene ingoiato e disattiva solo l'audio. Un gioco
muto e' meglio di un gioco che scatta o non parte - chi incontra
l'underrun ALSA su Pi usa --no-audio.

8 suoni collegati agli eventi: fendente, ferita, nemico distrutto,
sparo, scale, grata, boss colpito, boss sconfitto.

**20 nuovi test** (test_audio.py) che verificano forme d'onda,
determinismo del rumore, banco suoni, accodamento su PORT_SOUND e
play_sound() - tutti senza pygame ne' scheda audio.

## Gioco completo: attacco, nemici, proiettili, grata

Aggiunte tutte le meccaniche di combattimento, in cinque blocchi
(richiesti in quest'ordine dall'utente), su entrambe le versioni
(game.asm e game.py) e documentate nei tutorial (doc_asm.md sez.
17-21, doc_cl.md sez. 18-22).

- **Spritesheet esteso** a 4x5 (20 tile): slash frame 1/2, nemico,
  pietra, grata, animazione morte nemico.
- **Attacco (J)**: edge-trigger su J, attackTimer di 10 frame,
  slash disegnato un tile avanti nella direzione di `direction`,
  animazione a 2 frame (tile 14 -> 15 sotto meta' timer).
- **Due nemici che vagano**: 4px/frame continuo (NON allineato alla
  griglia - non ne hanno bisogno), rimbalzo ai bordi, cambio
  direzione pseudo-casuale (contatore + incremento dispari, `& 31`
  per la frequenza, `& 3` per la direzione). Nessun danno da
  collisione diretta, come richiesto.
- **Pietre**: sparate quando il giocatore e' sullo stesso asse X o Y
  (soglia 16px), cooldown 80 frame per nemico, 6px/frame, si
  disattivano ai bordi.
- **Danno**: pietra su giocatore (soglia 20px) toglie 1 HP, 20 frame
  di invincibilita' con lampeggio (`hurtTimer & 2` nasconde lo
  sprite a intermittenza), cuori HUD legati a playerHP.
- **Slash su nemico** (soglia 24px): alive 1 -> 2 (animazione morte,
  10 frame) -> 0, e incrementa `enemies_killed`.
- **Grata**: stage 1 = giorno con GRATA al posto delle scale, stage
  3 = giorno con scale vere. A `enemies_killed == 2`, room 1 -> 3 +
  select_stage(3). Nessuna variabile "gate_open" separata: `room`
  stesso codifica lo stato, essendo due tilemap diverse.

### Tre bug reali trovati TESTANDO (non leggendo il codice)

1. **J di avvio faceva partire un attacco** (entrambe le versioni):
   lo stesso J premuto per uscire dalla title screen veniva riletto
   nello stesso frame come "appena premuto". Corretto inizializzando
   `prevJ = 1` all'ingresso in gioco. Tolta anche la protezione
   iniziale (hurtTimer=16) che faceva lampeggiare il giocatore allo
   spawn senza motivo.

2. **Ternario ConsoleLang no-op su playerHP**: scritto
   `playerHP = playerHP - 1 ? playerHP` - la condizione e' quasi
   sempre vera, ma il ramo "vero" assegna il valore CORRENTE
   (invariato). Risultato: il giocatore non perdeva MAI vita colpito
   da una pietra, di fatto invincibile. 8 occorrenze corrette con
   if/else espliciti. Stesso errore su attackTimer/hurtTimer
   (congelati).

3. **Cooldown di sparo azzerato ogni frame**: una riga
   `e1shot = e1shot + 1 ? 0` (pensata come "tienilo a zero se non
   hai sparato") sovrascriveva sempre e1shot a 0, cancellando il
   cooldown di 80 frame appena impostato - il nemico avrebbe sparato
   ogni singolo frame. Rimossa.

Tutti e tre compilavano senza errori e il gioco girava: si vedono
solo testando il COMPORTAMENTO. Documentati nei tutorial come
esempi concreti, non solo corretti in silenzio.

## Bug trovato dall'utente su Pi: sprite fuori schermo disegnati e mai ripuliti ("scia")

Segnalazione: nemici visibili fuori dall'area di gioco (zona nera),
con una scia visibile mentre si muovevano. La domanda dell'utente
("possiamo star facendo render fuori dall'area visibile che
rallentano il gioco?") era esattamente giusta.

Causa: `iter_visible_sprite_tiles()` controllava solo se uno sprite
era esplicitamente nascosto (Y=0xFFFF), MAI se la sua posizione
calcolata (mondo - scroll) cadesse davvero dentro i 480x320 dello
schermo. Un nemico vaga in coordinate mondo indipendenti dalla
telecamera - quando questa e' lontana (es. scroll vicino al massimo
mentre il nemico e' vicino alla cima della stanza), la sua posizione
SCHERMO puo' finire a centinaia di pixel fuori vista, anche
"negativa" (che con registri senza segno diventa un numero enorme,
es. -348 -> 65188).

Il bug veniva comunque disegnato li' (`screen.blit(surf, (x,y))`
non fa controlli). Nel percorso veloce di IncrementalRenderer, il
frame SUCCESSIVO prova a ripristinare lo sfondo in quella posizione
con `area=r` da `bg_surface` - che e' grande ESATTAMENTE 480x320: se
l'area richiesta e' fuori da quei limiti, non esiste alcun pixel
sorgente li', quindi il ripristino non cancella nulla. Lo sprite
vecchio restava visibile - la "scia" ad ogni frame di movimento.

Corretto: `iter_visible_sprite_tiles()` ora scarta un sotto-tile la
cui area 32x32 non intersechi affatto [0,480)x[0,320), non solo
quelli col sentinel di Y. Stesso identico effetto visivo finale
(erano comunque invisibili), ma senza sprecare un blit ne' generare
un dirty-rect fantasma da (tentare di, fallendo) ripristinare - la
domanda dell'utente su un possibile impatto prestazionale era
fondata: ogni nemico/pietra/fuoco fuori vista veniva comunque
processato ad ogni frame.

5 nuovi test in test_ppu.py, incluso lo scenario ESATTO segnalato
(nemico con scroll estremo, coordinate che si avvolgono per
underflow) - verificato anche end-to-end con un mock di pygame: zero
blit fuori dai limiti schermo, zero dirty-rect fantasma nella lista
da ripristinare.

## Nota sulla posizione "in alto a sinistra" con area nera intorno

Ragionamento (non ancora verificabile da qui, serve conferma
sull'hardware vero): la correzione precedente
(`SDL_VIDEO_WINDOW_POS=center`) probabilmente NON si applica sotto
KMSDRM - quella variabile centra una FINESTRA gestita da un window
manager, ma KMSDRM e' rendering diretto al framebuffer, senza
finestre ne' window manager. Se lo schermo fisico ha una risoluzione
nativa piu' grande dei 480x320 della nostra superficie, KMSDRM la
piazza semplicemente a un'origine fissa (tipicamente (0,0), angolo
alto-sinistra) dentro quella risoluzione piu' grande, lasciando il
resto del framebuffer nero - esattamente il sintomo descritto.

`--fullscreen` (gia' presente, `pygame.FULLSCREEN | pygame.SCALED`)
dovrebbe risolvere questo caso specifico: SDL scala e centra il
contenuto nella risoluzione nativa reale, gestendo la differenza di
dimensione internamente - a differenza di SDL_VIDEO_WINDOW_POS,
questo meccanismo non dipende da un window manager. Non ancora
confermato sull'hardware reale.

## Bug corretto: flickering degli sprite durante lo scroll

Segnalato dall'utente dopo il fix del blob_cache (che ha portato lo
scroll da 8 a 12fps). Causa: durante un frame di scroll, il codice
faceva un `pygame.display.flip()` completo con SOLO lo sfondo (gli
sprite venivano disegnati DOPO, nel codice), poi un SECONDO
`pygame.display.update()` separato per aggiungere lo sprite sopra -
due presentazioni a schermo distinte nello stesso frame. Per un
istante lo schermo mostrava lo sfondo SENZA il giocatore - il
flickering. Da fermi non capitava (un solo `update()`, mai un flip
separato per lo sfondo).

Corretto: quando lo sfondo cambia (scroll o cambio stanza), gli
sprite si disegnano SOPRA il nuovo sfondo PRIMA di presentarlo -
un'unica chiamata `flip()` che include gia' tutto. Verificato con un
test mirato (mock di pygame, non solo lettura del codice) che conta
le chiamate reali a `flip()`/`update()`: rebuild completo -> 1 flip,
0 update separati; fermo -> 0 flip, 1 update piccolo; in scroll -> 1
flip, 0 update separati - mai piu' le due presentazioni distinte che
causavano il flicker.

## Nota aperta: costo di flip() ancora alto (~37ms)

Dal dettaglio scroll fornito dall'utente dopo il fix del blob_cache:
`strip_compute` sceso da 57ms a 3.6ms (~16x, come previsto), ma
`flip()` resta a ~37ms - ora la voce dominante (80% del costo dello
scroll). Questo e' probabilmente un limite del driver KMSDRM in
modalita' software su questo hardware (nessuna accelerazione grafica
confermata) - copiare l'intero framebuffer a schermo ha un costo
fisso che il nostro codice non calcola, solo presenta. Non ancora
esplorato: profondita' colore piu' bassa (RGB565 invece di RGB888,
meta' dei byte da spostare), o se il costo e' dominato da un'attesa
vsync. Discusso ma non implementato - serve capire se vale la pena
prima di investirci tempo, dato che potrebbe essere un limite
hardware non aggirabile via software.

## Blob dei tile: cache PERSISTENTE tra i frame (il vero costo dominante durante lo scroll)

Con l'aiuto dell'utente (misura dettagliata --stats con il
tracciamento aggiunto): durante lo scroll, il costo dominante NON
era il calcolo in se' ne' il blit/flip - era `strip_compute` da
solo, **57ms su 100ms totali**. Causa: `render_background_window()`
creava un blob_cache LOCALE (dict vuoto) ad OGNI chiamata - anche
richiedendo solo 2 righe di un tile, la funzione ricostruiva l'INTERO
blob del tile (1024 pixel, decodifica colore inclusa) da zero, ogni
singolo frame, perche' la cache non sopravviveva tra una chiamata e
la successiva.

Corretto: `render_background()` e `render_background_window()`
accettano ora un `blob_cache` OPZIONALE - se il chiamante ne passa
uno persistente (mantenuto tra i frame), un tile viene decodificato
UNA VOLTA SOLA per l'intera durata di uno stage, non ad ogni frame di
scroll. `IncrementalRenderer` (e anche il percorso 'buffer' e
`run_benchmark`, stesso principio) ora mantengono questa cache come
attributo persistente, invalidata solo al cambio stanza (insieme a
`sprite_tile_cache`, stesso schema gia' visto).

Verificato con un test dedicato che conta le chiamate reali a
`decode_tile()`: senza cache condivisa, chiamata ad ogni invocazione;
con cache condivisa, **esattamente 1 volta** su 5 chiamate ripetute.
MISURATO su macchina di sviluppo: 0.64ms -> 0.037ms per il calcolo
della striscia, ~17x. Non ancora confermato quanto scende il numero
assoluto sulla Pi 1 (57ms), ma il principio (evitare di rifare un
lavoro che non cambia) e' lo stesso che ha gia' funzionato per le
altre cache di questo progetto.

## Ripetizione automatica se il tasto resta tenuto (cambio richiesta)

L'utente ha cambiato idea rispetto alla richiesta precedente: tenere
premuto ora deve far PROSEGUIRE il movimento tile dopo tile
(cammino continuo), non fermarsi dopo il primo. Semplificazione
gradita: non serve piu' il trucco XOR/AND "appena premuto" - quando
il giocatore e' fermo (moving=0), l'input ATTUALE (non piu' un
edge-trigger) decide il prossimo target. Se il tasto resta tenuto,
appena un tile finisce il successivo riparte subito nella stessa
direzione; se viene rilasciato PRIMA che il tile finisca, quel tile
si completa comunque (mai un'interruzione a meta') e il giocatore si
ferma li', allineato. L'operatore XOR resta comunque disponibile nel
linguaggio (utile in generale), solo non piu' usato in questa demo.

## Scroll incrementale (sposta il gia' disegnato, calcola solo la striscia nuova) - NON ANCORA VERIFICATO

Diagnosi (con l'aiuto dell'utente, driver KMSDRM confermato attivo
con HDMI collegato - "offscreen" era solo l'assenza di HDMI durante
SSH): il movimento fluido (sopra) fa si' che lo scroll cambi quasi
OGNI FRAME durante uno scivolamento (~16 frame per tile), non piu'
una volta per pressione come nel primo tentativo di movimento a
griglia. La cache "sfondo fermo" si invalida quindi 16 volte piu'
spesso - da qui il calo progressivo osservato (62->33->29->27->14->4
fps durante il movimento).

QUESTO NON E' UN PROBLEMA DI QUALE API DI RENDERING (SDL2 accelerato
o software) - anche un renderer piu' sofisticato dovrebbe comunque
ridisegnare tutto lo schermo ogni frame durante lo scroll, A MENO
CHE non faccia la stessa cosa qui implementata.

`render_background()` e' stata generalizzata in
`render_background_window()` (finestra Y opzionale - render_background()
e' ora il caso speciale "finestra = tutto lo schermo", stesso
comportamento esatto, 36 test PPU invariati + 4 nuovi per la finestra).
`IncrementalRenderer` ora rileva quando lo scroll cambia di poco in
verticale (caso reale: 2px/frame) e invece di ricalcolare l'intero
sfondo: sposta il contenuto GIA' DISEGNATO con `pygame.Surface.scroll()`
(operazione a livello C) e calcola SOLO la striscia di pixel nuova
che entra in vista (2px alti, non 320). Un salto grande o uno scroll
orizzontale fa comunque un rebuild completo (fallback sicuro).

MISURATO su macchina di sviluppo: il calcolo della sola striscia
costa ~4x meno del render completo (1.88ms -> 0.47ms per una striscia
di 2px) - il guadagno REALE su Pi 1 non e' ancora confermato (stesso
limite di sempre: pygame non installabile nel sandbox di sviluppo).

## Movimento FLUIDO a tile (corretto rispetto al salto istantaneo)

Il primo tentativo di "movimento a griglia" (turno precedente) faceva
un salto istantaneo di 32px in un frame - segnalato dall'utente come
sbagliato: doveva muoversi FLUIDAMENTE alla stessa velocita' di
prima (2px/frame), fermandosi esattamente al tile di arrivo, non
proseguendo se il tasto resta tenuto. Implementato con uno stato
"moving" + "target" (X,Y): un tasto appena premuto imposta un target
un tile di distanza, poi OGNI FRAME successivo (tasto premuto o no)
il giocatore avanza di 2px verso quel target finche' non lo
raggiunge esattamente.

BUG TROVATO TESTANDO: il tracciamento "appena premuto" (XOR/AND, vedi
sopra) era dentro il ramo "non mi sto gia' muovendo" - durante i ~15
frame di un movimento, `previous_input` non si aggiornava, restando
al valore del frame della pressione originale. Una pressione
successiva dello STESSO tasto, dopo un movimento completato, veniva
letta come "gia' tenuto" invece che "appena premuto" (perche' il
confronto usava uno stato vecchio) - il movimento successivo non
partiva. Corretto spostando il tracciamento input FUORI dal
controllo "moving", cosi' si aggiorna ogni frame incondizionatamente.

## Scale: confronto ESATTO invece di un margine (risolve l'offset)

Con il movimento ora sempre allineato alla griglia (multipli di 32),
non serve piu' un margine "vicino alle scale" - il giocatore o e'
ESATTAMENTE sul tile delle scale o non lo e'. Sostituito il confronto
a soglia (es. `CMP #696 / JLT`) con un confronto esatto su entrambi
gli assi. Le posizioni di arrivo dopo una transizione sono ora
allineate alla griglia e ADIACENTI (un tile di distanza) alle scale
di ritorno, non piu' numeri arbitrari (100/660 -> 64/672) - risolve
sia il disallineamento visivo sia il rischio di ri-attivazione
immediata.

NOTA (ConsoleLang): la versione ConsoleLang ha un ritardo di 1 frame
rispetto all'assembly nel primo passo di ogni movimento (l'if/else
tra "imposta nuovo target" e "avanza verso il target" sono rami
mutuamente esclusivi, mentre in assembly il codice "cade" dall'uno
nell'altro nello stesso frame). Il risultato FINALE (posizioni,
soglie, numero di tile) e' identico tra le due lingue - solo il
timing esatto del primo passo differisce di un frame. Lasciato cosi'
com'e' (documentato) invece di complicare la struttura solo per
eliminare una differenza cosmetica.

## Movimento a griglia (1 tile per pressione) + operatore XOR

Prima ogni frame con un tasto direzione TENUTO muoveva il giocatore
di 2px - tenendolo premuto, movimento continuo. Ora un tasto muove
di un tile INTERO (32px) solo quando viene PREMUTO, non ad ogni
frame in cui resta tenuto (altrimenti sarebbe 32px/frame, troppo
veloce). Serve distinguere "appena premuto" da "tenuto" - la CPU non
ha un NOT diretto, ma `appena_premuto = attuale AND (attuale XOR
precedente)` ottiene lo stesso risultato (XOR isola i bit CAMBIATI,
l'AND con l'attuale scarta i bit appena RILASCIATI). Verificato:
tenere premuto 5 frame muove di un tile solo, non 5.

ConsoleLang non aveva l'operatore XOR (^) - solo +/-/&. Aggiunto
apposta per questo (lexer, parser, codegen - 1 test dedicato).

## Soglia scale di ritorno corretta (era troppo permissiva)

Segnalato dall'utente: la transizione di ritorno (stanza 2 -> 1)
scattava "prematura". Causa: soglia Y<96 con le scale a Y=32-64 - un
margine di quasi 32px, molto piu' largo delle 8px della soglia
discesa (Y>=696, scale a Y=704). Corretto a Y<72 (8px di margine,
ora simmetrico). Con movimento a griglia, la vicinanza tra passo
(32px) e soglia (8px) fa si' che basti UNA pressione per attivarla
dalla posizione di arrivo (100) - verificato.

## Finestra centrata + modalita' fullscreen

Su Raspberry Pi OS Lite (senza window manager) SDL piazzava la
finestra a (0,0), angolo alto-sinistra dello schermo fisico, senza
scalarla - segnalato dall'utente. Corretto: `SDL_VIDEO_WINDOW_POS`
impostato a 'center' prima di `pygame.init()`. Aggiunto anche il
flag `--fullscreen` (usa `pygame.FULLSCREEN | pygame.SCALED`, che
adatta il contenuto allo schermo fisico mantenendo le proporzioni,
con bande nere se necessario) per chi vuole riempire lo schermo
invece di una finestra piccola.

## Scale bidirezionali + palette notte piu' chiara

- **Scale di ritorno**: stanza 2 (notte) ora ha le sue scale vicino
  alla cima, che riportano a stanza 1 - percorso di andata E ritorno,
  non piu' solo unidirezionale. Verificato con 3 giri completi
  (andata-ritorno) senza blocchi.
- **Arrivo FUORI dalle scale**: prima il giocatore riappariva sempre
  a una posizione fissa "in alto" nella stanza di arrivo, che poteva
  sovrapporsi alle scale stesse. Ora arriva a una posizione
  leggermente spostata (dentro la stanza, non sopra al tile scale) -
  ne' si sovrappone visivamente ne' rischia di ri-attivare subito la
  transizione.
- **BUG TROVATO**: le scale renderizzavano NERE in stanza 2 - stesso
  tipo di bug gia' visto con pavimento/muro (indici colore
  dell'indicizzazione automatica non scritti nella palette notte).
  Le scale ora copiano i colori del giorno nella palette notte
  (sono un elemento funzionale, non ambientale - non serve una
  lettura "notturna" per loro).
- **Palette notte schiarita**: il primo tentativo era quasi
  illeggibile (segnalato dall'utente) - i valori RGB sono stati
  alzati sensibilmente pur mantenendo l'atmosfera piu' scura/fredda
  del giorno.

## Bug trovato con l'aiuto dell'utente: cache sprite cancellata inutilmente durante lo scroll

Segnalato dall'utente dopo aver provato lo scroll sulla Pi: framerate
sceso sotto i 10 (fino a 3) durante il movimento, e anche da fermi
solo ~20fps - molto meno dei 56-63fps misurati prima con la scena
statica. Causa: `IncrementalRenderer.sprite_tile_cache` veniva
cancellata ogni volta che la chiave (stage, scroll_x, scroll_y)
cambiava - ma i tile degli SPRITE non dipendono dallo scroll, solo
dallo stage (la loro cache andrebbe invalidata solo se cambia
stanza). Risultato: durante OGNI frame di movimento, ricostruivamo
da zero le Surface degli sprite (il lavoro pixel-per-pixel che
l'intero IncrementalRenderer esiste per evitare), oltre al costo
fisiologico del ridisegno completo dello sfondo. Corretto separando
le due chiavi di invalidazione (`sprite_stage_key` per gli sprite,
`bg_key` per lo sfondo). NON ANCORA RIMISURATO sulla Pi 1 - serve un
nuovo test, isolando esplicitamente "fermo del tutto" (nessun tasto
premuto) da "in movimento attivo", per capire quanto ha aiutato.

## Scroll verticale vero + porte SCROLL_X/SCROLL_Y

Aggiunte PORT_SCROLL_X (0x042002) e PORT_SCROLL_Y (0x042003) in
cpu.py - stesso schema di STAGE_SELECT ma senza copia, solo
memorizzano il valore in cpu.scroll_x/cpu.scroll_y. Tutti e 3 i
percorsi di rendering (buffer, SurfaceRenderer, IncrementalRenderer)
ora leggono lo scroll e lo includono nella chiave di cache (prima
era solo lo stage). Aggiunto `set_scroll(x, y)` a ConsoleLang, stesso
schema di `select_stage`.

CONSEGUENZA SULLE PRESTAZIONI (attesa, non un difetto): mentre la
telecamera si muove, la porzione di mappa visibile cambia DAVVERO
ogni frame - la cache (che aveva dato l'enorme guadagno visto sopra)
non puo' aiutare in quei frame, si ricalcola tutto come prima dello
scroll. Da fermi, la cache torna a funzionare normalmente. Non
ancora misurato quanto pesa questo sulla Pi 1 durante il movimento
attivo.

BUG TROVATO E CORRETTO: `playerY - 160` (per centrare la telecamera)
va in UNDERFLOW quando il giocatore e' vicino alla cima della stanza
- i registri sono SENZA SEGNO, una sottrazione che andrebbe negativa
si avvolge a un numero enorme, che poi CLAMPY scambia per "sopra il
massimo" invece che "sotto lo zero". Risolto con un controllo
esplicito PRIMA di sottrarre (`if playerY<160: scroll=0 else:
scroll=playerY-160`), sia in assembly che in ConsoleLang.

## Cartuccia demo aggiornata: cuori (HUD), scale, stanza notturna

- **3 cuori** (vita) disegnati come SPRITE (OAM), non tile di sfondo
  - restano fissi in coordinate schermo e sopravvivono a
  STAGE_SELECT (che tocca solo la tilemap, mai la OAM) - stesso
  principio di come lo SNES vero spesso usava sprite, non solo un
  layer BG dedicato, per gli elementi HUD (noi non abbiamo piu'
  layer BG, solo un tilemap + OAM)
- **Stanza alta 768px** (24 tile, ROOM_TILES_H in graphics.py) -
  piu' dei 320px di schermo, richiede scroll verticale vero
- **Scale come TILE di sfondo** (non sprite - scrollano con la
  stanza) vicino al fondo: raggiungerle passa a stage 2
- **Stage 2 = stessa stanza, palette notte** - BUG TROVATO: gli
  indici colore di pavimento/muro nello spritesheet unificato non
  sono prevedibili (1/2/3 come nel vecchio sistema disegnato a mano)
  - l'indicizzazione automatica li assegna in base all'ordine di
  scoperta nell'immagine intera. La palette notte ora li calcola
  dinamicamente da `sheet['tiles'][...]` invece di presumerli.
- Spritesheet esteso a 4x4 (16 tile): aggiunti indice 12 (cuore) e
  13 (scale)

## Novita' di linguaggio

- `poke(indirizzo_letterale, valore)` in ConsoleLang - scrittura
  diretta a un indirizzo di memoria arbitrario, per i casi non ancora
  coperti da `var`/`write_oam` (es. scrivere in VRAM a mano)
- letterali esadecimali (`0x...`) supportati ovunque un numero e'
  atteso in ConsoleLang, non solo decimali

## Mini-OS separato in os_menu.py, griglia di icone, multiplayer dal menu

Richiesta dell'utente: "sistemare l'OS" - tre cose distinte, fatte
tutte e tre insieme.

**1. Separazione vera da launcher.py.** `carts_registry.py` e
`menu_state.py` promettevano gia' nei loro stessi docstring un file
`os_menu.py` dedicato al disegno pygame ("separata da os_menu.py
apposta") - ma quel file non esisteva mai, il disegno (`run_os_menu`)
viveva dentro `launcher.py`. Estratto in `s32/os_menu.py` per davvero.
`launcher.py` resta solo l'ESECUZIONE (`run_direct`/
`_run_pygame_loop`) + due helper nuovi, `start_netcode_host()` e
`start_netcode_client()` (la stessa logica che gia' costruiva
LockstepHost/LockstepClient per i flag CLI, estratta cosi' il menu
puo' riusarla senza duplicarla).

**2. Griglia di icone invece della lista di titoli.** `menu_state.py`:
`MenuState` accetta ora `columns` (default 1, quindi ogni uso storico
a lista verticale resta invariato) - `move_up`/`move_down` avanzano di
`columns` posizioni, nuovi `move_left`/`move_right` di 1. `os_menu.py`
disegna una griglia (`GRID_COLUMNS=4`) invece di un elenco. Icona per
cartuccia: `carts_registry.py` cerca un `icon.png` opzionale
(`ICON_WIDTH_PX x ICON_HEIGHT_PX` = 32x40, convenzione indipendente da
`TILE_SIZE_PX` - questa e' un'icona di MENU, mai caricata in VRAM,
disegnata direttamente da pygame) - assente, `os_menu.py` disegna un
riquadro grigio col titolo sotto, mai un crash.

**3. Locale/Ospita/Unisciti dal menu, non solo da riga di comando.**
Dopo aver scelto una cartuccia, un secondo schermo chiede la modalita'
- "Locale" lancia subito come prima; "Ospita partita"/"Unisciti a
partita" mostrano un piccolo form (porta/numero giocatori, o ip/porta)
con un `TextField` minimale (nuova classe in `os_menu.py`, pura logica
senza pygame - accetta solo caratteri di un set consentito, es. sole
cifre per la porta), poi chiamano gli stessi `start_netcode_host`/
`start_netcode_client` del punto 1.

**Il menu OS ora e' un piccolo automa a stati** (`grid` -> `mode` ->
`host`/`join` -> lancio -> torna a `grid`) invece di uscire subito
dopo una partita. Punto delicato: **ESC dentro la partita torna al
menu, chiudere la FINESTRA chiude tutto** - servivano distinguibili,
prima non lo erano (`_run_pygame_loop` trattava `pygame.QUIT` ed ESC
allo stesso modo). `_run_pygame_loop`/`run_direct` ora ritornano
`True` solo se e' arrivato un vero `pygame.QUIT`, `False` altrimenti
(ESC, fine sequenza `--playtest`) - `os_menu.py` lo usa per decidere
se tornare alla griglia o chiudere il programma. La `MenuState` della
griglia viene creata **una volta sola** fuori dal ciclo di gioco, mai
ricreata tornando dal menu - e' cosi' che l'indice selezionato
sopravvive a una partita giocata ("riprendi da dove eri rimasto",
richiesto esplicitamente).

Testato con lo stesso mock di pygame gia' usato per il test del
netcode in `test_launcher.py` (`sys.modules['pygame']` finto,
`run_direct`/`start_netcode_host` sostituiti con finti che registrano
le chiamate): selezione cartuccia, ESC-in-game vs chiusura-finestra,
persistenza dell'indice tra una partita e l'altra, form "Ospita" con i
valori di default, chiusura della sessione di rete a fine partita.
Nessuna verifica visiva vera (nessun display disponibile in
quest'ambiente) - solo il FLUSSO, non il disegno, esattamente come gia'
sceglie di fare il resto del progetto per il codice che dipende da
pygame.

## Profilo giocatore (nickname + avatar), richiesto dall'utente

Richiesta: un'icona avatar in alto a destra nel menu OS, da cui
scegliere un avatar (4 icone retro 16x16, colori diversi) e un
nickname - mostrati come identita' dell'host a chi cerca partite.

**`s32/avatars/avatar_0.png`..`avatar_3.png`**: 4 "blob" pixel-art
16x16 generati (rosso/blu/verde/giallo - bordo scuro, due occhi, una
bocca), stessa tecnica gia' usata per `font_spritesheet.png`
(script Pillow one-off, non nel repo - solo l'output).

**`s32/player_profile.py`** (nuovo modulo): `load_profile()`/
`save_profile(nickname, avatar)`, persistiti in
`player_profile.json` accanto al modulo - stato PERSONALE della
macchina, non del progetto (in `.gitignore`, mai committato). Pura
logica, nessuna dipendenza da pygame, sanifica sempre l'input
(nickname vuoto/troppo lungo, avatar fuori range) - non e' mai
possibile ritrovarsi con un profilo non valido, nemmeno con un file
corrotto a mano.

**ATTENZIONE ALLA COLLISIONE DI NOME**: il modulo NON si chiama
`profile.py` di proposito - con quel nome collide con il modulo
della libreria standard di Python `profile` (usato internamente da
`cProfile`, quindi da `--profile`/`run_benchmark(profile=True)`) -
scritto per errore la prima volta, `import profile` dentro
`cProfile.py` prendeva il MIO file invece dello stdlib, rompendo
`--profile` con un `AttributeError` oscuro (`module 'profile' has no
attribute 'run'`). Trovato subito eseguendo la suite di test
completa dopo la prima stesura, prima di procedere oltre.

**`netcode_lockstep.py`**: `LanAnnouncer`/`LanBrowser` ora
scambiano anche un campo `avatar` nell'annuncio broadcast (oltre a
`name`/`port` gia' esistenti) - retrocompatibile (`.get('avatar', 0)`
lato browser, se un host piu' vecchio non lo manda).

**`launcher.py`**: `start_netcode_host(port, num_players,
host_name='S32', avatar=0)` - i due nuovi parametri sono opzionali
con default identici al comportamento precedente (la CLI
`--netplay-host` non ha un profilo, resta 'S32'/0).

**`os_menu.py`**: avatar+nickname disegnati in alto a destra sulla
griglia (tasto **P** per aprire l'editor - SOLO le frecce, non
'wasd', cambiano l'avatar nell'editor: 'a'/'d' sono lettere valide
nel nickname, riusarle come scorciatoia le avrebbe rese impossibili
da digitare). "Ospita partita" passa `profile['nickname']`/
`['avatar']` a `start_netcode_host`. La schermata "Unisciti a
partita" (lista degli host trovati) disegna l'avatar di ogni host
accanto al nome - `_draw_join_pick_screen`, nuova, sostituisce il
riuso generico di `_draw_list_screen` solo per questa schermata (le
altre liste, es. "Locale/Ospita/Unisciti", non hanno avatar).

40 nuovi test (19 in `test_player_profile.py` - default, save/load,
sanificazione, file corrotto/parziale; 8 in `test_os_menu.py` - flusso
completo apri-profilo/digita/scegli-avatar/salva verificato fino a
`start_netcode_host`, ESC annulla senza salvare). 400 test totali.

## Due crash risolti, segnalati dall'utente in un test reale su due PC

Stesso test (un PC di casa e uno di lavoro) ha fatto emergere, oltre
ai sospetti di rete gia' in `doc_networking.md` (sezione 2bis, non
risolvibili da codice - vedi li' l'ipotesi NAT/port-forwarding
aggiunta per lo scenario "reti diverse"), due crash veri e propri
nel codice, entrambi trovati e corretti.

**Chiudere la finestra durante una partita poteva far crashare
l'app**: alla fine di ogni partita, `os_menu.py` ridimensionava
SEMPRE la finestra per tornare a disegnare il menu
(`pygame.display.set_mode(...)`) PRIMA di controllare se l'utente
aveva invece chiuso la finestra di gioco - chiamare `set_mode()` su
una finestra gia' chiusa dall'utente e' un'operazione su una risorsa
non piu' valida. I 4 punti che lanciano una partita (locale, ospita,
unisciti via scoperta, unisciti manuale) duplicavano ognuno la stessa
logica, quindi lo stesso bug. Accorpati in `_after_match()`
(`os_menu.py`), che controlla la chiusura PRIMA di tutto e in tal
caso chiama solo `pygame.quit()`, mai piu' `set_mode()`; la chiusura
della sessione di rete e' anch'essa li', avvolta in `try/except
OSError` (un socket gia' in errore non deve mai impedire di tornare
al menu o di uscire).

**Un errore di rete a META' PARTITA non veniva mai catturato**: solo
il momento della connessione era gestito - una `OSError` sollevata
DOPO, da `submit_local_input()`/`get_frame_inputs()` durante il game
loop (`launcher.py`), risaliva non gestita fino a far crashare
l'intera applicazione con un traceback grezzo. Scenario molto piu'
frequente giocando tra due reti reali diverse (come nel test
casa/lavoro dell'utente) che sulla stessa LAN. Corretto avvolgendo lo
scambio di input di rete in `_run_pygame_loop` con `try/except
OSError`: trattato come un ESC, si torna al menu invece di chiudere
tutto. Approfittando della modifica, corretto anche un
`clock.tick(60)` mancante sul ramo che salta un frame in attesa
dell'input remoto.

10 nuovi test (8 in `test_os_menu.py` per `_after_match()`; 2 in
`test_launcher.py`, Test 13bis, con una sessione di rete finta che
solleva `OSError` a meta' di una partita vera in playtest). 410 test
totali. Dettagli completi in `doc_networking.md`, sezione 2ter.

## Bug di sincronizzazione risolto: "mi vedo giocatore 1 ma muovo il giocatore 2"

Segnalato dall'utente in un test reale funzionante (guest che trova
l'host e si connette senza problemi): host e guest si vedevano
entrambi come "giocatore 1", ma ognuno muoveva il "giocatore 2"
sullo schermo dell'altro. Non un crash ne' un problema di rete - un
bug di **sincronizzazione della simulazione**, piu' serio di un
semplice scambio di etichette.

Il lockstep deterministico richiede che OGNI istanza scriva lo
STESSO input sulla STESSA porta assoluta (`frame_inputs[i]` e' gia'
l'indice assoluto del giocatore i, uguale ovunque - vedi
`netcode_lockstep.py`). `_run_pygame_loop` in `launcher.py` invece
rimappava il vettore per `local_player_index` prima di passarlo alla
CPU, cosicche' la porta 0 (`input(0)`) riceveva SEMPRE il proprio
input locale su ogni macchina - host e client scrivevano valori
diversi sulla stessa porta, facendo divergere silenziosamente lo
stato della simulazione (mai visibile come un crash o un desync
plateale in questa cartuccia, perche' `barebone_p2p` non fa mai
interagire i giocatori tra loro). Corretto: `input_byte =
frame_inputs[0]`, `extra_inputs = frame_inputs[1:]`, sempre per
indice assoluto, mai per `local_player_index`. Corretto anche il
commento fuorviante in `carts/barebone_p2p/game.py` che documentava
"`input(0)` = il locale su ogni istanza" - la premessa sbagliata
all'origine del bug.

2 nuovi test (`test_launcher.py`, Test 13ter: `CPU.run` monkeypatchato
per verificare che `input_byte`/`extra_inputs` restino identici
indipendentemente da `local_player_index`). 414 test totali. Dettagli
in `doc_networking.md`, sezione 2quater.
