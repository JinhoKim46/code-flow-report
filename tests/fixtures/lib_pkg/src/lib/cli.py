from lib.store import add_note, list_notes


def run():
    add_note("hello")
    return list_notes()
