import os
import tempfile
import json

import player_profile as profile_mod

fails = 0

def check(label, got, expected):
    global fails
    status = "OK  " if got == expected else "FAIL"
    if got != expected:
        fails += 1
    print(f"{status} {label}: atteso {expected!r}, ottenuto {got!r}")

# tutti i test operano su un PROFILE_PATH temporaneo - non deve mai
# toccare il vero profile.json di chi esegue i test
_orig_path = profile_mod.PROFILE_PATH
_tmpdir = tempfile.mkdtemp(prefix='s32_profile_test_')
profile_mod.PROFILE_PATH = os.path.join(_tmpdir, 'profile.json')

try:
    # ---------------------------------------------------------------
    # Test 1: nessun file -> default sensato, nessun crash
    # ---------------------------------------------------------------
    p = profile_mod.load_profile()
    check("load_profile senza file: nickname di default", p['nickname'], 'Player')
    check("load_profile senza file: avatar di default", p['avatar'], 0)

    # ---------------------------------------------------------------
    # Test 2: save poi load ritorna lo stesso profilo
    # ---------------------------------------------------------------
    saved = profile_mod.save_profile('Mario', 2)
    check("save_profile ritorna il profilo salvato", saved, {'nickname': 'Mario', 'avatar': 2})
    loaded = profile_mod.load_profile()
    check("load_profile dopo save_profile ritorna lo stesso profilo", loaded, {'nickname': 'Mario', 'avatar': 2})

    # ---------------------------------------------------------------
    # Test 3: sanificazione - nickname vuoto/troppo lungo, avatar fuori range
    # ---------------------------------------------------------------
    saved2 = profile_mod.save_profile('', 0)
    check("save_profile con nickname vuoto: ripiega sul default", saved2['nickname'], 'Player')

    saved3 = profile_mod.save_profile('X' * 50, 1)
    check("save_profile: nickname troncato a MAX_NICKNAME_LEN", len(saved3['nickname']), profile_mod.MAX_NICKNAME_LEN)

    saved4 = profile_mod.save_profile('Luigi', 99)
    check("save_profile: avatar fuori range -> ripiega sul default", saved4['avatar'], 0)

    saved5 = profile_mod.save_profile('Peach', -1)
    check("save_profile: avatar negativo -> ripiega sul default", saved5['avatar'], 0)

    saved6 = profile_mod.save_profile('  spazi  ', 1)
    check("save_profile: spazi ai bordi rimossi", saved6['nickname'], 'spazi')

    # ---------------------------------------------------------------
    # Test 4: file corrotto -> default, nessun crash
    # ---------------------------------------------------------------
    with open(profile_mod.PROFILE_PATH, 'w') as f:
        f.write('{ non e" json valido ]')
    p_corrotto = profile_mod.load_profile()
    check("load_profile con file corrotto: nessun crash, default", p_corrotto, {'nickname': 'Player', 'avatar': 0})

    # ---------------------------------------------------------------
    # Test 5: file con campi mancanti/tipo sbagliato -> default sui
    # singoli campi mancanti, non un crash totale
    # ---------------------------------------------------------------
    with open(profile_mod.PROFILE_PATH, 'w') as f:
        json.dump({'nickname': 'Yoshi'}, f)  # 'avatar' assente
    p_parziale = profile_mod.load_profile()
    check("load_profile con 'avatar' mancante: nickname preservato", p_parziale['nickname'], 'Yoshi')
    check("load_profile con 'avatar' mancante: avatar di default", p_parziale['avatar'], 0)

    with open(profile_mod.PROFILE_PATH, 'w') as f:
        json.dump({'nickname': 'Toad', 'avatar': 'non-un-numero'}, f)
    p_tipo_sbagliato = profile_mod.load_profile()
    check("load_profile con avatar di tipo sbagliato: ripiega sul default", p_tipo_sbagliato['avatar'], 0)

    # ---------------------------------------------------------------
    # Test 6: avatar_path() - percorso coerente, sanificato come save/load
    # ---------------------------------------------------------------
    check("avatar_path(1): punta al file giusto", os.path.basename(profile_mod.avatar_path(1)), 'avatar_1.png')
    check("avatar_path(99) fuori range: ripiega sull'avatar di default",
          os.path.basename(profile_mod.avatar_path(99)), f'avatar_{profile_mod.DEFAULT_AVATAR}.png')

    # ---------------------------------------------------------------
    # Test 7: i 4 file avatar_N.png esistono davvero sul disco
    # ---------------------------------------------------------------
    for i in range(profile_mod.AVATAR_COUNT):
        check(f"avatars/avatar_{i}.png esiste", os.path.isfile(profile_mod.avatar_path(i)), True)

finally:
    profile_mod.PROFILE_PATH = _orig_path
    import shutil
    shutil.rmtree(_tmpdir)

print()
if fails == 0:
    print("Tutti i test passati.")
else:
    print(f"{fails} test falliti.")
