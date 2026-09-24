from fb_convert import rgb888_to_rgb565

fails = 0

def check(label, got, expected):
    global fails
    status = "OK  " if got == expected else "FAIL"
    if got != expected:
        fails += 1
    print(f"{status} {label}: atteso {expected!r}, ottenuto {got!r}")

# ---------------------------------------------------------------
# Test 1: colori pieni ai vertici del cubo RGB - valori noti a mano
# ---------------------------------------------------------------
def pixel16(buf, i):
    lo = buf[i * 2]
    hi = buf[i * 2 + 1]
    return lo | (hi << 8)

buf1 = bytearray([
    0, 0, 0,        # nero
    255, 0, 0,      # rosso pieno
    0, 255, 0,      # verde pieno
    0, 0, 255,      # blu pieno
    255, 255, 255,  # bianco
])
out1 = rgb888_to_rgb565(buf1)
check("lunghezza output: 2 byte/pixel", len(out1), 5 * 2)
check("nero -> 0x0000", pixel16(out1, 0), 0x0000)
check("rosso pieno -> 5 bit alti tutti a 1 (0xF800)", pixel16(out1, 1), 0xF800)
check("verde pieno -> 6 bit centrali tutti a 1 (0x07E0)", pixel16(out1, 2), 0x07E0)
check("blu pieno -> 5 bit bassi tutti a 1 (0x001F)", pixel16(out1, 3), 0x001F)
check("bianco -> tutti i bit a 1 (0xFFFF)", pixel16(out1, 4), 0xFFFF)

# ---------------------------------------------------------------
# Test 2: valori intermedi - verifica il troncamento a 5/6/5 bit
# (non un semplice shift, il MSB del canale viene perso per intero)
# ---------------------------------------------------------------
buf2 = bytearray([0b00000111, 0b00000011, 0b00000111])  # r=7,g=3,b=7: sotto la soglia dei bit conservati
out2 = rgb888_to_rgb565(buf2)
check("valori sotto la soglia troncati a zero (perdita di precisione attesa)", pixel16(out2, 0), 0x0000)

# ---------------------------------------------------------------
# Test 3: buffer piu' grande (dimensione di un frame vero) - solo
# per verificare che non esploda su input non banali, non i valori
# ---------------------------------------------------------------
import random
random.seed(42)
buf3 = bytearray(random.randrange(256) for _ in range(480 * 320 * 3))
out3 = rgb888_to_rgb565(buf3)
check("buffer dimensione frame: lunghezza output corretta", len(out3), 480 * 320 * 2)

print()
if fails == 0:
    print("Tutti i test passati.")
else:
    print(f"{fails} test falliti.")
