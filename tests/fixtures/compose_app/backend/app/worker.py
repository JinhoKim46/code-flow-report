from celery import Celery

celery = Celery("app")


@celery.task
def reindex(doc_id):
    return doc_id
