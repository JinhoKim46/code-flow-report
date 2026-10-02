"""Writes examples/demo-shop: a small, entirely invented shop used as the README example and as the
acceptance test for SKILL.md (a fresh agent must be able to produce its report from SKILL.md alone)."""
from pathlib import Path
from textwrap import dedent

ROOT = Path(__file__).resolve().parent / "demo-shop"

FILES = {
    "README.md": """
        # demo-shop (invented)

        A tiny shop: customers browse products, place orders, pay through an external provider, and get an
        AI-written order summary by email. Orders older than a day without payment are cancelled by a nightly job.
        Everything here is made up for the code-flow-report example.
    """,
    "schema.sql": """
        CREATE TABLE IF NOT EXISTS customers (id INTEGER PRIMARY KEY, email TEXT UNIQUE, name TEXT);
        CREATE TABLE IF NOT EXISTS products (id INTEGER PRIMARY KEY, sku TEXT UNIQUE, title TEXT, price_cents INTEGER);
        CREATE TABLE IF NOT EXISTS orders (id INTEGER PRIMARY KEY, customer_id INTEGER, status TEXT, total_cents INTEGER, created_at TEXT);
        CREATE TABLE IF NOT EXISTS order_items (order_id INTEGER, product_id INTEGER, qty INTEGER);
        CREATE TABLE IF NOT EXISTS audit_log (id INTEGER PRIMARY KEY, action TEXT, actor TEXT, detail TEXT, at TEXT);
    """,
    "shop/__init__.py": '''
        """demo-shop web app."""
        from flask import Flask


        def create_app():
            from shop.web import bp
            app = Flask(__name__)
            app.register_blueprint(bp, url_prefix="/shop")
            return app
    ''',
    "shop/db.py": '''
        """SQLite connection and the one write gateway every change goes through."""
        import json
        import sqlite3
        from datetime import datetime, timezone

        DB_PATH = "shop.db"


        def connect():
            return sqlite3.connect(DB_PATH)


        def run_write(action, actor, payload, work):
            """Runs work(cur) and its audit row in one transaction, so a change is never unrecorded."""
            with connect() as conn:
                cur = conn.cursor()
                result = work(cur)
                cur.execute("INSERT INTO audit_log (action, actor, detail, at) VALUES (?, ?, ?, ?)",
                            (action, actor, json.dumps(payload), datetime.now(timezone.utc).isoformat()))
                return result
    ''',
    "shop/catalog.py": '''
        """Products."""


        def list_products(cur):
            return cur.execute("SELECT id, sku, title, price_cents FROM products ORDER BY title").fetchall()


        def prices(cur, product_ids):
            marks = ",".join("?" for _ in product_ids)
            rows = cur.execute(f"SELECT id, price_cents FROM products WHERE id IN ({marks})", product_ids).fetchall()
            return dict(rows)
    ''',
    "shop/orders.py": '''
        """Order rules: totals are computed here, never taken from the client."""
        from datetime import datetime, timezone

        from shop import catalog

        MAX_QTY = 20


        class OrderError(ValueError):
            pass


        def validate(form):
            items = []
            for sku_id, qty in form.get("items", []):
                qty = int(qty)
                if not 0 < qty <= MAX_QTY:
                    raise OrderError(f"quantity must be 1-{MAX_QTY}")
                items.append((int(sku_id), qty))
            if not items:
                raise OrderError("empty order")
            return items


        def create_order(cur, customer_id, items):
            price = catalog.prices(cur, [p for p, _ in items])
            total = sum(price[p] * q for p, q in items)
            cur.execute("INSERT INTO orders (customer_id, status, total_cents, created_at) VALUES (?, 'new', ?, ?)",
                        (customer_id, total, datetime.now(timezone.utc).isoformat()))
            order_id = cur.lastrowid
            cur.executemany("INSERT INTO order_items (order_id, product_id, qty) VALUES (?, ?, ?)",
                            [(order_id, p, q) for p, q in items])
            return {"order_id": order_id, "total_cents": total}


        def mark_paid(cur, order_id):
            cur.execute("UPDATE orders SET status = 'paid' WHERE id = ?", (order_id,))


        def cancel_stale(cur, before_iso):
            cur.execute("UPDATE orders SET status = 'cancelled' WHERE status = 'new' AND created_at < ?", (before_iso,))
            return cur.rowcount
    ''',
    "shop/payments.py": '''
        """External payment provider (invented API)."""
        import os

        import requests

        API = os.environ.get("PAYMENTS_URL", "https://payments.example.invalid")


        def charge(order_id, total_cents, card_token):
            """One charge per order — the order id doubles as the idempotency key."""
            r = requests.post(f"{API}/charges", json={"amount": total_cents, "currency": "EUR", "source": card_token},
                              headers={"Idempotency-Key": f"order-{order_id}"}, timeout=10)
            r.raise_for_status()
            return r.json()["id"]
    ''',
    "shop/summary.py": '''
        """AI-written order summary for the confirmation email."""
        from anthropic import Anthropic

        from shop.mail import send

        MODEL = "demo-model"
        client = Anthropic()


        def summarise(order, customer_email):
            msg = client.messages.create(
                model=MODEL,
                max_tokens=300,
                temperature=0.3,
                system="Write a two-sentence, friendly order confirmation. Never invent items or prices.",
                messages=[{"role": "user", "content": f"Order {order['order_id']}: total {order['total_cents']} cents"}],
            )
            send(customer_email, "Your order", msg.content[0].text)
    ''',
    "shop/mail.py": '''
        import smtplib


        def send(to, subject, body):
            with smtplib.SMTP("localhost") as smtp:
                smtp.sendmail("shop@example.invalid", [to], f"Subject: {subject}\\n\\n{body}")
    ''',
    "shop/web.py": '''
        """HTTP routes."""
        from flask import Blueprint, abort, redirect, render_template, request, session

        from shop import catalog, orders, payments
        from shop.db import connect, run_write
        from shop.tasks import send_summary

        bp = Blueprint("shop", __name__)


        def login_required(view):
            def wrapped(*a, **kw):
                if "customer_id" not in session:
                    abort(401)
                return view(*a, **kw)
            wrapped.__name__ = view.__name__
            return wrapped


        @bp.get("/products")
        def products():
            with connect() as conn:
                rows = catalog.list_products(conn.cursor())
            return render_template("products.html", rows=rows)


        @bp.post("/orders")
        @login_required
        def place_order():
            try:
                items = orders.validate(request.get_json())
            except orders.OrderError as error:
                return {"error": str(error)}, 400

            def work(cur):
                order = orders.create_order(cur, session["customer_id"], items)
                payment = payments.charge(order["order_id"], order["total_cents"], request.get_json()["card_token"])
                orders.mark_paid(cur, order["order_id"])
                return {**order, "payment": payment}

            result = run_write("order_place", session["email"], request.get_json(), work)
            send_summary.delay(result, session["email"])
            return redirect(f"/shop/orders/{result['order_id']}")
    ''',
    "shop/tasks.py": '''
        """Background work (Celery)."""
        from datetime import datetime, timedelta, timezone

        from celery import shared_task

        from shop import orders
        from shop.db import run_write
        from shop.summary import summarise


        @shared_task
        def send_summary(order, email):
            summarise(order, email)


        @shared_task
        def cancel_unpaid():
            """Nightly: cancel orders still unpaid after a day."""
            before = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
            return run_write("order_cancel_stale", "scheduler", {"before": before}, lambda cur: orders.cancel_stale(cur, before))
    ''',
}


def main():
    for rel, text in FILES.items():
        p = ROOT / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(dedent(text).lstrip("\n"), encoding="utf-8")
    print("wrote", ROOT)


if __name__ == "__main__":
    main()
