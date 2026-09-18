from assembler import assemble, AssemblerError
from cpu import CPU

fails = 0

def check(label, got, expected):
    global fails
    status = "OK  " if got == expected else "FAIL"
    if got != expected:
        fails += 1
    print(f"{status} {label}: atteso {expected!r}, ottenuto {got!r}")

def run(src, base_addr=0x1000, input_byte=0):
    rom = assemble(src, base_addr=base_addr)
    c = CPU()
    for i, b in enumerate(rom):
        c.mem[base_addr + i] = b
    c.run(base_addr, input_byte=input_byte)
    return c

# ---------------------------------------------------------------
# Test 1: LDA/STA, disambiguazione immediato vs indirizzo
# ---------------------------------------------------------------
c1 = run("""
LDA #1234
STA 0x2000
LDA 0x2000
HALT
""")
check("LDA #imm poi STA poi LDA addr: valore ritrovato", c1.a, 1234)

# ---------------------------------------------------------------
# Test 2: LDX/STX/LDY/STY con significato vero (non A=X)
# ---------------------------------------------------------------
c2 = run("""
LDX #55
LDY #66
STX 0x2000
STY 0x2002
HALT
""")
check("LDX diretto", c2.x, 55)
check("LDY diretto", c2.y, 66)
check("STX su indirizzo", c2.read16(0x2000), 55)
check("STY su indirizzo", c2.read16(0x2002), 66)

# ---------------------------------------------------------------
# Test 3: trasferimenti
# ---------------------------------------------------------------
c3 = run("""
LDA #999
TAX
TAY
HALT
""")
check("TAX", c3.x, 999)
check("TAY", c3.y, 999)

# ---------------------------------------------------------------
# Test 4: ALU immediata e indirizzo insieme, con etichette avanti
# e indietro
# ---------------------------------------------------------------
c4 = run("""
JMP INIZIO
DATI_NON_RAGGIUNTI:
LDA #0
HALT
INIZIO:
LDA #100
STA 0x2000
SUB_ADDR_TEST:
LDA #30
SUB 0x2000
HALT
""")
check("etichetta in AVANTI (JMP INIZIO) funziona (30-100, avvolto a 16 bit)", c4.a, (30 - 100) & 0xffff)

# ---------------------------------------------------------------
# Test 5: CMP non distrugge A, e i salti JLT/JGE funzionano da
# programma assemblato vero
# ---------------------------------------------------------------
c5 = run("""
LDA #10
CMP #20
JLT MINORE
LDA #999
HALT
MINORE:
LDA #1
HALT
""")
check("CMP + JLT: preso quando 10<20", c5.a, 1)

c5b = run("""
LDA #50
CMP #20
JLT MINORE
LDA #999
HALT
MINORE:
LDA #1
HALT
""")
check("CMP + JLT: NON preso quando 50>=20", c5b.a, 999)

# ---------------------------------------------------------------
# Test 6: JSR/RTS assemblati, con etichetta della subroutine DOPO
# il chiamante (avanti) - stack hardware vero
# ---------------------------------------------------------------
c6 = run("""
JSR SOTTOPROGRAMMA
STA 0x2000
HALT
SOTTOPROGRAMMA:
LDA #42
RTS
""")
check("JSR verso etichetta in avanti + RTS", c6.read16(0x2000), 42)

# ---------------------------------------------------------------
# Test 7: CLAMPX/CLAMPY
# ---------------------------------------------------------------
c7 = run("""
LDX #500
CLAMPX 10,100
HALT
""")
check("CLAMPX: valore sopra il massimo viene limitato", c7.x, 100)

c7b = run("""
LDX #5
CLAMPX 10,100
HALT
""")
check("CLAMPX: valore sotto il minimo viene limitato", c7b.x, 10)

# ---------------------------------------------------------------
# Test 8: PHA/PLA in un programma assemblato vero
# ---------------------------------------------------------------
c8 = run("""
LDA #777
PHA
LDA #0
PLA
HALT
""")
check("PHA/PLA assemblati", c8.a, 777)

# ---------------------------------------------------------------
# Test 9: errori chiari (non crash silenziosi/comportamento indefinito)
# ---------------------------------------------------------------
try:
    assemble("FANTASIA #1\nHALT\n")
    check("istruzione sconosciuta: solleva errore", "nessun errore", "AssemblerError")
except AssemblerError:
    check("istruzione sconosciuta: solleva errore", "AssemblerError", "AssemblerError")

try:
    assemble("LDA 0x2000\nHALT\n")  # LDA senza '#' e senza etichetta valida per un indirizzo numerico va bene, ma proviamo un ADD malformato
    assemble("ADD 0x2000\nHALT\n")  # questo e' valido (modalita' indirizzo), non deve dare errore
    check("ADD in modalita' indirizzo (senza #) non da' errore", True, True)
except AssemblerError:
    check("ADD in modalita' indirizzo (senza #) non da' errore", False, True)

# ---------------------------------------------------------------
# Test 10: base_addr diverso da zero - le etichette devono comunque
# risolversi correttamente (rilevante: il vero motore carichera' i
# programmi non necessariamente a indirizzo 0)
# ---------------------------------------------------------------
c10 = run("""
JMP DOPO
LDA #0
HALT
DOPO:
LDA #55
HALT
""", base_addr=0x5000)
check("assemblaggio con base_addr diverso da zero", c10.a, 55)

print()
if fails == 0:
    print("Tutti i test passati.")
else:
    print(f"{fails} test falliti.")
