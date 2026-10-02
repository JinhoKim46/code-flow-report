from jobs.tasks import nightly_digest


def trigger():
    nightly_digest.delay()
