from django.db import models


class Order(models.Model):
    total = models.IntegerField()


class Invoice(models.Model):
    class Meta:
        db_table = "billing_invoice"
