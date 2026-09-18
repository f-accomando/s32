"""
assembler.py - assemblatore per il nucleo CPU di S32 (cpu.py).

Stessa filosofia della v1: testo leggibile (un'istruzione per riga,
"NOME arg", ";" per i commenti, "ETICHETTA:" per le etichette) che
compila in byte grezzi. Due passaggi: il primo registra l'indirizzo
di ogni etichetta, il secondo genera i byte veri risolvendo i
riferimenti (permette di saltare in avanti a un'etichetta non ancora
vista, esattamente come in v1).

DIFFERENZE rispetto all'assemblatore v1 (motivate dal nuovo bus/
registri, vedi memory_map.py):
- Gli operandi IMMEDIATI (#numero) sono a 16 bit (2 byte), non 8
- Gli operandi INDIRIZZO sono a 24 bit (3 byte), non 1 (v1 originale)
  ne' 2 (v1 dopo la correzione del bug dei salti troncati)
- LDX/STX/LDY/STY hanno DUE modalita' (immediata E indirizzo) come
  LDA/STA, non il trucco "A=X" della v1 - servono TAX/TXA/TAY/TYA/
  TXY/TYX per i trasferimenti tra registri
- CMP esiste (immediato e indirizzo) - confronta senza toccare A
- Nuovi salti: JCS/JCC (sul flag Carry), oltre a JZ/JNZ/JLT/JGE
"""

MNEMONIC_TABLE = {
    # mnemonico: (opcode, 'none' | 'imm16' | 'addr24' | 'clamp')
    'NOP':  (0x00, 'none'),
    'HALT': (0x01, 'none'),

    'LDA_IMM': (0x10, 'imm16'), 'LDA_ADDR': (0x11, 'addr24'),
    'STA':     (0x12, 'addr24'),
    'LDX_IMM': (0x13, 'imm16'), 'LDX_ADDR': (0x14, 'addr24'),
    'STX':     (0x15, 'addr24'),
    'LDY_IMM': (0x16, 'imm16'), 'LDY_ADDR': (0x17, 'addr24'),
    'STY':     (0x18, 'addr24'),

    'TAX': (0x20, 'none'), 'TXA': (0x21, 'none'),
    'TAY': (0x22, 'none'), 'TYA': (0x23, 'none'),
    'TXY': (0x24, 'none'), 'TYX': (0x25, 'none'),

    'ADD_IMM': (0x30, 'imm16'), 'SUB_IMM': (0x31, 'imm16'),
    'AND_IMM': (0x32, 'imm16'), 'OR_IMM':  (0x33, 'imm16'),
    'XOR_IMM': (0x34, 'imm16'), 'CMP_IMM': (0x35, 'imm16'),

    'ADD_ADDR': (0x40, 'addr24'), 'SUB_ADDR': (0x41, 'addr24'),
    'AND_ADDR': (0x42, 'addr24'), 'OR_ADDR':  (0x43, 'addr24'),
    'XOR_ADDR': (0x44, 'addr24'), 'CMP_ADDR': (0x45, 'addr24'),

    'ASL': (0x50, 'none'), 'LSR': (0x51, 'none'),
    'INC': (0x52, 'addr24'), 'DEC': (0x53, 'addr24'),
    'INX': (0x54, 'none'), 'INY': (0x55, 'none'),
    'DEX': (0x56, 'none'), 'DEY': (0x57, 'none'),

    'JMP': (0x60, 'addr24'), 'JZ':  (0x61, 'addr24'),
    'JNZ': (0x62, 'addr24'), 'JLT': (0x63, 'addr24'),
    'JGE': (0x64, 'addr24'), 'JCS': (0x65, 'addr24'),
    'JCC': (0x66, 'addr24'), 'JSR': (0x67, 'addr24'),
    'RTS': (0x68, 'none'),

    'PHA': (0x70, 'none'), 'PLA': (0x71, 'none'),
    'PHX': (0x72, 'none'), 'PLX': (0x73, 'none'),
    'PHY': (0x74, 'none'), 'PLY': (0x75, 'none'),

    'IN': (0x80, 'none'),

    'CLAMPX': (0x90, 'clamp'), 'CLAMPY': (0x91, 'clamp'),
}

SIZE_BY_MODE = {'none': 1, 'imm16': 3, 'addr24': 4, 'clamp': 5}

# mnemonici che esistono in DUE modalita' (immediata se l'argomento
# inizia con '#', indirizzo altrimenti) - si risolvono nel nome
# interno giusto (es. "LDA" -> "LDA_IMM" o "LDA_ADDR")
DUAL_MODE = {'LDA', 'LDX', 'LDY', 'ADD', 'SUB', 'AND', 'OR', 'XOR', 'CMP'}


class AssemblerError(Exception):
    pass


def _resolve_mnemonic(op, arg):
    if op in DUAL_MODE:
        return f'{op}_IMM' if arg.startswith('#') else f'{op}_ADDR'
    return op


def _parse_lines(src):
    lines = []
    for raw in src.split('\n'):
        line = raw.split(';')[0].strip()
        if line:
            lines.append(line)
    return lines


def _first_pass(lines):
    """Ritorna (istruzioni_parsate, tabella_etichette). Ogni
    istruzione parsata e' (mnemonico_interno, opcode, modalita', arg, indirizzo)."""
    labels = {}
    addr = 0
    parsed = []
    for line in lines:
        if line.endswith(':'):
            label = line[:-1].strip()
            if label in labels:
                raise AssemblerError(f'Etichetta duplicata: "{label}"')
            labels[label] = addr
            continue

        parts = line.split(None, 1)
        op = parts[0]
        arg = parts[1].strip() if len(parts) > 1 else ''
        internal = _resolve_mnemonic(op, arg)

        if internal not in MNEMONIC_TABLE:
            raise AssemblerError(f'Istruzione sconosciuta: "{op}"')

        opcode, mode = MNEMONIC_TABLE[internal]
        size = SIZE_BY_MODE[mode]
        parsed.append((internal, opcode, mode, arg, addr))
        addr += size

    return parsed, labels


def _emit_operand(mode, arg, labels):
    """Ritorna la lista di byte per l'operando di un'istruzione (non
    l'opcode, solo l'operando)."""
    if mode == 'none':
        return []

    if mode == 'imm16':
        if not arg.startswith('#'):
            raise AssemblerError(f'Operando immediato atteso (con "#"): "{arg}"')
        val = int(arg[1:], 0) & 0xffff
        return [val & 0xff, (val >> 8) & 0xff]

    if mode == 'addr24':
        val = labels[arg] if arg in labels else int(arg, 0)
        val &= 0xffffff
        return [val & 0xff, (val >> 8) & 0xff, (val >> 16) & 0xff]

    if mode == 'clamp':
        lo_str, hi_str = [s.strip() for s in arg.split(',')]
        lo = int(lo_str, 0) & 0xffff
        hi = int(hi_str, 0) & 0xffff
        return [lo & 0xff, (lo >> 8) & 0xff, hi & 0xff, (hi >> 8) & 0xff]

    raise AssemblerError(f'Modalita\' sconosciuta: {mode}')


def assemble(src, base_addr=0):
    """Compila il sorgente assembly in una lista di byte (int 0-255).
    base_addr: indirizzo a cui il programma verra' effettivamente
    caricato in memoria - necessario perche' i salti/JSR usano
    indirizzi ASSOLUTI (non relativi), quindi le etichette vanno
    calcolate gia' tenendo conto di dove il programma vivra' davvero."""
    lines = _parse_lines(src)
    parsed, labels = _first_pass(lines)
    labels = {name: addr + base_addr for name, addr in labels.items()}

    rom = []
    for internal, opcode, mode, arg, _addr in parsed:
        rom.append(opcode)
        rom.extend(_emit_operand(mode, arg, labels))

    return rom
