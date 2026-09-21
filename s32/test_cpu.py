from cpu import (
    CPU,
    PORT_INPUT,
    PORT_STAGE_SELECT,
    PORT_SCROLL_X,
    PORT_SCROLL_Y,
    EXTRA_INPUT_PORTS,
    ALL_INPUT_PORTS,
    PORT_SOUND,
)
from memory_map import (
    FLAG_ZERO,
    FLAG_NEGATIVE,
    FLAG_CARRY,
    FLAG_OVERFLOW,
    WRAM_END,
    WRAM_BASE,
    VRAM_BASE,
    TILEMAP_VRAM_OFFSET,
    TILEMAP_BYTES,
)

fails = 0

def check(label, got, expected):
    global fails
    status = "OK  " if got == expected else "FAIL"
    if got != expected:
        fails += 1
    print(f"{status} {label}: atteso {expected!r}, ottenuto {got!r}")

def load(cpu, addr, bytes_list):
    for i, b in enumerate(bytes_list):
        cpu.mem[addr + i] = b

def u16(v):
    return [v & 0xff, (v >> 8) & 0xff]

def u24(v):
    return [v & 0xff, (v >> 8) & 0xff, (v >> 16) & 0xff]

START = 0x1000  # zona di WRAM lontana dallo stack e dai dati di test

# ---------------------------------------------------------------
# Test 1: LDA/STA immediato e indirizzo
#
# Ogni test e' isolato in una funzione: la CPU() creata al suo
# interno (mem = 16MB, vedi memory_map.ADDRESS_SPACE) viene liberata
# non appena la funzione ritorna, invece di restare viva fino alla
# fine del file - con 31 CPU() a livello di modulo tutte insieme
# servirebbero ~500MB, troppi per hardware con RAM limitata (es.
# Raspberry Pi 1: "Killed" per OOM gia' durante l'import del file).
# ---------------------------------------------------------------
def test_lda_sta_imm_addr():
    c1 = CPU()
    prog = [0x10, *u16(4660)] + [0x12, *u24(0x2000)] + [0x11, *u24(0x2000)] + [0x01]
    load(c1, START, prog)
    c1.run(START)
    check("LDA #imm -> A", c1.a, 4660)
    check("STA addr -> memoria", c1.read16(0x2000), 4660)

def test_lda_addr():
    c2 = CPU()
    c2.write16(0x2000, 9999)
    prog2 = [0x11, *u24(0x2000), 0x01]
    load(c2, START, prog2)
    c2.run(START)
    check("LDA addr", c2.a, 9999)

# ---------------------------------------------------------------
# Test 2: LDX/STX/LDY/STY - significato VERO (memoria, non A=X)
# ---------------------------------------------------------------
def test_ldx_stx_ldy_sty():
    c3 = CPU()
    prog3 = [0x13, *u16(111), 0x16, *u16(222), 0x15, *u24(0x2100), 0x18, *u24(0x2102), 0x01]
    load(c3, START, prog3)
    c3.run(START)
    check("LDX #imm", c3.x, 111)
    check("LDY #imm", c3.y, 222)
    check("STX addr", c3.read16(0x2100), 111)
    check("STY addr", c3.read16(0x2102), 222)

# ---------------------------------------------------------------
# Test 3: trasferimenti TAX/TXA/TAY/TYA/TXY/TYX
# ---------------------------------------------------------------
def test_transfers():
    c4 = CPU()
    prog4 = [0x10, *u16(500), 0x20, 0x10, *u16(0), 0x21, 0x01]  # LDA 500; TAX; LDA 0; TXA
    load(c4, START, prog4)
    c4.run(START)
    check("TAX poi TXA: A torna 500", c4.a, 500)
    check("TAX: X=500", c4.x, 500)

# ---------------------------------------------------------------
# Test 4: ALU immediata (ADD/SUB/AND/OR/XOR)
# ---------------------------------------------------------------
def test_add_imm():
    c5 = CPU()
    prog5 = [0x10, *u16(10), 0x30, *u16(5), 0x01]
    load(c5, START, prog5)
    c5.run(START)
    check("ADD #imm", c5.a, 15)

def test_sub_imm():
    c6 = CPU()
    prog6 = [0x10, *u16(10), 0x31, *u16(3), 0x01]
    load(c6, START, prog6)
    c6.run(START)
    check("SUB #imm", c6.a, 7)

def test_and_imm():
    c7 = CPU()
    prog7 = [0x10, *u16(0b1100), 0x32, *u16(0b1010), 0x01]
    load(c7, START, prog7)
    c7.run(START)
    check("AND #imm", c7.a, 0b1000)

def test_or_imm():
    c8 = CPU()
    prog8 = [0x10, *u16(0b1100), 0x33, *u16(0b1010), 0x01]
    load(c8, START, prog8)
    c8.run(START)
    check("OR #imm", c8.a, 0b1110)

def test_xor_imm():
    c9 = CPU()
    prog9 = [0x10, *u16(0b1100), 0x34, *u16(0b1010), 0x01]
    load(c9, START, prog9)
    c9.run(START)
    check("XOR #imm", c9.a, 0b0110)

# ---------------------------------------------------------------
# Test 5: ALU in modalita' indirizzo (var op var)
# ---------------------------------------------------------------
def test_sub_addr_mode():
    c10 = CPU()
    c10.write16(0x2000, 7)
    prog10 = [0x10, *u16(20), 0x41, *u24(0x2000), 0x01]
    load(c10, START, prog10)
    c10.run(START)
    check("SUB addr (modalita' indirizzo)", c10.a, 13)

# ---------------------------------------------------------------
# Test 6: CMP - confronta SENZA distruggere A (impossibile in v1)
# ---------------------------------------------------------------
def test_cmp_equal():
    c11 = CPU()
    prog11 = [0x10, *u16(50), 0x35, *u16(50), 0x01]
    load(c11, START, prog11)
    c11.run(START)
    check("CMP: A NON viene modificato", c11.a, 50)
    check("CMP: uguali -> Zero=True", c11.flag(FLAG_ZERO), True)

def test_cmp_less():
    c12 = CPU()
    prog12 = [0x10, *u16(30), 0x35, *u16(50), 0x01]
    load(c12, START, prog12)
    c12.run(START)
    check("CMP: A ancora intatto dopo confronto 'minore'", c12.a, 30)
    check("CMP: 30<50 -> Carry=False (prestito)", c12.flag(FLAG_CARRY), False)
    check("CMP: 30<50 -> Negative=True", c12.flag(FLAG_NEGATIVE), True)

def test_cmp_greater():
    c13 = CPU()
    prog13 = [0x10, *u16(80), 0x35, *u16(50), 0x01]
    load(c13, START, prog13)
    c13.run(START)
    check("CMP: 80>50 -> Carry=True (nessun prestito)", c13.flag(FLAG_CARRY), True)
    check("CMP: 80>50 -> Negative=False", c13.flag(FLAG_NEGATIVE), False)

# ---------------------------------------------------------------
# Test 7: shift ASL/LSR
# ---------------------------------------------------------------
def test_asl():
    c14 = CPU()
    prog14 = [0x10, *u16(0b0101), 0x50, 0x01]
    load(c14, START, prog14)
    c14.run(START)
    check("ASL", c14.a, 0b1010)

def test_lsr():
    c15 = CPU()
    prog15 = [0x10, *u16(0b1010), 0x51, 0x01]
    load(c15, START, prog15)
    c15.run(START)
    check("LSR", c15.a, 0b0101)

# ---------------------------------------------------------------
# Test 8: INC/DEC diretti su memoria, INX/INY/DEX/DEY sui registri
# ---------------------------------------------------------------
def test_inc_addr():
    c16 = CPU()
    c16.write16(0x2000, 41)
    prog16 = [0x52, *u24(0x2000), 0x01]
    load(c16, START, prog16)
    c16.run(START)
    check("INC addr (memoria, non A)", c16.read16(0x2000), 42)

def test_inx_dey():
    c17 = CPU()
    prog17 = [0x13, *u16(9), 0x54, 0x16, *u16(9), 0x57, 0x01]
    load(c17, START, prog17)
    c17.run(START)
    check("INX", c17.x, 10)
    check("DEY", c17.y, 8)

# ---------------------------------------------------------------
# Test 9: salto JZ
# ---------------------------------------------------------------
def test_jz():
    c18 = CPU()
    prog18 = [0x10, *u16(0)]
    jz_target = START + 3 + 4 + 3 + 4 + 4
    prog18 += [0x61, *u24(jz_target)]
    prog18 += [0x10, *u16(99)]
    prog18 += [0x12, *u24(0x2000)]
    prog18 += [0x60, *u24(jz_target + 7)]
    prog18 += [0x10, *u16(1)]
    prog18 += [0x12, *u24(0x2000)]
    prog18 += [0x01]
    load(c18, START, prog18)
    c18.run(START)
    check("JZ preso quando A=0", c18.read16(0x2000), 1)

# ---------------------------------------------------------------
# Test 10: JSR/RTS con lo STACK HARDWARE vero
# ---------------------------------------------------------------
def test_jsr_rts():
    c19 = CPU()
    sub_addr = START + 100
    prog19 = [0x67, *u24(sub_addr), 0x01]
    load(c19, START, prog19)
    sub = [0x10, *u16(777), 0x12, *u24(0x2000), 0x68]
    load(c19, sub_addr, sub)
    sp_before = c19.sp
    c19.run(START)
    check("JSR ha eseguito la subroutine", c19.read16(0x2000), 777)
    check("RTS e' tornato correttamente (HALT raggiunto)", c19.a, 777)
    check("stack pointer tornato al valore di partenza dopo JSR/RTS", c19.sp, sp_before)

def test_jsr_nested():
    c20 = CPU()
    outer = START + 100
    inner = START + 200
    prog20 = [0x67, *u24(outer), 0x01]
    load(c20, START, prog20)
    load(c20, outer, [0x10, *u16(1), 0x12, *u24(0x2000), 0x67, *u24(inner), 0x10, *u16(3), 0x12, *u24(0x2004), 0x68])
    load(c20, inner, [0x10, *u16(2), 0x12, *u24(0x2002), 0x68])
    c20.run(START)
    check("JSR annidate: primo valore", c20.read16(0x2000), 1)
    check("JSR annidate: valore della subroutine interna", c20.read16(0x2002), 2)
    check("JSR annidate: torna correttamente alla esterna", c20.read16(0x2004), 3)

# ---------------------------------------------------------------
# Test 11: PHA/PLA/PHX/PLX/PHY/PLY
# ---------------------------------------------------------------
def test_pha_pla():
    c21 = CPU()
    prog21 = [0x10, *u16(555), 0x70, 0x10, *u16(0), 0x71, 0x01]
    load(c21, START, prog21)
    c21.run(START)
    check("PHA poi PLA: A ripristinato", c21.a, 555)

def test_pha_pla_lifo():
    c22 = CPU()
    prog22 = [0x10, *u16(11), 0x70, 0x10, *u16(22), 0x70, 0x71, 0x71, 0x01]
    load(c22, START, prog22)
    c22.run(START)
    check("stack LIFO con PHA/PLA multipli", c22.a, 11)

# ---------------------------------------------------------------
# Test 12: gli altri salti condizionali (JNZ, JLT, JGE, JCS, JCC)
# come SALTI VERI (non solo test sui flag in isolamento)
#
# branch_test crea gia' la propria CPU() in una variabile locale
# 'c' che viene liberata a ogni ritorno della funzione - nessuna
# modifica necessaria qui, era gia' isolata.
# ---------------------------------------------------------------
def branch_test(label, setup_asm, branch_op, expect_taken):
    c = CPU()
    skip_target = START + len(setup_asm) + 4 + 3 + 4 + 4  # +branch +LDA#0 +STA +JMP
    prog = list(setup_asm)
    prog += [branch_op, *u24(skip_target)]
    prog += [0x10, *u16(0)]            # ramo "non preso": A=0
    prog += [0x12, *u24(0x3000)]
    prog += [0x60, *u24(skip_target + 7)]
    prog += [0x10, *u16(1)]            # skip_target: A=1 (salto preso)
    prog += [0x12, *u24(0x3000)]
    prog += [0x01]
    load(c, START, prog)
    c.run(START)
    got_taken = c.read16(0x3000) == 1
    check(label, got_taken, expect_taken)

def test_branches():
    branch_test("JNZ preso quando A!=0", [0x10, *u16(5)], 0x62, True)
    branch_test("JNZ non preso quando A==0", [0x10, *u16(0)], 0x62, False)
    branch_test("JLT preso dopo CMP con risultato negativo (30 cmp 50)",
                [0x10, *u16(30), 0x35, *u16(50)], 0x63, True)
    branch_test("JGE preso dopo CMP con risultato >=0 (80 cmp 50)",
                [0x10, *u16(80), 0x35, *u16(50)], 0x64, True)
    branch_test("JCS preso quando Carry=True (80 cmp 50, nessun prestito)",
                [0x10, *u16(80), 0x35, *u16(50)], 0x65, True)
    branch_test("JCC preso quando Carry=False (30 cmp 50, prestito)",
                [0x10, *u16(30), 0x35, *u16(50)], 0x66, True)

# ---------------------------------------------------------------
# Test 13: flag Overflow (somma con segno che "trabocca")
# ---------------------------------------------------------------
def test_overflow_set():
    c23 = CPU()
    # due numeri positivi grandi la cui somma supera 32767 (diventa
    # "negativa" in complemento a due a 16 bit) -> overflow
    prog23 = [0x10, *u16(30000), 0x30, *u16(20000), 0x01]
    load(c23, START, prog23)
    c23.run(START)
    check("ADD: overflow rilevato (30000+20000 'trabocca' a 16 bit con segno)",
          c23.flag(FLAG_OVERFLOW), True)

def test_overflow_not_set():
    c24 = CPU()
    prog24 = [0x10, *u16(10), 0x30, *u16(20), 0x01]
    load(c24, START, prog24)
    c24.run(START)
    check("ADD: nessun overflow per una somma normale", c24.flag(FLAG_OVERFLOW), False)

# ---------------------------------------------------------------
# Test 14: PORT_STAGE_SELECT - caricamento stage stile DMA
# ---------------------------------------------------------------
def test_stage_select():
    c25 = CPU()
    stage_data = bytearray([0xAB] * TILEMAP_BYTES)
    c25.stages[1] = stage_data
    check("STAGE_SELECT: tilemap vuota prima della selezione", c25.mem[VRAM_BASE+TILEMAP_VRAM_OFFSET], 0)
    c25.write16(PORT_STAGE_SELECT, 1)
    check("STAGE_SELECT: primo byte copiato", c25.mem[VRAM_BASE+TILEMAP_VRAM_OFFSET], 0xAB)
    check("STAGE_SELECT: ultimo byte copiato", c25.mem[VRAM_BASE+TILEMAP_VRAM_OFFSET+TILEMAP_BYTES-1], 0xAB)
    check("STAGE_SELECT: current_stage aggiornato", c25.current_stage, 1)

    c25.write16(PORT_STAGE_SELECT, 99)  # stage inesistente
    check("STAGE_SELECT: stage inesistente non cambia nulla", c25.current_stage, 1)

    c25.write16(0x001000, 4660)
    check("scritture normali continuano a funzionare dopo STAGE_SELECT", c25.read16(0x001000), 4660)

# ---------------------------------------------------------------
# Test 15: PORT_SCROLL_X/Y
# ---------------------------------------------------------------
def test_scroll():
    c26 = CPU()
    check("scroll iniziale a zero", (c26.scroll_x, c26.scroll_y), (0, 0))
    c26.write16(PORT_SCROLL_X, 100)
    c26.write16(PORT_SCROLL_Y, 250)
    check("PORT_SCROLL_X aggiorna cpu.scroll_x", c26.scroll_x, 100)
    check("PORT_SCROLL_Y aggiorna cpu.scroll_y", c26.scroll_y, 250)
    c26.write16(0x001000, 4660)
    check("scritture normali continuano a funzionare dopo SCROLL_X/Y", c26.read16(0x001000), 4660)

# ---------------------------------------------------------------
# Test 16: porte input multiplayer (EXTRA_INPUT_PORTS/ALL_INPUT_PORTS)
# ---------------------------------------------------------------
def test_input_ports_constants():
    check("EXTRA_INPUT_PORTS: 7 porte (giocatori 2-8)", len(EXTRA_INPUT_PORTS), 7)
    check("ALL_INPUT_PORTS: PORT_INPUT + le 7 extra = 8 totali", len(ALL_INPUT_PORTS), 8)
    check("ALL_INPUT_PORTS: PORT_INPUT e' il primo elemento", ALL_INPUT_PORTS[0], PORT_INPUT)
    check("EXTRA_INPUT_PORTS: nessun indirizzo duplicato", len(set(ALL_INPUT_PORTS)), 8)
    check("EXTRA_INPUT_PORTS: non confligge con le porte esistenti (SCROLL/SOUND/STAGE)",
          set(EXTRA_INPUT_PORTS) & {PORT_STAGE_SELECT, PORT_SCROLL_X, PORT_SCROLL_Y, PORT_SOUND}, set())

def test_input_ports_read_mem():
    c27 = CPU()
    for i, porta in enumerate(ALL_INPUT_PORTS):
        check(f"read_mem riconosce la porta input del giocatore {i} (0x{porta:06X})",
              c27.read_mem(porta), 0)

    c27.mem[0x2000] = 0x01  # HALT - basta un'istruzione per verificare solo le porte, non serve una ROM vera
    c27.run(0x2000, input_byte=0x11, extra_inputs=(0x22, 0x33))
    check("run(): input_byte finisce su PORT_INPUT (giocatore 0)", c27.mem[PORT_INPUT], 0x11)
    check("run(): extra_inputs[0] finisce sulla porta del giocatore 1",
          c27.mem[EXTRA_INPUT_PORTS[0]], 0x22)
    check("run(): extra_inputs[1] finisce sulla porta del giocatore 2",
          c27.mem[EXTRA_INPUT_PORTS[1]], 0x33)
    check("run(): le porte dei giocatori 3-7 restano a zero se extra_inputs e' piu' corto",
          all(c27.mem[p] == 0 for p in EXTRA_INPUT_PORTS[2:]), True)

def test_input_ports_no_extra():
    c28 = CPU()
    c28.mem[0x2000] = 0x01  # HALT
    n_passi = c28.run(0x2000, input_byte=0x05)
    check("run(): senza extra_inputs (chiamata come sempre) continua a funzionare invariata",
          c28.mem[PORT_INPUT], 0x05)
    check("run(): extra_inputs=None non tocca nessuna porta extra",
          all(c28.mem[p] == 0 for p in EXTRA_INPUT_PORTS), True)

def test_input_byte_masked():
    c29 = CPU()
    c29.mem[0x2000] = 0x01  # HALT
    c29.run(0x2000, input_byte=0x300)  # valore fuori range di un byte
    check("run(): input_byte viene mascherato a 8 bit (& 0xff)", c29.mem[PORT_INPUT], 0x00)

# ---------------------------------------------------------------
# Test 17: state_checksum() - per rilevare disallineamenti in rete
# ---------------------------------------------------------------
def test_state_checksum():
    c30 = CPU()
    somma1 = c30.state_checksum()
    somma2 = c30.state_checksum()
    check("state_checksum: deterministico (stesso stato -> stesso checksum)", somma1, somma2)

    c30.write16(WRAM_BASE, 12345)
    somma3 = c30.state_checksum()
    check("state_checksum: cambia se cambia la WRAM", somma3 != somma1, True)

    c31 = CPU()
    c31.write16(WRAM_BASE, 12345)
    check("state_checksum: due CPU con la STESSA WRAM danno lo STESSO checksum (base del confronto in rete)",
          c31.state_checksum(), somma3)


def run_all():
    test_lda_sta_imm_addr()
    test_lda_addr()
    test_ldx_stx_ldy_sty()
    test_transfers()
    test_add_imm()
    test_sub_imm()
    test_and_imm()
    test_or_imm()
    test_xor_imm()
    test_sub_addr_mode()
    test_cmp_equal()
    test_cmp_less()
    test_cmp_greater()
    test_asl()
    test_lsr()
    test_inc_addr()
    test_inx_dey()
    test_jz()
    test_jsr_rts()
    test_jsr_nested()
    test_pha_pla()
    test_pha_pla_lifo()
    test_branches()
    test_overflow_set()
    test_overflow_not_set()
    test_stage_select()
    test_scroll()
    test_input_ports_constants()
    test_input_ports_read_mem()
    test_input_ports_no_extra()
    test_input_byte_masked()
    test_state_checksum()

    print()
    if fails == 0:
        print("Tutti i test passati.")
    else:
        print(f"{fails} test falliti.")


if __name__ == "__main__":
    run_all()
