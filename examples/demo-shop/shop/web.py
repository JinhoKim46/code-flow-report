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
