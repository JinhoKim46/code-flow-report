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
            def test_nothing():
                assert True
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
