"""
cpu.py - nucleo CPU di S32.

Differenze principali rispetto alla CPU virtuale della v1 (vedi
console_v1_frozen/DOCS.txt sezione 3 per il confronto con lo SNES
vero, e memory_map.py qui per il perche' dei numeri):

- Registri A/X/Y a 16 bit (v1: 8 bit, "sbloccato" per essere negativo)
- Bus a 24 bit FLAT, nessun banking (v1: 8 bit, 256 celle)
- REGISTRO FLAG vero (Z,N,C,V) - abilita CMP che non distrugge A,
  risolvendo il limite che in ConsoleLang v1 vietava "<" come valore
  generico (solo dentro if/ternario)
- STACK HARDWARE vero in cima alla WRAM (v1: una lista Python interna,
  usata solo per JSR/RTS, mai esposta al programma)
- LDX/STX/LDY/STY leggono/scrivono DAVVERO in memoria (in v1 erano un
  trucco: "LDX" voleva dire "A=X", cioe' il vero TXA - qui invece
  TAX/TXA/TAY/TYA/TXY/TYX sono istruzioni separate, vedi sotto)
- INC/DEC/INX/INY/DEX/DEY diretti (assenti in v1)
- ASL/LSR, OR, XOR (assenti in v1)

Memoria: indirizzabile a BYTE (come l'hardware reale), ma i registri
sono a 16 bit - un valore a 16 bit occupa quindi 2 byte consecutivi
in memoria, little-endian (byte basso all'indirizzo, byte alto a
indirizzo+1) - stessa convenzione del 6502/65816 vero.
"""

from memory_map import (
    ADDRESS_SPACE, REGISTER_MAX, WRAM_BASE, WRAM_END,
    FLAG_ZERO, FLAG_NEGATIVE, FLAG_CARRY, FLAG_OVERFLOW,
    TILEMAP_VRAM_OFFSET, TILEMAP_BYTES, VRAM_BASE,
)
import zlib

CALL_STACK_MAX_DEPTH = 256  # limite di sicurezza (JSR annidate), non
                             # un vincolo hardware - evita loop infiniti
                             # di ricorsione di finire la memoria

PORT_INPUT = 0x042000         # stessa porta INPUT della v1, nuovo indirizzo
                               # (giocatore 1 - locale, tastiera)
PORT_STAGE_SELECT = 0x042001  # scrivere un numero di stage qui copia
                               # ISTANTANEAMENTE (nessun ciclo CPU in
                               # piu', come il DMA del vero SNES - vedi
                               # v1 DOCS.txt sezione 13 per la spiegazione
                               # completa di questo pattern) la tilemap
                               # di quello stage dentro VRAM. Gli stage
                               # vanno registrati PRIMA in cpu.stages
                               # (dict {numero: 1024... byte di tilemap})
                               # dall'host (cart.py), la CPU sceglie
                               # solo TRA quelli gia' pronti
PORT_SCROLL_X = 0x042002      # scrivere qui imposta cpu.scroll_x - la
PORT_SCROLL_Y = 0x042003      # PPU (render_background) lo usa per
PORT_SOUND = 0x042004         # scrivere un ID suono qui lo ACCODA in
                               # cpu.sound_queue. La CPU NON produce
                               # audio: resta pura-Python e testabile
                               # senza pygame, esattamente come non
                               # disegna pixel (vedi PORT_STAGE_SELECT).
                               # E' il launcher che a fine frame svuota
                               # la coda e suona davvero - stessa
                               # separazione gia' usata per il video.
                               # decidere quale porzione della tilemap
                               # mostrare. A differenza di STAGE_SELECT
                               # non c'e' nessuna copia: solo un valore
                               # che il programma aggiorna ogni frame
                               # (es. la Y del giocatore, per la camera
                               # che segue verticalmente)

# Porte input aggiuntive per multiplayer locale (lockstep, vedi
# s32/netcode_lockstep.py). PORT_INPUT (0x042000) resta il giocatore
# 1/indice 0, invariato per compatibilita' con le ROM esistenti che
# chiamano input() senza argomenti.
EXTRA_INPUT_PORTS = (
    0x042010,  # giocatore 2 (indice 1)
    0x042011,  # giocatore 3 (indice 2)
    0x042012,  # giocatore 4 (indice 3)
    0x042013,  # giocatore 5 (indice 4)
    0x042014,  # giocatore 6 (indice 5)
    0x042015,  # giocatore 7 (indice 6)
    0x042016,  # giocatore 8 (indice 7)
)
ALL_INPUT_PORTS = (PORT_INPUT,) + EXTRA_INPUT_PORTS


class CPU:
    def __init__(self):
        self.mem = bytearray(ADDRESS_SPACE)
        self.a = 0
        self.x = 0
        self.y = 0
        self.pc = 0
        self.flags = 0
        # stack hardware: cresce verso il BASSO a partire dalla cima
        # della WRAM (convenzione 6502/65816 vera)
        self.sp = WRAM_END - 2  # -2 perche' spingiamo valori a 16 bit
        self.stages = {}       # popolato dall'host prima di avviare il
                                # ciclo di gioco - vedi PORT_STAGE_SELECT
        self.current_stage = 0
        self.scroll_x = 0      # vedi PORT_SCROLL_X/Y
        self.sound_queue = []  # ID suoni richiesti in questo frame (vedi
                                # PORT_SOUND). Il launcher la svuota dopo
                                # ogni run(); in --benchmark o nei test
                                # resta semplicemente piena e ignorata.
        self.scroll_y = 0
        self._build_opcode_table()  # O(1) dispatch invece di if/elif -
                                     # vedi step() e _build_opcode_table()
                                     # per il perche' (trovato misurando
                                     # su Pi 1 vera: le istruzioni piu'
                                     # usate nel codice reale, i salti
                                     # condizionali, cadevano in fondo
                                     # a una catena di 54 controlli)

    # -----------------------------------------------------------
    # accesso memoria a 16 bit (little-endian su 2 byte)
    # -----------------------------------------------------------
    def read16(self, addr):
        addr &= (1 << 24) - 1
        lo = self.mem[addr]
        hi = self.mem[(addr + 1) % ADDRESS_SPACE]
        return lo | (hi << 8)

    def write16(self, addr, value):
        addr &= (1 << 24) - 1
        value &= 0xffff
        if addr == PORT_STAGE_SELECT:
            if value in self.stages:
                data = self.stages[value]
                self.mem[VRAM_BASE + TILEMAP_VRAM_OFFSET:
                          VRAM_BASE + TILEMAP_VRAM_OFFSET + TILEMAP_BYTES] = data
                self.current_stage = value
            return
        if addr == PORT_SCROLL_X:
            self.scroll_x = value
            return
        if addr == PORT_SCROLL_Y:
            self.scroll_y = value
            return
        if addr == PORT_SOUND:
            self.sound_queue.append(value)
            return
        self.mem[addr] = value & 0xff
        self.mem[(addr + 1) % ADDRESS_SPACE] = (value >> 8) & 0xff

    def read_mem(self, addr):
        """Punto di estensione per le porte (vedi ports.py, non
        ancora scritto) - per ora legge sempre direttamente."""
        if addr in ALL_INPUT_PORTS:
            return self.mem[addr]
        return self.read16(addr)

    def write_mem(self, addr, value):
        self.write16(addr, value)

    # -----------------------------------------------------------
    # flag
    # -----------------------------------------------------------
    def set_flag(self, flag, condition):
        if condition:
            self.flags |= flag
        else:
            self.flags &= ~flag

    def update_zn(self, value):
        """Aggiorna Zero e Negative in base al risultato (con
        wraparound a 16 bit gia' applicato)."""
        self.set_flag(FLAG_ZERO, value == 0)
        self.set_flag(FLAG_NEGATIVE, bool(value & 0x8000))

    def flag(self, f):
        return bool(self.flags & f)

    # -----------------------------------------------------------
    # stack (16 bit per valore)
    # -----------------------------------------------------------
    def push(self, value):
        self.write16(self.sp, value)
        self.sp -= 2
        if self.sp < WRAM_BASE:
            raise RuntimeError("Stack overflow (sceso sotto WRAM_BASE)")

    def pop(self):
        self.sp += 2
        if self.sp > WRAM_END - 2:
            raise RuntimeError("Stack underflow (nessun valore da togliere)")
        return self.read16(self.sp)

    # -----------------------------------------------------------
    # ALU - helper condivisi da modalita' immediata e indirizzo
    # -----------------------------------------------------------
    def _add(self, operand):
        raw = self.a + operand
        self.set_flag(FLAG_CARRY, raw > 0xffff)
        result = raw & 0xffff
        a_sign, op_sign, r_sign = self.a & 0x8000, operand & 0x8000, result & 0x8000
        self.set_flag(FLAG_OVERFLOW, (a_sign == op_sign) and (r_sign != a_sign))
        self.update_zn(result)
        self.a = result

    def _sub(self, operand):
        raw = self.a - operand
        self.set_flag(FLAG_CARRY, self.a >= operand)  # niente prestito
        result = raw & 0xffff
        a_sign, op_sign, r_sign = self.a & 0x8000, operand & 0x8000, result & 0x8000
        self.set_flag(FLAG_OVERFLOW, (a_sign != op_sign) and (r_sign != a_sign))
        self.update_zn(result)
        self.a = result

    def _and(self, operand):
        self.a &= operand
        self.update_zn(self.a)

    def _or(self, operand):
        self.a |= operand
        self.update_zn(self.a)

    def _xor(self, operand):
        self.a ^= operand
        self.update_zn(self.a)

    def _cmp(self, operand):
        """Confronta SENZA modificare A - la capacita' che in v1 non
        avevamo (li' un confronto 'consumava' l'accumulatore)."""
        result = (self.a - operand) & 0xffff
        self.set_flag(FLAG_CARRY, self.a >= operand)
        self.update_zn(result)

    # -----------------------------------------------------------
    # esecuzione: UNA istruzione, ritorna il numero di byte consumati
    # (serve a run() per sapere quanto avanzare pc quando l'istruzione
    # stessa non e' un salto)
    # -----------------------------------------------------------
    def _imm16(self):
        return self.mem[self.pc+1] | (self.mem[self.pc+2] << 8)

    def _addr24(self):
        return self.mem[self.pc+1] | (self.mem[self.pc+2] << 8) | (self.mem[self.pc+3] << 16)

    # -----------------------------------------------------------
    # un metodo _op_XX per ogni istruzione - stesso identico corpo
    # che prima stava in un ramo elif dentro step(). Costruiti in
    # _build_opcode_table() come tabella {opcode: metodo}, UNA volta
    # sola nel costruttore, non ad ogni istruzione.
    #
    # PERCHE': con 54 istruzioni totali, un dispatch if/elif e'
    # O(n) - per un salto condizionale (JZ/JNZ/JLT/JGE, gli
    # opcode 0x61-0x64), tra le istruzioni piu' usate in QUALUNQUE
    # programma reale (ogni "if" di ConsoleLang ne genera uno),
    # Python doveva controllare 37-40 condizioni PRIMA di arrivare
    # a quella giusta. Un dict e' O(1): stesso costo qualunque sia
    # l'istruzione. Trovato misurando su Pi 1 vera: 300 istruzioni
    # (normali, verificate identiche al conteggio atteso) costavano
    # ~40ms - troppo anche per un ARM11 senza JIT, e la posizione
    # dei salti nella catena spiegava bene perche'.
    # -----------------------------------------------------------
    def _op_00(self):  # NOP
        self.pc += 1; return True

    def _op_01(self):  # HALT
        return False

    def _op_10(self):  # LDA #imm
        self.a = self._imm16(); self.update_zn(self.a); self.pc += 3; return True

    def _op_11(self):  # LDA addr
        self.a = self.read_mem(self._addr24()); self.update_zn(self.a); self.pc += 4; return True

    def _op_12(self):  # STA addr
        self.write_mem(self._addr24(), self.a); self.pc += 4; return True

    def _op_13(self):  # LDX #imm
        self.x = self._imm16(); self.update_zn(self.x); self.pc += 3; return True

    def _op_14(self):  # LDX addr
        self.x = self.read_mem(self._addr24()); self.update_zn(self.x); self.pc += 4; return True

    def _op_15(self):  # STX addr
        self.write_mem(self._addr24(), self.x); self.pc += 4; return True

    def _op_16(self):  # LDY #imm
        self.y = self._imm16(); self.update_zn(self.y); self.pc += 3; return True

    def _op_17(self):  # LDY addr
        self.y = self.read_mem(self._addr24()); self.update_zn(self.y); self.pc += 4; return True

    def _op_18(self):  # STY addr
        self.write_mem(self._addr24(), self.y); self.pc += 4; return True

    def _op_20(self):  # TAX
        self.x = self.a; self.update_zn(self.x); self.pc += 1; return True

    def _op_21(self):  # TXA
        self.a = self.x; self.update_zn(self.a); self.pc += 1; return True

    def _op_22(self):  # TAY
        self.y = self.a; self.update_zn(self.y); self.pc += 1; return True

    def _op_23(self):  # TYA
        self.a = self.y; self.update_zn(self.a); self.pc += 1; return True

    def _op_24(self):  # TXY
        self.y = self.x; self.update_zn(self.y); self.pc += 1; return True

    def _op_25(self):  # TYX
        self.x = self.y; self.update_zn(self.x); self.pc += 1; return True

    def _op_30(self):
        self._add(self._imm16()); self.pc += 3; return True

    def _op_31(self):
        self._sub(self._imm16()); self.pc += 3; return True

    def _op_32(self):
        self._and(self._imm16()); self.pc += 3; return True

    def _op_33(self):
        self._or(self._imm16()); self.pc += 3; return True

    def _op_34(self):
        self._xor(self._imm16()); self.pc += 3; return True

    def _op_35(self):
        self._cmp(self._imm16()); self.pc += 3; return True

    def _op_40(self):
        self._add(self.read_mem(self._addr24())); self.pc += 4; return True

    def _op_41(self):
        self._sub(self.read_mem(self._addr24())); self.pc += 4; return True

    def _op_42(self):
        self._and(self.read_mem(self._addr24())); self.pc += 4; return True

    def _op_43(self):
        self._or(self.read_mem(self._addr24())); self.pc += 4; return True

    def _op_44(self):
        self._xor(self.read_mem(self._addr24())); self.pc += 4; return True

    def _op_45(self):
        self._cmp(self.read_mem(self._addr24())); self.pc += 4; return True

    def _op_50(self):  # ASL
        carry_out = bool(self.a & 0x8000)
        self.a = (self.a << 1) & 0xffff
        self.set_flag(FLAG_CARRY, carry_out); self.update_zn(self.a); self.pc += 1; return True

    def _op_51(self):  # LSR
        carry_out = bool(self.a & 0x0001)
        self.a = self.a >> 1
        self.set_flag(FLAG_CARRY, carry_out); self.update_zn(self.a); self.pc += 1; return True

    def _op_52(self):  # INC addr
        a = self._addr24(); v = (self.read_mem(a) + 1) & 0xffff
        self.write_mem(a, v); self.update_zn(v); self.pc += 4; return True

    def _op_53(self):  # DEC addr
        a = self._addr24(); v = (self.read_mem(a) - 1) & 0xffff
        self.write_mem(a, v); self.update_zn(v); self.pc += 4; return True

    def _op_54(self):  # INX
        self.x = (self.x + 1) & 0xffff; self.update_zn(self.x); self.pc += 1; return True

    def _op_55(self):  # INY
        self.y = (self.y + 1) & 0xffff; self.update_zn(self.y); self.pc += 1; return True

    def _op_56(self):  # DEX
        self.x = (self.x - 1) & 0xffff; self.update_zn(self.x); self.pc += 1; return True

    def _op_57(self):  # DEY
        self.y = (self.y - 1) & 0xffff; self.update_zn(self.y); self.pc += 1; return True

    def _op_60(self):  # JMP
        self.pc = self._addr24(); return True

    def _op_61(self):  # JZ
        self.pc = self._addr24() if self.flag(FLAG_ZERO) else self.pc + 4; return True

    def _op_62(self):  # JNZ
        self.pc = self._addr24() if not self.flag(FLAG_ZERO) else self.pc + 4; return True

    def _op_63(self):  # JLT
        self.pc = self._addr24() if self.flag(FLAG_NEGATIVE) else self.pc + 4; return True

    def _op_64(self):  # JGE
        self.pc = self._addr24() if not self.flag(FLAG_NEGATIVE) else self.pc + 4; return True

    def _op_65(self):  # JCS
        self.pc = self._addr24() if self.flag(FLAG_CARRY) else self.pc + 4; return True

    def _op_66(self):  # JCC
        self.pc = self._addr24() if not self.flag(FLAG_CARRY) else self.pc + 4; return True

    def _op_67(self):  # JSR
        target = self._addr24()
        self.push(self.pc + 4)
        self.pc = target
        return True

    def _op_68(self):  # RTS
        self.pc = self.pop(); return True

    def _op_70(self):  # PHA
        self.push(self.a); self.pc += 1; return True

    def _op_71(self):  # PLA
        self.a = self.pop(); self.update_zn(self.a); self.pc += 1; return True

    def _op_72(self):  # PHX
        self.push(self.x); self.pc += 1; return True

    def _op_73(self):  # PLX
        self.x = self.pop(); self.update_zn(self.x); self.pc += 1; return True

    def _op_74(self):  # PHY
        self.push(self.y); self.pc += 1; return True

    def _op_75(self):  # PLY
        self.y = self.pop(); self.update_zn(self.y); self.pc += 1; return True

    def _op_80(self):  # IN
        self.a = self.mem[PORT_INPUT]; self.pc += 1; return True

    def _op_90(self):  # CLAMPX lo,hi
        lo = self._imm16(); hi = self.mem[self.pc+3] | (self.mem[self.pc+4] << 8)
        if self.x < lo: self.x = lo
        if self.x > hi: self.x = hi
        self.pc += 5; return True

    def _op_91(self):  # CLAMPY lo,hi
        lo = self._imm16(); hi = self.mem[self.pc+3] | (self.mem[self.pc+4] << 8)
        if self.y < lo: self.y = lo
        if self.y > hi: self.y = hi
        self.pc += 5; return True

    def _build_opcode_table(self):
        self._opcode_table = {
            0x00: self._op_00, 0x01: self._op_01,
            0x10: self._op_10, 0x11: self._op_11, 0x12: self._op_12,
            0x13: self._op_13, 0x14: self._op_14, 0x15: self._op_15,
            0x16: self._op_16, 0x17: self._op_17, 0x18: self._op_18,
            0x20: self._op_20, 0x21: self._op_21, 0x22: self._op_22,
            0x23: self._op_23, 0x24: self._op_24, 0x25: self._op_25,
            0x30: self._op_30, 0x31: self._op_31, 0x32: self._op_32,
            0x33: self._op_33, 0x34: self._op_34, 0x35: self._op_35,
            0x40: self._op_40, 0x41: self._op_41, 0x42: self._op_42,
            0x43: self._op_43, 0x44: self._op_44, 0x45: self._op_45,
            0x50: self._op_50, 0x51: self._op_51, 0x52: self._op_52,
            0x53: self._op_53, 0x54: self._op_54, 0x55: self._op_55,
            0x56: self._op_56, 0x57: self._op_57,
            0x60: self._op_60, 0x61: self._op_61, 0x62: self._op_62,
            0x63: self._op_63, 0x64: self._op_64, 0x65: self._op_65,
            0x66: self._op_66, 0x67: self._op_67, 0x68: self._op_68,
            0x70: self._op_70, 0x71: self._op_71, 0x72: self._op_72,
            0x73: self._op_73, 0x74: self._op_74, 0x75: self._op_75,
            0x80: self._op_80,
            0x90: self._op_90, 0x91: self._op_91,
        }

    # -----------------------------------------------------------
    # esecuzione: UNA istruzione, ritorna il numero di byte consumati
    # (serve a run() per sapere quanto avanzare pc quando l'istruzione
    # stessa non e' un salto)
    # -----------------------------------------------------------
    def step(self):
        op = self.mem[self.pc]
        handler = self._opcode_table.get(op)
        if handler is None:
            raise RuntimeError(f"Opcode sconosciuto: 0x{op:02X} a pc=0x{self.pc:06X}")
        return handler()

    def run(self, start_pc, input_byte=0, extra_inputs=None, max_steps=200000):
        self.pc = start_pc
        self.mem[PORT_INPUT] = input_byte & 0xff
        if extra_inputs:
            for port, value in zip(EXTRA_INPUT_PORTS, extra_inputs):
                self.mem[port] = value & 0xff
        steps = 0
        while steps < max_steps:
            steps += 1
            if not self.step():
                break
        else:
            raise RuntimeError(f"Superato il limite di sicurezza di {max_steps} passi (loop infinito?)")
        return steps

    def state_checksum(self):
        """Checksum leggero della WRAM (dove vive tutto lo stato
        persistente del gioco) - da chiamare ogni tot frame e
        confrontare tra le istanze in rete (vedi
        s32/netcode_lockstep.py). Se non combacia, le simulazioni
        sono andate fuori sincronia - un bug non deterministico o un
        input perso, utile scoprirlo subito invece che vederlo come
        un bug di gioco "misterioso" molto piu' tardi."""
        return zlib.crc32(bytes(self.mem[WRAM_BASE:WRAM_END]))
