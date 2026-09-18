; ============================================================
; ADVENTURE - S32, assembly puro - VERSIONE COMPLETA
; Movimento fluido a tile, attacco, nemici, proiettili,
; collisioni, grata che si apre sconfiggendo i nemici.
; ============================================================
;
; MAPPA WRAM
; [0x000100] mode           0=title 1=playing 2=game_over
; [0x000102] playerX        coordinate mondo
; [0x000104] playerY
; [0x000106] input          frame corrente
; [0x000108] room           1=giorno_locked 2=notte 3=giorno_open
; [0x00010A] scrollY
; [0x000110] moving         0=fermo 1=in scorrimento verso target
; [0x000112] targetX
; [0x000114] targetY
; [0x000116] direction      0=su 1=giu 2=sinistra 3=destra
; [0x000118] attackTimer    0=nessun attacco N=frame rimasti
; [0x00011A] prevJ          J era premuto il frame scorso
; [0x00011C] hurtTimer      frame di invincibilita dopo danno
; [0x00011E] playerHP       3=piena salute
;
; NEMICO 1 (ogni campo 2 byte, totale 14 byte)
; [0x000120] e1_x           [0x000122] e1_y
; [0x000124] e1_alive       0=morto 1=vivo 2=animazione morte
; [0x000126] e1_dir         0=su 1=giu 2=sx 3=dx
; [0x000128] e1_timer       contatore riuso: movimento/morte/carica
; [0x00012A] e1_rng         generatore pseudo-casuale
; [0x00012C] e1_shot        cooldown proiettile
; [0x00012E] e1_charging    0=normale 1=sta caricando (fermo, lampeggia)
;
; NEMICO 2
; [0x000130] e2_x  [0x000132] e2_y  [0x000134] e2_alive
; [0x000136] e2_dir  [0x000138] e2_timer  [0x00013A] e2_rng
; [0x00013C] e2_shot
; [0x00013E] e2_charging
;
; PIETRA 1 (da nemico 1)
; [0x000140] s1_x  [0x000142] s1_y  [0x000144] s1_active
; [0x000146] s1_dir
;
; PIETRA 2 (da nemico 2)
; [0x000148] s2_x  [0x00014A] s2_y  [0x00014C] s2_active
; [0x00014E] s2_dir
;
; [0x000150] enemies_killed
;
; BOSS (solo stanza 2 - notte)
; [0x000160] boss_x        angolo alto-sinistra (sprite 64x64)
; [0x000162] boss_y
; [0x000164] boss_hp       4 = barra piena, 0 = sconfitto
; [0x000166] boss_dir      0=sinistra 1=destra
; [0x000168] boss_steps    passi rimasti nella direzione corrente
; [0x00016A] boss_timer    contatore di fase (muove / spara / pausa)
; [0x00016C] boss_phase    0=movimento 1=sparo
; [0x00016E] boss_hitcool  invincibilita' dopo un colpo subito
;
; FUOCO del boss
; [0x000170] fire_x        [0x000172] fire_y
; [0x000174] fire_active   0=spento 1=in volo 2=fermo a terra
; [0x000176] fire_dirx     direzione X: 0=nessuna 1=destra 2=sinistra
; [0x000178] fire_diry     direzione Y: 0=nessuna 1=giu 2=su
; [0x00017A] fire_speed    velocita' attuale (cala fino a 0)
; [0x00017C] fire_life     frame rimasti prima di sparire
;
; TEMPORANEI (calcolati ogni frame, non persistenti)
; [0x000200] slashWorldX    posizione spada in coordinate mondo
; [0x000202] slashWorldY
;
; GAME OVER
; [0x000180] gameOverTimer  frame rimasti prima di tornare al titolo
;
; OAM SLOTS
; 0(0x040000)=giocatore  1-3(0x040008..18)=cuori
; 4(0x040020)=slash   5(0x040028)=nemico1   6(0x040030)=nemico2
; 7(0x040038)=pietra1  8(0x040040)=pietra2
; 9(0x040048)=BOSS (64x64, attr=0x01 -> griglia 2x2, tile 20-23)
; 10(0x040050)=fuoco
; 11-14(0x040058..0x040070)=barra vita boss (4 segmenti)
; ============================================================

; ---- TITOLO ----
LDA 0x000100
CMP #0
JZ TITLE_SCREEN
CMP #2
JZ GAME_OVER
JMP IN_GAME

TITLE_SCREEN:
IN
AND #16
CMP #0
JZ FINE_FRAME
; J premuto: inizializza e avvia
LDA #1
STA 0x000100

; -- stato giocatore --
LDA #1
STA 0x000108       ; room = 1 (giorno locked)
LDA #1
STA 0x042001       ; select_stage(1)
LDA #224
STA 0x000102       ; playerX = 224
LDA #64
STA 0x000104       ; playerY = 64
LDA #0
STA 0x000110       ; fermo
LDA #1
STA 0x000116       ; direzione = giu
LDA #0
STA 0x000118       ; nessun attacco
LDA #1
STA 0x00011A       ; prevJ = 1 (il J che ha avviato il gioco e'
                     ; "gia' visto" - altrimenti lo stesso frame lo
                     ; rileggerebbe come "appena premuto" e farebbe
                     ; scattare anche un attacco, bug trovato testando)
LDA #0
STA 0x00011C       ; hurtTimer = 0 (nessuna protezione iniziale -
                     ; non serve, i nemici non sono mai adiacenti
                     ; allo spawn, e causava solo sfarfallio confuso)
LDA #3
STA 0x00011E       ; HP = 3

; -- nemico 1 --
LDA #128
STA 0x000120       ; e1_x = tile 4 (128px)
LDA #352
STA 0x000122       ; e1_y = tile 11 (352px)
LDA #1
STA 0x000124       ; alive
LDA #3
STA 0x000126       ; direzione = destra
LDA #0
STA 0x000128       ; timer = 0
LDA #0x47
STA 0x00012A       ; rng seed
LDA #60
STA 0x00012C       ; shot cooldown (ritardo iniziale)
LDA #0
STA 0x00012E       ; non in carica

; -- nemico 2 --
LDA #320
STA 0x000130       ; e2_x = tile 10 (320px)
LDA #512
STA 0x000132       ; e2_y = tile 16 (512px)
LDA #1
STA 0x000134
LDA #2
STA 0x000136       ; direzione = sinistra
LDA #0
STA 0x000138
LDA #0x7B
STA 0x00013A       ; rng seed diverso
LDA #90
STA 0x00013C       ; cooldown diverso
LDA #0
STA 0x00013E       ; non in carica

; -- pietre inattive --
LDA #0
STA 0x000144
STA 0x00014C

; -- contatore uccisioni --
LDA #0
STA 0x000150

; -- BOSS (attende nella stanza 2, in FONDO: il giocatore entra
; dall'alto (y=64) e lo incontra dopo aver percorso tutta la
; stanza notturna, "a fine schermo" come richiesto) --
LDA #208
STA 0x000160       ; boss_x (centrato: 208..272 su 480 di larghezza)
LDA #608
STA 0x000162       ; boss_y: occupa 608..672, appena sopra il muro di fondo
LDA #4
STA 0x000164       ; boss_hp = 4 (barra piena)
LDA #1
STA 0x000166       ; boss_dir = destra
LDA #2
STA 0x000168       ; boss_steps = 2 (si muove "un paio di volte")
LDA #0
STA 0x00016A       ; boss_timer
STA 0x00016C       ; boss_phase = movimento
STA 0x00016E       ; nessuna invincibilita'

; -- fuoco del boss spento --
LDA #0
STA 0x000174
STA 0x00017A
STA 0x00017C

JMP IN_GAME

; ================================================================
IN_GAME:

; ---- MORTE: controllata PRIMA di ogni altra logica - se il
; giocatore e' arrivato a 0 HP (in un frame precedente, durante una
; collisione), passa subito al game over invece di processare
; un altro frame di movimento/combattimento ----
LDA 0x00011E
CMP #0
JNZ IN_GAME_VIVO

LDA #2
STA 0x000100          ; mode = 2 (game over)
LDA #180
STA 0x000180             ; timer: 3 secondi a 60fps
LDA #9
STA 0x042004                ; suono: sconfitta

; scrive "GAME OVER" nella tilemap - UNA sola volta, qui alla
; transizione, non ad ogni frame di game over (e' sfondo, non OAM)
LDA #28
STA 0x020506           ; G
LDA #8
STA 0x020508              ; A
LDA #29
STA 0x02050A                ; M
LDA #3
STA 0x02050C                   ; E
LDA #0
STA 0x02050E                      ; (spazio)
LDA #7
STA 0x020510                         ; O
LDA #30
STA 0x020512                            ; V
LDA #3
STA 0x020514                               ; E
LDA #2
STA 0x020516                                  ; R

JMP FINE_FRAME

IN_GAME_VIVO:

; ---- LEGGI INPUT ----
IN
STA 0x000106

; ---- RILEVAMENTO J (edge: solo alla prima pressione) ----
LDA 0x000106
AND #16
CMP #0
JZ J_NON_PREMUTO

; J premuto ora
LDA 0x00011A       ; era premuto il frame scorso?
CMP #0
JNZ J_TENUTO       ; si: gia gestito
; nuova pressione - avvia attacco se non gia attivo
LDA 0x000118
CMP #0
JNZ J_TENUTO
LDA #10
STA 0x000118       ; attackTimer = 10 frame
LDA #1
STA 0x042004       ; suono: fendente

J_TENUTO:
LDA #1
STA 0x00011A
JMP J_FINE
J_NON_PREMUTO:
LDA #0
STA 0x00011A
J_FINE:

; ---- MOVIMENTO GIOCATORE (tile-based fluido con ripetizione) ----
LDA 0x000110       ; gia in movimento?
CMP #0
JNZ GIA_IN_MOVIMENTO

; Fermo: leggi input per nuovo target
LDA 0x000102
STA 0x000112
LDA 0x000104
STA 0x000114

LDA 0x000106
AND #1             ; su
CMP #0
JZ CHECK_GIU
LDA #0
STA 0x000116
LDA 0x000114
SUB #32
STA 0x000114
LDA #1
STA 0x000110
JMP TARGET_OK

CHECK_GIU:
LDA 0x000106
AND #2
CMP #0
JZ CHECK_SX
LDA #1
STA 0x000116
LDA 0x000114
ADD #32
STA 0x000114
LDA #1
STA 0x000110
JMP TARGET_OK

CHECK_SX:
LDA 0x000106
AND #4
CMP #0
JZ CHECK_DX
LDA #2
STA 0x000116
LDA 0x000112
SUB #32
STA 0x000112
LDA #1
STA 0x000110
JMP TARGET_OK

CHECK_DX:
LDA 0x000106
AND #8
CMP #0
JZ TARGET_OK
LDA #3
STA 0x000116
LDA 0x000112
ADD #32
STA 0x000112
LDA #1
STA 0x000110

TARGET_OK:
LDX 0x000112
LDY 0x000114
CLAMPX 32,416
CLAMPY 32,704
STX 0x000112
STY 0x000114

GIA_IN_MOVIMENTO:
; Avanza 2px verso il target
LDA 0x000110
CMP #0
JZ DOPO_MOVIMENTO

LDA 0x000102
CMP 0x000112
JZ X_OK
JLT X_INC
SUB #2
JMP X_SALVA
X_INC:
ADD #2
X_SALVA:
STA 0x000102
X_OK:

LDA 0x000104
CMP 0x000114
JZ Y_OK
JLT Y_INC
SUB #2
JMP Y_SALVA
Y_INC:
ADD #2
Y_SALVA:
STA 0x000104
Y_OK:

LDA 0x000102
CMP 0x000112
JNZ DOPO_MOVIMENTO
LDA 0x000104
CMP 0x000114
JNZ DOPO_MOVIMENTO
LDA #0
STA 0x000110

DOPO_MOVIMENTO:

; ---- CALCOLA POSIZIONE SPADA IN COORDINATE MONDO ----
; Usata sia per la collisione che per il disegno OAM.
LDA 0x000102
STA 0x000200       ; slashWorldX = playerX (default)
LDA 0x000104
STA 0x000202       ; slashWorldY = playerY (default)

LDA 0x000116       ; direzione
CMP #0             ; su
JNZ SLASH_W_NOT_UP
LDA 0x000202
CMP #32
JLT SLASH_W_FINE   ; fuori dai limiti = nessun hit
SUB #32
STA 0x000202
JMP SLASH_W_FINE
SLASH_W_NOT_UP:
CMP #1             ; giu
JNZ SLASH_W_NOT_DOWN
LDA 0x000202
ADD #32
STA 0x000202
JMP SLASH_W_FINE
SLASH_W_NOT_DOWN:
CMP #2             ; sinistra
JNZ SLASH_W_NOT_LEFT
LDA 0x000200
CMP #32
JLT SLASH_W_FINE
SUB #32
STA 0x000200
JMP SLASH_W_FINE
SLASH_W_NOT_LEFT:
; destra
LDA 0x000200
ADD #32
STA 0x000200
SLASH_W_FINE:

; ---- COLLISIONE SPADA vs NEMICO 1 ----
LDA 0x000118       ; attacco attivo?
CMP #0
JZ SKIP_SLASH_E1

LDA 0x000124       ; e1 vivo?
CMP #1
JNZ SKIP_SLASH_E1

; |slashWorldX - e1_x| < 24
LDA 0x000200
CMP 0x000120
JLT SE1_X_NEG
SUB 0x000120
CMP #24
JGE SKIP_SLASH_E1
JMP SE1_CHECK_Y
SE1_X_NEG:
LDA 0x000120
SUB 0x000200
CMP #24
JGE SKIP_SLASH_E1
SE1_CHECK_Y:
; |slashWorldY - e1_y| < 24
LDA 0x000202
CMP 0x000122
JLT SE1_Y_NEG
SUB 0x000122
CMP #24
JGE SKIP_SLASH_E1
JMP SLASH_KILLS_E1
SE1_Y_NEG:
LDA 0x000122
SUB 0x000202
CMP #24
JGE SKIP_SLASH_E1
SLASH_KILLS_E1:
LDA #3
STA 0x042004       ; suono: nemico distrutto
LDA #2
STA 0x000124       ; e1 -> animazione morte
LDA #10
STA 0x000128       ; timer morte = 10 frame
LDA #0
STA 0x000118       ; consuma l'attacco
SKIP_SLASH_E1:

; ---- COLLISIONE SPADA vs NEMICO 2 ----
LDA 0x000118
CMP #0
JZ SKIP_SLASH_E2
LDA 0x000134
CMP #1
JNZ SKIP_SLASH_E2

LDA 0x000200
CMP 0x000130
JLT SE2_X_NEG
SUB 0x000130
CMP #24
JGE SKIP_SLASH_E2
JMP SE2_CHECK_Y
SE2_X_NEG:
LDA 0x000130
SUB 0x000200
CMP #24
JGE SKIP_SLASH_E2
SE2_CHECK_Y:
LDA 0x000202
CMP 0x000132
JLT SE2_Y_NEG
SUB 0x000132
CMP #24
JGE SKIP_SLASH_E2
JMP SLASH_KILLS_E2
SE2_Y_NEG:
LDA 0x000132
SUB 0x000202
CMP #24
JGE SKIP_SLASH_E2
SLASH_KILLS_E2:
LDA #3
STA 0x042004       ; suono: nemico distrutto
LDA #2
STA 0x000134
LDA #10
STA 0x000138
LDA #0
STA 0x000118
SKIP_SLASH_E2:

; ---- DECREMENTA TIMER ATTACCO ----
LDA 0x000118
CMP #0
JZ SKIP_ATK_DEC
SUB #1
STA 0x000118
SKIP_ATK_DEC:

; ---- DECREMENTA HURT TIMER ----
LDA 0x00011C
CMP #0
JZ SKIP_HURT_DEC
SUB #1
STA 0x00011C
SKIP_HURT_DEC:

; ================================================================
; ---- AGGIORNA NEMICO 1 ----
LDA 0x000124
CMP #0
JZ SKIP_E1_ALL     ; morto

; Gestisci animazione morte
CMP #2
JNZ E1_VIVO
LDA 0x000128       ; timer morte
CMP #0
JZ E1_MUORE_ORA
SUB #1
STA 0x000128
JMP SKIP_E1_ALL
E1_MUORE_ORA:
LDA #0
STA 0x000124       ; e1 = morto definitivamente
LDA 0x000150
ADD #1
STA 0x000150       ; enemies_killed++
JMP SKIP_E1_ALL

E1_VIVO:
; Se in carica (sta per sparare), resta fermo: nessun movimento
; ne' aggiornamento del generatore pseudo-casuale questo frame.
LDA 0x00012E
CMP #0
JNZ E1_MOVE_DONE

; Aggiorna pseudo-random e valuta cambio direzione. BUG TROVATO: il
; trigger controllava gli STESSI bit (0-4) poi usati per scegliere
; la direzione (0-1) - un sottoinsieme di bit zero implica l'altro
; sottoinsieme zero, quindi la direzione "casuale" risultava SEMPRE
; 0 (su). Ora il trigger controlla i bit 5-9 (indipendenti dai bit
; 0-1 usati per la direzione) - verificato con una simulazione: da
; "sempre su" a distribuzione uniforme sulle 4 direzioni.
LDA 0x00012A
ADD #0x37
STA 0x00012A
AND #0x3E0
CMP #0
JNZ SKIP_E1_DIR
LDA 0x00012A
AND #3
STA 0x000126
SKIP_E1_DIR:

; Muovi 4px nella direzione corrente, rimbalza ai bordi
LDA 0x000126
CMP #0             ; su
JNZ E1_NOT_UP
LDA 0x000122
CMP #100
JLT E1_BOUNCE_UP
SUB #2
STA 0x000122
JMP E1_MOVE_DONE
E1_BOUNCE_UP:
LDA #1
STA 0x000126       ; inverti: giu
JMP E1_MOVE_DONE

E1_NOT_UP:
CMP #1             ; giu
JNZ E1_NOT_DOWN
LDA 0x000122
ADD #2
CMP #669
JGE E1_BOUNCE_DOWN
STA 0x000122
JMP E1_MOVE_DONE
E1_BOUNCE_DOWN:
LDA #672
STA 0x000122
LDA #0
STA 0x000126
JMP E1_MOVE_DONE

E1_NOT_DOWN:
CMP #2             ; sinistra
JNZ E1_NOT_LEFT
LDA 0x000120
CMP #36
JLT E1_BOUNCE_LEFT
SUB #2
STA 0x000120
JMP E1_MOVE_DONE
E1_BOUNCE_LEFT:
LDA #3
STA 0x000126
JMP E1_MOVE_DONE

E1_NOT_LEFT:
; destra
LDA 0x000120
ADD #2
CMP #413
JGE E1_BOUNCE_RIGHT
STA 0x000120
JMP E1_MOVE_DONE
E1_BOUNCE_RIGHT:
LDA #416
STA 0x000120
LDA #2
STA 0x000126
E1_MOVE_DONE:

; -- Nemico 1: sparo pietra, con animazione di CARICA prima dello
; sparo (richiesta dall'utente) - quando si allinea, il nemico non
; spara subito: salva la direzione, resta fermo 40 frame (~0.67s,
; lampeggia per segnalarlo), POI spara. --
LDA 0x00012C       ; shot cooldown
CMP #0
JZ E1_NON_IN_COOLDOWN
SUB #1
STA 0x00012C
JMP SKIP_E1_ALL

E1_NON_IN_COOLDOWN:
LDA 0x00012E          ; gia' in carica?
CMP #0
JNZ E1_CARICA_IN_CORSO

; -- non in carica: controlla allineamento come prima --
LDA 0x000144       ; pietra1 gia attiva?
CMP #0
JNZ SKIP_E1_ALL

; Controlla allineamento X: |px - e1x| < 16
LDA 0x000102
CMP 0x000120
JLT E1_PX_MINORE
SUB 0x000120
CMP #16
JGE E1_CONTROLLA_Y
JMP E1_ALLINEATO_X
E1_PX_MINORE:
LDA 0x000120
SUB 0x000102
CMP #16
JGE E1_CONTROLLA_Y
E1_ALLINEATO_X:
; allineato in X: sparera' in verticale (su/giu) - decide ORA la
; direzione e la salva, non la ricalcola quando la carica finisce
LDA 0x000104
CMP 0x000122
JLT E1_DIR_SU
LDA #1                  ; giu
JMP E1_SALVA_DIR_CARICA
E1_DIR_SU:
LDA #0                    ; su
JMP E1_SALVA_DIR_CARICA

E1_CONTROLLA_Y:
; Controlla allineamento Y: |py - e1y| < 16
LDA 0x000104
CMP 0x000122
JLT E1_PY_MINORE
SUB 0x000122
CMP #16
JGE SKIP_E1_ALL
JMP E1_ALLINEATO_Y
E1_PY_MINORE:
LDA 0x000122
SUB 0x000104
CMP #16
JGE SKIP_E1_ALL
E1_ALLINEATO_Y:
; allineato in Y: sparera' in orizzontale (sx/dx)
LDA 0x000102
CMP 0x000120
JLT E1_DIR_SX
LDA #3                  ; destra
JMP E1_SALVA_DIR_CARICA
E1_DIR_SX:
LDA #2                    ; sinistra

E1_SALVA_DIR_CARICA:
STA 0x000146           ; direzione della pietra, gia' decisa ora
LDA #1
STA 0x00012E              ; avvia la carica
LDA #40
STA 0x000128                 ; durata carica: 40 frame (~0.67s) -
                               ; riusa e1_timer, libero mentre alive=1
JMP SKIP_E1_ALL

E1_CARICA_IN_CORSO:
LDA 0x000128
CMP #0
JNZ E1_CARICA_DECREMENTA

; -- carica completata: spara ORA, con la direzione gia' salvata --
LDA #4
STA 0x042004       ; suono: sparo
LDA 0x000120
STA 0x000140       ; pietra1 parte dalla posizione nemico
LDA 0x000122
STA 0x000142
LDA #1
STA 0x000144       ; pietra1 attiva
LDA #180
STA 0x00012C       ; reset cooldown: 3 secondi a 60fps
LDA #0
STA 0x00012E          ; fine carica
JMP SKIP_E1_ALL

E1_CARICA_DECREMENTA:
LDA 0x000128
SUB #1
STA 0x000128

SKIP_E1_ALL:

; ================================================================
; ---- AGGIORNA NEMICO 2 (struttura identica) ----
LDA 0x000134
CMP #0
JZ SKIP_E2_ALL

CMP #2
JNZ E2_VIVO
LDA 0x000138
CMP #0
JZ E2_MUORE_ORA
SUB #1
STA 0x000138
JMP SKIP_E2_ALL
E2_MUORE_ORA:
LDA #0
STA 0x000134
LDA 0x000150
ADD #1
STA 0x000150
JMP SKIP_E2_ALL

E2_VIVO:
; Se in carica, resta fermo (stesso schema del nemico1)
LDA 0x00013E
CMP #0
JNZ E2_MOVE_DONE

LDA 0x00013A
ADD #0x5B          ; seme diverso da e1
STA 0x00013A
AND #0x3E0            ; stesso fix del nemico1: bit indipendenti da quelli della direzione
CMP #0
JNZ SKIP_E2_DIR
LDA 0x00013A
AND #3
STA 0x000136
SKIP_E2_DIR:

LDA 0x000136
CMP #0
JNZ E2_NOT_UP
LDA 0x000132
CMP #100
JLT E2_BOUNCE_UP
SUB #2
STA 0x000132
JMP E2_MOVE_DONE
E2_BOUNCE_UP:
LDA #1
STA 0x000136
JMP E2_MOVE_DONE

E2_NOT_UP:
CMP #1
JNZ E2_NOT_DOWN
LDA 0x000132
ADD #2
CMP #669
JGE E2_BOUNCE_DOWN
STA 0x000132
JMP E2_MOVE_DONE
E2_BOUNCE_DOWN:
LDA #672
STA 0x000132
LDA #0
STA 0x000136
JMP E2_MOVE_DONE

E2_NOT_DOWN:
CMP #2
JNZ E2_NOT_LEFT
LDA 0x000130
CMP #36
JLT E2_BOUNCE_LEFT
SUB #2
STA 0x000130
JMP E2_MOVE_DONE
E2_BOUNCE_LEFT:
LDA #3
STA 0x000136
JMP E2_MOVE_DONE

E2_NOT_LEFT:
LDA 0x000130
ADD #2
CMP #413
JGE E2_BOUNCE_RIGHT
STA 0x000130
JMP E2_MOVE_DONE
E2_BOUNCE_RIGHT:
LDA #416
STA 0x000130
LDA #2
STA 0x000136
E2_MOVE_DONE:

; -- Nemico 2: sparo pietra, con animazione di CARICA (stesso schema
; del nemico1) --
LDA 0x00013C
CMP #0
JZ E2_NON_IN_COOLDOWN
SUB #1
STA 0x00013C
JMP SKIP_E2_ALL

E2_NON_IN_COOLDOWN:
LDA 0x00013E
CMP #0
JNZ E2_CARICA_IN_CORSO

LDA 0x00014C
CMP #0
JNZ SKIP_E2_ALL

LDA 0x000102
CMP 0x000130
JLT E2_PX_MINORE
SUB 0x000130
CMP #16
JGE E2_CONTROLLA_Y
JMP E2_ALLINEATO_X
E2_PX_MINORE:
LDA 0x000130
SUB 0x000102
CMP #16
JGE E2_CONTROLLA_Y
E2_ALLINEATO_X:
LDA 0x000104
CMP 0x000132
JLT E2_DIR_SU
LDA #1
JMP E2_SALVA_DIR_CARICA
E2_DIR_SU:
LDA #0
JMP E2_SALVA_DIR_CARICA

E2_CONTROLLA_Y:
LDA 0x000104
CMP 0x000132
JLT E2_PY_MINORE
SUB 0x000132
CMP #16
JGE SKIP_E2_ALL
JMP E2_ALLINEATO_Y
E2_PY_MINORE:
LDA 0x000132
SUB 0x000104
CMP #16
JGE SKIP_E2_ALL
E2_ALLINEATO_Y:
LDA 0x000102
CMP 0x000130
JLT E2_DIR_SX
LDA #3
JMP E2_SALVA_DIR_CARICA
E2_DIR_SX:
LDA #2

E2_SALVA_DIR_CARICA:
STA 0x00014E
LDA #1
STA 0x00013E
LDA #40
STA 0x000138          ; riusa e2_timer, libero mentre alive=1
JMP SKIP_E2_ALL

E2_CARICA_IN_CORSO:
LDA 0x000138
CMP #0
JNZ E2_CARICA_DECREMENTA

LDA #4
STA 0x042004       ; suono: sparo
LDA 0x000130
STA 0x000148
LDA 0x000132
STA 0x00014A
LDA #1
STA 0x00014C
LDA #180
STA 0x00013C
LDA #0
STA 0x00013E
JMP SKIP_E2_ALL

E2_CARICA_DECREMENTA:
LDA 0x000138
SUB #1
STA 0x000138

SKIP_E2_ALL:

; ================================================================
; ---- AGGIORNA PIETRA 1 ----
LDA 0x000144
CMP #0
JZ SKIP_S1

; Muovi pietra
LDA 0x000146       ; direzione
CMP #0             ; su
JNZ S1_NOT_UP
LDA 0x000142
CMP #36
JLT DISATTIVA_S1
SUB #3
STA 0x000142
JMP S1_COLLISIONE
S1_NOT_UP:
CMP #1             ; giu
JNZ S1_NOT_DOWN
LDA 0x000142
ADD #3
CMP #730
JGE DISATTIVA_S1
STA 0x000142
JMP S1_COLLISIONE
S1_NOT_DOWN:
CMP #2             ; sinistra
JNZ S1_NOT_LEFT
LDA 0x000140
CMP #36
JLT DISATTIVA_S1
SUB #3
STA 0x000140
JMP S1_COLLISIONE
S1_NOT_LEFT:
; destra
LDA 0x000140
ADD #3
CMP #442
JGE DISATTIVA_S1
STA 0x000140
JMP S1_COLLISIONE
DISATTIVA_S1:
LDA #0
STA 0x000144
JMP SKIP_S1

S1_COLLISIONE:
; Controlla hit giocatore (invincibile se hurtTimer > 0)
LDA 0x00011C
CMP #0
JNZ SKIP_S1

; |s1_x - playerX| < 20
LDA 0x000140
CMP 0x000102
JLT S1_X_NEG
SUB 0x000102
CMP #20
JGE SKIP_S1
JMP S1_CHECK_Y
S1_X_NEG:
LDA 0x000102
SUB 0x000140
CMP #20
JGE SKIP_S1
S1_CHECK_Y:
; |s1_y - playerY| < 20
LDA 0x000142
CMP 0x000104
JLT S1_Y_NEG
SUB 0x000104
CMP #20
JGE SKIP_S1
JMP S1_HIT
S1_Y_NEG:
LDA 0x000104
SUB 0x000142
CMP #20
JGE SKIP_S1
S1_HIT:
LDA #0
STA 0x000144       ; pietra sparisce
LDA 0x00011E       ; playerHP
CMP #0
JZ SKIP_S1         ; gia a 0?
SUB #1
STA 0x00011E
LDA #2
STA 0x042004       ; suono: ferita
LDA #20
STA 0x00011C       ; 20 frame di invincibilita

SKIP_S1:

; ---- AGGIORNA PIETRA 2 (struttura identica) ----
LDA 0x00014C
CMP #0
JZ SKIP_S2

LDA 0x00014E
CMP #0
JNZ S2_NOT_UP
LDA 0x00014A
CMP #36
JLT DISATTIVA_S2
SUB #3
STA 0x00014A
JMP S2_COLLISIONE
S2_NOT_UP:
CMP #1
JNZ S2_NOT_DOWN
LDA 0x00014A
ADD #3
CMP #730
JGE DISATTIVA_S2
STA 0x00014A
JMP S2_COLLISIONE
S2_NOT_DOWN:
CMP #2
JNZ S2_NOT_LEFT
LDA 0x000148
CMP #36
JLT DISATTIVA_S2
SUB #3
STA 0x000148
JMP S2_COLLISIONE
S2_NOT_LEFT:
LDA 0x000148
ADD #3
CMP #442
JGE DISATTIVA_S2
STA 0x000148
JMP S2_COLLISIONE
DISATTIVA_S2:
LDA #0
STA 0x00014C
JMP SKIP_S2

S2_COLLISIONE:
LDA 0x00011C
CMP #0
JNZ SKIP_S2
LDA 0x000148
CMP 0x000102
JLT S2_X_NEG
SUB 0x000102
CMP #20
JGE SKIP_S2
JMP S2_CHECK_Y
S2_X_NEG:
LDA 0x000102
SUB 0x000148
CMP #20
JGE SKIP_S2
S2_CHECK_Y:
LDA 0x00014A
CMP 0x000104
JLT S2_Y_NEG
SUB 0x000104
CMP #20
JGE SKIP_S2
JMP S2_HIT
S2_Y_NEG:
LDA 0x000104
SUB 0x00014A
CMP #20
JGE SKIP_S2
S2_HIT:
LDA #0
STA 0x00014C
LDA 0x00011E
CMP #0
JZ SKIP_S2
SUB #1
STA 0x00011E
LDA #2
STA 0x042004       ; suono: ferita
LDA #20
STA 0x00011C

SKIP_S2:

; ================================================================
; ================================================================
; ---- BOSS (attivo SOLO nella stanza 2, e solo se ancora vivo) ----
LDA 0x000108
CMP #2
JNZ SKIP_BOSS_ALL
LDA 0x000164        ; boss_hp
CMP #0
JZ SKIP_BOSS_ALL      ; sconfitto: niente da aggiornare

; -- scala l'invincibilita' da colpo --
LDA 0x00016E
CMP #0
JZ BOSS_NO_COOL
SUB #1
STA 0x00016E
BOSS_NO_COOL:

; -- due fasi alternate: 0 = movimento, 1 = sparo --
LDA 0x00016C
CMP #0
JNZ BOSS_FASE_SPARO

; ---- FASE MOVIMENTO: scorre a destra o sinistra ----
LDA 0x00016A         ; timer del passo corrente
CMP #0
JZ BOSS_NUOVO_PASSO
SUB #1
STA 0x00016A
; muove 1px nella direzione corrente, con i limiti della stanza
LDA 0x000166
CMP #0
JNZ BOSS_VERSO_DX
LDA 0x000160         ; verso sinistra
CMP #40
JLT BOSS_INVERTI
SUB #1
STA 0x000160
JMP SKIP_BOSS_MOVE
BOSS_VERSO_DX:
LDA 0x000160
CMP #376              ; 480 - 64 (larghezza boss) - 40 di margine
JGE BOSS_INVERTI
ADD #1
STA 0x000160
JMP SKIP_BOSS_MOVE
BOSS_INVERTI:
LDA 0x000166
CMP #0
JZ BOSS_INV_A_DX
LDA #0
STA 0x000166
JMP SKIP_BOSS_MOVE
BOSS_INV_A_DX:
LDA #1
STA 0x000166
JMP SKIP_BOSS_MOVE

BOSS_NUOVO_PASSO:
; un passo e' finito: ne restano altri?
LDA 0x000168
CMP #0
JZ BOSS_PASSA_A_SPARO
SUB #1
STA 0x000168
LDA #24
STA 0x00016A         ; durata del prossimo passo
; alterna la direzione a ogni passo
LDA 0x000166
CMP #0
JZ BOSS_PASSO_DX
LDA #0
STA 0x000166
JMP SKIP_BOSS_MOVE
BOSS_PASSO_DX:
LDA #1
STA 0x000166
JMP SKIP_BOSS_MOVE

BOSS_PASSA_A_SPARO:
LDA #1
STA 0x00016C         ; fase = sparo
LDA #0
STA 0x00016A
SKIP_BOSS_MOVE:
JMP BOSS_FASE_FINE

; ---- FASE SPARO: lancia il fuoco verso il giocatore ----
BOSS_FASE_SPARO:
LDA 0x000174         ; fuoco gia' in gioco?
CMP #0
JNZ BOSS_ASPETTA_FUOCO

; nessun fuoco attivo: creane uno adesso
LDA 0x000160
ADD #16               ; parte dal centro del boss (64/2 - 16)
STA 0x000170
LDA 0x000162
ADD #16
STA 0x000172
LDA #1
STA 0x000174         ; attivo, in volo
LDA #6
STA 0x00017A         ; velocita' iniziale DIMEZZATA (era 13) - stessa
                       ; riduzione applicata a nemici e pietre. Cala di
                       ; 1 al frame come prima: 6+5+4+3+2+1 = 21px
                       ; percorsi prima di fermarsi (era 91px/3 tile -
                       ; la distanza si riduce insieme alla velocita',
                       ; non e' stata chiesta esplicitamente invariata)
LDA #120
STA 0x00017C         ; durata: ~2 secondi a 60fps

; direzione: SEMPRE dritto verso l'alto - cardinale fissa, non
; obliqua. Prima mirava al giocatore su entrambi gli assi (poteva
; volare in diagonale); ora e' un pattern fisso, prevedibile.
LDA #0
STA 0x000176         ; nessuna componente X
LDA #2
STA 0x000178         ; componente Y: su
JMP BOSS_FASE_FINE

BOSS_ASPETTA_FUOCO:
; il fuoco e' ancora in gioco: quando sparisce, torna a muoversi
LDA #0
STA 0x00016C
LDA #2
STA 0x000168          ; di nuovo "un paio" di passi
LDA #24
STA 0x00016A

BOSS_FASE_FINE:

; ---- COLLISIONE SLASH vs BOSS ----
LDA 0x000118          ; attacco attivo?
CMP #0
JZ SKIP_SLASH_BOSS
LDA 0x00016E          ; boss appena colpito? (invincibile)
CMP #0
JNZ SKIP_SLASH_BOSS

; il boss e' 64x64: il suo centro sta a +32,+32 dall'angolo
LDA 0x000160
ADD #32
STA 0x000204          ; bossCenterX (temporaneo)
LDA 0x000162
ADD #32
STA 0x000206          ; bossCenterY

; |slashWorldX - bossCenterX| < 48  (soglia piu' larga: bersaglio grande)
LDA 0x000200
CMP 0x000204
JLT SB_X_NEG
SUB 0x000204
CMP #48
JGE SKIP_SLASH_BOSS
JMP SB_CHECK_Y
SB_X_NEG:
LDA 0x000204
SUB 0x000200
CMP #48
JGE SKIP_SLASH_BOSS
SB_CHECK_Y:
LDA 0x000202
CMP 0x000206
JLT SB_Y_NEG
SUB 0x000206
CMP #48
JGE SKIP_SLASH_BOSS
JMP SLASH_COLPISCE_BOSS
SB_Y_NEG:
LDA 0x000206
SUB 0x000202
CMP #48
JGE SKIP_SLASH_BOSS
SLASH_COLPISCE_BOSS:
LDA 0x000164
SUB #1
STA 0x000164
CMP #0
JNZ BOSS_SOLO_FERITO
LDA #8
STA 0x042004       ; suono: boss sconfitto
JMP BOSS_SUONO_FATTO
BOSS_SOLO_FERITO:
LDA #7
STA 0x042004       ; suono: boss colpito
BOSS_SUONO_FATTO:          ; -1/4 di barra
LDA #20
STA 0x00016E          ; invincibilita' breve: un colpo per fendente
LDA #0
STA 0x000118          ; consuma l'attacco
SKIP_SLASH_BOSS:

; ---- COLLISIONE CORPO BOSS vs GIOCATORE (ruba un cuore) ----
LDA 0x00011C          ; giocatore invincibile?
CMP #0
JNZ SKIP_BOSS_TOUCH
LDA 0x000164          ; boss ancora vivo?
CMP #0
JZ SKIP_BOSS_TOUCH

LDA 0x000160
ADD #32
STA 0x000204
LDA 0x000162
ADD #32
STA 0x000206

LDA 0x000102
CMP 0x000204
JLT BT_X_NEG
SUB 0x000204
CMP #44
JGE SKIP_BOSS_TOUCH
JMP BT_CHECK_Y
BT_X_NEG:
LDA 0x000204
SUB 0x000102
CMP #44
JGE SKIP_BOSS_TOUCH
BT_CHECK_Y:
LDA 0x000104
CMP 0x000206
JLT BT_Y_NEG
SUB 0x000206
CMP #44
JGE SKIP_BOSS_TOUCH
JMP BOSS_TOCCA_GIOCATORE
BT_Y_NEG:
LDA 0x000206
SUB 0x000104
CMP #44
JGE SKIP_BOSS_TOUCH
BOSS_TOCCA_GIOCATORE:
LDA 0x00011E
CMP #0
JZ SKIP_BOSS_TOUCH
SUB #1
STA 0x00011E          ; -1 cuore
LDA #2
STA 0x042004           ; suono: ferita (mancava - trovato testando)
LDA #20
STA 0x00011C          ; invincibilita'
SKIP_BOSS_TOUCH:

SKIP_BOSS_ALL:

; ================================================================
; ---- FUOCO DEL BOSS: rallenta, si ferma, poi svanisce ----
LDA 0x000174
CMP #0
JZ SKIP_FUOCO

; durata: scade dopo ~2 secondi, qualunque sia il suo stato
LDA 0x00017C
CMP #0
JZ FUOCO_SVANISCE
SUB #1
STA 0x00017C

; -- movimento: solo finche' ha ancora velocita' --
LDA 0x00017A
CMP #0
JZ FUOCO_COLLISIONE   ; fermo a terra: salta il movimento

; asse X: si sposta DI 'speed' pixel, non di una quantita' fissa -
; e' questo che produce il rallentamento progressivo
LDA 0x000176
CMP #1
JNZ FUOCO_X_NON_DX
LDA 0x000170
ADD 0x00017A
STA 0x000170
JMP FUOCO_MOVE_Y
FUOCO_X_NON_DX:
CMP #2
JNZ FUOCO_MOVE_Y
LDA 0x000170
SUB 0x00017A
STA 0x000170

; asse Y
FUOCO_MOVE_Y:
LDA 0x000178
CMP #1
JNZ FUOCO_Y_NON_GIU
LDA 0x000172
ADD 0x00017A
STA 0x000172
JMP FUOCO_RALLENTA
FUOCO_Y_NON_GIU:
CMP #2
JNZ FUOCO_RALLENTA
LDA 0x000172
SUB 0x00017A
STA 0x000172

; -- rallentamento: la velocita' cala di 1 ogni frame, e ogni frame
; il fuoco avanza DI QUELLA velocita'. Partendo da 13 percorre
; 13+12+...+1 = 91px prima di fermarsi: quasi esattamente 3 tile
; (96px), come richiesto.
; NOTA: la prima versione muoveva di 2px FISSI mentre la velocita'
; scendeva - percorreva solo 24px (meno di un tile) invece di 3.
; Il rallentamento si vedeva nel valore ma non nel movimento. --
FUOCO_RALLENTA:
LDA 0x00017A
SUB #1
STA 0x00017A

FUOCO_COLLISIONE:
; il fuoco brucia il giocatore sia in volo sia da fermo
LDA 0x00011C
CMP #0
JNZ SKIP_FUOCO

LDA 0x000170
CMP 0x000102
JLT FU_X_NEG
SUB 0x000102
CMP #22
JGE SKIP_FUOCO
JMP FU_CHECK_Y
FU_X_NEG:
LDA 0x000102
SUB 0x000170
CMP #22
JGE SKIP_FUOCO
FU_CHECK_Y:
LDA 0x000172
CMP 0x000104
JLT FU_Y_NEG
SUB 0x000104
CMP #22
JGE SKIP_FUOCO
JMP FUOCO_BRUCIA
FU_Y_NEG:
LDA 0x000104
SUB 0x000172
CMP #22
JGE SKIP_FUOCO
FUOCO_BRUCIA:
LDA #0
STA 0x000174          ; il fuoco si consuma nell'impatto
LDA 0x00011E
CMP #0
JZ SKIP_FUOCO
SUB #1
STA 0x00011E
LDA #2
STA 0x042004       ; suono: ferita
LDA #20
STA 0x00011C
JMP SKIP_FUOCO

FUOCO_SVANISCE:
LDA #0
STA 0x000174

SKIP_FUOCO:

; ---- CONTROLLO VITTORIA: apri grata quando 2 nemici morti ----
LDA 0x000108
CMP #1
JNZ SKIP_GATE_OPEN ; solo da room=1
LDA 0x000150
CMP #2
JLT SKIP_GATE_OPEN
; entrambi morti! passa a stage 3 (grata aperta)
LDA #6
STA 0x042004       ; suono: grata che si apre
LDA #3
STA 0x000108
STA 0x042001       ; select_stage(3)
; deattiva pietre (transizione pulita)
LDA #0
STA 0x000144
STA 0x00014C
SKIP_GATE_OPEN:

; ================================================================
; ---- TELECAMERA ----
LDA 0x000104
CMP #160
JLT SCROLL_ZERO
SUB #160
JMP SCROLL_CALC
SCROLL_ZERO:
LDA #0
SCROLL_CALC:
TAY
CLAMPY 0,448
STY 0x042003
STY 0x00010A

; ================================================================
; ---- TRANSIZIONE SCALE GIU (solo room=3, grata aperta) ----
LDA 0x000108
CMP #3
JNZ CHECK_SCALE_SU
LDA 0x000102
CMP #224
JNZ CHECK_SCALE_SU
LDA 0x000104
CMP #704
JNZ CHECK_SCALE_SU
; scende!
LDA #5
STA 0x042004       ; suono: scale
LDA #2
STA 0x000108
STA 0x042001       ; select_stage(2)
LDA #224
STA 0x000102
LDA #64
STA 0x000104
LDA #0
STA 0x000110
LDA #64
CMP #160
JLT SCROLL2_ZERO
SUB #160
JMP SCROLL2_CALC
SCROLL2_ZERO:
LDA #0
SCROLL2_CALC:
TAY
CLAMPY 0,448
STY 0x042003
STY 0x00010A

; ---- TRANSIZIONE SCALE SU (solo room=2) ----
CHECK_SCALE_SU:
LDA 0x000108
CMP #2
JNZ SKIP_TRANSIZIONI
LDA 0x000102
CMP #224
JNZ SKIP_TRANSIZIONI
LDA 0x000104
CMP #32
JNZ SKIP_TRANSIZIONI
; risale!
LDA #5
STA 0x042004       ; suono: scale
LDA #3
STA 0x000108
STA 0x042001       ; select_stage(3) - torna con grata aperta
LDA #224
STA 0x000102
LDA #672
STA 0x000104
LDA #0
STA 0x000110
LDA #672
SUB #160
TAY
CLAMPY 0,448
STY 0x042003
STY 0x00010A

SKIP_TRANSIZIONI:

; ================================================================
; ---- DISEGNA TUTTO ----

; Posizione schermo giocatore
LDX 0x000102
LDA 0x000104
SUB 0x00010A
TAY

; -- Giocatore (con lampeggio se ferito) --
LDA 0x00011C       ; hurtTimer
AND #2             ; bit1: lampeggia ogni 2 frame
CMP #0
JNZ NASCONDI_GIOCATORE
STX 0x040000
STY 0x040002
LDA #11
STA 0x040004
LDA #0
STA 0x040006
JMP GIOCATORE_FATTO
NASCONDI_GIOCATORE:
LDA #0
STA 0x040000
LDA #0xFFFF
STA 0x040002
GIOCATORE_FATTO:

; -- Cuori HUD (tre cuori fissi a schermo, spariscono con i danni) --
; Cuore 1
LDA 0x00011E       ; playerHP
CMP #1
JLT NASCONDI_H1
LDA #8
STA 0x040008
LDA #8
STA 0x04000A
LDA #12
STA 0x04000C
LDA #0
STA 0x04000E
JMP H1_FATTO
NASCONDI_H1:
LDA #0xFFFF
STA 0x04000A
H1_FATTO:

; Cuore 2
LDA 0x00011E
CMP #2
JLT NASCONDI_H2
LDA #44
STA 0x040010
LDA #8
STA 0x040012
LDA #12
STA 0x040014
LDA #0
STA 0x040016
JMP H2_FATTO
NASCONDI_H2:
LDA #0xFFFF
STA 0x040012
H2_FATTO:

; Cuore 3
LDA 0x00011E
CMP #3
JLT NASCONDI_H3
LDA #80
STA 0x040018
LDA #8
STA 0x04001A
LDA #12
STA 0x04001C
LDA #0
STA 0x04001E
JMP H3_FATTO
NASCONDI_H3:
LDA #0xFFFF
STA 0x04001A
H3_FATTO:

; -- Spada/Slash (OAM slot 4) --
LDA 0x000118
CMP #0
JZ NASCONDI_SLASH

; Posizione schermo dalla posizione mondo
LDA 0x000200       ; slashWorldX
STA 0x040020
LDA 0x000202       ; slashWorldY
SUB 0x00010A       ; - scrollY
STA 0x040022
; Tile: frame1 se timer>=5, frame2 se timer<5
LDA 0x000118
CMP #5
JLT USA_SLASH2
LDA #14
STA 0x040024
JMP SLASH_ATTR
USA_SLASH2:
LDA #15
STA 0x040024
SLASH_ATTR:
LDA #0
STA 0x040026
JMP SLASH_FATTO
NASCONDI_SLASH:
LDA #0
STA 0x040020
LDA #0xFFFF
STA 0x040022
SLASH_FATTO:

; -- Nemico 1 (OAM slot 5) --
LDA 0x000124
CMP #0
JZ NASCONDI_E1
; vivo o animazione morte?
CMP #2
JNZ E1_NORMALE
; animazione morte: tile stella
LDA 0x000120
STA 0x040028
LDA 0x000122
SUB 0x00010A
STA 0x04002A
LDA #19
STA 0x04002C
LDA #0
STA 0x04002E
JMP E1_FATTO
E1_NORMALE:
; lampeggia durante la carica (segnala che sta per sparare)
LDA 0x00012E
CMP #0
JZ E1_DISEGNA_NORMALE
LDA 0x000128
AND #2
CMP #0
JNZ NASCONDI_E1
E1_DISEGNA_NORMALE:
LDA 0x000120
STA 0x040028
LDA 0x000122
SUB 0x00010A
STA 0x04002A
LDA #16
STA 0x04002C
LDA #0
STA 0x04002E
JMP E1_FATTO
NASCONDI_E1:
LDA #0
STA 0x040028
LDA #0xFFFF
STA 0x04002A
E1_FATTO:

; -- Nemico 2 (OAM slot 6) --
LDA 0x000134
CMP #0
JZ NASCONDI_E2
CMP #2
JNZ E2_NORMALE
LDA 0x000130
STA 0x040030
LDA 0x000132
SUB 0x00010A
STA 0x040032
LDA #19
STA 0x040034
LDA #0
STA 0x040036
JMP E2_FATTO
E2_NORMALE:
LDA 0x00013E
CMP #0
JZ E2_DISEGNA_NORMALE
LDA 0x000138
AND #2
CMP #0
JNZ NASCONDI_E2
E2_DISEGNA_NORMALE:
LDA 0x000130
STA 0x040030
LDA 0x000132
SUB 0x00010A
STA 0x040032
LDA #16
STA 0x040034
LDA #0
STA 0x040036
JMP E2_FATTO
NASCONDI_E2:
LDA #0
STA 0x040030
LDA #0xFFFF
STA 0x040032
E2_FATTO:

; -- Pietra 1 (OAM slot 7) --
LDA 0x000144
CMP #0
JZ NASCONDI_S1
LDA 0x000140
STA 0x040038
LDA 0x000142
SUB 0x00010A
STA 0x04003A
LDA #17
STA 0x04003C
LDA #0
STA 0x04003E
JMP S1_OAM_FATTO
NASCONDI_S1:
LDA #0
STA 0x040038
LDA #0xFFFF
STA 0x04003A
S1_OAM_FATTO:

; -- Pietra 2 (OAM slot 8) --
LDA 0x00014C
CMP #0
JZ NASCONDI_S2
LDA 0x000148
STA 0x040040
LDA 0x00014A
SUB 0x00010A
STA 0x040042
LDA #17
STA 0x040044
LDA #0
STA 0x040046
JMP S2_OAM_FATTO
NASCONDI_S2:
LDA #0
STA 0x040040
LDA #0xFFFF
STA 0x040042
S2_OAM_FATTO:

; -- BOSS (OAM slot 9): un solo slot, attr=0x01 -> griglia 2x2 (64x64).
; Il PPU legge da solo i 4 tile consecutivi 20,21,22,23 --
LDA 0x000108
CMP #2
JNZ NASCONDI_BOSS
LDA 0x000164          ; hp
CMP #0
JZ NASCONDI_BOSS
; lampeggia quando ha appena incassato un colpo
LDA 0x00016E
AND #2
CMP #0
JNZ NASCONDI_BOSS
LDA 0x000160
STA 0x040048
; conversione mondo->schermo. ATTENZIONE: se boss_y < scrollY la
; sottrazione va sotto zero e, essendo i registri SENZA SEGNO, si
; avvolge a un numero enorme (>= 0xFFF0) che il PPU interpreta come
; "sprite nascosto" - il boss spariva. Stessa insidia gia' vista
; per la telecamera: si controlla PRIMA di sottrarre.
LDA 0x000162
CMP 0x00010A
JLT NASCONDI_BOSS      ; sopra il bordo alto dello schermo: non disegnarlo
SUB 0x00010A
STA 0x04004A
LDA #20
STA 0x04004C          ; primo tile della griglia 2x2
LDA #1
STA 0x04004E          ; attr: bit0-1 = 01 -> 64x64
JMP BOSS_OAM_FATTO
NASCONDI_BOSS:
LDA #0
STA 0x040048
LDA #0xFFFF
STA 0x04004A
BOSS_OAM_FATTO:

; -- FUOCO (OAM slot 10) --
LDA 0x000174
CMP #0
JZ NASCONDI_FUOCO
LDA 0x000170
STA 0x040050
LDA 0x000172
CMP 0x00010A
JLT NASCONDI_FUOCO     ; sopra il bordo alto: stessa insidia del boss
SUB 0x00010A
STA 0x040052
LDA #24
STA 0x040054
LDA #0
STA 0x040056
JMP FUOCO_OAM_FATTO
NASCONDI_FUOCO:
LDA #0
STA 0x040050
LDA #0xFFFF
STA 0x040052
FUOCO_OAM_FATTO:

; -- BARRA VITA BOSS (OAM slot 11-14): SOLO nella stanza del boss.
; Coordinate schermo fisse come i cuori - e' HUD, non scrolla.
; Ogni segmento e' pieno (25) o vuoto (26) a seconda di boss_hp --
LDA 0x000108
CMP #2
JNZ NASCONDI_BARRA
LDA 0x000164
CMP #0
JZ NASCONDI_BARRA

; segmento 1
LDA #176
STA 0x040058
LDA #8
STA 0x04005A
LDA 0x000164
CMP #1
JLT BARRA1_VUOTA
LDA #25
JMP BARRA1_SCRIVI
BARRA1_VUOTA:
LDA #26
BARRA1_SCRIVI:
STA 0x04005C
LDA #0
STA 0x04005E

; segmento 2
LDA #208
STA 0x040060
LDA #8
STA 0x040062
LDA 0x000164
CMP #2
JLT BARRA2_VUOTA
LDA #25
JMP BARRA2_SCRIVI
BARRA2_VUOTA:
LDA #26
BARRA2_SCRIVI:
STA 0x040064
LDA #0
STA 0x040066

; segmento 3
LDA #240
STA 0x040068
LDA #8
STA 0x04006A
LDA 0x000164
CMP #3
JLT BARRA3_VUOTA
LDA #25
JMP BARRA3_SCRIVI
BARRA3_VUOTA:
LDA #26
BARRA3_SCRIVI:
STA 0x04006C
LDA #0
STA 0x04006E

; segmento 4
LDA #272
STA 0x040070
LDA #8
STA 0x040072
LDA 0x000164
CMP #4
JLT BARRA4_VUOTA
LDA #25
JMP BARRA4_SCRIVI
BARRA4_VUOTA:
LDA #26
BARRA4_SCRIVI:
STA 0x040074
LDA #0
STA 0x040076
JMP BARRA_FATTA

NASCONDI_BARRA:
LDA #0xFFFF
STA 0x04005A
STA 0x040062
STA 0x04006A
STA 0x040072
BARRA_FATTA:

FINE_FRAME:
HALT

; ================================================================
; ---- GAME OVER: teschio al posto del giocatore, tutto il resto
; nascosto, 3 secondi (180 frame) poi torna al titolo ----
GAME_OVER:
LDA 0x000180
CMP #0
JZ GAME_OVER_RESET
SUB #1
STA 0x000180

; -- teschio: posizione fissa, sopra il testo GAME OVER (non
; sovrapposto - il testo occupa y=160-192, il teschio sta a
; y=100-132, con margine tra i due) --
LDA #224
STA 0x040000
LDA #100
STA 0x040002
LDA #27
STA 0x040004        ; SKULL_TILE_IDX
LDA #0
STA 0x040006

; -- nasconde tutto il resto: cuori, slash, nemici, pietre, boss,
; fuoco, barra vita - una schermata di game over pulita, senza
; residui della partita appena persa --
LDA #0xFFFF
STA 0x04000A
STA 0x040012
STA 0x04001A
STA 0x040022
STA 0x04002A
STA 0x040032
STA 0x04003A
STA 0x040042
STA 0x04004A
STA 0x040052
STA 0x04005A
STA 0x040062
STA 0x04006A
STA 0x040072

JMP FINE_FRAME

GAME_OVER_RESET:
; -- torna al titolo: mode=0 e select_stage(0) ricarica la tilemap
; "PRESS J START" - senza questo, lo schermo resterebbe bloccato
; sulla scritta GAME OVER anche tornando al titolo, dato che quella
; scritta ha sovrascritto permanentemente la tilemap in VRAM --
LDA #0
STA 0x000100
STA 0x042001
JMP FINE_FRAME
