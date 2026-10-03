from sqlmodel import select

from notes.db import Note, Tag, session_scope


def save_note(engine, text: str) -> None:
    with session_scope(engine) as s:
        s.add(Note(text=text))


def delete_note(engine, note_id: int) -> bool:
    with session_scope(engine) as s:
        row = s.exec(select(Note).where(Note.id == note_id)).first()
        tags = s.exec(select(Tag).where(Tag.note_id == note_id)).all()
        if row is None:
            return False
        s.delete(row)
        return bool(tags)
