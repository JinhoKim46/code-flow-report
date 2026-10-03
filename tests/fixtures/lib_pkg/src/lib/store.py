from typing import ClassVar


class Record:
    table_name: ClassVar[str] = ""

    def save(self):
        return self

    @classmethod
    def get_all(cls):
        return []


class Note(Record):
    table_name: ClassVar[str] = "note"


def add_note(text: str) -> Note:
    note = Note()
    note.save()
    return note


def list_notes():
    return Note.get_all()
