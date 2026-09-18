# Tutorial: scrivere un gioco per S32 in assembly

Questa guida parte da zero e arriva alla title screen vera che
abbiamo in `carts/adventure_asm/`. Ogni concetto è seguito da codice
che gira davvero — non c'è teoria senza un esempio eseguibile.

Se preferisci ConsoleLang (un linguaggio ad alto livello che genera
lo stesso assembly per te), vedi `doc_cl.md` — copre gli stessi
argomenti, stesso ordine, così puoi confrontare.

---

## 1. I registri

La CPU di S32 ha tre registri di lavoro, tutti a **16 bit** (valori
0-65535):

- **A** (accumulatore) — dove succede la maggior parte del lavoro:
  quasi ogni istruzione o legge da A o scrive in A
- **X**, **Y** — due registri "indice", usati tipicamente per
  coordinate (X per la posizione orizzontale, Y per la verticale —
  è una convenzione nostra, non un obbligo dell'hardware)

Più un **registro FLAG** invisibile (4 bit: Zero, Negative, Carry,
Overflow), aggiornato automaticamente da molte istruzioni e letto
dai salti condizionali (`JZ`, `JLT`, ecc. — sezione 5).

E uno **stack hardware** — una pila di valori in memoria, usata per
`JSR`/`RTS` (chiamate a subroutine) e per `PHA`/`PLA` (salvare un
valore temporaneamente). Ne riparliamo quando arriveremo alle
subroutine.

---

## 2. La memoria: un unico spazio, diviso per convenzione

Non esistono "RAM", "VRAM", "OAM" come cose separate — è **tutto
lo stesso spazio di memoria**, indirizzabile con numeri da
`0x000000` a `0xFFFFFF` (16 milioni di indirizzi). La CPU non sa
nulla di questa divisione: per lei, scrivere in un punto o in un
altro è sempre la stessa istruzione (`STA indirizzo`). La divisione
è solo una convenzione che noi rispettiamo e che la PPU (il chip
grafico) interpreta a modo suo.

Le zone:

| Zona | Indirizzi | Cosa contiene |
|---|---|---|
| WRAM | `0x000000` - `0x01FFFF` | Variabili del programma, stack |
| VRAM | `0x020000` - `0x03FFFF` | Tilemap + tile grafici (sezione 4) |
| OAM | `0x040000` - `0x040FFF` | Sprite (512 slot da 8 byte) |
| CGRAM | `0x041000` - `0x041FFF` | Colori (8 palette da 256 colori) |
| Porte | `0x042000` - `0x0420FF` | Input e altri segnali di sistema |

**Un dettaglio che conta**: ogni "cella" di memoria contiene un
valore a **16 bit**, non 8 — quindi occupa **2 byte consecutivi**
(il primo byte basso, il secondo alto — convenzione "little-endian",
la stessa dell'hardware reale). Questo significa che se scrivi a
`0x020E10` e poi vuoi scrivere il valore *successivo* nella riga
della tilemap, il prossimo indirizzo è `0x020E12`, non `0x020E11` —
lo vedrai tra poco nell'esempio della title screen.

---

## 3. Il tuo primo programma

Un file `.asm` è testo semplice: un'istruzione per riga, `;` per i
commenti, `NOME:` per le etichette. Ecco il programma più corto
possibile:

```asm
LDA #42
STA 0x001000
HALT
```

- `LDA #42` — carica il numero 42 (letterale, per questo il `#`)
  nell'accumulatore A
- `STA 0x001000` — salva A nella cella di memoria `0x001000`
  (dentro la WRAM, lontano da altre cose)
- `HALT` — ferma l'esecuzione per questo frame (il programma gira
  di nuovo dall'inizio al frame successivo — non c'è un "avanti" tra
  un frame e l'altro se non quello che hai scritto in memoria)

**Le due modalità di ogni istruzione che legge un valore**: con `#`
è un numero letterale scritto direttamente nel programma (`LDA
#42`); senza `#` è un indirizzo di memoria da cui leggere (`LDA
0x001000` legge quello che c'è là dentro, qualunque cosa sia).
Questo vale per `LDA`/`ADD`/`SUB`/`AND`/`OR`/`XOR`/`CMP`.

---

## 4. Le risorse grafiche: dallo spritesheet PNG alla VRAM

**Un tile** è un quadratino 32×32 pixel. A differenza di molte console
storiche, qui **un pixel è un byte intero** (valore 0-255): il byte
è l'indice del colore da usare, letto dalla palette. L'indice `0` è
sempre "trasparente" (per lo sfondo: mostra il nero; per uno sprite:
lascia vedere quello che c'è sotto) — **deve** finire in cima allo
spritesheet o comunque essere il primo colore incontrato, altrimenti
ogni cella non disegnata esplicitamente nella tilemap mostrerebbe un
tile a caso invece di restare vuota (un bug reale che abbiamo trovato
così, con l'intero schermo pieno di una lettera ripetuta).

**La tilemap** è una griglia enorme (128×128 tile — molto più grande
dello schermo visibile, 15×10) che dice, per ogni posizione, *quale*
tile disegnare. Ogni cella della tilemap è **2 byte**: 12 bit per
l'indice del tile (quale disegno), 3 bit per la palette (quale set
di colori usare — sì, ogni singolo tile può avere una palette
diversa dagli altri, lo sfrutteremo per la stanza notturna più
avanti).

**La palette (CGRAM)**: ogni colore è 2 byte in formato RGB555 (5
bit per canale rosso/verde/blu). Ci sono 8 palette, 256 colori
ciascuna.

### Non disegni i tile in Python — li disegni in un editor di immagini

Le prime versioni di questo motore costruivano i tile come stringhe
ASCII ("griglie di cifre") scritte a mano in Python — pratico per un
font a blocchi, impossibile per qualunque cosa più ricca. Il flusso
vero: **uno spritesheet PNG**, una griglia di celle 32×32, disegnato
in un editor qualunque (anche Paint va bene). `spritesheet_tool.py`
lo carica:

```python
from spritesheet_tool import load_spritesheet

sheet = load_spritesheet("adventure_spritesheet.png", tile_size=32)
# sheet['tiles']   -> lista di byte, uno per tile (indice colore diretto)
# sheet['palette']  -> lista di (r,g,b), i colori trovati nell'immagine
# sheet['cols'], sheet['rows'] -> dimensioni della griglia
```

La griglia si legge riga per riga, da sinistra: la cella in alto a
sinistra è il tile indice 0, quella alla sua destra l'indice 1, e
così via. `carts/_shared/adventure_spritesheet.png` è una griglia
4×4 (16 tile): lettere del font, pavimento, muro, il cerchio del
giocatore, un cuore, delle scale — vedi il file `graphics.py` accanto
per la mappa completa indice→disegno.

### L'indicizzazione dei colori è AUTOMATICA — e non sempre quella che ti aspetti

`load_spritesheet` scandisce l'immagine e assegna un indice a ogni
colore RGB distinto **nell'ordine in cui lo incontra**, dall'angolo
in alto a sinistra. Questo ha un'implicazione non ovvia: se disegni
il pavimento a metà dello spritesheet, il suo indice colore **non è
1, 2 o 3** come potresti aspettarti — è qualunque numero tocchi in
base a cosa c'è *prima* di lui nell'immagine (lettere del font,
tipicamente). Abbiamo scoperto questo bug costruendo la palette
"notte" della stanza: avevamo scritto colori scuri agli indici 1/2/3
pensando fossero pavimento/muro — non lo erano, e il risultato era
uno schermo quasi tutto nero. La correzione:

```python
sheet = _sheet()
floor_indices = sorted(set(sheet['tiles'][STAGE_FLOOR_IDX]) - {0})
wall_indices = sorted(set(sheet['tiles'][STAGE_WALL_IDX]) - {0})
```

cioè: non presumere l'indice, **leggilo dal tile stesso** dopo averlo
caricato.

### Scrivere i tile e la palette in memoria

```python
from spritesheet_tool import write_tiles_to_vram, write_palette_to_cgram
from memory_map import TILE_GRAPHICS_VRAM_OFFSET, TILE_BYTES

write_tiles_to_vram(vram, TILE_GRAPHICS_VRAM_OFFSET, TILE_BYTES,
                     start_index=0, tiles=sheet['tiles'])
write_palette_to_cgram(cgram, palette_index=0, palette=sheet['palette'])
```

Questo è lavoro "da host" (Python, eseguito da `cart.py` prima
ancora che la CPU parta — vedi `carts/adventure_asm/cart.py` per
l'esempio completo), non qualcosa che la CPU calcola — esattamente
come una cartuccia vera arriva già con la sua grafica pronta.

---

## 5. I salti e il confronto

Per far fare qualcosa di diverso al programma a seconda delle
condizioni, servono `CMP` (confronta, senza modificare A) e un
salto condizionale:

```asm
LDA 0x001000     ; carica un valore
CMP #10          ; confrontalo con 10 (A resta INVARIATO dopo CMP)
JLT MINORE       ; salta a MINORE se il valore era < 10
LDA #999
HALT
MINORE:
LDA #1
HALT
```

I salti condizionali disponibili: `JZ`/`JNZ` (zero/non-zero), `JLT`/
`JGE` (minore/maggiore-o-uguale, basati sul segno dopo un `CMP` o
un calcolo), `JCS`/`JCC` (basati sul riporto — utile per confronti
senza segno). `JMP` è incondizionato. Le etichette (`MINORE:`)
possono stare *prima o dopo* il salto che le usa — l'assemblatore
le risolve in un secondo passaggio.

---

## 6. Leggere l'input

Una singola istruzione, `IN`, mette lo stato attuale dei tasti in A
— un bit per tasto:

```
bit0 = su       bit1 = giù      bit2 = sinistra   bit3 = destra
bit4 = azione (J / Spazio)
```

Per controllare un tasto specifico, isoli il suo bit con `AND`:

```asm
IN
AND #16          ; isola il bit4 (azione)
CMP #0
JZ NON_PREMUTO
; qui dentro: il tasto azione ERA premuto
```

---

## 7. Tutto insieme: la title screen vera

Ecco `carts/adventure_asm/game.asm`, riga per riga. Il gioco parte
in "modalità 0" (title screen visibile, testo già scritto da
`cart.py`), e passa a "modalità 1" quando premi il tasto azione:

```asm
LDA 0x000100      ; mem[0x000100] = la nostra "modalita' attuale"
CMP #0
JNZ GIA_AVVIATO   ; se non e' 0, siamo gia' avviati: non rifare nulla

IN
AND #16           ; il tasto azione e' premuto?
CMP #0
JZ FINE_FRAME     ; no: non fare nulla questo frame

; --- si', e' stato premuto: passa a modalita' 1 ---
LDA #1
STA 0x000100

; --- cancella il testo, 16 tile "spazio" (indice 0) in sequenza ---
LDA #0
STA 0x020E10
STA 0x020E12
...               ; (16 scritture in tutto, 2 byte di distanza l'una
                   ; dall'altra - vedi sezione 2 sul perche')
STA 0x020E2E

FINE_FRAME:
HALT

GIA_AVVIATO:
HALT
```

**Perché 16 scritture separate e non un ciclo?** La nostra CPU non
ha indirizzamento indicizzato (niente `STA indirizzo,X` per scrivere
a un indirizzo calcolato a runtime) — è un limite reale, non una
dimenticanza (vedi `README.md` del motore). Per 16 celle consecutive,
scriverle a mano è comunque leggibile; per qualcosa di più grande
(es. cancellare l'intero schermo), inizierebbe a essere scomodo — ed
è esattamente il tipo di lavoro ripetitivo che ConsoleLang (vedi
`doc_cl.md`) può rendere più corto da scrivere, anche se sotto
produce lo stesso tipo di codice.

---

## 8. Lanciarlo

```
python3 s32/launcher.py carts/adventure_asm/game.asm
```

Bypassa il menu e lancia direttamente questa cartuccia. Premi **J**
o **Spazio** quando vedi "PRESS J START": il testo sparisce,
conferma che sei passato in modalità 1.

---

## 9. Caricare uno stage nuovo

Finora la CPU ha solo scritto in memoria "in piccolo" (un valore,
un indirizzo). Sostituire un intero sfondo (migliaia di byte di
tilemap) istruzione per istruzione sarebbe troppo lento — quindi
esiste una scorciatoia hardware, la porta `STAGE_SELECT`
(`0x042001`): scriverci un numero copia ISTANTANEAMENTE (senza
consumare cicli CPU aggiuntivi) la tilemap di quello stage dentro
VRAM, sovrascrivendo quella attiva. È lo stesso principio del DMA
sui computer veri: un controller a parte fa la copia, la CPU dice
solo *quando*.

Gli stage disponibili li prepara `cart.py` **prima** che la CPU
inizi a eseguire — la CPU non può "inventare" uno stage nuovo a
runtime, solo scegliere tra quelli già pronti:

```python
# carts/_shared/graphics.py
def build_stages():
    return {1: build_stage_tilemap()}
```

Dalla CPU, un semplice `STA`:

```asm
LDA #1
STA 0x042001      ; carica lo stage 1
```

---

## 10. Tutto insieme: title screen -> stage vero

`carts/adventure_asm/game.asm` aggiornato:

```asm
LDA 0x000100
CMP #0
JNZ GIA_AVVIATO

IN
AND #16
CMP #0
JZ FINE_FRAME

LDA #1
STA 0x000100
LDA #1
STA 0x042001      ; sostituisce l'INTERA tilemap - il testo della
                   ; title screen sparisce come conseguenza naturale,
                   ; non serve cancellarlo pezzo per pezzo

FINE_FRAME:
HALT

GIA_AVVIATO:
HALT
```

Molto più corto della versione precedente (che cancellava il testo
lettera per lettera) — cambiare stanza intera è più semplice che
modificarne una in corso.

---

## 11. Caricare uno sprite (il giocatore)

Uno sprite è un tile che la PPU disegna a una posizione libera
(non ancorata alla griglia della tilemap) — la OAM (`0x040000` in
su) tiene fino a 512 sprite, 8 byte ciascuno: **X** (2 byte), **Y**
(2 byte), **indice tile** (2 byte), **attributi** (2 byte).

Il tile si prepara come qualunque altro (sezione 4), solo che invece
di finire nella tilemap, il suo indice va scritto direttamente in
OAM:

```asm
LDA #224          ; posizione X
STA 0x040000       ; OAM slot 0, campo X
LDA #144           ; posizione Y
STA 0x040002        ; OAM slot 0, campo Y
LDA #11             ; indice del tile giocatore
STA 0x040004
LDA #0               ; attributi: bit0-1=dimensione (00=un tile, gia' 32x32), bit2-4=palette
STA 0x040006
```

**Gli attributi**, bit per bit: bit0-1 = dimensione (`00`=un tile
(32×32, la dimensione base), `01`=griglia 2×2 (64×64), `10`=griglia
4×4 (128×128) - indici consecutivi); bit2-4 = quale palette usare
(0-7). `0` significa: un tile solo, palette 0 (l'unica che usiamo
finora - font, stage e giocatore condividono la stessa, 8 colori in
tutto, ben dentro il limite di 255).

**Nascondere uno sprite**: scrivi un valore Y molto alto (`>= 0xFFF0`)
— la PPU lo salta del tutto, non solo lo rende trasparente. Ogni
slot OAM parte già nascosto di default (il motore lo fa per te
all'avvio di ogni cartuccia — un dettaglio importante, vedi
`README.md` del motore per la storia completa del perché).

---

## 12. Il movimento fluido a tile

Un tasto direzione non sposta il giocatore pixel per pixel finché
resta premuto — sposta di **un tile intero (32px)**, ma **fluidamente**
(2px per frame, la stessa velocità di un movimento libero), fermandosi
esattamente al tile di arrivo. Se il tasto resta tenuto, appena un
tile finisce il successivo riparte subito nella stessa direzione —
un cammino continuo, non uno scatto per pressione.

Serve uno stato persistente in più: non basta la posizione attuale,
serve anche un **target** (dove il movimento in corso si fermerà).

```asm
; mem[0x000110] = in movimento? (0=fermo, 1=in scorrimento)
; mem[0x000112] = targetX     mem[0x000114] = targetY

LDA 0x000110
CMP #0
JNZ GIA_IN_MOVIMENTO    ; se in movimento, salta il controllo di un nuovo target

IN
STA 0x000106

LDA 0x000102             ; il target parte uguale alla posizione attuale
STA 0x000112
LDA 0x000104
STA 0x000114

LDA 0x000106
AND #1                     ; su - controlla l'input ATTUALE (non "appena
CMP #0                      ; premuto" - tenerlo fa proseguire da solo)
JZ CHECK_DOWN_T
LDA 0x000114
SUB #32                       ; un tile INTERO in un colpo solo sul target...
STA 0x000114
LDA #1
STA 0x000110
JMP TARGET_FATTO
CHECK_DOWN_T:
; ... stesso schema per giu'/sinistra/destra ...

TARGET_FATTO:
LDX 0x000112                  ; il target non deve mai uscire dalla stanza -
LDY 0x000114                   ; CLAMP prima di iniziare a muoversi verso
CLAMPX 32,416                    ; di lui, non durante
CLAMPY 32,704
STX 0x000112
STY 0x000114

GIA_IN_MOVIMENTO:
```

Il target si sposta di un tile intero **in un colpo**, ma il
*giocatore* no — quello avanza di 2px per volta verso quel target,
ogni frame, finché non lo raggiunge:

```asm
LDA 0x000110
CMP #0
JZ DOPO_MOVIMENTO       ; non in movimento: niente da fare

LDA 0x000102              ; asse X: confronta con il target
CMP 0x000112
JZ X_FATTO                  ; gia' uguale, niente da fare su questo asse
JLT X_INCREMENTA
SUB #2
JMP X_SALVA
X_INCREMENTA:
ADD #2
X_SALVA:
STA 0x000102
X_FATTO:
; ... stesso schema per l'asse Y ...

LDA 0x000102                 ; ENTRAMBI gli assi arrivati? movimento finito
CMP 0x000112
JNZ DOPO_MOVIMENTO
LDA 0x000104
CMP 0x000114
JNZ DOPO_MOVIMENTO
LDA #0
STA 0x000110                   ; moving=0: il prossimo frame puo' leggere
                                 ; un nuovo target (se un tasto e' ancora
                                 ; premuto, ripartira' immediatamente)
DOPO_MOVIMENTO:
```

**Perché controllare l'input `IN` invece di un "appena premuto"?**
Prima avevamo effettivamente un edge-detector (con XOR — vedi
`doc_cl.md` sezione corrispondente per l'operatore) che faceva
fermare il movimento dopo un tile anche tenendo il tasto premuto.
Cambiando idea su come doveva sentirsi il gioco, l'abbiamo tolto: ora
quando il giocatore è fermo, guardiamo semplicemente cosa è premuto
*in quel momento* — se è ancora la stessa direzione, si riparte.
Codice più semplice, non solo diverso.

**Se rilasci a metà tile**: il movimento in corso si completa sempre
(non si ferma mai a metà) — solo che, una volta arrivato, non ne
parte uno nuovo.

---

## 13. HUD persistente: sprite invece di tile

Lo SNES vero aveva più layer di sfondo (BG1-4) — spesso uno dedicato
a elementi fissi come la barra vita, che non scrollava con il mondo.
Noi abbiamo un solo tilemap, sostituito interamente da
`STAGE_SELECT` a ogni cambio stanza — se disegnassi la vita
*nella* tilemap, sparirebbe cambiando stanza.

**La soluzione**: disegnarla come **sprite**, non come tile. Gli
sprite (OAM) sono già completamente indipendenti dalla tilemap —
`STAGE_SELECT` non li tocca mai. È anche storicamente corretta come
tecnica: molti giochi SNES veri usavano sprite per l'HUD, non solo
il layer dedicato.

```asm
LDA #8
STA 0x040008        ; OAM slot 1, campo X - SEMPRE 8, mai lo scroll
LDA #8
STA 0x04000A         ; campo Y - SEMPRE 8
LDA #12               ; indice del tile cuore
STA 0x04000C
LDA #0
STA 0x04000E
```

Ridisegnato ogni frame in coordinate **schermo fisse** — a
differenza del giocatore (sezione 15), non va mai convertito da
coordinate mondo.

---

## 14. Un tile che fa da interruttore

Le scale che portano alla stanza successiva sono un **tile di
sfondo** (non uno sprite) — hanno senso come parte della stanza
perché scrollano insieme a lei.

Con il movimento sempre allineato alla griglia (ogni posizione è
un multiplo esatto di 32), il controllo può essere un **confronto
ESATTO**, non un margine di tolleranza:

```asm
LDA 0x000108       ; stanza attuale
CMP #1
JNZ SKIP_STAIRS_DOWN  ; le scale funzionano solo in stanza 1

LDA 0x000102          ; playerX (mondo) - deve essere ESATTAMENTE
CMP #224                ; sulla colonna delle scale
JNZ SKIP_STAIRS_DOWN

LDA 0x000104             ; playerY (mondo) - ESATTAMENTE sulla riga
CMP #704
JNZ SKIP_STAIRS_DOWN

; tutte le condizioni soddisfatte: cambia stanza
LDA #2
STA 0x000108
STA 0x042001
...

SKIP_STAIRS_DOWN:
```

**Prima usavamo un margine** ("Y è abbastanza vicino a 704?") perché
il movimento a salti non garantiva un allineamento preciso — con il
movimento fluido a griglia, il giocatore o è *esattamente* sul tile
delle scale o non lo è mai, un confronto esatto è più semplice e più
corretto (niente più margini sbilanciati tra andata e ritorno, un
bug che avevamo davvero).

**Arrivo fuori dalle scale**: quando la transizione scatta, il
giocatore riappare un tile di distanza dalle scale dell'*altra*
stanza (mai sopra di esse) — allineato alla griglia, così non rischia
di riattivare subito la transizione né di apparire visivamente
sovrapposto.

---

## 15. Lo scroll: la telecamera che segue il giocatore

Il giocatore vive in coordinate **mondo** — può superare i 320px di
schermo (la stanza è alta 768px). Va disegnato in coordinate
**schermo**, sempre dentro 0-320.

```asm
; --- calcola scroll_y: centra la telecamera sul giocatore ---
LDA 0x000104
CMP #160
JLT SCROLL_E_ZERO      ; se playerY<160, non possiamo sottrarre 160
SUB #160                 ; (vedi sezione 16 - qui evitiamo il bug)
JMP SCROLL_CALCOLATO
SCROLL_E_ZERO:
LDA #0
SCROLL_CALCOLATO:
TAY
CLAMPY 0,448              ; non scrollare oltre i bordi della stanza
STY 0x042003                ; porta SCROLL_Y - la PPU la legge al render
STY 0x00010A

; --- posizione A SCHERMO = posizione MONDO - scroll ---
LDA 0x000104
SUB 0x00010A
TAY                          ; Y ora e' la posizione SCHERMO
```

`CLAMPY 0,448` limita la telecamera: non scrolla oltre l'inizio (0)
né oltre la fine della stanza (768px di stanza - 320px di schermo =
448 il massimo scroll sensato).

---

## 16. Attenzione ai registri senza segno

Un bug reale, trovato costruendo questa demo: `playerY - 160` sembra
innocuo, ma se `playerY` è **minore di 160** (giocatore vicino alla
cima), il risultato dovrebbe essere negativo — e i nostri registri
sono **senza segno** (0-65535, mai negativi). Una sottrazione che
"andrebbe sotto zero" si **avvolge** a un numero enorme (vicino a
65535), non diventa negativa. `CLAMPY 0,448` allora la scambia per
"sopra il massimo" invece che "sotto lo zero".

**La lezione**: prima di sottrarre un letterale da un valore che
potrebbe essere più piccolo, controlla PRIMA con `CMP`/salto — non
dopo.

---

## 17. L'attacco e lo slash

Premere **J** in gioco (non in title screen) avvia un attacco - un
timer che conta alla rovescia, non un singolo evento istantaneo:

```asm
LDA 0x000106        ; input di questo frame
AND #16
CMP #0
JZ J_NON_PREMUTO

LDA 0x00011A          ; J era gia' premuto il frame scorso?
CMP #0
JNZ J_TENUTO             ; si: non e' una pressione NUOVA, ignora
LDA 0x000118
CMP #0
JNZ J_TENUTO               ; attacco gia' in corso: ignora
LDA #10
STA 0x000118                 ; NUOVA pressione: avvia, 10 frame

J_TENUTO:
LDA #1
STA 0x00011A
JMP J_FINE
J_NON_PREMUTO:
LDA #0
STA 0x00011A
J_FINE:
```

Lo stesso edge-detector di sezione 12, applicato a un tasto diverso
(J invece delle direzioni) - un attacco per pressione, non uno per
frame tenuto.

**Un bug trovato testando**: `prevJ` deve partire già a `1` quando
il gioco inizia (non `0`) - altrimenti lo stesso J che hai premuto
per *avviare* il gioco viene riletto, nello stesso frame, come "J
appena premuto" e fa scattare *anche* un attacco non voluto. Impostare
`prevJ = 1` all'ingresso in gioco dice "questo J è già stato visto".

**Dove appare la spada**: un tile davanti al giocatore, nella
direzione in cui guarda (`direction`, aggiornata quando inizia un
movimento - sezione 12):

```asm
LDA 0x000102
STA 0x000200        ; slashWorldX = playerX (default: nessuno spostamento)
LDA 0x000104
STA 0x000202          ; slashWorldY = playerY

LDA 0x000116            ; direzione
CMP #0
JNZ SLASH_W_NOT_UP
LDA 0x000202
SUB #32
STA 0x000202
JMP SLASH_W_FINE
SLASH_W_NOT_UP:
; ... stesso schema per giu'/sinistra/destra ...
SLASH_W_FINE:
```

**Animazione a due frame**: mentre `attackTimer` scende da 10 a 0, il
disegno sceglie tra due tile in base al valore:

```asm
LDA 0x000118
CMP #5
JLT USA_SLASH2
LDA #14              ; primo frame (luminoso): timer >= 5
STA 0x040024
JMP SLASH_ATTR
USA_SLASH2:
LDA #15                ; secondo frame (sbiadisce): timer < 5
STA 0x040024
```

---

## 18. I nemici che vagano

Un nemico non insegue il giocatore - si muove a scatti in una
direzione, urta i bordi della stanza e rimbalza, e ogni tanto cambia
direzione a caso:

```asm
; -- generatore pseudo-casuale: un contatore con un incremento
; "brutto" (0x37, un numero dispari senza fattori comuni con le
; dimensioni dello schermo) produce una sequenza che SEMBRA casuale
; pur essendo completamente deterministica --
LDA 0x00012A
ADD #0x37
STA 0x00012A
AND #0x1F              ; ogni ~32 frame...
CMP #0
JNZ SKIP_E1_DIR
LDA 0x00012A
AND #3                   ; ...scegli una nuova direzione (0-3)
STA 0x000126
SKIP_E1_DIR:
```

Il movimento vero e proprio (4px/frame, continuo - **non** allineato
alla griglia come il giocatore, i nemici non hanno bisogno di
fermarsi su un tile) controlla i bordi e **inverte la direzione**
invece di fermarsi:

```asm
LDA 0x000126
CMP #0                ; direzione = su?
JNZ E1_NOT_UP
LDA 0x000122
CMP #100
JLT E1_BOUNCE_UP        ; troppo vicino al bordo alto: rimbalza
SUB #4
STA 0x000122
JMP E1_MOVE_DONE
E1_BOUNCE_UP:
LDA #1
STA 0x000126              ; inverti: ora scende
```

**Nessun danno da collisione**: toccare il nemico direttamente non
fa nulla - l'unico modo di farsi male è una pietra (sezione 20).

---

## 19. I proiettili: le pietre

Un nemico spara quando il giocatore è **sullo stesso asse** (X o Y),
entro una soglia - non serve mirare, solo allinearsi:

```asm
; |playerX - e1x| < 16 ?
LDA 0x000102
CMP 0x000120
JLT E1_PX_MINORE
SUB 0x000120
CMP #16
JGE E1_CONTROLLA_Y     ; troppo lontano in X: prova l'asse Y
JMP E1_SPARA_VERTICALE   ; allineato in X: spara lungo Y
E1_PX_MINORE:
LDA 0x000120
SUB 0x000102
CMP #16
JGE E1_CONTROLLA_Y
```

Un `shot_cooldown` per nemico (separato dal timer di movimento)
impedisce raffiche continue - dopo ogni sparo si resetta a 80 frame:

```asm
LDA 0x00012C          ; cooldown
CMP #0
JZ E1_CONTROLLA_SPARO   ; puo' sparare: controlla l'allineamento
SUB #1
STA 0x00012C
JMP SKIP_E1_ALL           ; ancora in cooldown: salta tutto il resto
```

La pietra stessa è un secondo insieme di celle WRAM (posizione,
direzione, attivo/non attivo) che si muove a 6px/frame finché non
esce dai bordi della stanza - stessa struttura di un nemico, più
semplice (nessun rimbalzo: esce e sparisce).

---

## 20. Danno al giocatore e invincibilità

La pietra controlla la collisione **dopo** essersi mossa, con lo
stesso confronto per distanza già visto per lo slash (sezione 17),
soglia più larga (20px):

```asm
LDA 0x00011C           ; invincibile? (hurtTimer > 0)
CMP #0
JNZ SKIP_S1               ; si': ignora completamente la collisione

; |s1_x - playerX| < 20 e |s1_y - playerY| < 20 (stesso schema slash)
...
S1_HIT:
LDA #0
STA 0x000144              ; la pietra sparisce sempre, colpisca o meno
LDA 0x00011E
CMP #0
JZ SKIP_S1                  ; HP gia' a 0: non scendere sotto zero
SUB #1
STA 0x00011E
LDA #20
STA 0x00011C                 ; 20 frame di invincibilita'
```

**L'animazione di ferita** è un lampeggio, non uno sprite dedicato -
un bit del timer di invincibilità nasconde il giocatore a intermittenza:

```asm
LDA 0x00011C
AND #2                 ; bit1: alterna visibile/nascosto ogni 2 frame
CMP #0
JNZ NASCONDI_GIOCATORE
```

**I cuori nella HUD** (sezione 13) ora rispondono a `playerHP` -
ne nascondi uno alla volta quando l'HP scende sotto la soglia
corrispondente, invece di disegnarli sempre tutti e tre.

---

## 21. La grata: sconfiggere per aprire

Tre varianti della **stessa stanza** (sezione 4 - una palette e un
tile diversi non cambiano la struttura): stage 1 (giorno, grata
chiusa), stage 2 (notte), stage 3 (giorno, grata aperta - le vere
scale al posto della grata). Un contatore condiviso tra i due nemici:

```asm
; (nella gestione morte di OGNI nemico, quando l'animazione finisce)
LDA #0
STA 0x000124         ; nemico definitivamente morto
LDA 0x000150
ADD #1
STA 0x000150            ; enemies_killed++
```

Controllato una volta per frame, in un punto qualsiasi dopo
l'aggiornamento di entrambi i nemici:

```asm
LDA 0x000108
CMP #1
JNZ SKIP_GATE_OPEN     ; solo se sei ancora nella stanza 1
LDA 0x000150
CMP #2
JLT SKIP_GATE_OPEN       ; meno di 2 uccisi: niente
LDA #3
STA 0x000108
STA 0x042001                ; select_stage(3): la grata e' sparita
SKIP_GATE_OPEN:
```

Nota cosa **non** serve: nessuna variabile "gate_open" separata -
`room` stesso (1 vs 3) codifica se la grata è aperta o chiusa, dato
che sono due tilemap diverse caricate da `STAGE_SELECT`.

---

## 22. Il boss: uno sprite 64x64

Il boss non e' uno sprite piu' grande disegnato a mano: e' **UN SOLO
slot OAM** con l'attributo di dimensione impostato a `01` (griglia
2x2). Il PPU legge da solo i **4 tile consecutivi** a partire
dall'indice che gli dai, e li dispone cosi':

```
  tile 20  |  tile 21        (alto-sx, alto-dx)
  ---------+---------
  tile 22  |  tile 23        (basso-sx, basso-dx)
```

```asm
LDA 0x000160
STA 0x040048        ; X dello slot 9
LDA 0x000162
CMP 0x00010A
JLT NASCONDI_BOSS      ; vedi sotto: la protezione dall'underflow
SUB 0x00010A
STA 0x04004A
LDA #20
STA 0x04004C          ; PRIMO tile: il PPU usa 20,21,22,23
LDA #1
STA 0x04004E            ; attributi: bit0-1 = 01 -> 64x64
```

Questo significa che nello spritesheet i 4 quadranti del boss devono
stare in celle **consecutive** - conviene disegnare il boss come
un'unica immagine 64x64 e poi tagliarla, non disegnare quattro
pezzi separati sperando che combacino.

**Un bug reale trovato qui**: il boss spariva del tutto quando la
telecamera si trovava piu' in basso di lui. Causa: `boss_y - scrollY`
va sotto zero, i registri sono SENZA SEGNO (sezione 16, di nuovo), e
il valore si avvolge a un numero >= 0xFFF0 - che e' esattamente il
codice che dice al PPU "sprite nascosto". Non era un errore di
disegno, era la stessa insidia dei registri senza segno che avevamo
gia' incontrato per la telecamera. La protezione e' il `CMP`/`JLT`
prima della sottrazione.

### Le due azioni del boss

Una variabile `boss_phase` alterna fra due comportamenti, senza mai
eseguirli insieme:

```asm
LDA 0x00016C
CMP #0
JNZ BOSS_FASE_SPARO
; ... fase 0: movimento ...
```

**Fase movimento**: scorre orizzontalmente per `boss_steps` passi
(due, "un paio di volte"), invertendo direzione a ogni passo e ai
bordi della stanza. Esauriti i passi, passa alla fase di sparo.

**Fase sparo**: crea il fuoco e attende che sparisca, poi ricarica
`boss_steps = 2` e torna a muoversi.

### Il fuoco che rallenta

Il dettaglio interessante e' come si ottiene "rallenta fino a
fermarsi a 3 tile". La velocita' parte da 13 e cala di 1 ogni frame,
e il fuoco avanza **DI QUELLA velocita'** ogni frame:

```asm
LDA 0x000170
ADD 0x00017A          ; avanza DI 'speed', non di una quantita' fissa
STA 0x000170
...
LDA 0x00017A
SUB #1                  ; e la velocita' cala
STA 0x00017A
```

La distanza totale e' la somma 13+12+11+...+1 = **91px**, quasi
esattamente 3 tile (96px). Il rallentamento e l'arresto alla
distanza giusta escono gratis dalla stessa riga, senza contatori
di distanza.

**L'errore che avevo fatto**: muovere di 2px FISSI mentre la
velocita' calava. Il valore della velocita' scendeva regolarmente -
sembrava corretto leggendo il codice - ma il fuoco percorreva solo
24px e il rallentamento non si vedeva affatto nel movimento. Si e'
scoperto solo misurando la distanza percorsa in un test.

### La barra della vita

Quattro sprite HUD affiancati (slot 11-14), ciascuno che sceglie fra
il tile "segmento pieno" (25) e "segmento vuoto" (26) confrontando
`boss_hp` con la propria soglia:

```asm
LDA 0x000164
CMP #3
JLT BARRA3_VUOTA
LDA #25
JMP BARRA3_SCRIVI
BARRA3_VUOTA:
LDA #26
BARRA3_SCRIVI:
STA 0x04006C
```

Sono coordinate schermo fisse, come i cuori (sezione 13) - e
l'intero blocco e' avvolto da un controllo su `room`, cosi' la barra
esiste **solo** nella stanza del boss.

---

## 23. L'audio

L'audio segue la stessa filosofia del video: la CPU **non produce
suono**, esattamente come non disegna pixel. Scrivere un ID sulla
porta `0x042004` lo **accoda** e basta:

```asm
LDA #1
STA 0x042004        ; suono 1 = fendente
```

E' il launcher che, a fine frame, svuota la coda e suona davvero.
Cosi' `cpu.py` resta puro Python testabile senza scheda audio, e
`audio.py` genera solo byte PCM - lo stesso rapporto che c'e' fra
`ppu.py` (produce byte RGB) e il launcher (li mette a schermo).

### Gli ID dei suoni

Fanno parte dell'"hardware" dal punto di vista del gioco, come gli
indici dei tile:

| ID | Evento |
|----|--------|
| 1 | fendente del giocatore |
| 2 | il giocatore incassa un colpo |
| 3 | nemico distrutto |
| 4 | nemico/boss spara |
| 5 | cambio stanza (scale) |
| 6 | la grata si apre |
| 7 | il boss incassa un colpo |
| 8 | il boss viene sconfitto |

### Come sono fatti i suoni

Nessun file audio: `audio.py` genera onde a runtime, come facevano i
chip sonori veri. Tre primitive bastano per tutto:

- `square_wave(freq, durata, duty)` - onda quadra, il timbro 8-bit
  classico. `duty` cambia il carattere: 0.5 e' pieno, 0.25 e' piu'
  nasale.
- `sweep_wave(f_inizio, f_fine, durata)` - una quadra che scivola fra
  due frequenze. In discesa suona "colpito", in salita "raccolto":
  e' il modo piu' economico di dare un'intenzione a un suono.
- `noise(durata)` - rumore pseudo-casuale con inviluppo calante:
  esplosioni, impatti, pietra che scorre.

Tutti e otto i suoni si costruiscono **una volta sola** all'avvio
(`build_sound_bank`) - generarli a ogni riproduzione costerebbe
millisecondi dentro al ciclo di gioco, lo stesso errore gia'
corretto per i tile dello sfondo.

### Attivo di default, disattivabile con --no-audio

```
python3 s32/launcher.py carts/adventure_asm/game.asm
```

L'audio parte da solo. Se serve disattivarlo (vedi sotto perche'):

```
python3 s32/launcher.py carts/adventure_asm/game.asm --no-audio
```

Il motivo per cui esiste una via di fuga e' concreto e documentato:
su Raspberry Pi, con ALSA mal configurato, il mixer di pygame puo'
spammare "underrun occurred" a ogni frame e rallentare l'intero
gioco. In quel caso `--no-audio` toglie il problema; ogni errore di
inizializzazione audio viene comunque ingoiato automaticamente,
disattivando solo il suono: **un gioco muto e' molto meglio di un
gioco che scatta o non parte**.

---

## 24. Il game over: una stanza che torna ad essere uno stage

Prima di scrivere qualunque logica di game over, un problema si e'
presentato subito: la title screen ("PRESS J START") era scritta
nella tilemap **una volta sola**, da Python, prima ancora che la CPU
eseguisse la prima istruzione (vedi `cart.py`). Una volta premuto J
e caricata la stanza 1 con `STAGE_SELECT`, quella scritta e'
sovrascritta per sempre - non c'era alcun modo, dalla CPU, di
tornarci.

La correzione e' stata trattare la title screen come una stanza
qualunque: `build_title_tilemap()` costruisce la sua tilemap con lo
stesso schema di `_make_room()` (sezione 4), e viene registrata
come **stage 0**:

```python
def build_stages():
    return {
        0: build_title_tilemap(),
        1: _make_room(...),
        ...
    }
```

Da questo momento, `select_stage(0)` (cioe' `LDA #0 / STA
0x042001`) ricarica "PRESS J START" in qualunque istante - lo stesso
identico meccanismo gia' usato per cambiare stanza, applicato al
titolo.

### Rilevare la morte

Controllato PRIMA di ogni altra cosa, all'inizio del frame - non nei
singoli punti che riducono HP (pietra, fuoco, boss sono fonti
diverse, controllarle tutte singolarmente sarebbe ripetitivo e
fragile):

```asm
IN_GAME:
LDA 0x00011E
CMP #0
JNZ IN_GAME_VIVO

LDA #2
STA 0x000100          ; mode = 2 (game over)
LDA #180
STA 0x000180             ; 3 secondi a 60fps
LDA #9
STA 0x042004                ; suono di sconfitta
```

### Scrivere testo nella tilemap A RUNTIME

Fin qui il testo (title screen, HUD) era sempre stato preparato da
Python, mai dalla CPU. "GAME OVER" e' la prima eccezione - scritto
direttamente in VRAM, un tile alla volta, con l'indirizzo calcolato
a mano (riga 5, colonna 3 in poi, centrata su 15 colonne):

```asm
LDA #28
STA 0x020506           ; G
LDA #8
STA 0x020508              ; A
LDA #29
STA 0x02050A                ; M
...
```

Ogni indirizzo e' `VRAM_BASE + TILEMAP_VRAM_OFFSET + (riga*128 +
colonna) * 2` - la stessa formula che `_write_tilemap_cell()` applica
in Python, qui srotolata a mano perche' la CPU non ha moltiplicazione
(sezione 2). Scritto **una volta sola**, alla transizione - non ad
ogni frame: e' sfondo (tilemap), non uno sprite OAM che va ridisegnato
di continuo.

### Il teschio, e nascondere tutto il resto

Ogni frame di game over disegna il teschio (tile 27) in posizione
fissa e nasconde ogni altro sprite (cuori, slash, nemici, pietre,
boss, fuoco, barra vita) scrivendo Y=0xFFFF - lo stesso trucco
"fuori schermo" gia' visto in tutta la demo:

```asm
GAME_OVER:
LDA 0x000180
CMP #0
JZ GAME_OVER_RESET
SUB #1
STA 0x000180

LDA #224
STA 0x040000
LDA #100
STA 0x040002            ; sopra il testo, non sovrapposto
LDA #27
STA 0x040004
...
LDA #0xFFFF
STA 0x04000A               ; cuore1 nascosto
STA 0x040012                 ; cuore2 nascosto
...                              ; (un blocco per ogni sprite)
```

**Un aggiustamento fatto dopo aver guardato il risultato**: la prima
versione metteva il teschio sopra la posizione del giocatore,
sovrapposto al testo sottostante. Spostato piu' in alto, con
margine - il tipo di correzione che si vede solo guardando l'immagine
finale, non leggendo le coordinate.

### Il reset

```asm
GAME_OVER_RESET:
LDA #0
STA 0x000100
STA 0x042001            ; select_stage(0): ricarica "PRESS J START"
JMP FINE_FRAME
```

Due scritture, `mode` e la porta stage - lo stesso identico pattern
di ogni altro cambio stanza in questa demo, applicato al ritorno al
titolo.

---

## 25. Il programma completo

`carts/adventure_asm/game.asm` — la demo completa: title screen,
stage, movimento fluido a griglia con ripetizione, attacco, due
nemici che vagano e sparano, collisioni, HUD con cuori, scale
bidirezionali, stanza notturna, grata che si apre sconfiggendo i
nemici. Vale la pena aprirlo per intero ora che conosci ogni pezzo —
è più lungo di questa guida (i cinque blocchi di sezione 17-21 si
ripetono, quasi identici, per nemico 1 e nemico 2, e per pietra 1 e
pietra 2), ma ogni singolo pezzo è già stato spiegato.

```
python3 s32/launcher.py carts/adventure_asm/game.asm
```

Frecce per muoverti (tenute premute per camminare senza interruzioni),
**J** per attaccare o per iniziare dalla title screen.

---

## Fine di questo tutorial

Hai visto, in ordine: registri, mappa di memoria, il tuo primo
programma, risorse grafiche (dallo spritesheet PNG alla VRAM), salti
e confronti, input, caricare uno stage, caricare uno sprite,
muoverlo fluidamente con ripetizione, HUD persistente, tile che
fanno da interruttore, scroll, un'insidia reale dei registri senza
segno, l'attacco con animazione a due frame, nemici che vagano con
un generatore pseudo-casuale, proiettili sparati per allineamento,
danno con invincibilità temporanea, e una grata che si apre in base
a un contatore condiviso — la stessa progressione (con le
correzioni, e i bug, fatti strada facendo) con cui è stata costruita
la demo vera. Da qui, il resto è applicare questi stessi pezzi a
idee nuove: più nemici, un oggetto da raccogliere, scroll
orizzontale.
