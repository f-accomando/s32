"""test_memory_map.py - verifica la selezione della risoluzione via
S32_SCREEN_MODE (vedi memory_map.py). Usa SUBPROCESS invece di
importlib.reload(): SCREEN_W_PX/H_PX vengono lette da altri moduli
(ppu.py, launcher.py) con `from memory_map import SCREEN_W_PX`, una
sintassi che COPIA il valore al momento del LORO import - se questo
processo di test avesse gia' importato uno di quei moduli prima
(succede con pytest/un runner che importa tutto), un reload di
memory_map non li aggiornerebbe comunque, e testeremmo qualcosa che
non riflette il comportamento reale. Un sottoprocesso pulito, con la
variabile d'ambiente impostata PRIMA che Python parta, riproduce
esattamente come viene lanciato launcher.py sul Raspberry Pi vero."""
import subprocess
import sys
import os

fails = 0

def check(label, got, expected):
    global fails
    status = "OK  " if got == expected else "FAIL"
    if got != expected:
        fails += 1
    print(f"{status} {label}: atteso {expected!r}, ottenuto {got!r}")


def read_resolution(env_value):
    env = os.environ.copy()
    if env_value is None:
        env.pop("S32_SCREEN_MODE", None)
    else:
        env["S32_SCREEN_MODE"] = env_value
    out = subprocess.run(
        [sys.executable, "-c",
         "from memory_map import SCREEN_W_PX, SCREEN_H_PX, SCREEN_TILES_W, SCREEN_TILES_H; "
         "print(SCREEN_W_PX, SCREEN_H_PX, SCREEN_TILES_W, SCREEN_TILES_H)"],
        cwd=os.path.dirname(os.path.abspath(__file__)),
        env=env, capture_output=True, text=True, check=True,
    )
    w, h, tw, th = out.stdout.split()
    return int(w), int(h), int(tw), int(th)


check("nessuna variabile d'ambiente -> default 480x320 (comportamento di sempre)",
      read_resolution(None), (480, 320, 15, 10))
check("S32_SCREEN_MODE='4:3' -> 320x224", read_resolution("4:3"), (320, 224, 10, 7))
check("S32_SCREEN_MODE='16:9' -> 400x224 (12 tile, 16px avanzati non contati)",
      read_resolution("16:9"), (400, 224, 12, 7))
check("S32_SCREEN_MODE con valore sconosciuto -> default 480x320 (nessun crash)",
      read_resolution("bogus"), (480, 320, 15, 10))

print()
if fails == 0:
    print("Tutti i test passati.")
else:
    print(f"{fails} test falliti.")
