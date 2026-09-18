"""
test_audio.py - verifica il sistema audio SENZA pygame e senza una
scheda audio: audio.py produce solo byte PCM, e la CPU si limita ad
accodare ID su PORT_SOUND. E' esattamente la stessa separazione che
rende testabile la PPU (che produce solo byte RGB).
"""

import struct

import audio
from assembler import assemble
from cpu import CPU
from lang import compile_source

fails = 0


def check(label, got, expected):
    global fails
    if got == expected:
        print(f"OK   {label}: atteso {expected}, ottenuto {got}")
    else:
        fails += 1
        print(f"FAIL {label}: atteso {expected}, ottenuto {got}")


# ---------------------------------------------------------------
# 1. Forme d'onda: lunghezza in campioni e ampiezza
# ---------------------------------------------------------------
sq = audio.square_wave(440, 0.1)
check("square_wave: lunghezza in byte (16 bit = 2 byte/campione)",
      len(sq), int(audio.SAMPLE_RATE * 0.1) * 2)

vals = struct.unpack(f"<{len(sq)//2}h", sq)
check("square_wave: raggiunge +ampiezza", max(vals), audio.AMPLITUDE)
check("square_wave: raggiunge -ampiezza", min(vals), -audio.AMPLITUDE)

# un'onda quadra al 50% passa meta' tempo in alto e meta' in basso
alti = sum(1 for v in vals if v > 0)
check("square_wave: duty 50% bilanciato (entro l'1%)",
      abs(alti - len(vals) / 2) < len(vals) * 0.01, True)

# duty basso -> molto meno tempo in alto
sq25 = audio.square_wave(440, 0.1, duty=0.25)
vals25 = struct.unpack(f"<{len(sq25)//2}h", sq25)
alti25 = sum(1 for v in vals25 if v > 0)
check("square_wave: duty 0.25 sta in alto meno del 50%", alti25 < alti, True)

# ---------------------------------------------------------------
# 2. Sweep: la frequenza cambia davvero nel tempo
# ---------------------------------------------------------------
sw = audio.sweep_wave(200, 2000, 0.2)
check("sweep_wave: lunghezza corretta", len(sw), int(audio.SAMPLE_RATE * 0.2) * 2)

sv = struct.unpack(f"<{len(sw)//2}h", sw)
meta = len(sv) // 2


def cambi_segno(seq):
    return sum(1 for i in range(1, len(seq)) if (seq[i] > 0) != (seq[i-1] > 0))


# salendo di frequenza, la seconda meta' deve oscillare piu' della prima
check("sweep_wave: la frequenza sale (piu' oscillazioni nella 2a meta')",
      cambi_segno(sv[meta:]) > cambi_segno(sv[:meta]), True)

# ---------------------------------------------------------------
# 3. Rumore: deterministico e con inviluppo calante
# ---------------------------------------------------------------
check("noise: deterministico (stessa uscita a ogni chiamata)",
      audio.noise(0.05) == audio.noise(0.05), True)

nz = audio.noise(0.2, decay=True)
nv = struct.unpack(f"<{len(nz)//2}h", nz)
picco_inizio = max(abs(v) for v in nv[:len(nv)//10])
picco_fine = max(abs(v) for v in nv[-len(nv)//10:])
check("noise: l'inviluppo cala verso la fine", picco_fine < picco_inizio, True)

nz_flat = audio.noise(0.2, decay=False)
nfv = struct.unpack(f"<{len(nz_flat)//2}h", nz_flat)
check("noise: senza decay l'ampiezza resta piena",
      max(abs(v) for v in nfv[-len(nfv)//10:]) == audio.AMPLITUDE, True)

# ---------------------------------------------------------------
# 4. Silenzio
# ---------------------------------------------------------------
sil = audio.silence(0.1)
check("silence: tutti campioni a zero", set(sil), {0})

# ---------------------------------------------------------------
# mono_to_stereo(): adatta i campioni quando il mixer nega stereo
# nonostante la richiesta di mono (capita su Windows) - senza
# questo l'audio sarebbe silenzioso o distorto senza errore esplicito
# ---------------------------------------------------------------
mono_test = struct.pack('<3h', 100, -200, 300)
stereo_test = audio.mono_to_stereo(mono_test)
check("mono_to_stereo: raddoppia la lunghezza in byte",
      len(stereo_test), len(mono_test) * 2)
vals_stereo = struct.unpack(f"<{len(stereo_test)//2}h", stereo_test)
check("mono_to_stereo: ogni campione duplicato su L e R",
      vals_stereo, (100, 100, -200, -200, 300, 300))

# ---------------------------------------------------------------
# 5. Banco suoni: tutti gli ID presenti e non vuoti
# ---------------------------------------------------------------
bank = audio.build_sound_bank()
attesi = {audio.SND_ATTACK, audio.SND_HURT, audio.SND_ENEMY_HIT,
          audio.SND_SHOOT, audio.SND_STAIRS, audio.SND_GATE,
          audio.SND_BOSS_HIT, audio.SND_BOSS_DIE, audio.SND_DEFEAT}
check("build_sound_bank: contiene tutti gli ID dichiarati",
      set(bank.keys()), attesi)
check("build_sound_bank: nessun suono vuoto",
      all(len(v) > 0 for v in bank.values()), True)
check("build_sound_bank: campioni pari (16 bit)",
      all(len(v) % 2 == 0 for v in bank.values()), True)

# ---------------------------------------------------------------
# 6. PORT_SOUND: la CPU accoda, non suona
# ---------------------------------------------------------------
rom = assemble("LDA #3\nSTA 0x042004\nLDA #7\nSTA 0x042004\nHALT\n", base_addr=0x2000)
c = CPU()
for i, b in enumerate(rom):
    c.mem[0x2000 + i] = b
c.run(0x2000)
check("PORT_SOUND: accoda gli ID nell'ordine di scrittura", c.sound_queue, [3, 7])

# la porta NON deve finire nella RAM come un indirizzo qualunque
check("PORT_SOUND: non scrive un byte in memoria", c.mem[0x042004], 0)

# svuotando la coda (come fa il launcher) il frame successivo riparte pulito
del c.sound_queue[:]
c.run(0x2000)
check("PORT_SOUND: la coda si ricostruisce dopo lo svuotamento",
      c.sound_queue, [3, 7])

# ---------------------------------------------------------------
# 7. play_sound() in ConsoleLang
# ---------------------------------------------------------------
r = compile_source("play_sound(5)\n", var_base=0x3000)
check("play_sound: genera la scrittura sulla porta SOUND",
      "STA 0x042004" in r["asm"], True)

rom2 = assemble(r["asm"], base_addr=0x2000)
c2 = CPU()
for i, b in enumerate(rom2):
    c2.mem[0x2000 + i] = b
c2.run(0x2000)
check("play_sound(5): accoda l'ID 5", c2.sound_queue, [5])

# play_sound accetta un'espressione, non solo un letterale
r3 = compile_source("var s = 2\nplay_sound(s + 1)\n", var_base=0x3000)
rom3 = assemble(r3["asm"], base_addr=0x2000)
c3 = CPU()
for i, b in enumerate(rom3):
    c3.mem[0x2000 + i] = b
c3.run(0x2000)
check("play_sound: accetta un'espressione", c3.sound_queue, [3])

print()
if fails == 0:
    print("Tutti i test passati.")
else:
    print(f"{fails} test falliti.")
