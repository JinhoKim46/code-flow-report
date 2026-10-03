from contextlib import contextmanager
from typing import Iterator

from pydantic import SecretStr
from sqlmodel import Field, Session, SQLModel, create_engine


class Note(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    text: str


class Tag(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    note_id: int


def make_engine(key: SecretStr | None = None):
    token = key.get_secret_value() if key else ""
    return create_engine("sqlite://", connect_args={"token": token})


@contextmanager
def session_scope(engine) -> Iterator[Session]:
    with Session(engine) as session:
        yield session
        session.commit()
