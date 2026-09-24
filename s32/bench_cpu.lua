--[[
bench_cpu.lua - meta' del confronto Python/LuaJIT (vedi bench_cpu.py
per l'altra meta'): carica la STESSA immagine di memoria prodotta da
dump_cpu_state.py e cronometra N chiamate a cpu:run() con cpu.lua.

Uso (da lanciare con luajit, non lua "normale" - vedi cpu.lua):
    luajit bench_cpu.lua [cpu_bench_mem.bin] [start_pc] [n_frame]

Esempio:
    luajit bench_cpu.lua cpu_bench_mem.bin 0x1000 1000

Deve girare dalla stessa cartella di cpu.lua (require("cpu") lo cerca
li' di default).
]]
local ffi = require("ffi")

ffi.cdef[[
typedef struct { long tv_sec; long tv_nsec; } timespec_t;
int clock_gettime(int clk_id, timespec_t *tp);
]]
local CLOCK_MONOTONIC = 1
local function now()
    local ts = ffi.new("timespec_t")
    ffi.C.clock_gettime(CLOCK_MONOTONIC, ts)
    return tonumber(ts.tv_sec) + tonumber(ts.tv_nsec) / 1e9
end

local cpu_module = require("cpu")

local mem_path = arg[1] or "cpu_bench_mem.bin"
local start_pc = arg[2] and tonumber(arg[2]) or 0x001000
local n_frames = arg[3] and tonumber(arg[3]) or 1000

local cpu = cpu_module.new()
cpu:load_memory_image(mem_path)

local cpu_total = 0
local total_instr = 0
for i = 1, n_frames do
    local t0 = now()
    local n = cpu:run(start_pc, 0)
    local t1 = now()
    cpu_total = cpu_total + (t1 - t0)
    total_instr = total_instr + n
end

local cpu_ms = cpu_total / n_frames * 1000
local avg_instr = total_instr / n_frames
local us_per_instr = total_instr > 0 and (cpu_total / total_instr) * 1e6 or 0

print("LuaJIT (cpu.lua)")
print(string.format("  %d frame, cpu totale %.2fms, media %.4fms/frame, istruzioni media %.1f/frame, %.2fus/istruzione",
    n_frames, cpu_total * 1000, cpu_ms, avg_instr, us_per_instr))
