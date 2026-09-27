"""Клиент LaTeX API: повтор, когда общий latex-api занят (503/429)."""
import base64
from unittest import mock

from django.test import SimpleTestCase, override_settings

from .services import LatexCompileError, compile_latex

PDF = b'%PDF-1.5 test'


def reply(status, data=None, retry_after=None):
    response = mock.Mock(status_code=status, headers={}, text='')
    if retry_after is not None:
        response.headers['Retry-After'] = str(retry_after)
    response.json.return_value = data if data is not None else {'detail': 'busy'}
    return response


OK = {'success': True, 'pdf_base64': base64.b64encode(PDF).decode()}


@override_settings(LATEX_API_KEY='k', LATEX_API_URL='http://api',
                   LATEX_API_RETRIES=4, LATEX_API_RETRY_MAX_DELAY=10,
                   LATEX_API_RETRY_BUDGET=30)
@mock.patch('worksheets.services.time.sleep')
class LatexRetryTests(SimpleTestCase):
    def test_retries_503_then_succeeds(self, sleep):
        with mock.patch('worksheets.services.requests.post',
                        side_effect=[reply(503, retry_after=3), reply(429), reply(200, OK)]) as post:
            self.assertEqual(compile_latex('x'), PDF)
        self.assertEqual(post.call_count, 3)
        # Retry-After из ответа; без него — нарастающая пауза
        self.assertEqual([c.args[0] for c in sleep.call_args_list], [3.0, 4.0])

    def test_gives_up_after_retries(self, sleep):
        with mock.patch('worksheets.services.requests.post',
                        return_value=reply(503, retry_after=1)) as post:
            with self.assertRaisesMessage(LatexCompileError, 'занят'):
                compile_latex('x')
        self.assertEqual(post.call_count, 5)  # первая попытка + 4 повтора

    @override_settings(LATEX_API_RETRY_BUDGET=35)
    def test_budget_limits_total_wait(self, sleep):
        with mock.patch('worksheets.services.requests.post',
                        return_value=reply(503, retry_after=60)) as post:
            with self.assertRaises(LatexCompileError):
                compile_latex('x')
        # пауза обрезается до 10 с, бюджет 35 с — три повтора (4-я пауза дала бы 40)
        self.assertEqual(post.call_count, 4)
        self.assertEqual(sum(c.args[0] for c in sleep.call_args_list), 30.0)

    def test_compile_error_is_not_retried(self, sleep):
        with mock.patch('worksheets.services.requests.post',
                        return_value=reply(422, {'success': False, 'log': '! Undefined'})) as post:
            with self.assertRaisesMessage(LatexCompileError, 'Ошибка компиляции'):
                compile_latex('x')
        self.assertEqual(post.call_count, 1)
        sleep.assert_not_called()


@override_settings(LATEX_API_KEY='k', LATEX_API_URL='http://api',
                   LATEX_API_RETRIES=4, LATEX_API_RETRY_MAX_DELAY=10,
                   LATEX_API_RETRY_BUDGET=60)
@mock.patch('worksheets.services.time.sleep')
class LatexRetrySlowQueueTests(SimpleTestCase):
    def test_time_in_server_queue_counts_toward_budget(self, sleep):
        # каждая попытка висит в очереди latex-api 30 с и получает 503
        clock = iter([0, 30, 32, 62, 64, 94])
        with mock.patch('worksheets.services.time.monotonic', side_effect=lambda: next(clock)), \
             mock.patch('worksheets.services.requests.post',
                        return_value=reply(503, retry_after=2)) as post:
            with self.assertRaises(LatexCompileError):
                compile_latex('x')
        # 30 с + пауза 2 → вторая попытка (ещё 30) → 62 + 2 > 60: хватит
        self.assertEqual(post.call_count, 2)
