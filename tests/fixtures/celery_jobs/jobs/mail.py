import smtplib


def send_digest():
    smtplib.SMTP("localhost").sendmail("from@example.invalid", ["to@example.invalid"], "summary")
