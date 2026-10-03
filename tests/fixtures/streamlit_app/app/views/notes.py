import streamlit as st

from notes.store import delete_note, save_note
from notes.db import make_engine

engine = make_engine()
text = st.text_area("Note")
if st.button("Save note"):
    save_note(engine, text)
    st.toast("Saved")


def delete_form(note_id: int):
    if st.button("Delete"):
        delete_note(engine, note_id)
