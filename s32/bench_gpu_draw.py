"""bench_gpu_draw.py - diagnostica isolata per issue #24 (draw_sprites
e' il costo di rendering dominante durante lo scroll, ~12-14ms/frame
misurato su Pi 1 reale, a fronte di soli 3-7 sotto-tile disegnati per
frame - vedi test_launcher.py e README.md per il contesto completo).

Il gioco vero mischia SEMPRE draw_sprites con CPU, scroll, audio -
impossibile isolare da li' quanto costa DAVVERO una singola chiamata
Texture.draw() sulla GPU del Pi. Questo script misura SOLO quello,
per rispondere a tre domande concrete:

  1. Quanto costa un Texture.draw() da solo, senza nient'altro
     intorno? (numero -> se e' alto anche qui, e' un costo FISSO
     della chiamata/binding/driver, non del resto del motore)
  2. Conviene ricomporre uno sprite fatto di N tile piccoli (es. un
     boss 2x2 di tile 32x32) in UNA texture grande e disegnarla con
     UN SOLO draw(), invece di N draw() separati dall'atlas? Lo
     script disegna lo STESSO NUMERO di pixel nei due modi e
     confronta.
  3. NUOVO (dopo il primo giro di misure reali sulla Pi 1, vedi
     README.md): il primo giro mostrava che disegnare 7 tile 32x32
     costa solo ~1.7ms in isolamento - una FRAZIONE dei ~12-14ms
     misurati per la voce 'draw_sprites' nel gioco vero. Motivo
     trovato RILEGGENDO il codice sorgente: quella voce, prima di
     questa versione dello script, includeva ANCHE renderer.clear()
     e il draw dell'INTERO sfondo (480x320, un'area ~150 volte piu'
     grande di un tile 32x32), non solo gli sprite - un'etichetta
     fuorviante gia' corretta in launcher.py (ora clear/bg_draw/
     sprite_draws sono tre timing separati). Questa funzione misura
     ESATTAMENTE quella nuova ipotesi: il costo di disegnare lo
     sfondo a schermo intero, isolato dagli sprite.

Uso: python3 bench_gpu_draw.py  (lanciarlo SULLA Pi 1 vera - qui in
sviluppo i numeri non sono comparabili, nessuna GPU reale disponibile
in questo ambiente. Serve pygame-ce/pygame con supporto _sdl2.video).
"""
import time
import sys

import pygame
from pygame._sdl2 import video

N_ITER = 300  # ripetizioni per ogni misura - abbastanza per mediare
              # via il rumore di misura senza far durare lo script
              # troppo a lungo su hardware lento


def _timeit(label, fn, n=N_ITER):
    # scarta le prime iterazioni (warm-up: prima chiamata a una
    # texture/stato spesso piu' lenta per allocazioni pigre lato
    # driver) - le successive sono piu' rappresentative del costo
    # STEADY STATE che conta durante il gioco vero
    for _ in range(5):
        fn()
    t0 = time.perf_counter()
    for _ in range(n):
        fn()
    t1 = time.perf_counter()
    ms = (t1 - t0) / n * 1000
    print(f"{label:<45} {ms:8.3f} ms/iterazione  ({n} iterazioni)")
    return ms


def main():
    pygame.init()
    win = video.Window("bench_gpu_draw", size=(480, 320), hidden=True)
    renderer = video.Renderer(win, accelerated=1, vsync=False)

    # -- baseline: clear()+present() da soli, senza disegnare nulla -
    # tutto il resto va confrontato CONTRO questo, non contro zero --
    def _solo_clear_present():
        renderer.clear()
        renderer.present()
    ms_baseline = _timeit("clear()+present() da soli (baseline)", _solo_clear_present)

    # -- un tile 32x32, riusato per le misure sotto --
    tile_surf = pygame.Surface((32, 32))
    tile_surf.fill((200, 80, 40))
    tile_tex = video.Texture(renderer, (32, 32), target=True)
    tile_tex.update(tile_surf)

    # -- N draw() dello stesso tile, come farebbe draw_sprites() con
    # N sotto-tile visibili (dati reali dal gioco: 3-7 per frame
    # durante lo scroll - qui ne usiamo alcuni valori rappresentativi) --
    for n_tile in (1, 4, 7, 16):
        def _n_draws(n=n_tile):
            renderer.clear()
            for i in range(n):
                tile_tex.draw(dstrect=(i * 32, 0, 32, 32))
            renderer.present()
        ms_n = _timeit(f"clear()+{n_tile} draw(32x32)+present()", _n_draws)
        per_draw = (ms_n - ms_baseline) / n_tile if n_tile else 0
        print(f"  -> costo stimato per singolo draw() extra: {per_draw:.3f} ms")

    # -- confronto diretto per la domanda 2: un'entita' 2x2 tile
    # (64x64 totali) disegnata come 4 draw() separati (come oggi,
    # dall'atlas) contro la STESSA area disegnata con UN SOLO draw()
    # da una texture 64x64 pre-composta. Stessi pixel totali, chiamate
    # diverse - se il secondo e' significativamente piu' veloce,
    # conviene precomporre le entita' multi-tile (vedi issue #24) --
    big_surf = pygame.Surface((64, 64))
    big_surf.fill((80, 160, 220))
    big_tex = video.Texture(renderer, (64, 64), target=True)
    big_tex.update(big_surf)

    def _quattro_tile_separati():
        renderer.clear()
        for dx in (0, 32):
            for dy in (0, 32):
                tile_tex.draw(dstrect=(dx, dy, 32, 32))
        renderer.present()
    ms_4tile = _timeit("clear()+4 draw(32x32) [entita' come oggi]+present()", _quattro_tile_separati)

    def _un_tile_grande():
        renderer.clear()
        big_tex.draw(dstrect=(0, 0, 64, 64))
        renderer.present()
    ms_1tile_grande = _timeit("clear()+1 draw(64x64) [entita' precomposta]+present()", _un_tile_grande)

    # -- DOMANDA 3 (nuova): quanto costa disegnare lo SFONDO a schermo
    # intero (480x320, come fa bg_texture.draw() nel gioco vero), da
    # solo e insieme a una manciata di sprite - per capire se il vero
    # costo di 'draw_sprites' nel gioco (~12-14ms su Pi 1 reale) viene
    # dallo sfondo o dagli sprite --
    bg_surf = pygame.Surface((480, 320))
    for y in range(0, 320, 32):
        for x in range(0, 480, 32):
            colore = (120, 90, 40) if (x // 32 + y // 32) % 2 == 0 else (140, 100, 50)
            bg_surf.fill(colore, rect=(x, y, 32, 32))
    bg_tex = video.Texture(renderer, (480, 320), target=True)
    bg_tex.update(bg_surf)

    def _solo_sfondo():
        renderer.clear()
        bg_tex.draw(dstrect=(0, 0, 480, 320))
        renderer.present()
    ms_solo_sfondo = _timeit("clear()+1 draw(480x320, SFONDO INTERO)+present()", _solo_sfondo)

    N_SPRITE_REALISTICO = 7  # dato reale dal gioco: 3-7 sotto-tile/frame durante lo scroll

    def _sfondo_piu_sprite():
        renderer.clear()
        bg_tex.draw(dstrect=(0, 0, 480, 320))
        for i in range(N_SPRITE_REALISTICO):
            tile_tex.draw(dstrect=(i * 32, 0, 32, 32))
        renderer.present()
    ms_sfondo_piu_sprite = _timeit(
        f"clear()+1 draw(480x320 sfondo)+{N_SPRITE_REALISTICO} draw(32x32 sprite)+present() [sequenza REALE]",
        _sfondo_piu_sprite)

    print()
    print("=== riepilogo ===")
    print(f"overhead fisso di clear()+present() da soli: {ms_baseline:.3f} ms")
    print(f"costo di un singolo draw() extra (stimato sopra, 1/4/7/16 tile): vedi righe '-> costo stimato' sopra")
    risparmio = ms_4tile - ms_1tile_grande
    pct = (risparmio / ms_4tile * 100) if ms_4tile else 0
    print(f"4 tile separati: {ms_4tile:.3f} ms  vs  1 tile precomposto equivalente: {ms_1tile_grande:.3f} ms "
          f"-> {'CONVIENE precomporre' if risparmio > 0.1 else 'NESSUN vantaggio significativo'} "
          f"({pct:.0f}% se positivo)")
    costo_sfondo = ms_solo_sfondo - ms_baseline
    costo_sfondo_piu_sprite = ms_sfondo_piu_sprite - ms_baseline
    print(f"costo dello SFONDO INTERO (480x320) da solo: {costo_sfondo:.3f} ms oltre il baseline")
    print(f"costo sfondo+{N_SPRITE_REALISTICO} sprite insieme (sequenza reale del gioco): "
          f"{costo_sfondo_piu_sprite:.3f} ms oltre il baseline")
    if costo_sfondo > 0 and costo_sfondo_piu_sprite > 0:
        quota_sfondo_pct = costo_sfondo / costo_sfondo_piu_sprite * 100
        commento = "e' quindi il vero collo di bottiglia" if quota_sfondo_pct > 50 else "gli sprite restano una quota significativa"
        print(f"-> lo SFONDO da solo spiega circa il {quota_sfondo_pct:.0f}% del costo combinato ({commento})")
    print()
    print("Incolla questo intero output com'e' per l'analisi.")

    pygame.quit()


if __name__ == "__main__":
    if not hasattr(video, "Renderer"):
        print("pygame._sdl2.video.Renderer non disponibile - serve pygame-ce o pygame >= 2.1 con supporto GPU")
        sys.exit(1)
    main()
