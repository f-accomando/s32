from lang import compile_source
from assembler import assemble
from cpu import CPU

fails = 0

def check(label, got, expected):
    global fails
    status = "OK  " if got == expected else "FAIL"
    if got != expected:
        fails += 1
    print(f"{status} {label}: atteso {expected!r}, ottenuto {got!r}")

def run(src, input_byte=0, base_addr=0x1000, **init):
    r = compile_source(src, var_base=0x2000)
    rom = assemble(r['asm'], base_addr=base_addr)
    c = CPU()
    for i, b in enumerate(rom):
        c.mem[base_addr + i] = b
    for name, (addr, init_val) in r['state_vars'].items():
        c.mem[addr] = init_val & 0xff
        c.mem[addr+1] = (init_val >> 8) & 0xff
    for k, v in init.items():
        setattr(c, k, v)
    c.run(base_addr, input_byte=input_byte)
    return c, r

# ---------------------------------------------------------------
# Test 1: var + assegnazione
# ---------------------------------------------------------------
r1 = compile_source("var x = 5\nx = x + 3\n", var_base=0x2000)
rom1 = assemble(r1['asm'], base_addr=0x1000)
c1b = CPU()
for i, b in enumerate(rom1): c1b.mem[0x1000+i] = b
c1b.run(0x1000)
check("var + assegnazione (5+3=8)", c1b.read16(r1['vars']['x']), 8)

# ---------------------------------------------------------------
# Test 2: if/else con CMP (condizione normale, non confronto <)
# ---------------------------------------------------------------
c2a, _ = run("""
var tile = 3
if (input() & 16) {
    tile = 4
} else {
    tile = 9
}
write_oam(0, 1, 2, tile, 0)
""", input_byte=16)
from memory_map import OAM_BASE
check("if vero (bit16) -> tile 4", c2a.read16(OAM_BASE + 4), 4)

c2b, _ = run("""
var tile = 3
if (input() & 16) {
    tile = 4
} else {
    tile = 9
}
write_oam(0, 1, 2, tile, 0)
""", input_byte=0)
check("if falso -> ramo else -> tile 9", c2b.read16(OAM_BASE + 4), 9)

# ---------------------------------------------------------------
# Test 3: confronto '<' con CMP (if e ternario)
# ---------------------------------------------------------------
c3a, _ = run("""
var a = 5
var b = 10
var esito = 0
if (a < b) {
    esito = 1
} else {
    esito = 2
}
write_oam(0, esito, 0, 0, 0)
""")
check("if (5<10): vero", c3a.read16(OAM_BASE), 1)

c3b, _ = run("""
var a = 20
var b = 10
var esito = a < b ? 100 : 200
write_oam(0, esito, 0, 0, 0)
""")
check("ternario con confronto <: falso", c3b.read16(OAM_BASE), 200)

# ---------------------------------------------------------------
# Test 4: ternario con ':' omesso (default = valore attuale)
# ---------------------------------------------------------------
r4 = compile_source("""
regy = input() & 1 ? regy - 2
write_oam(0, 0, regy, 0, 0)
""", var_base=0x2000)
rom4 = assemble(r4['asm'], base_addr=0x1000)
c4a = CPU(); c4a.y = 100
for i, b in enumerate(rom4): c4a.mem[0x1000+i] = b
c4a.run(0x1000, input_byte=1)
check("ternario senza ':': vero (100-2)", c4a.read16(OAM_BASE+2), 98)

c4b = CPU(); c4b.y = 100
for i, b in enumerate(rom4): c4b.mem[0x1000+i] = b
c4b.run(0x1000, input_byte=0)
check("ternario senza ':': falso (invariato)", c4b.read16(OAM_BASE+2), 100)

# ---------------------------------------------------------------
# Test 5: func con salvataggio/ripristino AUTOMATICO di X/Y
# ---------------------------------------------------------------
r5 = compile_source("""
var enemyX = 100

func move_enemy() {
    regx = enemyX
    regx = regx + 1
    enemyX = regx
    write_oam(1, regx, 60, 5, 0)
}

regx = 77
call move_enemy()
write_oam(0, regx, 88, 3, 0)
""", var_base=0x2000)
rom5 = assemble(r5['asm'], base_addr=0x1000)
c5 = CPU()
for i, b in enumerate(rom5): c5.mem[0x1000+i] = b
c5.run(0x1000)
check("[func] enemyX aggiornata dalla funzione", c5.read16(r5['vars']['enemyX']), 101)
check("[func] regx RIPRISTINATO dopo call (era 77 prima)", c5.read16(OAM_BASE), 77)

# ---------------------------------------------------------------
# Test 6: NOVITA' rispetto a v1 - return ANTICIPATO ripristina
# X/Y correttamente (in v1 questo era un limite noto/documentato)
# ---------------------------------------------------------------
r6 = compile_source("""
func forse_esci() {
    regx = 999
    if (input() & 1) {
        return
    }
    regx = 111
}

regx = 42
call forse_esci()
write_oam(0, regx, 0, 0, 0)
""", var_base=0x2000)
rom6 = assemble(r6['asm'], base_addr=0x1000)

c6a = CPU()
for i, b in enumerate(rom6): c6a.mem[0x1000+i] = b
c6a.run(0x1000, input_byte=1)  # return anticipato preso
check("[NOVITA'] return anticipato: X ripristinato correttamente (42)", c6a.read16(OAM_BASE), 42)

c6b = CPU()
for i, b in enumerate(rom6): c6b.mem[0x1000+i] = b
c6b.run(0x1000, input_byte=0)  # return anticipato NON preso, la funzione continua
check("return non preso: X resta ripristinato al valore chiamante (42)", c6b.read16(OAM_BASE), 42)

# ---------------------------------------------------------------
# Test 7: state (persistente tra i frame)
# ---------------------------------------------------------------
r7 = compile_source("""
state counter = 10
counter = counter + 1
write_oam(0, counter, 0, 0, 0)
""", var_base=0x2000)
rom7 = assemble(r7['asm'], base_addr=0x1000)
addr, init_val = r7['state_vars']['counter']
c7 = CPU()
for i, b in enumerate(rom7): c7.mem[0x1000+i] = b
c7.write16(addr, init_val)
c7.run(0x1000)
check("[state] frame 1: 10+1=11", c7.read16(OAM_BASE), 11)
c7.run(0x1000)
check("[state] frame 2: continua da 11 (non riparte da 10!)", c7.read16(OAM_BASE), 12)

# ---------------------------------------------------------------
# Test 8: CASO REALE - ABS_DIFF con CMP invece di SUB
# ---------------------------------------------------------------
r8 = compile_source("""
var playerX = 100
var enemyX = 130
var dx = 0
if (playerX < enemyX) {
    dx = enemyX - playerX
} else {
    dx = playerX - enemyX
}
write_oam(0, dx, 0, 0, 0)
""", var_base=0x2000)
rom8 = assemble(r8['asm'], base_addr=0x1000)
c8 = CPU()
for i, b in enumerate(rom8): c8.mem[0x1000+i] = b
c8.run(0x1000)
check("ABS_DIFF in ConsoleLang S32: |100-130|=30", c8.read16(OAM_BASE), 30)

# ---------------------------------------------------------------
# Test 9: poke() - scrittura diretta a un indirizzo letterale
# ---------------------------------------------------------------
r9 = compile_source("""
poke(0x001000, 42)
var x = 10
poke(0x001002, x + 5)
""", var_base=0x2000)
rom9 = assemble(r9['asm'], base_addr=0x1000)
c9 = CPU()
for i, b in enumerate(rom9): c9.mem[0x1000+i] = b
c9.run(0x1000)
check("poke con valore letterale", c9.read16(0x001000), 42)
check("poke con espressione", c9.read16(0x001002), 15)

# ---------------------------------------------------------------
# Test 10: letterali esadecimali ovunque un numero e' atteso
# ---------------------------------------------------------------
r10 = compile_source("""
var x = 0xFF
poke(0x001004, x)
""", var_base=0x2000)
rom10 = assemble(r10['asm'], base_addr=0x1000)
c10 = CPU()
for i, b in enumerate(rom10): c10.mem[0x1000+i] = b
c10.run(0x1000)
check("letterale esadecimale in var", c10.read16(0x001004), 255)

# ---------------------------------------------------------------
# Test 11: select_stage()
# ---------------------------------------------------------------
from cpu import PORT_STAGE_SELECT
r11 = compile_source("""
select_stage(1)
""", var_base=0x2000)
rom11 = assemble(r11['asm'], base_addr=0x1000)
c11 = CPU()
c11.stages[1] = bytearray([0xAB] * 32768)
for i, b in enumerate(rom11): c11.mem[0x1000+i] = b
c11.run(0x1000)
check("select_stage(1)", c11.current_stage, 1)

# ---------------------------------------------------------------
# Test 12: set_scroll()
# ---------------------------------------------------------------
r12 = compile_source("""
set_scroll(50, 100)
""", var_base=0x2000)
rom12 = assemble(r12['asm'], base_addr=0x1000)
c12 = CPU()
for i, b in enumerate(rom12): c12.mem[0x1000+i] = b
c12.run(0x1000)
check("set_scroll: scroll_x", c12.scroll_x, 50)
check("set_scroll: scroll_y", c12.scroll_y, 100)

# ---------------------------------------------------------------
# Test 13: operatore XOR (^)
# ---------------------------------------------------------------
r13 = compile_source("""
var a = 3
var b = a ^ 1
poke(0x001000, b)
""", var_base=0x2000)
rom13 = assemble(r13['asm'], base_addr=0x1000)
c13 = CPU()
for i, b in enumerate(rom13): c13.mem[0x1000+i] = b
c13.run(0x1000)
check("operatore XOR: 3^1", c13.read16(0x001000), 2)

# ---------------------------------------------------------------
# input(N): multiplayer locale - un giocatore per porta
# ---------------------------------------------------------------
from cpu import PORT_INPUT, EXTRA_INPUT_PORTS

# input() senza argomenti deve restare identico a prima: legge
# SOLO la porta del giocatore 0 (PORT_INPUT), come sempre
r14 = compile_source("""
var x = input()
poke(0x001000, x)
""", var_base=0x2000)
rom14 = assemble(r14['asm'], base_addr=0x1000)
c14 = CPU()
for i, b in enumerate(rom14): c14.mem[0x1000+i] = b
c14.run(0x1000, input_byte=0x11, extra_inputs=(0x99,))  # rumore sul giocatore 2: non deve influenzare
check("input() senza argomenti: legge SOLO PORT_INPUT (giocatore 0), invariato",
      c14.read16(0x001000), 0x11)

# input(0) deve essere ESATTAMENTE equivalente a input() - stessa porta
r15 = compile_source("""
var x = input(0)
poke(0x001000, x)
""", var_base=0x2000)
rom15 = assemble(r15['asm'], base_addr=0x1000)
c15 = CPU()
for i, b in enumerate(rom15): c15.mem[0x1000+i] = b
c15.run(0x1000, input_byte=0x22)
check("input(0): equivalente a input() - stessa porta, stesso risultato",
      c15.read16(0x001000), 0x22)

# le due porte devono rispondere in modo DAVVERO indipendente - il
# cuore della richiesta (multiplayer locale, un giocatore per porta)
r16 = compile_source("""
var p1 = input(0)
var p2 = input(1)
poke(0x001000, p1)
poke(0x001002, p2)
""", var_base=0x2000)
rom16 = assemble(r16['asm'], base_addr=0x1000)
c16 = CPU()
for i, b in enumerate(rom16): c16.mem[0x1000+i] = b
c16.run(0x1000, input_byte=0x05, extra_inputs=(0x0A,))  # giocatore1=su+giu, giocatore2=sx+dx (diverso)
check("input(0)/input(1): porte indipendenti - giocatore 1 legge il proprio valore",
      c16.read16(0x001000), 0x05)
check("input(0)/input(1): porte indipendenti - giocatore 2 legge il PROPRIO valore, non quello del giocatore 1",
      c16.read16(0x001002), 0x0A)

# tutti e 8 i giocatori, un giro completo - 8 poke individuali (non
# una somma: ConsoleLang supporta un solo operatore per espressione,
# "a + b", non catene lunghe "a+b+c+...", limite preesistente del
# linguaggio - non e' quello che questa patch doveva cambiare)
r17 = compile_source("""
poke(0x001000, input(0))
poke(0x001002, input(1))
poke(0x001004, input(2))
poke(0x001006, input(3))
poke(0x001008, input(4))
poke(0x00100A, input(5))
poke(0x00100C, input(6))
poke(0x00100E, input(7))
""", var_base=0x2000)
rom17 = assemble(r17['asm'], base_addr=0x1000)
c17 = CPU()
for i, b in enumerate(rom17): c17.mem[0x1000+i] = b
c17.run(0x1000, input_byte=1, extra_inputs=(2, 3, 4, 5, 6, 7, 8))
valori_letti = [c17.read16(0x001000 + i*2) for i in range(8)]
check("input(0)..input(7): tutti e 8 i giocatori, ciascuno legge il proprio valore",
      valori_letti, [1, 2, 3, 4, 5, 6, 7, 8])

# range non valido: deve fallire in modo chiaro, non silenziosamente
try:
    compile_source("var x = input(8)\n", var_base=0x2000)
    check("input(8): fuori range - doveva sollevare SyntaxError", False, True)
except SyntaxError:
    check("input(8): fuori range - solleva SyntaxError come atteso", True, True)

try:
    compile_source("var x = input(-1)\n", var_base=0x2000)
    check("input(-1): fuori range - doveva sollevare SyntaxError", False, True)
except SyntaxError:
    check("input(-1): fuori range - solleva SyntaxError come atteso", True, True)

print()
if fails == 0:
    print("Tutti i test passati.")
else:
    print(f"{fails} test falliti.")
