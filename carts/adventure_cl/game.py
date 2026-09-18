"""
game.py - ADVENTURE completo in ConsoleLang.

Stessa logica di game.asm - confronta riga per riga come sempre.
Per la collisione a distanza (|a - b| < soglia) con solo '<'
disponibile: se a >= b -> (a - b) < soglia, else -> (b - a) < soglia.
Scritto sempre come due rami if/else separati.

Due limitazioni di ConsoleLang rispetto all'assembly:
- Nessun AND tra condizioni: le collisioni usano if annidati.
- Il confronto 'uguale' si scrive come: not (a<b) and not (b<a).
"""

SOURCE_LANG = "consolelang"

ROM_SOURCE = """
state mode = 0
state playerX = 0
state playerY = 0
state room = 0
state scrollY = 0
state moving = 0
state targetX = 0
state targetY = 0
state direction = 1
state attackTimer = 0
state prevJ = 0
state hurtTimer = 0
state playerHP = 0

state e1x = 0
state e1y = 0
state e1alive = 0
state e1dir = 0
state e1timer = 0
state e1rng = 0
state e1shot = 0

state e2x = 0
state e2y = 0
state e2alive = 0
state e2dir = 0
state e2timer = 0
state e2rng = 0
state e2shot = 0

state s1x = 0
state s1y = 0
state s1active = 0
state s1dir = 0

state s2x = 0
state s2y = 0
state s2active = 0
state s2dir = 0

state killed = 0

state bossX = 0
state bossY = 0
state bossHP = 0
state bossDir = 0
state bossSteps = 0
state bossTimer = 0
state bossPhase = 0
state bossCool = 0
state bossCX = 0
state bossCY = 0

state fireX = 0
state fireY = 0
state fireActive = 0
state fireDirX = 0
state fireDirY = 0
state fireSpeed = 0
state fireLife = 0

state slashWX = 0
state slashWY = 0

state gameOverTimer = 0

if (mode < 1) {
    if (input() & 16) {
        mode = 1
        room = 1
        select_stage(1)
        playerX = 224
        playerY = 64
        moving = 0
        direction = 1
        attackTimer = 0
        prevJ = 1
        hurtTimer = 0
        playerHP = 3
        e1x = 128
        e1y = 352
        e1alive = 1
        e1dir = 3
        e1timer = 0
        e1rng = 71
        e1shot = 60
        e2x = 320
        e2y = 512
        e2alive = 1
        e2dir = 2
        e2timer = 0
        e2rng = 123
        e2shot = 90
        s1active = 0
        s2active = 0
        killed = 0
        bossX = 208
        bossY = 608
        bossHP = 4
        bossDir = 1
        bossSteps = 2
        bossTimer = 0
        bossPhase = 0
        bossCool = 0
        fireActive = 0
        fireSpeed = 0
        fireLife = 0
    }
}

if (mode < 1) {
    halt()
}

if (mode < 2) {
} else {
    if (gameOverTimer < 1) {
        mode = 0
        select_stage(0)
        halt()
    } else {
        gameOverTimer = gameOverTimer - 1
    }
    write_oam(0, 224, 100, 27, 0)
    write_oam(1, 0, 65535, 0, 0)
    write_oam(2, 0, 65535, 0, 0)
    write_oam(3, 0, 65535, 0, 0)
    write_oam(4, 0, 65535, 0, 0)
    write_oam(5, 0, 65535, 0, 0)
    write_oam(6, 0, 65535, 0, 0)
    write_oam(7, 0, 65535, 0, 0)
    write_oam(8, 0, 65535, 0, 0)
    write_oam(9, 0, 65535, 0, 0)
    write_oam(10, 0, 65535, 0, 0)
    write_oam(11, 0, 65535, 0, 0)
    write_oam(12, 0, 65535, 0, 0)
    write_oam(13, 0, 65535, 0, 0)
    write_oam(14, 0, 65535, 0, 0)
    halt()
}

if (playerHP < 1) {
    mode = 2
    gameOverTimer = 180
    play_sound(9)
    poke(0x020506, 28)
    poke(0x020508, 8)
    poke(0x02050A, 29)
    poke(0x02050C, 3)
    poke(0x02050E, 0)
    poke(0x020510, 7)
    poke(0x020512, 30)
    poke(0x020514, 3)
    poke(0x020516, 2)
    halt()
}

if (input() & 16) {
    if (prevJ < 1) {
        if (attackTimer < 1) {
            attackTimer = 10
            play_sound(1)
        }
    }
    prevJ = 1
} else {
    prevJ = 0
}

if (moving < 1) {
    targetX = playerX
    targetY = playerY

    if (input() & 1) {
        direction = 0
        targetY = targetY - 32
        moving = 1
    } else {
        if (input() & 2) {
            direction = 1
            targetY = targetY + 32
            moving = 1
        } else {
            if (input() & 4) {
                direction = 2
                targetX = targetX - 32
                moving = 1
            } else {
                if (input() & 8) {
                    direction = 3
                    targetX = targetX + 32
                    moving = 1
                }
            }
        }
    }

    regx = targetX
    regy = targetY
    clamp_x(32, 416)
    clamp_y(32, 704)
    targetX = regx
    targetY = regy
} else {
    if (playerX < targetX) {
        playerX = playerX + 2
    } else {
        if (targetX < playerX) { playerX = playerX - 2 }
    }
    if (playerY < targetY) {
        playerY = playerY + 2
    } else {
        if (targetY < playerY) { playerY = playerY - 2 }
    }
    if (playerX < targetX) {
    } else {
        if (targetX < playerX) {
        } else {
            if (playerY < targetY) {
            } else {
                if (targetY < playerY) {
                } else {
                    moving = 0
                }
            }
        }
    }
}

slashWX = playerX
slashWY = playerY
if (direction < 1) {
    slashWY = playerY - 32
} else {
    if (direction < 2) {
        slashWY = playerY + 32
    } else {
        if (direction < 3) {
            slashWX = playerX - 32
        } else {
            slashWX = playerX + 32
        }
    }
}

if (attackTimer < 1) {
} else {
    if (e1alive < 1) {
    } else {
        if (e1alive < 2) {
            if (slashWX < e1x) {
                if (e1x - slashWX < 24) {
                    if (slashWY < e1y) {
                        if (e1y - slashWY < 24) {
                            e1alive = 2
                            e1timer = 10
                            attackTimer = 0
                            play_sound(3)
                        }
                    } else {
                        if (slashWY - e1y < 24) {
                            e1alive = 2
                            e1timer = 10
                            attackTimer = 0
                            play_sound(3)
                        }
                    }
                }
            } else {
                if (slashWX - e1x < 24) {
                    if (slashWY < e1y) {
                        if (e1y - slashWY < 24) {
                            e1alive = 2
                            e1timer = 10
                            attackTimer = 0
                            play_sound(3)
                        }
                    } else {
                        if (slashWY - e1y < 24) {
                            e1alive = 2
                            e1timer = 10
                            attackTimer = 0
                            play_sound(3)
                        }
                    }
                }
            }
        }
    }
}

if (attackTimer < 1) {
} else {
    if (e2alive < 1) {
    } else {
        if (e2alive < 2) {
            if (slashWX < e2x) {
                if (e2x - slashWX < 24) {
                    if (slashWY < e2y) {
                        if (e2y - slashWY < 24) {
                            e2alive = 2
                            e2timer = 10
                            attackTimer = 0
                            play_sound(3)
                        }
                    } else {
                        if (slashWY - e2y < 24) {
                            e2alive = 2
                            e2timer = 10
                            attackTimer = 0
                            play_sound(3)
                        }
                    }
                }
            } else {
                if (slashWX - e2x < 24) {
                    if (slashWY < e2y) {
                        if (e2y - slashWY < 24) {
                            e2alive = 2
                            e2timer = 10
                            attackTimer = 0
                            play_sound(3)
                        }
                    } else {
                        if (slashWY - e2y < 24) {
                            e2alive = 2
                            e2timer = 10
                            attackTimer = 0
                            play_sound(3)
                        }
                    }
                }
            }
        }
    }
}

if (attackTimer < 1) {
} else {
    attackTimer = attackTimer - 1
}
if (hurtTimer < 1) {
} else {
    hurtTimer = hurtTimer - 1
}

if (e1alive < 1) {
} else {
    if (e1alive < 2) {
        e1rng = e1rng + 55
        if (e1rng & 992) {
        } else {
            e1dir = e1rng & 3
        }
        if (e1dir < 1) {
            if (e1y < 100) {
                e1dir = 1
            } else {
                e1y = e1y - 2
            }
        } else {
            if (e1dir < 2) {
                if (e1y < 669) {
                    e1y = e1y + 2
                } else {
                    e1y = 672
                    e1dir = 0
                }
            } else {
                if (e1dir < 3) {
                    if (e1x < 36) {
                        e1dir = 3
                    } else {
                        e1x = e1x - 2
                    }
                } else {
                    if (e1x < 413) {
                        e1x = e1x + 2
                    } else {
                        e1x = 416
                        e1dir = 2
                    }
                }
            }
        }
        if (e1shot < 1) {
            if (s1active < 1) {
                if (playerX < e1x) {
                    if (e1x - playerX < 16) {
                        if (playerY < e1y) {
                            s1dir = 0
                        } else {
                            s1dir = 1
                        }
                        s1x = e1x
                        s1y = e1y
                        s1active = 1
                        e1shot = 80
                        play_sound(4)
                    } else {
                        if (playerY < e1y) {
                            if (e1y - playerY < 16) {
                                if (playerX < e1x) {
                                    s1dir = 2
                                } else {
                                    s1dir = 3
                                }
                                s1x = e1x
                                s1y = e1y
                                s1active = 1
                                e1shot = 80
                                play_sound(4)
                            }
                        } else {
                            if (playerY - e1y < 16) {
                                if (playerX < e1x) {
                                    s1dir = 2
                                } else {
                                    s1dir = 3
                                }
                                s1x = e1x
                                s1y = e1y
                                s1active = 1
                                e1shot = 80
                                play_sound(4)
                            }
                        }
                    }
                } else {
                    if (playerX - e1x < 16) {
                        if (playerY < e1y) {
                            s1dir = 0
                        } else {
                            s1dir = 1
                        }
                        s1x = e1x
                        s1y = e1y
                        s1active = 1
                        e1shot = 80
                        play_sound(4)
                    } else {
                        if (playerY < e1y) {
                            if (e1y - playerY < 16) {
                                if (playerX < e1x) {
                                    s1dir = 2
                                } else {
                                    s1dir = 3
                                }
                                s1x = e1x
                                s1y = e1y
                                s1active = 1
                                e1shot = 80
                                play_sound(4)
                            }
                        } else {
                            if (playerY - e1y < 16) {
                                if (playerX < e1x) {
                                    s1dir = 2
                                } else {
                                    s1dir = 3
                                }
                                s1x = e1x
                                s1y = e1y
                                s1active = 1
                                e1shot = 80
                                play_sound(4)
                            }
                        }
                    }
                }
            }
        } else {
            e1shot = e1shot - 1
        }
    } else {
        if (e1timer < 1) {
            e1alive = 0
            killed = killed + 1
        } else {
            e1timer = e1timer - 1
        }
    }
}

if (e2alive < 1) {
} else {
    if (e2alive < 2) {
        e2rng = e2rng + 91
        if (e2rng & 992) {
        } else {
            e2dir = e2rng & 3
        }
        if (e2dir < 1) {
            if (e2y < 100) {
                e2dir = 1
            } else {
                e2y = e2y - 2
            }
        } else {
            if (e2dir < 2) {
                if (e2y < 669) {
                    e2y = e2y + 2
                } else {
                    e2y = 672
                    e2dir = 0
                }
            } else {
                if (e2dir < 3) {
                    if (e2x < 36) {
                        e2dir = 3
                    } else {
                        e2x = e2x - 2
                    }
                } else {
                    if (e2x < 413) {
                        e2x = e2x + 2
                    } else {
                        e2x = 416
                        e2dir = 2
                    }
                }
            }
        }
        if (e2shot < 1) {
            if (s2active < 1) {
                if (playerX < e2x) {
                    if (e2x - playerX < 16) {
                        if (playerY < e2y) {
                            s2dir = 0
                        } else {
                            s2dir = 1
                        }
                        s2x = e2x
                        s2y = e2y
                        s2active = 1
                        e2shot = 80
                        play_sound(4)
                    } else {
                        if (playerY < e2y) {
                            if (e2y - playerY < 16) {
                                if (playerX < e2x) {
                                    s2dir = 2
                                } else {
                                    s2dir = 3
                                }
                                s2x = e2x
                                s2y = e2y
                                s2active = 1
                                e2shot = 80
                                play_sound(4)
                            }
                        } else {
                            if (playerY - e2y < 16) {
                                if (playerX < e2x) {
                                    s2dir = 2
                                } else {
                                    s2dir = 3
                                }
                                s2x = e2x
                                s2y = e2y
                                s2active = 1
                                e2shot = 80
                                play_sound(4)
                            }
                        }
                    }
                } else {
                    if (playerX - e2x < 16) {
                        if (playerY < e2y) {
                            s2dir = 0
                        } else {
                            s2dir = 1
                        }
                        s2x = e2x
                        s2y = e2y
                        s2active = 1
                        e2shot = 80
                        play_sound(4)
                    } else {
                        if (playerY < e2y) {
                            if (e2y - playerY < 16) {
                                if (playerX < e2x) {
                                    s2dir = 2
                                } else {
                                    s2dir = 3
                                }
                                s2x = e2x
                                s2y = e2y
                                s2active = 1
                                e2shot = 80
                                play_sound(4)
                            }
                        } else {
                            if (playerY - e2y < 16) {
                                if (playerX < e2x) {
                                    s2dir = 2
                                } else {
                                    s2dir = 3
                                }
                                s2x = e2x
                                s2y = e2y
                                s2active = 1
                                e2shot = 80
                                play_sound(4)
                            }
                        }
                    }
                }
            }
        } else {
            e2shot = e2shot - 1
        }
    } else {
        if (e2timer < 1) {
            e2alive = 0
            killed = killed + 1
        } else {
            e2timer = e2timer - 1
        }
    }
}

if (s1active < 1) {
} else {
    if (s1dir < 1) {
        if (s1y < 36) {
            s1active = 0
        } else {
            s1y = s1y - 3
        }
    } else {
        if (s1dir < 2) {
            if (s1y < 730) {
                s1y = s1y + 3
            } else {
                s1active = 0
            }
        } else {
            if (s1dir < 3) {
                if (s1x < 36) {
                    s1active = 0
                } else {
                    s1x = s1x - 3
                }
            } else {
                if (s1x < 442) {
                    s1x = s1x + 3
                } else {
                    s1active = 0
                }
            }
        }
    }
    if (s1active < 1) {
    } else {
        if (hurtTimer < 1) {
            if (s1x < playerX) {
                if (playerX - s1x < 20) {
                    if (s1y < playerY) {
                        if (playerY - s1y < 20) {
                            s1active = 0
                            if (playerHP < 1) {
                            } else {
                                playerHP = playerHP - 1
                            }
                            hurtTimer = 20
                            play_sound(2)
                        }
                    } else {
                        if (s1y - playerY < 20) {
                            s1active = 0
                            if (playerHP < 1) {
                            } else {
                                playerHP = playerHP - 1
                            }
                            hurtTimer = 20
                            play_sound(2)
                        }
                    }
                }
            } else {
                if (s1x - playerX < 20) {
                    if (s1y < playerY) {
                        if (playerY - s1y < 20) {
                            s1active = 0
                            if (playerHP < 1) {
                            } else {
                                playerHP = playerHP - 1
                            }
                            hurtTimer = 20
                            play_sound(2)
                        }
                    } else {
                        if (s1y - playerY < 20) {
                            s1active = 0
                            if (playerHP < 1) {
                            } else {
                                playerHP = playerHP - 1
                            }
                            hurtTimer = 20
                            play_sound(2)
                        }
                    }
                }
            }
        }
    }
}

if (s2active < 1) {
} else {
    if (s2dir < 1) {
        if (s2y < 36) {
            s2active = 0
        } else {
            s2y = s2y - 3
        }
    } else {
        if (s2dir < 2) {
            if (s2y < 730) {
                s2y = s2y + 3
            } else {
                s2active = 0
            }
        } else {
            if (s2dir < 3) {
                if (s2x < 36) {
                    s2active = 0
                } else {
                    s2x = s2x - 3
                }
            } else {
                if (s2x < 442) {
                    s2x = s2x + 3
                } else {
                    s2active = 0
                }
            }
        }
    }
    if (s2active < 1) {
    } else {
        if (hurtTimer < 1) {
            if (s2x < playerX) {
                if (playerX - s2x < 20) {
                    if (s2y < playerY) {
                        if (playerY - s2y < 20) {
                            s2active = 0
                            if (playerHP < 1) {
                            } else {
                                playerHP = playerHP - 1
                            }
                            hurtTimer = 20
                            play_sound(2)
                        }
                    } else {
                        if (s2y - playerY < 20) {
                            s2active = 0
                            if (playerHP < 1) {
                            } else {
                                playerHP = playerHP - 1
                            }
                            hurtTimer = 20
                            play_sound(2)
                        }
                    }
                }
            } else {
                if (s2x - playerX < 20) {
                    if (s2y < playerY) {
                        if (playerY - s2y < 20) {
                            s2active = 0
                            if (playerHP < 1) {
                            } else {
                                playerHP = playerHP - 1
                            }
                            hurtTimer = 20
                            play_sound(2)
                        }
                    } else {
                        if (s2y - playerY < 20) {
                            s2active = 0
                            if (playerHP < 1) {
                            } else {
                                playerHP = playerHP - 1
                            }
                            hurtTimer = 20
                            play_sound(2)
                        }
                    }
                }
            }
        }
    }
}

if (room < 2) {
} else {
    if (2 < room) {
    } else {
        if (bossHP < 1) {
        } else {
            if (bossCool < 1) {
            } else {
                bossCool = bossCool - 1
            }

            if (bossPhase < 1) {
                if (bossTimer < 1) {
                    if (bossSteps < 1) {
                        bossPhase = 1
                        bossTimer = 0
                    } else {
                        bossSteps = bossSteps - 1
                        bossTimer = 24
                        if (bossDir < 1) {
                            bossDir = 1
                        } else {
                            bossDir = 0
                        }
                    }
                } else {
                    bossTimer = bossTimer - 1
                    if (bossDir < 1) {
                        if (bossX < 40) {
                            bossDir = 1
                        } else {
                            bossX = bossX - 1
                        }
                    } else {
                        if (bossX < 376) {
                            bossX = bossX + 1
                        } else {
                            bossDir = 0
                        }
                    }
                }
            } else {
                if (fireActive < 1) {
                    fireX = bossX + 16
                    fireY = bossY + 16
                    fireActive = 1
                    fireSpeed = 6
                    fireLife = 120
                    fireDirX = 0
                    fireDirY = 2
                } else {
                    bossPhase = 0
                    bossSteps = 2
                    bossTimer = 24
                }
            }

            bossCX = bossX + 32
            bossCY = bossY + 32

            if (attackTimer < 1) {
            } else {
                if (bossCool < 1) {
                    if (slashWX < bossCX) {
                        if (bossCX - slashWX < 48) {
                            if (slashWY < bossCY) {
                                if (bossCY - slashWY < 48) {
                                    bossHP = bossHP - 1
                                    bossCool = 20
                                    attackTimer = 0
                                    if (bossHP < 1) {
                                        play_sound(8)
                                    } else {
                                        play_sound(7)
                                    }
                                }
                            } else {
                                if (slashWY - bossCY < 48) {
                                    bossHP = bossHP - 1
                                    bossCool = 20
                                    attackTimer = 0
                                    if (bossHP < 1) {
                                        play_sound(8)
                                    } else {
                                        play_sound(7)
                                    }
                                }
                            }
                        }
                    } else {
                        if (slashWX - bossCX < 48) {
                            if (slashWY < bossCY) {
                                if (bossCY - slashWY < 48) {
                                    bossHP = bossHP - 1
                                    bossCool = 20
                                    attackTimer = 0
                                    if (bossHP < 1) {
                                        play_sound(8)
                                    } else {
                                        play_sound(7)
                                    }
                                }
                            } else {
                                if (slashWY - bossCY < 48) {
                                    bossHP = bossHP - 1
                                    bossCool = 20
                                    attackTimer = 0
                                    if (bossHP < 1) {
                                        play_sound(8)
                                    } else {
                                        play_sound(7)
                                    }
                                }
                            }
                        }
                    }
                }
            }

            if (hurtTimer < 1) {
                if (bossHP < 1) {
                } else {
                    if (playerX < bossCX) {
                        if (bossCX - playerX < 44) {
                            if (playerY < bossCY) {
                                if (bossCY - playerY < 44) {
                                    if (playerHP < 1) {
                                    } else {
                                        playerHP = playerHP - 1
                                    }
                                    hurtTimer = 20
                                    play_sound(2)
                                }
                            } else {
                                if (playerY - bossCY < 44) {
                                    if (playerHP < 1) {
                                    } else {
                                        playerHP = playerHP - 1
                                    }
                                    hurtTimer = 20
                                    play_sound(2)
                                }
                            }
                        }
                    } else {
                        if (playerX - bossCX < 44) {
                            if (playerY < bossCY) {
                                if (bossCY - playerY < 44) {
                                    if (playerHP < 1) {
                                    } else {
                                        playerHP = playerHP - 1
                                    }
                                    hurtTimer = 20
                                    play_sound(2)
                                }
                            } else {
                                if (playerY - bossCY < 44) {
                                    if (playerHP < 1) {
                                    } else {
                                        playerHP = playerHP - 1
                                    }
                                    hurtTimer = 20
                                    play_sound(2)
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

if (fireActive < 1) {
} else {
    if (fireLife < 1) {
        fireActive = 0
    } else {
        fireLife = fireLife - 1
        if (fireSpeed < 1) {
        } else {
            if (fireDirX < 1) {
            } else {
                if (fireDirX < 2) {
                    fireX = fireX + fireSpeed
                } else {
                    fireX = fireX - fireSpeed
                }
            }
            if (fireDirY < 1) {
            } else {
                if (fireDirY < 2) {
                    fireY = fireY + fireSpeed
                } else {
                    fireY = fireY - fireSpeed
                }
            }
            fireSpeed = fireSpeed - 1
        }
        if (hurtTimer < 1) {
            if (fireX < playerX) {
                if (playerX - fireX < 22) {
                    if (fireY < playerY) {
                        if (playerY - fireY < 22) {
                            fireActive = 0
                            if (playerHP < 1) {
                            } else {
                                playerHP = playerHP - 1
                            }
                            hurtTimer = 20
                            play_sound(2)
                        }
                    } else {
                        if (fireY - playerY < 22) {
                            fireActive = 0
                            if (playerHP < 1) {
                            } else {
                                playerHP = playerHP - 1
                            }
                            hurtTimer = 20
                            play_sound(2)
                        }
                    }
                }
            } else {
                if (fireX - playerX < 22) {
                    if (fireY < playerY) {
                        if (playerY - fireY < 22) {
                            fireActive = 0
                            if (playerHP < 1) {
                            } else {
                                playerHP = playerHP - 1
                            }
                            hurtTimer = 20
                            play_sound(2)
                        }
                    } else {
                        if (fireY - playerY < 22) {
                            fireActive = 0
                            if (playerHP < 1) {
                            } else {
                                playerHP = playerHP - 1
                            }
                            hurtTimer = 20
                            play_sound(2)
                        }
                    }
                }
            }
        }
    }
}

if (room < 2) {
    if (killed < 2) {
    } else {
        room = 3
        select_stage(3)
        s1active = 0
        s2active = 0
        play_sound(6)
    }
}

if (playerY < 160) {
    regy = 0
} else {
    regy = playerY - 160
}
clamp_y(0, 448)
scrollY = regy
set_scroll(0, scrollY)

if (room < 3) {
    if (room < 2) {
    } else {
        if (playerX < 224) {
        } else {
            if (224 < playerX) {
            } else {
                if (playerY < 704) {
                } else {
                    if (704 < playerY) {
                    } else {
                        room = 2
                        play_sound(5)
                        select_stage(2)
                        playerX = 224
                        playerY = 64
                        moving = 0
                        if (playerY < 160) {
                            regy = 0
                        } else {
                            regy = playerY - 160
                        }
                        clamp_y(0, 448)
                        scrollY = regy
                        set_scroll(0, scrollY)
                    }
                }
            }
        }
    }
} else {
    if (playerX < 224) {
    } else {
        if (224 < playerX) {
        } else {
            if (playerY < 704) {
            } else {
                if (704 < playerY) {
                } else {
                    room = 2
                    play_sound(5)
                    select_stage(2)
                    playerX = 224
                    playerY = 64
                    moving = 0
                    if (playerY < 160) {
                        regy = 0
                    } else {
                        regy = playerY - 160
                    }
                    clamp_y(0, 448)
                    scrollY = regy
                    set_scroll(0, scrollY)
                }
            }
        }
    }
}

if (room < 2) {
} else {
    if (2 < room) {
    } else {
        if (playerX < 224) {
        } else {
            if (224 < playerX) {
            } else {
                if (playerY < 32) {
                } else {
                    if (32 < playerY) {
                    } else {
                        room = 3
                        play_sound(5)
                        select_stage(3)
                        playerX = 224
                        playerY = 672
                        moving = 0
                        regy = playerY - 160
                        clamp_y(0, 448)
                        scrollY = regy
                        set_scroll(0, scrollY)
                    }
                }
            }
        }
    }
}

regy = playerY - scrollY
regx = playerX

if (hurtTimer & 2) {
    write_oam(0, 0, 65535, 0, 0)
} else {
    write_oam(0, regx, regy, 11, 0)
}

if (playerHP < 1) {
    write_oam(1, 0, 65535, 0, 0)
} else {
    write_oam(1, 8, 8, 12, 0)
}
if (playerHP < 2) {
    write_oam(2, 0, 65535, 0, 0)
} else {
    write_oam(2, 44, 8, 12, 0)
}
if (playerHP < 3) {
    write_oam(3, 0, 65535, 0, 0)
} else {
    write_oam(3, 80, 8, 12, 0)
}

if (attackTimer < 1) {
    write_oam(4, 0, 65535, 0, 0)
} else {
    regy = slashWY - scrollY
    regx = slashWX
    if (attackTimer < 5) {
        write_oam(4, regx, regy, 15, 0)
    } else {
        write_oam(4, regx, regy, 14, 0)
    }
}

if (e1alive < 1) {
    write_oam(5, 0, 65535, 0, 0)
} else {
    regy = e1y - scrollY
    if (e1alive < 2) {
        write_oam(5, e1x, regy, 16, 0)
    } else {
        write_oam(5, e1x, regy, 19, 0)
    }
}

if (e2alive < 1) {
    write_oam(6, 0, 65535, 0, 0)
} else {
    regy = e2y - scrollY
    if (e2alive < 2) {
        write_oam(6, e2x, regy, 16, 0)
    } else {
        write_oam(6, e2x, regy, 19, 0)
    }
}

if (s1active < 1) {
    write_oam(7, 0, 65535, 0, 0)
} else {
    regy = s1y - scrollY
    write_oam(7, s1x, regy, 17, 0)
}

if (s2active < 1) {
    write_oam(8, 0, 65535, 0, 0)
} else {
    regy = s2y - scrollY
    write_oam(8, s2x, regy, 17, 0)
}

if (room < 2) {
    write_oam(9, 0, 65535, 0, 0)
    write_oam(10, 0, 65535, 0, 0)
    write_oam(11, 0, 65535, 0, 0)
    write_oam(12, 0, 65535, 0, 0)
    write_oam(13, 0, 65535, 0, 0)
    write_oam(14, 0, 65535, 0, 0)
} else {
    if (2 < room) {
        write_oam(9, 0, 65535, 0, 0)
        write_oam(10, 0, 65535, 0, 0)
        write_oam(11, 0, 65535, 0, 0)
        write_oam(12, 0, 65535, 0, 0)
        write_oam(13, 0, 65535, 0, 0)
        write_oam(14, 0, 65535, 0, 0)
    } else {
        if (bossHP < 1) {
            write_oam(9, 0, 65535, 0, 0)
            write_oam(11, 0, 65535, 0, 0)
            write_oam(12, 0, 65535, 0, 0)
            write_oam(13, 0, 65535, 0, 0)
            write_oam(14, 0, 65535, 0, 0)
        } else {
            if (bossCool & 2) {
                write_oam(9, 0, 65535, 0, 0)
            } else {
                if (bossY < scrollY) {
                    write_oam(9, 0, 65535, 0, 0)
                } else {
                    regy = bossY - scrollY
                    write_oam(9, bossX, regy, 20, 1)
                }
            }
            if (bossHP < 1) {
                write_oam(11, 176, 8, 26, 0)
            } else {
                write_oam(11, 176, 8, 25, 0)
            }
            if (bossHP < 2) {
                write_oam(12, 208, 8, 26, 0)
            } else {
                write_oam(12, 208, 8, 25, 0)
            }
            if (bossHP < 3) {
                write_oam(13, 240, 8, 26, 0)
            } else {
                write_oam(13, 240, 8, 25, 0)
            }
            if (bossHP < 4) {
                write_oam(14, 272, 8, 26, 0)
            } else {
                write_oam(14, 272, 8, 25, 0)
            }
        }
        if (fireActive < 1) {
            write_oam(10, 0, 65535, 0, 0)
        } else {
            if (fireY < scrollY) {
                write_oam(10, 0, 65535, 0, 0)
            } else {
                regy = fireY - scrollY
                write_oam(10, fireX, regy, 24, 0)
            }
        }
    }
}

halt()
"""
