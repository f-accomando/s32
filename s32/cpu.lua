--[[
cpu.lua - stessa CPU di cpu.py (stesso set di opcode, stessi registri,
stessa mappa indirizzi), riscritta in LuaJIT per confrontare la
velocita' di emulazione con la versione Python/Cython.

ESPERIMENTO, non ancora integrato nel motore vero (launcher.py resta
Python) - vedi bench_cpu.lua/bench_cpu.py per il confronto diretto,
entrambi caricano LA STESSA immagine di memoria (dump_cpu_state.py) e
misurano lo stesso identico lavoro.

Ogni funzione qui sotto e' la traduzione RIGA PER RIGA del corrispondente
_op_XX in cpu.py - stessa logica, stessi flag, nessuna scorciatoia. Se
cpu.py cambia, questo file va aggiornato a mano (nessuna generazione
automatica).
]]
local ffi = require("ffi")
local bit = require("bit")

local M = {}

-- ---------------------------------------------------------------
-- mappa indirizzi (copiata da memory_map.py - valori fissi del
-- progetto, non ricavati a runtime)
-- ---------------------------------------------------------------
local ADDRESS_SPACE = 16777216  -- 1 << 24
local ADDRESS_MASK = ADDRESS_SPACE - 1
local WRAM_BASE = 0x000000
local WRAM_END = 0x020000
local VRAM_BASE = 0x020000
local TILEMAP_VRAM_OFFSET = 0
local TILEMAP_BYTES = 32768

local FLAG_ZERO = 0x01
local FLAG_NEGATIVE = 0x02
local FLAG_CARRY = 0x04
local FLAG_OVERFLOW = 0x08

local PORT_INPUT = 0x042000
local PORT_STAGE_SELECT = 0x042001
local PORT_SCROLL_X = 0x042002
local PORT_SCROLL_Y = 0x042003
local PORT_SOUND = 0x042004

local EXTRA_INPUT_PORTS = {0x042010, 0x042011, 0x042012, 0x042013, 0x042014, 0x042015, 0x042016}
local IS_INPUT_PORT = {[PORT_INPUT] = true}
for _, p in ipairs(EXTRA_INPUT_PORTS) do IS_INPUT_PORT[p] = true end

-- ---------------------------------------------------------------
-- CPU: mem come array C tipizzato (ffi) - stesso ruolo di
-- bytearray(ADDRESS_SPACE) in Python, ma indicizzazione a costo zero
-- una volta che LuaJIT compila il ciclo caldo
-- ---------------------------------------------------------------
local CPU = {}
CPU.__index = CPU
M.CPU = CPU

function M.new()
    local self = setmetatable({}, CPU)
    self.mem = ffi.new("uint8_t[?]", ADDRESS_SPACE)
    self.a, self.x, self.y, self.pc, self.flags = 0, 0, 0, 0, 0
    self.sp = WRAM_END - 2  -- stack hardware, cresce verso il basso (vedi cpu.py)
    self.stages = {}
    self.current_stage = 0
    self.scroll_x, self.scroll_y = 0, 0
    self.sound_queue = {}
    return self
end
M.new_cpu = M.new  -- alias esplicito, in caso "new" confligga col naming di chi importa

function CPU:load_memory_image(path)
    local f = assert(io.open(path, "rb"))
    local data = f:read("*all")
    f:close()
    assert(#data == ADDRESS_SPACE,
        string.format("dimensione immagine inattesa: %d byte (attesi %d)", #data, ADDRESS_SPACE))
    ffi.copy(self.mem, data, ADDRESS_SPACE)
end

-- -----------------------------------------------------------
-- accesso memoria a 16 bit (little-endian su 2 byte) - vedi
-- cpu.py:read16/write16
-- -----------------------------------------------------------
function CPU:read16(addr)
    addr = bit.band(addr, ADDRESS_MASK)
    local lo = self.mem[addr]
    local hi = self.mem[bit.band(addr + 1, ADDRESS_MASK)]
    return bit.bor(lo, bit.lshift(hi, 8))
end

function CPU:write16(addr, value)
    addr = bit.band(addr, ADDRESS_MASK)
    value = bit.band(value, 0xffff)
    if addr == PORT_STAGE_SELECT then
        local data = self.stages[value]
        if data ~= nil then
            -- copia della tilemap: non serve al benchmark CPU-only
            -- (self.stages resta vuoto, stesso setup di
            -- run_benchmark() in launcher.py, che non chiama mai
            -- _load_cart_graphics) - lasciato qui solo per fedelta'
            -- di comportamento se in futuro si popola self.stages
            self.current_stage = value
        end
        return
    end
    if addr == PORT_SCROLL_X then self.scroll_x = value; return end
    if addr == PORT_SCROLL_Y then self.scroll_y = value; return end
    if addr == PORT_SOUND then self.sound_queue[#self.sound_queue + 1] = value; return end
    self.mem[addr] = bit.band(value, 0xff)
    self.mem[bit.band(addr + 1, ADDRESS_MASK)] = bit.band(bit.rshift(value, 8), 0xff)
end

function CPU:read_mem(addr)
    if IS_INPUT_PORT[addr] then
        return self.mem[addr]
    end
    return self:read16(addr)
end

function CPU:write_mem(addr, value)
    self:write16(addr, value)
end

-- -----------------------------------------------------------
-- flag - vedi cpu.py:set_flag/update_zn/flag
-- -----------------------------------------------------------
function CPU:set_flag(flag_bit, condition)
    if condition then
        self.flags = bit.bor(self.flags, flag_bit)
    else
        self.flags = bit.band(self.flags, bit.bnot(flag_bit))
    end
end

function CPU:update_zn(value)
    self:set_flag(FLAG_ZERO, value == 0)
    self:set_flag(FLAG_NEGATIVE, bit.band(value, 0x8000) ~= 0)
end

function CPU:flag(f)
    return bit.band(self.flags, f) ~= 0
end

-- -----------------------------------------------------------
-- stack (16 bit per valore) - vedi cpu.py:push/pop
-- -----------------------------------------------------------
function CPU:push(value)
    self:write16(self.sp, value)
    self.sp = self.sp - 2
    if self.sp < WRAM_BASE then
        error("Stack overflow (sceso sotto WRAM_BASE)")
    end
end

function CPU:pop()
    self.sp = self.sp + 2
    if self.sp > WRAM_END - 2 then
        error("Stack underflow (nessun valore da togliere)")
    end
    return self:read16(self.sp)
end

-- -----------------------------------------------------------
-- ALU - vedi cpu.py:_add/_sub/_and/_or/_xor/_cmp
-- -----------------------------------------------------------
function CPU:_add(operand)
    local raw = self.a + operand
    self:set_flag(FLAG_CARRY, raw > 0xffff)
    local result = bit.band(raw, 0xffff)
    local a_sign, op_sign, r_sign = bit.band(self.a, 0x8000), bit.band(operand, 0x8000), bit.band(result, 0x8000)
    self:set_flag(FLAG_OVERFLOW, (a_sign == op_sign) and (r_sign ~= a_sign))
    self:update_zn(result)
    self.a = result
end

function CPU:_sub(operand)
    local raw = self.a - operand
    self:set_flag(FLAG_CARRY, self.a >= operand)
    local result = bit.band(raw, 0xffff)
    local a_sign, op_sign, r_sign = bit.band(self.a, 0x8000), bit.band(operand, 0x8000), bit.band(result, 0x8000)
    self:set_flag(FLAG_OVERFLOW, (a_sign ~= op_sign) and (r_sign ~= a_sign))
    self:update_zn(result)
    self.a = result
end

function CPU:_and(operand) self.a = bit.band(self.a, operand); self:update_zn(self.a) end
function CPU:_or(operand) self.a = bit.bor(self.a, operand); self:update_zn(self.a) end
function CPU:_xor(operand) self.a = bit.bxor(self.a, operand); self:update_zn(self.a) end

function CPU:_cmp(operand)
    local result = bit.band(self.a - operand, 0xffff)
    self:set_flag(FLAG_CARRY, self.a >= operand)
    self:update_zn(result)
end

-- -----------------------------------------------------------
-- helper di lettura operandi - vedi cpu.py:_imm16/_addr24
-- -----------------------------------------------------------
function CPU:_imm16()
    return bit.bor(self.mem[self.pc + 1], bit.lshift(self.mem[self.pc + 2], 8))
end

function CPU:_addr24()
    return bit.bor(self.mem[self.pc + 1], bit.lshift(self.mem[self.pc + 2], 8), bit.lshift(self.mem[self.pc + 3], 16))
end

-- -----------------------------------------------------------
-- un opcode per funzione, stesso identico corpo di ogni _op_XX in
-- cpu.py - tabella condivisa fra tutte le istanze (le funzioni
-- prendono self esplicitamente, non serve ricostruirla per CPU, a
-- differenza del dict per-istanza di Python che li' serviva per i
-- metodi bound)
-- -----------------------------------------------------------
local OPCODES = {}

OPCODES[0x00] = function(c) c.pc = c.pc + 1; return true end  -- NOP
OPCODES[0x01] = function(c) return false end  -- HALT

OPCODES[0x10] = function(c) c.a = c:_imm16(); c:update_zn(c.a); c.pc = c.pc + 3; return true end  -- LDA #imm
OPCODES[0x11] = function(c) c.a = c:read_mem(c:_addr24()); c:update_zn(c.a); c.pc = c.pc + 4; return true end  -- LDA addr
OPCODES[0x12] = function(c) c:write_mem(c:_addr24(), c.a); c.pc = c.pc + 4; return true end  -- STA addr
OPCODES[0x13] = function(c) c.x = c:_imm16(); c:update_zn(c.x); c.pc = c.pc + 3; return true end  -- LDX #imm
OPCODES[0x14] = function(c) c.x = c:read_mem(c:_addr24()); c:update_zn(c.x); c.pc = c.pc + 4; return true end  -- LDX addr
OPCODES[0x15] = function(c) c:write_mem(c:_addr24(), c.x); c.pc = c.pc + 4; return true end  -- STX addr
OPCODES[0x16] = function(c) c.y = c:_imm16(); c:update_zn(c.y); c.pc = c.pc + 3; return true end  -- LDY #imm
OPCODES[0x17] = function(c) c.y = c:read_mem(c:_addr24()); c:update_zn(c.y); c.pc = c.pc + 4; return true end  -- LDY addr
OPCODES[0x18] = function(c) c:write_mem(c:_addr24(), c.y); c.pc = c.pc + 4; return true end  -- STY addr

OPCODES[0x20] = function(c) c.x = c.a; c:update_zn(c.x); c.pc = c.pc + 1; return true end  -- TAX
OPCODES[0x21] = function(c) c.a = c.x; c:update_zn(c.a); c.pc = c.pc + 1; return true end  -- TXA
OPCODES[0x22] = function(c) c.y = c.a; c:update_zn(c.y); c.pc = c.pc + 1; return true end  -- TAY
OPCODES[0x23] = function(c) c.a = c.y; c:update_zn(c.a); c.pc = c.pc + 1; return true end  -- TYA
OPCODES[0x24] = function(c) c.y = c.x; c:update_zn(c.y); c.pc = c.pc + 1; return true end  -- TXY
OPCODES[0x25] = function(c) c.x = c.y; c:update_zn(c.x); c.pc = c.pc + 1; return true end  -- TYX

OPCODES[0x30] = function(c) c:_add(c:_imm16()); c.pc = c.pc + 3; return true end
OPCODES[0x31] = function(c) c:_sub(c:_imm16()); c.pc = c.pc + 3; return true end
OPCODES[0x32] = function(c) c:_and(c:_imm16()); c.pc = c.pc + 3; return true end
OPCODES[0x33] = function(c) c:_or(c:_imm16()); c.pc = c.pc + 3; return true end
OPCODES[0x34] = function(c) c:_xor(c:_imm16()); c.pc = c.pc + 3; return true end
OPCODES[0x35] = function(c) c:_cmp(c:_imm16()); c.pc = c.pc + 3; return true end

OPCODES[0x40] = function(c) c:_add(c:read_mem(c:_addr24())); c.pc = c.pc + 4; return true end
OPCODES[0x41] = function(c) c:_sub(c:read_mem(c:_addr24())); c.pc = c.pc + 4; return true end
OPCODES[0x42] = function(c) c:_and(c:read_mem(c:_addr24())); c.pc = c.pc + 4; return true end
OPCODES[0x43] = function(c) c:_or(c:read_mem(c:_addr24())); c.pc = c.pc + 4; return true end
OPCODES[0x44] = function(c) c:_xor(c:read_mem(c:_addr24())); c.pc = c.pc + 4; return true end
OPCODES[0x45] = function(c) c:_cmp(c:read_mem(c:_addr24())); c.pc = c.pc + 4; return true end

OPCODES[0x50] = function(c)  -- ASL
    local carry_out = bit.band(c.a, 0x8000) ~= 0
    c.a = bit.band(bit.lshift(c.a, 1), 0xffff)
    c:set_flag(FLAG_CARRY, carry_out); c:update_zn(c.a); c.pc = c.pc + 1; return true
end
OPCODES[0x51] = function(c)  -- LSR
    local carry_out = bit.band(c.a, 0x0001) ~= 0
    c.a = bit.rshift(c.a, 1)
    c:set_flag(FLAG_CARRY, carry_out); c:update_zn(c.a); c.pc = c.pc + 1; return true
end
OPCODES[0x52] = function(c)  -- INC addr
    local addr = c:_addr24(); local v = bit.band(c:read_mem(addr) + 1, 0xffff)
    c:write_mem(addr, v); c:update_zn(v); c.pc = c.pc + 4; return true
end
OPCODES[0x53] = function(c)  -- DEC addr
    local addr = c:_addr24(); local v = bit.band(c:read_mem(addr) - 1, 0xffff)
    c:write_mem(addr, v); c:update_zn(v); c.pc = c.pc + 4; return true
end
OPCODES[0x54] = function(c) c.x = bit.band(c.x + 1, 0xffff); c:update_zn(c.x); c.pc = c.pc + 1; return true end  -- INX
OPCODES[0x55] = function(c) c.y = bit.band(c.y + 1, 0xffff); c:update_zn(c.y); c.pc = c.pc + 1; return true end  -- INY
OPCODES[0x56] = function(c) c.x = bit.band(c.x - 1, 0xffff); c:update_zn(c.x); c.pc = c.pc + 1; return true end  -- DEX
OPCODES[0x57] = function(c) c.y = bit.band(c.y - 1, 0xffff); c:update_zn(c.y); c.pc = c.pc + 1; return true end  -- DEY

OPCODES[0x60] = function(c) c.pc = c:_addr24(); return true end  -- JMP
OPCODES[0x61] = function(c) c.pc = c:flag(FLAG_ZERO) and c:_addr24() or c.pc + 4; return true end  -- JZ
OPCODES[0x62] = function(c) c.pc = (not c:flag(FLAG_ZERO)) and c:_addr24() or c.pc + 4; return true end  -- JNZ
OPCODES[0x63] = function(c) c.pc = c:flag(FLAG_NEGATIVE) and c:_addr24() or c.pc + 4; return true end  -- JLT
OPCODES[0x64] = function(c) c.pc = (not c:flag(FLAG_NEGATIVE)) and c:_addr24() or c.pc + 4; return true end  -- JGE
OPCODES[0x65] = function(c) c.pc = c:flag(FLAG_CARRY) and c:_addr24() or c.pc + 4; return true end  -- JCS
OPCODES[0x66] = function(c) c.pc = (not c:flag(FLAG_CARRY)) and c:_addr24() or c.pc + 4; return true end  -- JCC
OPCODES[0x67] = function(c)  -- JSR
    local target = c:_addr24()
    c:push(c.pc + 4)
    c.pc = target
    return true
end
OPCODES[0x68] = function(c) c.pc = c:pop(); return true end  -- RTS

OPCODES[0x70] = function(c) c:push(c.a); c.pc = c.pc + 1; return true end  -- PHA
OPCODES[0x71] = function(c) c.a = c:pop(); c:update_zn(c.a); c.pc = c.pc + 1; return true end  -- PLA
OPCODES[0x72] = function(c) c:push(c.x); c.pc = c.pc + 1; return true end  -- PHX
OPCODES[0x73] = function(c) c.x = c:pop(); c:update_zn(c.x); c.pc = c.pc + 1; return true end  -- PLX
OPCODES[0x74] = function(c) c:push(c.y); c.pc = c.pc + 1; return true end  -- PHY
OPCODES[0x75] = function(c) c.y = c:pop(); c:update_zn(c.y); c.pc = c.pc + 1; return true end  -- PLY

OPCODES[0x80] = function(c) c.a = c.mem[PORT_INPUT]; c.pc = c.pc + 1; return true end  -- IN

OPCODES[0x90] = function(c)  -- CLAMPX lo,hi
    local lo = c:_imm16(); local hi = bit.bor(c.mem[c.pc + 3], bit.lshift(c.mem[c.pc + 4], 8))
    if c.x < lo then c.x = lo end
    if c.x > hi then c.x = hi end
    c.pc = c.pc + 5; return true
end
OPCODES[0x91] = function(c)  -- CLAMPY lo,hi
    local lo = c:_imm16(); local hi = bit.bor(c.mem[c.pc + 3], bit.lshift(c.mem[c.pc + 4], 8))
    if c.y < lo then c.y = lo end
    if c.y > hi then c.y = hi end
    c.pc = c.pc + 5; return true
end

-- -----------------------------------------------------------
-- esecuzione - vedi cpu.py:step/run
-- -----------------------------------------------------------
function CPU:step()
    local op = self.mem[self.pc]
    local handler = OPCODES[op]
    if not handler then
        error(string.format("Opcode sconosciuto: 0x%02X a pc=0x%06X", op, self.pc))
    end
    return handler(self)
end

function CPU:run(start_pc, input_byte, max_steps)
    input_byte = input_byte or 0
    max_steps = max_steps or 200000
    self.pc = start_pc
    self.mem[PORT_INPUT] = bit.band(input_byte, 0xff)
    local steps = 0
    while steps < max_steps do
        steps = steps + 1
        if not self:step() then
            return steps
        end
    end
    error(string.format("Superato il limite di sicurezza di %d passi (loop infinito?)", max_steps))
end

return M
