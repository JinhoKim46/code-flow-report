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
