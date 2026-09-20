"""
menu_state.py - navigazione del menu di avvio, senza pygame.

Separata da os_menu.py apposta: questa e' pura logica (indice
selezionato, quanti elementi, layout a griglia, su/giu/sinistra/destra)
e si testa senza bisogno di un display. os_menu.py la usa e ci aggiunge
solo il disegno con pygame (griglia di icone).

Griglia "invisibile": items resta una lista PIATTA (nessuna struttura
a righe/colonne separata) - columns dice solo di quanti passi avanzare
per su/giu, mentre sinistra/destra avanzano sempre di 1. Con
columns=1 (default) su/giu si comportano esattamente come prima
(equivalenti a sinistra/destra) - retrocompatibile con l'uso storico
a lista verticale."""


class MenuState:
    def __init__(self, items, columns=1):
        """items: lista di oggetti Cart (o qualunque cosa abbia un
        .title) - il menu non sa nulla della loro struttura interna.
        columns: quante colonne ha la griglia visiva - vedi sopra."""
        self.items = items
        self.index = 0
        self.columns = max(1, columns)

    def move_up(self):
        if not self.items:
            return
        self.index = (self.index - self.columns) % len(self.items)

    def move_down(self):
        if not self.items:
            return
        self.index = (self.index + self.columns) % len(self.items)

    def move_left(self):
        if not self.items:
            return
        self.index = (self.index - 1) % len(self.items)

    def move_right(self):
        if not self.items:
            return
        self.index = (self.index + 1) % len(self.items)

    def selected(self):
        if not self.items:
            return None
        return self.items[self.index]

    def is_empty(self):
        return len(self.items) == 0
