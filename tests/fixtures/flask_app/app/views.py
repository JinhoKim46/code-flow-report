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
