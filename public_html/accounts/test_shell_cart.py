"""Контекст корзины в оболочке считается один раз на запрос
(аудит быстродействия 06.11.2026)."""
from unittest.mock import patch

from django.template import RequestContext, Template
from django.test import RequestFactory, TestCase
from django.contrib.sessions.backends.db import SessionStore

from accounts.context_processors import shell
from accounts.tests import make_teacher
from worksheets import cart as cart_module


class ShellCartMemoTests(TestCase):
    def setUp(self):
        self.teacher = make_teacher()
        self.request = RequestFactory().get('/dashboard/')
        self.request.user = self.teacher
        self.request.session = SessionStore()

    def test_cart_context_called_once_per_request(self):
        with patch.object(cart_module, 'cart_context',
                          wraps=cart_module.cart_context) as spy:
            first = shell(self.request)['cart']
            second = shell(self.request)['cart']
            # Частичные шаблоны с request тоже идут через контекст-процессор
            Template('{{ cart.count }}').render(RequestContext(self.request))
        self.assertEqual(spy.call_count, 1)
        self.assertIs(first, second)

    def test_cart_change_in_same_request_is_seen(self):
        shell(self.request)
        self.request.session[cart_module.SESSION_KEY] = [1]
        self.assertEqual(shell(self.request)['cart']['count'], 1)
