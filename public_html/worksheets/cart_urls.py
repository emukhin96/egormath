from django.urls import path

from . import cart

urlpatterns = [
    path('add/', cart.cart_add, name='cart_add'),
    path('remove/', cart.cart_remove, name='cart_remove'),
    path('create/', cart.cart_create, name='cart_create'),
    path('append/', cart.cart_append, name='cart_append'),
    path('clear/', cart.cart_clear, name='cart_clear'),
]
