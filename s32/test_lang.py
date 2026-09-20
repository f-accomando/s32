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
# Test 14: peek(indirizzo) - controparte in lettura di poke(), aggiunta
# per leggere l'input dei giocatori 2-4 (PORT_INPUT_P2/P3/P4, vedi
# cpu.py e carts/barebone_p2p/)
# ---------------------------------------------------------------
r14 = compile_source("""
var p2 = peek(0x042005)
poke(0x001000, p2)
""", var_base=0x2000)
rom14 = assemble(r14['asm'], base_addr=0x1000)
c14 = CPU()
for i, b in enumerate(rom14): c14.mem[0x1000+i] = b
c14.run(0x1000, input_p2=9)
check("peek(indirizzo letterale): legge il valore scritto li'", c14.read16(0x001000), 9)

# peek() usato direttamente in una condizione, come fara' davvero
# barebone_p2p per leggere il tasto premuto dal giocatore 2
r14b = compile_source("""
var out = 0
if (peek(0x042005) & 1) {
    out = 77
}
poke(0x001000, out)
""", var_base=0x2000)
rom14b = assemble(r14b['asm'], base_addr=0x1000)
c14b = CPU()
for i, b in enumerate(rom14b): c14b.mem[0x1000+i] = b
c14b.run(0x1000, input_p2=1)  # bit UP premuto
check("peek() dentro if(): legge un bit dell'input del giocatore 2", c14b.read16(0x001000), 77)

# indirizzo non letterale: deve restare un errore chiaro, stesso
# vincolo di poke() (la CPU non ha indirizzamento indicizzato)
try:
    compile_source("var addr = 0x042005\nvar x = peek(addr)\n", var_base=0x2000)
    check("peek() con indirizzo non letterale: solleva SyntaxError", "nessun errore", "SyntaxError")
except SyntaxError:
    check("peek() con indirizzo non letterale: solleva SyntaxError", "SyntaxError", "SyntaxError")

print()
if fails == 0:
    print("Tutti i test passati.")
else:
    print(f"{fails} test falliti.")
