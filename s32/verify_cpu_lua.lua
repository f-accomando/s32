--[[
verify_cpu_lua.lua - meta' LuaJIT del confronto di correttezza (vedi
verify_cpu_lua.py per l'altra meta'). Carica cpu_lua_coverage_test.rom
(scritto da verify_cpu_lua.py - lancia prima quello) nella STESSA
posizione (CART_LOAD_ADDR) e con lo STESSO input byte, poi stampa lo
stato finale nello stesso formato: se le due righe "STATO:" sono
identiche, cpu.lua si comporta come cpu.py.

Uso:
    python3 verify_cpu_lua.py     -- genera cpu_lua_coverage_test.rom
    luajit verify_cpu_lua.lua     -- confronta
]]
local cpu_module = require("cpu")

local CART_LOAD_ADDR = 0x001000
local INPUT_BYTE = 42

local f = assert(io.open("cpu_lua_coverage_test.rom", "rb"))
local rom = f:read("*all")
f:close()

local cpu = cpu_module.new()
for i = 1, #rom do
    cpu.mem[CART_LOAD_ADDR + i - 1] = rom:byte(i)
end

local steps = cpu:run(CART_LOAD_ADDR, INPUT_BYTE)

local mem_hex = {}
for addr = 0x3000, 0x3033 do
    mem_hex[#mem_hex + 1] = string.format("%02x", cpu.mem[addr])
end

print(string.format("LuaJIT: istruzioni eseguite = %d", steps))
print(string.format("STATO: a=%d x=%d y=%d pc=%d flags=%d sp=%d mem[0x3000:0x3034]=%s",
    cpu.a, cpu.x, cpu.y, cpu.pc, cpu.flags, cpu.sp, table.concat(mem_hex)))
