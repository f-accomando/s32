# Tutorial: scrivere un gioco per S32 in ConsoleLang

Stessa guida di `doc_asm.md`, stessi argomenti, stesso ordine — ma
con ConsoleLang, un linguaggio ad alto livello che genera lo stesso
assembly per te. Utile leggerli affiancati: vedrai che ogni pezzo di
ConsoleLang corrisponde a un pattern preciso in assembly, non è
magia.

**Importante da subito**: ConsoleLang non nasconde l'hardware
sottostante, lo *abbrevia*. Se hai già letto `doc_asm.md`, riconoscerai
subito i limiti (niente moltiplicazione, niente indirizzamento
indicizzato) — sono ancora lì, solo espressi con meno righe.

---

## 1. I registri, in ConsoleLang

Non scrivi `LDA`/`STA` direttamente — usi **variabili**:

```
var x = 42          // alloca una cella in WRAM, ci scrive 42
state y = 0          // come var, ma NON si reimposta ogni frame
                     // (utile per la posizione di uno sprite, un
                     // contatore, tutto cio' che deve "ricordare")
```

I registri X e Y restano accessibili come `regx`/`regy` quando ti
serve muovere uno sprite (sezione futura) o passare un valore a
`write_oam`. Il registro FLAG e lo stack restano invisibili — li
gestisce il compilatore da solo (lo vedrai nella sezione sulle
funzioni, quando arriveremo lì).

---

## 2. La memoria: stessa mappa di doc_asm.md

ConsoleLang non introduce una mappa memoria diversa — è la stessa
esatta di `doc_asm.md` sezione 2 (WRAM/VRAM/OAM/CGRAM/Porte). La sola
differenza pratica: le tue `var`/`state` vengono allocate
automaticamente dal compilatore a partire da un indirizzo WRAM
(`0x000200` di default) — non devi sceglierlo tu, a meno che non ti
serva evitare una collisione con qualcos'altro.

---

## 3. Il tuo primo programma

```
var x = 42
halt()
```

Confrontalo con l'equivalente assembly (`doc_asm.md` sezione 3): due
righe invece di tre, e non devi scegliere tu l'indirizzo `0x001000`
— il compilatore lo fa per te. Sotto, genera letteralmente `LDA #42`
seguito da `STA <indirizzo scelto automaticamente>`.

**Le espressioni supportate**: un numero, una variabile, `regx`/
`regy`, `input()`, e un singolo `+`/`-`/`&` tra due di queste cose
(es. `x + 5`, `regx - 2`, `input() & 16`). Niente di più composito
(niente `a + b + c`) — stesso limite dell'assembly (ADD/SUB/AND
leggono solo un letterale o UN indirizzo, non una catena di calcoli).

---

## 4. Le risorse grafiche

**Identico** a `doc_asm.md` sezione 4 — gli asset si disegnano in un
editor di immagini vero (uno spritesheet PNG, una griglia di celle
32×32), caricati con `spritesheet_tool.py` e scritti in VRAM/CGRAM da
`cart.py` lato host, non ConsoleLang. Il linguaggio non ha (ancora)
una sintassi dedicata per costruire grafica — quella resta lavoro
Python, fuori dalla CPU. Vale la pena leggere quella sezione per
intero: copre anche un'insidia reale (l'indicizzazione dei colori
nello spritesheet è automatica, non prevedibile a occhio).

---

## 5. Condizioni e confronti

```
var x = 5
if (x < 10) {
    x = 1
} else {
    x = 2
}
```

`if`/`else` funzionano come ti aspetti. Il confronto `<` è
utilizzabile **solo** dentro `if` o dentro un ternario — non come
valore generico (`var esito = x < 10` dà un errore di compilazione
chiaro, non un risultato sbagliato). Il motivo è lo stesso
dell'assembly: l'hardware sa solo *decidere se saltare* dopo un
confronto, non trasformarlo in un numero 0/1 pulito.

**Il ternario**, per assegnazioni brevi:

```
regy = input() & 1 ? regy - 2         // ":" omesso = "altrimenti invariato"
tile = input() & 16 ? 4 : 3           // ":" esplicito
```

---

## 6. Leggere l'input

```
if (input() & 16) {
    // tasto azione premuto
}
```

Stessi bit di `doc_asm.md` sezione 6 (bit0-3 direzioni, bit4 azione)
— `input()` è semplicemente `IN` sotto mentite spoglie.

---

## 7. poke() — l'uscita di sicurezza verso l'hardware grezzo

ConsoleLang copre bene i casi comuni (variabili, sprite via
`write_oam`), ma a volte serve scrivere in un punto preciso della
memoria che il linguaggio non conosce ancora — es. cancellare del
testo scritto direttamente in VRAM. Per questo esiste `poke`:

```
poke(0x020E10, 0)          // scrive il valore 0 all'indirizzo dato
poke(0x020E12, x + 5)      // il valore puo' essere un'espressione
```

L'indirizzo deve essere un **numero letterale** (0x... o decimale) —
non una variabile, perché la CPU non ha modo di calcolare un
indirizzo a runtime (`STA` accetta solo un indirizzo scritto nel
programma, non uno "puntato" da un registro) — un limite
dell'hardware sotto, non di ConsoleLang: nessuna istruzione assembly
di questa CPU supporta l'indirizzamento indicizzato.

---

## 8. Tutto insieme: la title screen vera

Ecco `carts/adventure_cl/game.py` — stesso identico comportamento di
`carts/adventure_asm/game.asm`, stessi indirizzi VRAM per il testo:

```
state mode = 0

if (mode < 1) {
    if (input() & 16) {
        mode = 1
        poke(0x020E10, 0)
        poke(0x020E12, 0)
        ...                    // 16 poke in tutto, come le 16 STA
                                // della versione assembly
        poke(0x020E2E, 0)
    }
}
halt()
```

**Confronto diretto con la versione assembly**: `state mode = 0`
sostituisce la scelta manuale dell'indirizzo `0x000100`; `mode < 1`
sostituisce `CMP #0` + `JNZ`; l'`if` annidato sostituisce i due salti
condizionali in sequenza. Le 16 `poke` restano 16 righe comunque —
ConsoleLang non ha (ancora) un modo di esprimere un ciclo, per lo
stesso motivo per cui l'assembly non ce l'ha: l'hardware sotto non
supporta l'indirizzamento indicizzato necessario a farlo in modo
compatto.

---

## 9. Lanciarlo

```
python3 s32/launcher.py carts/adventure_cl/game.py
```

Stesso comportamento della versione assembly: premi **J** o
**Spazio**, il testo sparisce.

---

## 10. Caricare uno stage nuovo

```
select_stage(1)
```

Una riga, stesso meccanismo di `doc_asm.md` sezione 9 (la porta
`STAGE_SELECT`): sostituisce l'intera tilemap con quella dello stage
1, preparata da `cart.py` (`build_stages()`) prima ancora che la CPU
parta. Come `poke`, richiede un numero letterale o un'espressione, ma
qui sotto compila direttamente in `STA 0x042001` — non serve
ricordare l'indirizzo della porta, il linguaggio lo fa per te.

---

## 11. Tutto insieme: title screen -> stage vero

`carts/adventure_cl/game.py` aggiornato:

```
state mode = 0

if (mode < 1) {
    if (input() & 16) {
        mode = 1
        select_stage(1)
    }
}
halt()
```

Confrontalo con `doc_asm.md` sezione 10 — stessa struttura,
`select_stage(1)` al posto di `LDA #1 / STA 0x042001`.

---

## 12. Caricare uno sprite (il giocatore)

```
write_oam(slot, x, y, tile, attr)
```

Un'unica istruzione invece di 4 `STA` separate — `write_oam` scrive
tutti e 4 i campi di uno slot OAM in un colpo. Stessi significati di
`doc_asm.md` sezione 11: `slot` è un numero letterale (0-511), `attr`
segue la stessa codifica a bit (bit0-1=dimensione, bit2-4=palette).

```
write_oam(0, 224, 144, 11, 0)   // slot 0, x=224, y=144, tile 11, palette 0
```

**Nascondere uno sprite**: nessuna sintassi dedicata ancora — usa
`write_oam` con una Y alta (`write_oam(0, 0, 0xFFFF, 0, 0)`), oppure
semplicemente non scriverci nulla (ogni slot parte già nascosto di
default, vedi `doc_asm.md` sezione 11).

---

## 13. Il movimento fluido a tile

Come in `doc_asm.md` sezione 12: un tasto non sposta pixel per pixel
finché resta premuto, sposta di **un tile intero (32px)**, ma
**fluidamente** (2px/frame), fermandosi esattamente al tile di
arrivo. Se il tasto resta tenuto, il tile successivo riparte subito.

Serve un `target` oltre alla posizione attuale:

```
state moving = 0
state targetX = 0
state targetY = 0

if (moving < 1) {
    targetX = playerX
    targetY = playerY

    if (input() & 1) {
        targetY = targetY - 32
        moving = 1
    } else {
        if (input() & 2) {
            targetY = targetY + 32
            moving = 1
        } else {
            if (input() & 4) {
                targetX = targetX - 32
                moving = 1
            } else {
                if (input() & 8) {
                    targetX = targetX + 32
                    moving = 1
                }
            }
        }
    }

    regx = targetX
    regy = targetY
    clamp_x(32, 416)
    clamp_y(32, 704)
    targetX = regx
    targetY = regy
} else {
    if (playerX < targetX) {
        playerX = playerX + 2
    } else {
        if (targetX < playerX) {
            playerX = playerX - 2
        }
    }
    if (playerY < targetY) {
        playerY = playerY + 2
    } else {
        if (targetY < playerY) {
            playerY = playerY - 2
        }
    }
    if (playerX < targetX) {
    } else {
        if (targetX < playerX) {
        } else {
            if (playerY < targetY) {
            } else {
                if (targetY < playerY) {
                } else {
                    moving = 0
                }
            }
        }
    }
}
```

Il ramo `if (moving < 1)` legge l'input **attuale** (`input() & 1`,
non un edge-trigger) — se il tasto è ancora premuto quando un tile
finisce, il prossimo parte immediatamente. Il ramo `else` avanza di
2px per asse, poi controlla se **entrambi** gli assi hanno raggiunto
il target (quattro `if` annidati — ConsoleLang ha solo `<`, un test
di uguaglianza è sempre "non minore in un verso, non minore
nell'altro").

**Una versione precedente** distingueva "appena premuto" da "tenuto"
con un trucco XOR (`justPressed = input() ^ prevInput`, poi `& input()`
per tenere solo i bit diventati 1) — utile se un giorno vuoi che
tenere premuto **non** faccia camminare in continuazione. L'operatore
XOR (`^`) resta disponibile nel linguaggio, aggiunto apposta per
questo, anche se questa demo ora non lo usa più.

---

## 14. HUD persistente: sprite invece di tile

Lo SNES vero aveva più layer di sfondo (BG1-4) — spesso uno dedicato
a elementi fissi come la barra vita, che non scrollava con il mondo.
Noi abbiamo un solo tilemap, sostituito interamente da
`select_stage()` a ogni cambio stanza — se disegnassi la vita *nella*
tilemap, sparirebbe cambiando stanza. La soluzione: disegnarla come
**sprite**, indipendente dalla tilemap:

```
write_oam(1, 8, 8, 12, 0)   // cuore 1: SEMPRE x=8,y=8, mai lo scroll
write_oam(2, 44, 8, 12, 0)
write_oam(3, 80, 8, 12, 0)
```

Ridisegnati ogni frame in coordinate **schermo fisse** — a
differenza del giocatore (sezione 16), non vanno mai convertiti da
coordinate mondo.

---

## 15. Un tile che fa da interruttore

Le scale sono un **tile di sfondo** (non uno sprite) — scrollano
insieme alla stanza. Con il movimento sempre allineato alla griglia,
il controllo è un confronto **ESATTO**, non un margine:

```
if (room < 2) {
    if (playerX < 224) {
    } else {
        if (224 < playerX) {
        } else {
            if (playerY < 704) {
            } else {
                if (704 < playerY) {
                } else {
                    room = 2
                    select_stage(2)
                    playerX = 224
                    playerY = 64
                    moving = 0
                    ...
                }
            }
        }
    }
}
```

I quattro `if` annidati (`playerX < 224` / `224 < playerX`) insieme
testano "playerX è esattamente 224?" — lo stesso pattern usato per
il target (sezione 13), qui applicato alla posizione delle scale.
Blocchi vuoti (`{ }`) non sono un errore: significano "questa
condizione non è soddisfatta, non fare nulla, prosegui dopo l'intero
blocco".

**Un bug che ho fatto scrivendo questa demo**: usare `halt()` al
posto di un blocco vuoto pensando "salta questo controllo" — ma
`halt()` ferma l'**intero frame**, impedendo di raggiungere il
disegno degli sprite più sotto. L'unico modo di "saltare" un blocco
in ConsoleLang è strutturare l'`if/else` perché il codice dopo si
raggiunga comunque.

**Arrivo fuori dalle scale**: la transizione porta il giocatore a un
tile di distanza dalle scale dell'altra stanza, mai sopra di esse -
allineato alla griglia, niente sovrapposizioni né retrigger immediati.

---

## 16. Lo scroll: la telecamera che segue il giocatore

```
if (playerY < 160) {
    regy = 0
} else {
    regy = playerY - 160
}
clamp_y(0, 448)
scrollY = regy
set_scroll(0, scrollY)
```

`set_scroll(x, y)` scrive alle porte SCROLL_X/SCROLL_Y (stesso
meccanismo di `select_stage`, vedi `doc_asm.md` sezione 15).

Poi la posizione a schermo (per `write_oam`) si ottiene sottraendo
lo scroll da quella nel mondo:

```
regy = playerY - scrollY
regx = playerX
write_oam(0, regx, regy, 11, 0)
```

---

## 17. Attenzione ai registri senza segno

`if (playerY < 160) { regy = 0 } else { regy = playerY - 160 }` non
è verboso per caso: `playerY - 160` da solo andrebbe in **underflow**
quando `playerY` è minore di 160 - i registri sono senza segno, un
risultato "negativo" si avvolge a un numero enorme, e `clamp_y` lo
scambierebbe per "sopra il massimo" invece che "sotto lo zero".
Stesso bug, stessa soluzione, di `doc_asm.md` sezione 16.

---

## 18. L'attacco e lo slash

Come in `doc_asm.md` sezione 17: premere **J** avvia un timer di 10
frame, non un evento istantaneo. Stesso edge-detector delle
direzioni (sezione 13), applicato a J:

```
if (input() & 16) {
    if (prevJ < 1) {
        if (attackTimer < 1) {
            attackTimer = 10
        }
    }
    prevJ = 1
} else {
    prevJ = 0
}
```

**Bug trovato testando**: `prevJ` deve partire a `1` (non `0`)
quando il gioco inizia — altrimenti lo stesso J che hai premuto per
*avviare* il gioco fa scattare anche un attacco nello stesso frame,
prima ancora che tu abbia lasciato il tasto. `prevJ = 1`
all'inizializzazione dice "questo J è già stato visto".

La posizione della spada segue la direzione (`direction`, aggiornata
quando parte un movimento):

```
slashWX = playerX
slashWY = playerY
if (direction < 1) {
    slashWY = playerY - 32
} else {
    if (direction < 2) {
        slashWY = playerY + 32
    } else {
        if (direction < 3) {
            slashWX = playerX - 32
        } else {
            slashWX = playerX + 32
        }
    }
}
```

Quattro rami invece di quattro etichette (`SLASH_W_NOT_UP` ecc. in
assembly) — stesso albero decisionale, scritto come annidamento
invece che come salti.

---

## 19. I nemici che vagano

Un generatore pseudo-casuale con un incremento "brutto" (numeri
senza fattori comuni con le dimensioni schermo) e un `&` per
estrarne pochi bit:

```
e1rng = e1rng + 55
if (e1rng & 31) {
} else {
    e1dir = e1rng & 3
}
```

Il blocco vuoto (`{ }`) nel primo ramo è lo stesso pattern già visto
— "se questa condizione (un resto diverso da zero) è vera, non fare
nulla, prosegui oltre l'intero if/else".

Il movimento con rimbalzo ai bordi è quattro rami `if`/`else if`
annidati (uno per direzione), ciascuno che o avanza o inverte
`e1dir` — stessa logica di `doc_asm.md` sezione 18, un ramo in più
di profondità per ogni direzione controllata (ConsoleLang non ha un
`elif`, solo `if`/`else` annidati).

---

## 20. I proiettili: le pietre

Sparo quando il giocatore è sullo stesso asse (X o Y), entro 16px —
lo stesso controllo di distanza "senza `<=`" già visto (sezione 15):

```
if (playerX < e1x) {
    if (e1x - playerX < 16) {
        ...
    }
} else {
    if (playerX - e1x < 16) {
        ...
    }
}
```

Un cooldown (`e1shot`) separato dal timer di movimento impedisce
raffiche continue:

```
if (e1shot < 1) {
    if (s1active < 1) {
        ... controlla allineamento, eventualmente spara ...
    }
} else {
    e1shot = e1shot - 1
}
```

**Bug trovato testando**: la prima versione aveva una riga in più
dopo il blocco di sparo (`e1shot = e1shot + 1 ? 0`) pensata per
"tenerlo a zero se non hai sparato" — ma quel ternario è sempre vero
(`e1shot + 1` non è mai zero), quindi sovrascriveva **sempre**
`e1shot` a 0, cancellando il cooldown di 80 frame appena impostato
dallo sparo. Il nemico avrebbe sparato ogni singolo frame invece che
ogni 80. Rimossa — non serviva: il valore resta quello che la logica
di sparo ha già impostato, non va toccato oltre.

---

## 21. Danno al giocatore e invincibilità

Stesso controllo a distanza dello slash, soglia più larga (20px),
guardia sull'invincibilità:

```
if (s1active < 1) {
} else {
    if (hurtTimer < 1) {
        if (s1x < playerX) {
            if (playerX - s1x < 20) {
                if (s1y < playerY) {
                    if (playerY - s1y < 20) {
                        s1active = 0
                        if (playerHP < 1) {
                        } else {
                            playerHP = playerHP - 1
                        }
                        hurtTimer = 20
                    }
                }
                ...
```

**Lo stesso bug del ternario**, trovato di nuovo: la prima versione
aveva `playerHP = playerHP - 1 ? playerHP` — la condizione
(`playerHP - 1`) è quasi sempre vera, e il ramo "vero" assegna
`playerHP` (il suo stesso valore corrente, invariato) — un
**no-op travestito da decremento**: il giocatore non perdeva mai
vita colpito da una pietra, in nessuno dei due rami del ternario.
Corretto con un `if`/`else` esplicito, come sopra. La lezione: il
ternario di ConsoleLang (`cond ? valore`) ha senso solo quando il
valore nel ramo "vero" è *diverso* dal valore corrente — se stai
scrivendo un decremento condizionato, quasi sempre serve un `if`
vero, non un ternario.

Il lampeggio da ferito è lo stesso trucco a bit di `doc_asm.md`
sezione 20, applicato all'argomento Y di `write_oam`:

```
if (hurtTimer & 2) {
    write_oam(0, 0, 65535, 0, 0)
} else {
    write_oam(0, regx, regy, 11, 0)
}
```

---

## 22. La grata: sconfiggere per aprire

Tre varianti della stessa stanza (`select_stage(1)`, `(2)`, `(3)`) —
`room` stesso codifica se la grata è aperta, nessuna variabile
booleana separata:

```
if (e1timer < 1) {
    e1alive = 0
    killed = killed + 1
} else {
    e1timer = e1timer - 1
}
```

```
if (room < 2) {
    if (killed < 2) {
    } else {
        room = 3
        select_stage(3)
        s1active = 0
        s2active = 0
    }
}
```

Le pietre attive vengono disattivate esplicitamente alla transizione
(`s1active = 0`) — altrimenti una pietra a mezz'aria resterebbe
nello stato "attiva" con una posizione della stanza precedente,
visibile per un frame nella stanza nuova.

---

## 23. Il boss e l'audio

Il **boss** segue esattamente la logica di `doc_asm.md` sezione 22 -
vale la pena leggere quella sezione per il ragionamento, qui solo le
differenze di scrittura.

Uno sprite 64x64 e' un solo `write_oam` con l'ultimo argomento a 1
(l'attributo di dimensione): il PPU compone da solo i 4 tile
consecutivi 20,21,22,23.

```
if (bossY < scrollY) {
    write_oam(9, 0, 65535, 0, 0)
} else {
    regy = bossY - scrollY
    write_oam(9, bossX, regy, 20, 1)
}
```

Il controllo `bossY < scrollY` prima della sottrazione non e'
pignoleria: senza, il boss sparisce quando la telecamera sta piu' in
basso di lui (underflow senza segno, sezione 17 - lo stesso bug e'
stato trovato davvero costruendo questa demo).

Le due fasi si alternano con un `if (bossPhase < 1)`, e il fuoco
rallenta avanzando **di** `fireSpeed` mentre quella cala:

```
fireY = fireY + fireSpeed
...
fireSpeed = fireSpeed - 1
```

13+12+...+1 = 91px, quasi esattamente 3 tile.

### L'audio

Una sola istruzione nuova:

```
play_sound(1)      // 1 = fendente
```

Compila in una scrittura sulla porta `0x042004`, che **accoda**
l'ID: la CPU non produce suono, lo fa il launcher a fine frame (vedi
`doc_asm.md` sezione 23 per l'architettura completa e la tabella
degli otto ID).

L'argomento puo' essere un'espressione, non solo un numero:

```
play_sound(base + 2)
```

L'audio e' attivo di default:

```
python3 s32/launcher.py carts/adventure_cl/game.py
```

`--no-audio` lo disattiva - utile su Raspberry Pi con ALSA mal
configurato (vedi `doc_asm.md` sezione 23 per il motivo).

---

## 24. Il game over

Stessa storia di `doc_asm.md` sezione 24 - qui solo le differenze di
scrittura. Il problema strutturale (la title screen scritta una
volta sola, mai piu' ricaricabile) e la sua soluzione (registrarla
come stage 0) sono identici e non dipendono dal linguaggio - vale la
pena leggerli li'.

Rilevare la morte, PRIMA di ogni altra logica:

```
if (playerHP < 1) {
    mode = 2
    gameOverTimer = 180
    play_sound(9)
    poke(0x020506, 28)
    poke(0x020508, 8)
    poke(0x02050A, 29)
    poke(0x02050C, 3)
    poke(0x02050E, 0)
    poke(0x020510, 7)
    poke(0x020512, 30)
    poke(0x020514, 3)
    poke(0x020516, 2)
    halt()
}
```

`poke()` (sezione 7) e' l'unico modo di scrivere nella tilemap da
ConsoleLang - il linguaggio non ha una sintassi dedicata per il
testo, esattamente come non l'ha per i tile in generale (sezione 4).
Gli indirizzi sono numeri letterali, non variabili - stesso limite
di sempre (`poke` non accetta un indirizzo calcolato a runtime).

Il blocco di gioco e' avvolto in un `if (mode < 2) {} else { ... }`
- lo stesso pattern "condizione vuota, il vero lavoro nell'else" gia'
visto piu' volte. Dentro, il conteggio alla rovescia e il reset:

```
if (gameOverTimer < 1) {
    mode = 0
    select_stage(0)
    halt()
} else {
    gameOverTimer = gameOverTimer - 1
}
write_oam(0, 224, 100, 27, 0)
write_oam(1, 0, 65535, 0, 0)
...
halt()
```

Ogni `write_oam` con Y=65535 nasconde uno sprite - quattordici righe
quasi identiche, una per slot, perche' ConsoleLang non ha un modo di
esprimere "per ogni slot da 1 a 14" (nessun ciclo, sezione 23).

**Lo stesso aggiustamento visivo** di `doc_asm.md`: il teschio era
inizialmente sovrapposto al testo, spostato piu' in alto dopo aver
guardato il risultato renderizzato.

---

## 25. Il programma completo

`carts/adventure_cl/game.py` — la demo completa: title screen,
movimento fluido a griglia con ripetizione, attacco, due nemici che
vagano e sparano, pietre, collisioni, HUD con cuori, scale
bidirezionali, stanza notturna, grata che si apre sconfiggendo i
nemici.

Non lo incolliamo più qui per intero: è cresciuto oltre le 800
righe, e ogni suo pezzo è già stato spiegato nelle sezioni
precedenti. Aprilo direttamente e confrontalo con
`carts/adventure_asm/game.asm` riga per riga — è la cosa più utile
che puoi fare a questo punto, e la ragione per cui i due file sono
tenuti deliberatamente allineati.

Una nota su cosa aspettarsi leggendolo: la **maggior parte** della
lunghezza sono i blocchi ripetuti quasi identici per nemico 1 /
nemico 2 e pietra 1 / pietra 2. ConsoleLang non ha ancora array né
funzioni con parametri, quindi due entità dello stesso tipo si
scrivono davvero due volte — è un limite reale del linguaggio, non
una scelta stilistica, e si vede.

```
python3 s32/launcher.py carts/adventure_cl/game.py
```

Frecce per muoverti (tenute premute per camminare senza
interruzioni), **J** per attaccare o per iniziare dalla title
screen.

---

## Fine di questo tutorial

Confronta questo file con `doc_asm.md` dall'inizio alla fine —
stesso comportamento finale, ma ConsoleLang toglie la gestione
manuale dei trasferimenti tra registri e degli indirizzi di porta.
Non toglie i LIMITI dell'hardware sotto (niente moltiplicazione,
niente indirizzamento indicizzato, niente confronto come valore
generico, niente "E" logico diretto - un'uguaglianza si scrive come
due `<` annidati) - quelli restano, il linguaggio li eredita
fedelmente. E ne aggiunge di suoi: niente array né funzioni con
parametri, quindi due nemici dello stesso tipo si scrivono
letteralmente due volte (sezione 23).

Una trappola specifica del linguaggio, incontrata due volte
costruendo questa demo (sezioni 20 e 21): il ternario
`nome = cond ? valore` mantiene il valore CORRENTE quando la
condizione è falsa - scriverci `x = x - 1 ? x` sembra un decremento
condizionato ma è un no-op in entrambi i rami. Per decrementare
davvero serve un `if`/`else` esplicito. Entrambe le volte il codice
compilava senza errori e il gioco girava: il bug si è visto solo
testando il comportamento (una vita che non scendeva mai, un
cooldown che non tratteneva nulla), non leggendo il sorgente.

Da qui, il resto è applicare questi stessi pezzi a idee nuove: più
nemici, un oggetto da raccogliere, scroll orizzontale.
