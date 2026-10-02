from django.urls import path

from shop import views

urlpatterns = [
    path("orders/", views.order_list),
    path("orders/<int:pk>/", views.OrderDetail.as_view()),
]
