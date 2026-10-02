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
