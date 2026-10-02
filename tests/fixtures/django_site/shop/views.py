from django.views import View

from shop.models import Order


def order_list(request):
    return list(Order.objects.all())


class OrderDetail(View):
    def get(self, request, pk):
        return Order.objects.get(pk=pk)
