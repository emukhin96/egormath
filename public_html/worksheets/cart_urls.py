from django.urls import path

from . import cart

urlpatterns = [
    path('add/', cart.cart_add, name='cart_add'),
    path('remove/', cart.cart_remove, name='cart_remove'),
    path('select/', cart.cart_select, name='cart_select'),
    path('clear/', cart.cart_clear, name='cart_clear'),
]
