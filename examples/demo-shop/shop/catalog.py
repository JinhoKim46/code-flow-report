"""Products."""


def list_products(cur):
    return cur.execute("SELECT id, sku, title, price_cents FROM products ORDER BY title").fetchall()


def prices(cur, product_ids):
    marks = ",".join("?" for _ in product_ids)
    rows = cur.execute(f"SELECT id, price_cents FROM products WHERE id IN ({marks})", product_ids).fetchall()
    return dict(rows)
