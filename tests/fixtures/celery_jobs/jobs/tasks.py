from celery import shared_task

from jobs.mail import send_digest


@shared_task
def nightly_digest():
    """Mails yesterday's summary."""
    send_digest()
