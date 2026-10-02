import smtplib


def send(to, subject, body):
    with smtplib.SMTP("localhost") as smtp:
        smtp.sendmail("shop@example.invalid", [to], f"Subject: {subject}\n\n{body}")
