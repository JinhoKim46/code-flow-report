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
