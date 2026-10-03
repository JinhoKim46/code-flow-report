"""Writes the fixture repos under tests/fixtures/. Run once; the result is committed.

Every name, URL and value here is invented. Each fixture exercises one part of the extractor;
tests/test_extract.py states exactly what must come out of each.
"""
from pathlib import Path
from textwrap import dedent

ROOT = Path(__file__).resolve().parent / "fixtures"

FIXTURES = {
    "flask_app": {
        "schema.sql": """
            -- invented schema
            CREATE TABLE IF NOT EXISTS orders (id serial PRIMARY KEY, customer_id int, total int);
            CREATE TABLE customers (id serial PRIMARY KEY, name text);
            CREATE OR REPLACE VIEW order_totals AS SELECT customer_id, sum(total) FROM orders GROUP BY 1;
        """,
        "app/__init__.py": '''
            """Shop web app."""
            from flask import Flask

            from app.views import bp


            def create_app():
                app = Flask(__name__)
                app.register_blueprint(bp, url_prefix="/shop")
                return app
        ''',
        "app/auth.py": '''
            def login_required(view):
                """Lets the view run only for a signed-in user."""
                return view
        ''',
        "app/db.py": '''
            import sqlite3


            def connect():
                return sqlite3.connect("shop.db")
        ''',
        "app/orders.py": '''
            """Order reads and writes."""
            import requests

            from app.db import connect

            TOTALS_SQL = "SELECT customer_id FROM order_totals"


            def run_write(action, payload, work):
                """Every write goes through here."""
                with connect() as conn:
                    return work(conn.cursor())


            def list_orders(cur):
                return cur.execute("SELECT o.id, c.name FROM orders o JOIN customers c ON c.id = o.customer_id").fetchall()


            def insert_order(cur, form):
                cur.execute("INSERT INTO orders (customer_id, total) VALUES (%s, %s)", (form["customer"], form["total"]))
                notify(form)


            def notify(form):
                requests.post("https://hooks.example.invalid/orders", json=form)


            def totals(cur):
                return cur.execute(TOTALS_SQL).fetchall()


            def unused_helper():
                return 1
        ''',
        "app/views.py": '''
            from flask import Blueprint, render_template, request

            from app import orders
            from app.auth import login_required
            from app.db import connect

            bp = Blueprint("shop", __name__)


            @bp.get("/orders")
            @login_required
            def list_orders():
                with connect() as conn:
                    rows = orders.list_orders(conn.cursor())
                return render_template("orders.html", rows=rows)


            @bp.route("/orders", methods=["POST"])
            @login_required
            def create_order():
                def work(cur):
                    orders.insert_order(cur, request.form)
                return orders.run_write("order_create", dict(request.form), work)
        ''',
        "tests/test_views.py": '''
            from app.orders import totals


            def test_totals():
                assert totals is not None
        ''',
    },
    "fastapi_llm": {
        "svc/__init__.py": "",
        "svc/main.py": '''
            from fastapi import FastAPI

            from svc.routes import router

            app = FastAPI()
            app.include_router(router, prefix="/api")
        ''',
        "svc/routes.py": '''
            from fastapi import APIRouter

            from svc.agent import answer

            router = APIRouter(prefix="/v1")


            @router.post("/ask")
            def ask(question: str):
                """Answers one question."""
                return {"answer": answer(question)}
        ''',
        "svc/agent.py": '''
            from anthropic import Anthropic
            from pydantic import BaseModel

            MODEL = "demo-model-1"
            client = Anthropic()


            class Answer(BaseModel):
                text: str


            def answer(question):
                msg = client.messages.create(
                    model=MODEL,
                    max_tokens=512,
                    temperature=0.2,
                    system="You answer briefly.",
                    messages=[{"role": "user", "content": question}],
                    output_format=Answer,
                )
                return msg.content
        ''',
    },
    "django_site": {
        "shop/__init__.py": "",
        "shop/models.py": '''
            from django.db import models


            class Order(models.Model):
                total = models.IntegerField()


            class Invoice(models.Model):
                class Meta:
                    db_table = "billing_invoice"
        ''',
        "shop/views.py": '''
            from django.views import View

            from shop.models import Order


            def order_list(request):
                return list(Order.objects.all())


            class OrderDetail(View):
                def get(self, request, pk):
                    return Order.objects.get(pk=pk)
        ''',
        "shop/urls.py": '''
            from django.urls import path

            from shop import views

            urlpatterns = [
                path("orders/", views.order_list),
                path("orders/<int:pk>/", views.OrderDetail.as_view()),
            ]
        ''',
    },
    "celery_jobs": {
        "jobs/__init__.py": "",
        "jobs/tasks.py": '''
            from celery import shared_task

            from jobs.mail import send_digest


            @shared_task
            def nightly_digest():
                """Mails yesterday's summary."""
                send_digest()
        ''',
        "jobs/mail.py": '''
            import smtplib


            def send_digest():
                smtplib.SMTP("localhost").sendmail("from@example.invalid", ["to@example.invalid"], "summary")
        ''',
        "jobs/api.py": '''
            from jobs.tasks import nightly_digest


            def trigger():
                nightly_digest.delay()
        ''',
    },
    "src_layout_lib": {
        "src/pkg/__init__.py": '''
            """A tiny library."""
            from .core import run
        ''',
        "src/pkg/core.py": '''
            from . import util


            class Engine:
                def start(self):
                    return self.step()

                def step(self):
                    return util.helper(1)


            def run(x):
                return Engine().start() + util.helper(x)
        ''',
        "src/pkg/util.py": '''
            def helper(x):
                from pkg.core import run  # lazy on purpose: avoids a module-level cycle
                return x if x else run
        ''',
        "src/pkg/a.py": '''
            from pkg import b


            def fa():
                return b.fb()
        ''',
        "src/pkg/b.py": '''
            from pkg import a


            def fb():
                return a.fa
        ''',
        "src/pkg/cli.py": '''
            from pkg import run


            def main():
                run(1)


            if __name__ == "__main__":
                main()
        ''',
    },
    "oo_lib": {
        "oo/__init__.py": "",
        "oo/base.py": '''
            import argparse


            class Parser(argparse.ArgumentParser):
                """A library subclass: its inherited methods live in argparse."""


            class Store:
                def save(self):
                    return 1
        ''',
        "oo/app.py": '''
            import argparse

            from oo.base import Parser, Store

            parser = Parser()
            parser.add_argument("--verbose")


            class Service:
                def __init__(self):
                    self.store = Store()

                def run(self):
                    return self.store.save()


            def configure(p: argparse.ArgumentParser):
                p.add_argument("--quiet")
        ''',
        "oo/use.py": '''
            from oo.app import parser


            def main():
                return parser.parse_args()
        ''',
        "oo/models.py": '''
            from sqlmodel import SQLModel


            class Hero(SQLModel, table=True):
                id: int
        ''',
    },
    "types_lib": {
        "tl/__init__.py": "",
        "tl/store.py": '''
            from dataclasses import dataclass
            from typing import Optional


            class Store:
                def save(self):
                    return 1

                def only_here_xyz(self):
                    return 2


            class Child(Store):
                def save(self):
                    return super().save()


            @dataclass
            class Box:
                store: Store


            def make() -> Store:
                return Store()


            def build():
                return Store()


            def maybe(s: Optional[Store]):
                return s.save()


            def quoted(s: "Store"):
                return s.save()
        ''',
        "tl/use.py": '''
            import csv

            from tl.store import Box, Store, build, make


            def returns():
                a = make()
                b = build()
                return a.save() + b.save()


            def field(box: Box):
                return box.store.save()


            def takes(x):
                return x.save()


            def caller():
                return takes(Store())


            def values(data=None):
                d = data or {}
                return d.get("k"), ", ".join(["a", "b"]), "x".upper().strip()


            def rows(f):
                for row in csv.reader(f):
                    row.count("a")


            def guess(obj):
                return obj.only_here_xyz()
        ''',
    },
    "broken": {
        "good.py": '''
            def ok():
                return 1
        ''',
        "bad.py": '''
            def broken(:
                pass
        ''',
    },
    "llm_app": {
        "src/ai/__init__.py": "",
        "src/ai/client.py": """
            from openai import OpenAI


            class LLMClient:
                def __init__(self, sdk: OpenAI | None = None):
                    self.sdk = sdk or OpenAI()

                def chat(self, role: str, messages: list, model: str | None = None) -> str:
                    return self.sdk.chat.completions.create(model=model, messages=messages)

                def chat_json(self, role: str, messages: list, schema, model: str | None = None):
                    return schema.model_validate_json(self.chat(role, messages, model=model))
        """,
        "src/ai/deps.py": """
            from dataclasses import dataclass
            from typing import Callable

            from ai.client import LLMClient


            @dataclass
            class Deps:
                make_llm: Callable[[int], LLMClient]
        """,
        "src/ai/wiring.py": """
            from ai.client import LLMClient
            from ai.deps import Deps


            def build_deps() -> Deps:
                def make_llm(user_id: int) -> LLMClient:
                    return LLMClient()

                return Deps(make_llm=make_llm)
        """,
        "src/ai/judge.py": """
            from pydantic import BaseModel

            from ai.deps import Deps


            class Verdict(BaseModel):
                score: int


            def judge_messages(text: str) -> list:
                return [{"role": "user", "content": text}]


            def run_judge(deps: Deps, text: str) -> Verdict:
                llm = deps.make_llm(1)
                return llm.chat_json("judge", judge_messages(text), Verdict, model="demo-judge", temperature=0)
        """,
        "src/ai/guard.py": """
            from ai.client import LLMClient


            class Guard:
                def __init__(self, llm: LLMClient | None = None):
                    self.llm = llm

                def check(self, text: str) -> str:
                    return self.llm.chat("guard", [{"role": "user", "content": text}])
        """,
        "src/ai/decide.py": """
            import httpx


            def decide(payload: dict) -> dict:
                return httpx.post("https://openrouter.ai/api/v1/decisions", json=payload).json()
        """,
        "scripts/helpers.py": """
            def ping() -> str:
                return "pong"
        """,
        "scripts/run.py": """
            import helpers


            def main():
                return helpers.ping()


            if __name__ == "__main__":
                main()
        """,
    },
    "lib_pkg": {
        "pyproject.toml": """
            [project]
            name = "lib"
            version = "0.1.0"

            [project.scripts]
            libtool = "lib.cli:run"
        """,
        "schema/0001.surql": """
            DEFINE TABLE IF NOT EXISTS note SCHEMAFULL;
        """,
        "src/lib/__init__.py": "",
        "src/lib/models.py": """
            from openai import OpenAI


            class Model:
                def generate(self, messages):
                    raise NotImplementedError


            class ApiModel(Model):
                pass


            class OpenAIModel(ApiModel):
                def __init__(self):
                    self.client = OpenAI()

                def generate(self, messages):
                    return self.retry(self.client.chat.completions.create, messages=messages)

                def retry(self, fn, **kwargs):
                    return fn(**kwargs)
        """,
        "src/lib/agents.py": """
            from lib.models import Model

            __all__ = ["Agent"]


            class Base:
                def __init__(self, model: Model):
                    self.model = model

                def run(self, task):
                    return self.step(task)

                def step(self, task):
                    raise NotImplementedError


            class Agent(Base):
                def step(self, task):
                    return self.model.generate([task])
        """,
        "src/lib/store.py": """
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
        """,
        "src/lib/chain.py": """
            from langchain_core.messages import HumanMessage


            def ask(llm, question: str):
                return llm.invoke([HumanMessage(content=question)])
        """,
        "src/lib/cli.py": """
            from lib.store import add_note, list_notes


            def run():
                add_note("hello")
                return list_notes()
        """,
        "scripts/seed.py": """
            from lib.store import add_note, list_notes

            add_note("one")
            add_note("two")
            print(list_notes())
        """,
    },
    "streamlit_app": {
        "app/main.py": """
            import streamlit as st

            st.navigation([st.Page("views/notes.py", title="Notes")]).run()
        """,
        "app/views/notes.py": """
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
        """,
        "src/notes/__init__.py": "",
        "src/notes/db.py": """
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
        """,
        "src/notes/store.py": """
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
        """,
    },
}


def main():
    for name, files in FIXTURES.items():
        for rel, text in files.items():
            path = ROOT / name / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(dedent(text).lstrip("\n"), encoding="utf-8")
    print("fixtures written:", ", ".join(FIXTURES))


if __name__ == "__main__":
    main()
