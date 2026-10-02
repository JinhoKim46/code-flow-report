from sqlmodel import SQLModel


class Hero(SQLModel, table=True):
    id: int
