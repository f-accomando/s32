"""
lang.py - ConsoleLang per S32.

Il LINGUAGGIO (sintassi, lexer, parser) e' IDENTICO a quello della
v1 (console_v1_frozen/lang.py) - stesso "var", "if", "func" eccetera.
Cambia SOLO il CodeGen: qui genera per il nuovo set di istruzioni
S32 (assembler.py), non piu' per quello a 8 bit della v1.

MIGLIORAMENTI nel codice generato, resi possibili dalla nuova CPU:
- regx/regy usano TAX/TXA/TAY/TYA (trasferimenti VERI), non piu' il
  riuso improprio di LDX/STX come in v1
- il confronto '<' usa CMP (che non distrugge A) + JLT/JGE, non piu'
  una SUB che consumava l'accumulatore - stesso limite di superficie
  ("< solo nei condizionali", l'hardware non produce un booleano
  pulito), ma l'implementazione sotto e' piu' pulita
- le funzioni salvano/ripristinano X/Y con PHX/PHY/PLY/PLX (stack
  hardware vero), non piu' uno scratch di memoria fisso
- write_oam scrive DIRETTAMENTE agli indirizzi OAM (bus flat a 24
  bit) - niente piu' la danza "imposta indirizzo poi scrivi dato"
  delle porte indirette di v1

NON ANCORA PORTATO: select_room/set_bg_palette (le porte ROOM_SELECT/
BG_PALETTE erano specifiche del meccanismo di cambio stanza di v1 -
S32 non ha ancora un equivalente, la VRAM piu' grande apre altre
strade non ancora decise). Verranno aggiunte quando quel meccanismo
sara' progettato per S32, non prima.
"""

import re

from memory_map import WRAM_BASE, OAM_BASE, OAM_SLOT_BYTES

# ---------------------------------------------------------------
# LEXER - identico a v1
# ---------------------------------------------------------------

TOKEN_SPEC = [
    ('COMMENT',  r'//[^\n]*|--[^\n]*'),
    ('NUMBER',   r'0[xX][0-9a-fA-F]+|\d+'),
    ('IDENT',    r'[A-Za-z_][A-Za-z0-9_]*'),
    ('OP',       r'==|[+\-&^=(){},?:<]'),
    ('NEWLINE',  r'\n'),
    ('SKIP',     r'[ \t]+'),
    ('MISMATCH', r'.'),
]
TOKEN_RE = re.compile('|'.join(f'(?P<{n}>{p})' for n, p in TOKEN_SPEC))

KEYWORDS = {'var', 'state', 'if', 'else', 'func', 'call', 'return', 'input',
            'regx', 'regy', 'clamp_x', 'clamp_y', 'write_oam', 'halt', 'poke',
            'select_stage', 'set_scroll', 'play_sound'}


def tokenize(src):
    tokens = []
    for m in TOKEN_RE.finditer(src):
        kind = m.lastgroup
        text = m.group()
        if kind in ('SKIP', 'COMMENT', 'NEWLINE'):
            continue
        if kind == 'MISMATCH':
            raise SyntaxError(f'Carattere inatteso: {text!r}')
        tokens.append((kind, text))
    tokens.append(('EOF', ''))
    return tokens


# ---------------------------------------------------------------
# PARSER - identico a v1 (meno select_room/set_bg_palette, vedi sopra)
# ---------------------------------------------------------------

class Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    def peek(self):
        return self.tokens[self.pos]

    def next(self):
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def expect(self, text):
        kind, val = self.next()
        if val != text:
            raise SyntaxError(f'Atteso {text!r}, trovato {val!r}')
        return val

    def parse_program(self):
        stmts = []
        while self.peek()[0] != 'EOF':
            stmts.append(self.parse_stmt())
        return ('program', stmts)

    def parse_block(self):
        self.expect('{')
        stmts = []
        while self.peek()[1] != '}':
            stmts.append(self.parse_stmt())
        self.expect('}')
        return stmts

    def parse_stmt(self):
        kind, val = self.peek()

        if val == 'var':
            self.next()
            name = self.next()[1]
            self.expect('=')
            expr = self.parse_expr()
            return ('var', name, expr)

        if val == 'state':
            self.next()
            name = self.next()[1]
            self.expect('=')
            if self.peek()[0] != 'NUMBER':
                raise SyntaxError('state richiede un valore iniziale numerico letterale')
            init_val = int(self.next()[1], 0)
            return ('state', name, init_val)

        if val == 'if':
            self.next()
            self.expect('(')
            cond = self.parse_expr()
            self.expect(')')
            then_body = self.parse_block()
            else_body = []
            if self.peek()[1] == 'else':
                self.next()
                else_body = self.parse_block()
            return ('if', cond, then_body, else_body)

        if val == 'func':
            self.next()
            name = self.next()[1]
            self.expect('(')
            self.expect(')')
            body = self.parse_block()
            return ('func', name, body)

        if val == 'call':
            self.next()
            name = self.next()[1]
            self.expect('(')
            self.expect(')')
            return ('call', name)

        if val == 'return':
            self.next()
            return ('return',)

        if val == 'clamp_x' or val == 'clamp_y':
            self.next()
            self.expect('(')
            lo = int(self.next()[1], 0)
            self.expect(',')
            hi = int(self.next()[1], 0)
            self.expect(')')
            return ('clamp', val, lo, hi)

        if val == 'write_oam':
            self.next()
            self.expect('(')
            args = [self.parse_expr()]
            while self.peek()[1] == ',':
                self.next()
                args.append(self.parse_expr())
            self.expect(')')
            if len(args) != 5:
                raise SyntaxError('write_oam richiede 5 argomenti: slot,x,y,tile,attr')
            return ('write_oam', args)

        if val == 'halt':
            self.next()
            self.expect('(')
            self.expect(')')
            return ('halt',)

        if val == 'poke':
            self.next()
            self.expect('(')
            if self.peek()[0] != 'NUMBER':
                raise SyntaxError(
                    'poke() richiede un indirizzo LETTERALE come primo argomento '
                    '(la CPU non ha indirizzamento indicizzato - vedi doc_asm.md)'
                )
            addr = int(self.next()[1], 0)
            self.expect(',')
            value_expr = self.parse_expr()
            self.expect(')')
            return ('poke', addr, value_expr)

        if val == 'select_stage':
            self.next()
            self.expect('(')
            value_expr = self.parse_expr()
            self.expect(')')
            return ('select_stage', value_expr)

        if val == 'play_sound':
            self.next()
            self.expect('(')
            value_expr = self.parse_expr()
            self.expect(')')
            return ('play_sound', value_expr)

        if val == 'set_scroll':
            self.next()
            self.expect('(')
            x_expr = self.parse_expr()
            self.expect(',')
            y_expr = self.parse_expr()
            self.expect(')')
            return ('set_scroll', x_expr, y_expr)

        if kind == 'IDENT':
            name = self.next()[1]
            self.expect('=')
            expr = self.parse_expr()
            return ('assign', name, expr)

        raise SyntaxError(f'Istruzione inattesa: {val!r}')

    def parse_primary(self):
        kind, val = self.next()
        if kind == 'NUMBER':
            return ('num', int(val, 0))
        if val == 'input':
            self.expect('(')
            self.expect(')')
            return ('input',)
        if val == 'regx':
            return ('regx',)
        if val == 'regy':
            return ('regy',)
        if kind == 'IDENT':
            return ('var_ref', val)
        raise SyntaxError(f'Espressione inattesa: {val!r}')

    def parse_expr(self):
        return self.parse_comparable()

    def parse_comparable(self):
        left = self.parse_binop_expr()

        if self.peek()[1] == '<':
            self.next()
            right = self.parse_binop_expr()
            left = ('lt', left, right)

        if self.peek()[1] == '?':
            self.next()
            true_expr = self.parse_binop_expr()
            false_expr = None
            if self.peek()[1] == ':':
                self.next()
                false_expr = self.parse_binop_expr()
            return ('ternary', left, true_expr, false_expr)

        return left

    def parse_binop_expr(self):
        left = self.parse_primary()
        if self.peek()[1] in ('+', '-', '&', '^'):
            op = self.next()[1]
            right = self.parse_primary()
            left = ('binop', op, left, right)
        return left


# ---------------------------------------------------------------
# describe_* - identico a v1 (per l'annotazione dell'assembly generato)
# ---------------------------------------------------------------

def describe_expr(expr):
    tag = expr[0]
    if tag == 'num':
        return str(expr[1])
    if tag == 'input':
        return 'input()'
    if tag == 'regx':
        return 'regx'
    if tag == 'regy':
        return 'regy'
    if tag == 'var_ref':
        return expr[1]
    if tag == 'binop':
        return f'{describe_expr(expr[2])} {expr[1]} {describe_expr(expr[3])}'
    if tag == 'lt':
        return f'{describe_expr(expr[1])} < {describe_expr(expr[2])}'
    if tag == 'ternary':
        false_txt = describe_expr(expr[3]) if expr[3] is not None else '(implicito)'
        return f'{describe_expr(expr[1])} ? {describe_expr(expr[2])} : {false_txt}'
    return '?'


def describe_stmt(stmt):
    tag = stmt[0]
    if tag == 'var':
        return f'var {stmt[1]} = {describe_expr(stmt[2])}'
    if tag == 'state':
        return f'state {stmt[1]} = {stmt[2]}'
    if tag == 'assign':
        return f'{stmt[1]} = {describe_expr(stmt[2])}'
    if tag == 'if':
        return f'if ({describe_expr(stmt[1])}) {{ ... }}' + (' else { ... }' if stmt[3] else '')
    if tag == 'func':
        return f'func {stmt[1]}() {{ ... }}'
    if tag == 'call':
        return f'call {stmt[1]}()'
    if tag == 'return':
        return 'return'
    if tag == 'clamp':
        return f'{stmt[1]}({stmt[2]}, {stmt[3]})'
    if tag == 'write_oam':
        args = ', '.join(describe_expr(a) for a in stmt[1])
        return f'write_oam({args})'
    if tag == 'halt':
        return 'halt()'
    if tag == 'poke':
        return f'poke({stmt[1]}, {describe_expr(stmt[2])})'
    if tag == 'select_stage':
        return f'select_stage({describe_expr(stmt[1])})'
    if tag == 'play_sound':
        return f'play_sound({describe_expr(stmt[1])})'
    if tag == 'set_scroll':
        return f'set_scroll({describe_expr(stmt[1])}, {describe_expr(stmt[2])})'
    return '?'


# ---------------------------------------------------------------
# CODEGEN - NUOVO per S32 (questa e' la parte che cambia rispetto a v1)
# ---------------------------------------------------------------

class CodeGen:
    def __init__(self, var_base=WRAM_BASE + 0x200, annotate=False):
        self.lines = []
        self.vars = {}
        self.state_vars = {}
        self.next_var_addr = var_base
        self.label_count = 0
        self.func_names = set()
        self.annotate = annotate

    def new_label(self, hint):
        self.label_count += 1
        return f'{hint}_{self.label_count}'

    def alloc_var(self, name):
        if name in self.vars:
            raise SyntaxError(f'Variabile "{name}" gia\' dichiarata')
        addr = self.next_var_addr
        self.next_var_addr += 2  # ogni valore e' a 16 bit = 2 byte
        self.vars[name] = addr
        return addr

    def var_addr(self, name):
        if name not in self.vars:
            raise SyntaxError(f'Variabile "{name}" non dichiarata (usa "var" prima)')
        return self.vars[name]

    def emit(self, line):
        self.lines.append(line)

    def resolve_rhs(self, node):
        """Come in v1: per il secondo operando di +/-/&/<, ritorna
        ('imm', valore) o ('addr', indirizzo). Se il nodo e' regx/
        regy/input() (un valore in un registro, non in memoria), lo
        materializza prima in uno scratch, perche' ADD_ADDR/SUB_ADDR/
        ecc. leggono solo dalla memoria."""
        if node[0] == 'num':
            return ('imm', node[1])
        if node[0] == 'var_ref':
            return ('addr', self.var_addr(node[1]))
        if node[0] in ('regx', 'regy', 'input'):
            if not hasattr(self, '_rhs_temp_addr'):
                self._rhs_temp_addr = self.alloc_var('__rhs_temp')
            self.gen_expr(node)
            self.emit(f'STA {self._rhs_temp_addr}')
            return ('addr', self._rhs_temp_addr)
        raise SyntaxError(
            f'Operando non supportato come secondo termine di +/-/&/<: {node!r}'
        )

    def gen_condition(self, cond, false_label):
        """Come in v1, ma usa CMP invece di SUB per il confronto '<'
        - stesso comportamento visibile, A pero' resta intatto (CMP
        non lo distrugge, a differenza della SUB che usavamo in v1)."""
        if cond[0] == 'lt':
            _, left, right = cond
            kind, val = self.resolve_rhs(right)
            self.gen_expr(left)
            if kind == 'imm':
                self.emit(f'CMP #{val}')
            else:
                self.emit(f'CMP {val}')
            self.emit(f'JGE {false_label}')
        else:
            self.gen_expr(cond)
            self.emit(f'CMP #0')
            self.emit(f'JZ {false_label}')

    def gen_expr(self, expr):
        """Genera codice che lascia il risultato in A."""
        tag = expr[0]
        if tag == 'num':
            self.emit(f'LDA #{expr[1]}')
        elif tag == 'input':
            self.emit('IN')
        elif tag == 'regx':
            self.emit('TXA')  # A = X
        elif tag == 'regy':
            self.emit('TYA')  # A = Y
        elif tag == 'var_ref':
            self.emit(f'LDA {self.var_addr(expr[1])}')
        elif tag == 'binop':
            op, left, right = expr[1], expr[2], expr[3]
            kind, val = self.resolve_rhs(right)
            self.gen_expr(left)
            mnem = {'+': 'ADD', '-': 'SUB', '&': 'AND', '^': 'XOR'}[op]
            if kind == 'imm':
                self.emit(f'{mnem} #{val}')
            else:
                self.emit(f'{mnem} {val}')
        elif tag == 'lt':
            raise SyntaxError(
                "Il confronto '<' si puo' usare SOLO come condizione di "
                "if/ternario, non come valore generico."
            )
        elif tag == 'ternary':
            cond, true_expr, false_expr = expr[1], expr[2], expr[3]
            if false_expr is None:
                raise SyntaxError(
                    'Ternario senza ramo ":" fuori da un contesto di '
                    'assegnazione: non so quale valore usare come "altrimenti".'
                )
            else_label = self.new_label('TELSE')
            end_label = self.new_label('TEND')
            self.gen_condition(cond, else_label)
            self.gen_expr(true_expr)
            self.emit(f'JMP {end_label}')
            self.emit(f'{else_label}:')
            self.gen_expr(false_expr)
            self.emit(f'{end_label}:')
        else:
            raise SyntaxError(f'Espressione non gestita: {expr!r}')

    def gen_stmt(self, stmt):
        if self.annotate and stmt[0] not in ('func',):
            self.emit(f'; --- {describe_stmt(stmt)}')

        tag = stmt[0]

        if tag == 'var':
            _, name, expr = stmt
            addr = self.alloc_var(name)
            self.gen_expr(expr)
            self.emit(f'STA {addr}')

        elif tag == 'state':
            _, name, init_val = stmt
            addr = self.alloc_var(name)
            self.state_vars[name] = (addr, init_val)

        elif tag == 'assign':
            _, name, expr = stmt
            if expr[0] == 'ternary' and expr[3] is None:
                current = ('regx',) if name == 'regx' else \
                          ('regy',) if name == 'regy' else \
                          ('var_ref', name)
                expr = ('ternary', expr[1], expr[2], current)
            self.gen_expr(expr)
            if name == 'regx':
                self.emit('TAX')  # X = A
            elif name == 'regy':
                self.emit('TAY')  # Y = A
            else:
                self.emit(f'STA {self.var_addr(name)}')

        elif tag == 'if':
            _, cond, then_body, else_body = stmt
            else_label = self.new_label('ELSE')
            end_label = self.new_label('ENDIF')
            self.gen_condition(cond, else_label)
            for s in then_body:
                self.gen_stmt(s)
            self.emit(f'JMP {end_label}')
            self.emit(f'{else_label}:')
            for s in else_body:
                self.gen_stmt(s)
            self.emit(f'{end_label}:')

        elif tag == 'func':
            _, name, body = stmt
            if self.annotate:
                self.emit(f'; --- func {name}() {{ ... }} (prologo: PHX/PHY) ---')
            self.func_names.add(name)
            self.emit(f'{name}:')
            self.emit('PHX')
            self.emit('PHY')
            for s in body:
                self.gen_stmt(s)
            self.emit('PLY')
            self.emit('PLX')
            self.emit('RTS')

        elif tag == 'call':
            self.emit(f'JSR {stmt[1]}')

        elif tag == 'return':
            self.emit('PLY')
            self.emit('PLX')
            self.emit('RTS')

        elif tag == 'clamp':
            _, which, lo, hi = stmt
            mnem = 'CLAMPX' if which == 'clamp_x' else 'CLAMPY'
            self.emit(f'{mnem} {lo},{hi}')

        elif tag == 'write_oam':
            _, args = stmt
            slot_expr = args[0]
            if slot_expr[0] != 'num':
                raise SyntaxError('write_oam: "slot" deve essere un numero letterale (0-511)')
            slot = slot_expr[1]
            base = OAM_BASE + slot * OAM_SLOT_BYTES
            field_offsets = [0, 2, 4, 6]  # x,y,tile,attr - ciascuno 2 byte
            for field_expr, offset in zip(args[1:], field_offsets):
                self.gen_expr(field_expr)
                self.emit(f'STA {base + offset}')

        elif tag == 'halt':
            self.emit('HALT')

        elif tag == 'poke':
            _, addr, value_expr = stmt
            self.gen_expr(value_expr)
            self.emit(f'STA {addr}')

        elif tag == 'select_stage':
            self.gen_expr(stmt[1])
            self.emit('STA 0x042001')  # porta STAGE_SELECT, vedi cpu.py

        elif tag == 'play_sound':
            self.gen_expr(stmt[1])
            self.emit('STA 0x042004')  # porta SOUND, vedi cpu.py - la
                                        # CPU accoda l'ID, il launcher
                                        # lo suona a fine frame

        elif tag == 'set_scroll':
            self.gen_expr(stmt[1])
            self.emit('STA 0x042002')  # porta SCROLL_X, vedi cpu.py
            self.gen_expr(stmt[2])
            self.emit('STA 0x042003')  # porta SCROLL_Y, vedi cpu.py

        else:
            raise SyntaxError(f'Istruzione non gestita: {stmt!r}')

    def generate(self, ast):
        _, stmts = ast
        main_stmts = [s for s in stmts if s[0] != 'func']
        func_stmts = [s for s in stmts if s[0] == 'func']

        for s in main_stmts:
            self.gen_stmt(s)

        if main_stmts and main_stmts[-1][0] != 'halt':
            self.emit('HALT')

        for s in func_stmts:
            self.gen_stmt(s)

        return '\n'.join(self.lines)


def compile_source(src, var_base=WRAM_BASE + 0x200, annotate=False):
    """Compila il sorgente ConsoleLang per S32. Ritorna un dict con:
       'asm':        testo assembly (da passare a assembler.assemble())
       'vars':       nome variabile -> indirizzo WRAM (tutte)
       'state_vars': nome -> (indirizzo, valore_iniziale) SOLO per le
                     variabili 'state' - l'host deve scriverle in
                     memoria UNA VOLTA prima del ciclo di gioco
    """
    tokens = tokenize(src)
    ast = Parser(tokens).parse_program()
    gen = CodeGen(var_base=var_base, annotate=annotate)
    asm = gen.generate(ast)
    return {'asm': asm, 'vars': gen.vars, 'state_vars': gen.state_vars}
