"""
menu_state.py - navigazione del menu di avvio, senza pygame.

Separata da os_menu.py apposta: questa e' pura logica (indice
selezionato, quanti elementi, su/giu/seleziona) e si testa senza
bisogno di un display. os_menu.py la usa e ci aggiunge solo il
disegno con pygame.
"""


class MenuState:
    def __init__(self, items):
        """items: lista di oggetti Cart (o qualunque cosa abbia un
        .title) - il menu non sa nulla della loro struttura interna."""
        self.items = items
        self.index = 0

    def move_up(self):
        if not self.items:
            return
        self.index = (self.index - 1) % len(self.items)

    def move_down(self):
        if not self.items:
            return
        self.index = (self.index + 1) % len(self.items)

    def selected(self):
        if not self.items:
            return None
        return self.items[self.index]

    def is_empty(self):
        return len(self.items) == 0
