import json
import re

from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils.html import escape

from accounts.models import Profile

from .latex_utils import (escape_latex, restore_json_eaten_latex,
                          split_items, strip_latex, wrap_bare_math)
from .models import Tag, Task, Topic


def make_teacher(username='teacher1'):
    user = User.objects.create_user(username=username, password='pass12345',
                                    first_name='Иван', last_name='Учителев')
    Profile.objects.create(user=user, role=Profile.ROLE_TEACHER)
    return user


def make_student(teacher, username='student1'):
    user = User.objects.create_user(username=username, password='pass12345',
                                    first_name='Петя', last_name='Ученик/ов')
    Profile.objects.create(user=user, role=Profile.ROLE_STUDENT,
                           grade=8, teacher=teacher)
    return user


class LatexUtilsTests(TestCase):
    def test_escape_latex(self):
        self.assertEqual(escape_latex('50% & #1'), r'50\% \& \#1')
        self.assertIn(r'\textbackslash', escape_latex('a\\b'))

    def test_strip_latex(self):
        s = strip_latex(r'Решите уравнение $x^2-5x+6=0$ \textbf{устно}')
        self.assertIn('Решите уравнение', s)
        self.assertNotIn('\\textbf', s)

    def test_split_items_strips_punctuation(self):
        chunks = split_items('\\item $1+1$; \\item $2+2$ ; \\item $3+3$.')
        self.assertEqual(chunks, ['$1+1$', '$2+2$', '$3+3$'])

    def test_split_items_keeps_sentence_punctuation(self):
        # Предложение с «.» и любой «?» сохраняются; служебные «;»/«.»
        # у фрагментов перечисления срезаются
        chunks = split_items(
            '\\item Докажите неравенство. '
            '\\item Верно ли обратное? '
            '\\item чему равен $x$? '
            '\\item $x>0$? '
            '\\item $2+2$;')
        self.assertEqual(chunks, [
            'Докажите неравенство.',
            'Верно ли обратное?',
            'чему равен $x$?',
            '$x>0$?',
            '$2+2$',
        ])

    def test_wrap_bare_math_task9_style(self):
        # Ответ целиком — формула без долларов
        self.assertEqual(
            wrap_bare_math(r'a = \pm \frac{4}{5}'),
            r'$a = \pm \frac{4}{5}$')
        # Уже обёрнутое не трогаем
        self.assertEqual(
            wrap_bare_math(r'$a = \pm \frac{4}{5}$'),
            r'$a = \pm \frac{4}{5}$')
        self.assertEqual(wrap_bare_math('нет корней'), 'нет корней')
        self.assertEqual(wrap_bare_math('42'), '42')
        solution = (
            'Дискриминант D = (-5a)^2 - 4 \\cdot 1 \\cdot 4 = 25a^2 - 16. '
            'Приравняем дискриминант к нулю: 25a^2 - 16 = 0, откуда '
            'a^2 = \\frac{16}{25}, следовательно a = \\pm \\frac{4}{5}.')
        wrapped = wrap_bare_math(solution)
        self.assertIn(r'$D = (-5a)^2 - 4 \cdot 1 \cdot 4 = 25a^2 - 16$',
                      wrapped)
        self.assertIn(r'$25a^2 - 16 = 0$', wrapped)
        self.assertIn(r'$a^2 = \frac{16}{25}$', wrapped)
        self.assertIn(r'$a = \pm \frac{4}{5}$', wrapped)
        self.assertEqual(wrap_bare_math(wrapped), wrapped)

    def test_restore_json_eaten_latex(self):
        # json.loads съедает \f и \t: form feed + "rac", tab + "imes"
        self.assertEqual(restore_json_eaten_latex('-\x0crac{1}{2}'),
                         r'-\frac{1}{2}')
        eaten_times = 'a \times b'  # обычная строка: \t → tab
        self.assertIn('\t', eaten_times)
        self.assertEqual(restore_json_eaten_latex(eaten_times),
                         r'a \times b')
        self.assertEqual(restore_json_eaten_latex(r'a \times b'),
                         r'a \times b')
        self.assertEqual(
            restore_json_eaten_latex('шаг.\nПриведем'),
            'шаг.\nПриведем')
        self.assertEqual(restore_json_eaten_latex(r'-\frac{1}{2}'),
                         r'-\frac{1}{2}')


class NeuroTests(TestCase):
    """Сервис нейрогенерации ответов/решений (Gemini, REST)."""

    def _response(self, data, status=200):
        from unittest import mock
        response = mock.Mock()
        response.status_code = status
        response.text = 'raw'
        response.json.return_value = {
            'candidates': [{'content': {'parts': [{
                'text': json.dumps(data)}]}}],
        }
        return response

    def test_no_key_raises(self):
        from django.test import override_settings

        from .neuro import NeuroError, solve_task
        with override_settings(GEMINI_API_KEY='', GOOGLE_API_KEY=''):
            with self.assertRaises(NeuroError):
                solve_task('Задача')

    def test_solve_task_parses_and_normalizes(self):
        from unittest import mock

        from django.test import override_settings

        from . import neuro
        payload = {
            'answer': ' 42 ', 'solution': 'Очевидно.',
            # Лишний элемент отрезается, недостающий добивается пустым
            'subitem_answers': ['1', '2', '3'],
            'subitem_solutions': ['a'],
        }
        with override_settings(GEMINI_API_KEY='k', GEMINI_MODEL='m',
                               GEMINI_TIMEOUT=5):
            with mock.patch('problems.neuro.requests.post',
                            return_value=self._response(payload)) as post:
                result = neuro.solve_task('Задача', ['$x$', '$y$'])
        self.assertEqual(result['answer'], '42')
        self.assertEqual(result['solution'], 'Очевидно.')
        self.assertEqual(result['subitem_answers'], ['1', '2'])
        self.assertEqual(result['subitem_solutions'], ['a', ''])
        body = post.call_args.kwargs['json']
        self.assertIn('Задача', body['contents'][0]['parts'][0]['text'])
        self.assertEqual(
            body['generationConfig']['response_mime_type'],
            'application/json')

    def test_invented_subitems_fold_into_answer(self):
        """Параметр без подпунктов модель часто кладёт в массивы — не теряем."""
        from unittest import mock

        from django.test import override_settings

        from . import neuro
        payload = {
            'answer': '', 'solution': '',
            'subitem_answers': ['$x=3/a$', 'нет корней'],
            'subitem_solutions': ['при $a\\neq 0$', 'при $a=0$'],
        }
        with override_settings(GEMINI_API_KEY='k', GEMINI_MODEL='m',
                               GEMINI_TIMEOUT=5):
            with mock.patch('problems.neuro.requests.post',
                            return_value=self._response(payload)):
                result = neuro.solve_task('Решите $2ax=6$')
        self.assertEqual(result['answer'], '$x=3/a$; нет корней')
        self.assertIn('при $a\\neq 0$', result['solution'])
        self.assertIn('при $a=0$', result['solution'])
        self.assertEqual(result['subitem_answers'], [])
        self.assertEqual(result['subitem_solutions'], [])

    def test_solve_task_wraps_bare_math(self):
        from unittest import mock

        from django.test import override_settings

        from . import neuro
        payload = {
            'answer': r'a = \pm \frac{4}{5}',
            'solution': r'Дискриминант D = 25a^2 - 16.',
            'subitem_answers': [], 'subitem_solutions': [],
        }
        with override_settings(GEMINI_API_KEY='k', GEMINI_MODEL='m',
                               GEMINI_TIMEOUT=5):
            with mock.patch('problems.neuro.requests.post',
                            return_value=self._response(payload)):
                result = neuro.solve_task('При каких a...')
        self.assertEqual(result['answer'], r'$a = \pm \frac{4}{5}$')
        self.assertIn(r'$D = 25a^2 - 16$', result['solution'])

    def test_solve_task_restores_json_eaten_commands(self):
        """Gemini пишет \\frac без экранирования — json.loads даёт form feed."""
        from unittest import mock

        from django.test import override_settings

        from . import neuro
        # Как Gemini: в JSON один слэш перед f/t, не два
        raw = (
            '{"answer": "$-\\frac{1}{2}$",'
            ' "solution": "a \\times b",'
            ' "subitem_answers": [], "subitem_solutions": []}')
        self.assertIn('\x0c', json.loads(raw)['answer'])
        response = mock.Mock(status_code=200, text='ok')
        response.json.return_value = {
            'candidates': [{'content': {'parts': [{'text': raw}]}}],
        }
        with override_settings(GEMINI_API_KEY='k', GEMINI_MODEL='m',
                               GEMINI_TIMEOUT=5):
            with mock.patch('problems.neuro.requests.post',
                            return_value=response):
                result = neuro.solve_task('Упростите')
        self.assertIn(r'\frac', result['answer'])
        self.assertNotIn('\x0c', result['answer'])
        self.assertIn(r'\times', result['solution'])

    def test_empty_draft_raises(self):
        from unittest import mock

        from django.test import override_settings

        from .neuro import NeuroError, solve_task
        payload = {
            'answer': '', 'solution': '',
            'subitem_answers': [], 'subitem_solutions': [],
        }
        with override_settings(GEMINI_API_KEY='k'):
            with mock.patch('problems.neuro.requests.post',
                            return_value=self._response(payload)):
                with self.assertRaises(NeuroError) as ctx:
                    solve_task('Задача')
        self.assertIn('не вернула ответ', str(ctx.exception))

    def test_http_error_raises(self):
        from unittest import mock

        from django.test import override_settings

        from .neuro import NeuroError, solve_task
        response = mock.Mock(status_code=503, text='oops')
        with override_settings(GEMINI_API_KEY='k'):
            with mock.patch('problems.neuro.requests.post',
                            return_value=response):
                with self.assertLogs('problems.neuro', level='WARNING'):
                    with self.assertRaises(NeuroError):
                        solve_task('Задача')

    def test_retired_model_shows_api_message(self):
        from unittest import mock

        from django.test import override_settings

        from .neuro import NeuroError, solve_task
        response = mock.Mock(status_code=404, text='not found')
        response.json.return_value = {
            'error': {
                'message': (
                    'This model models/gemini-2.5-flash-lite '
                    'is no longer available'),
            },
        }
        with override_settings(GEMINI_API_KEY='k'):
            with mock.patch('problems.neuro.requests.post',
                            return_value=response):
                with self.assertLogs('problems.neuro', level='WARNING'):
                    with self.assertRaises(NeuroError) as ctx:
                        solve_task('Задача')
        self.assertIn('недоступна', str(ctx.exception))
        self.assertIn('gemini-2.5-flash-lite', str(ctx.exception))

    def test_quota_parallel_and_rate(self):
        from django.test import override_settings

        from .neuro import NeuroQuotaError, acquire_quota, release_quota
        user = make_teacher('neuro-user')
        with override_settings(GEMINI_RATE_PER_MINUTE=1, GEMINI_TIMEOUT=60):
            started = acquire_quota(user)
            with self.assertRaises(NeuroQuotaError):
                acquire_quota(user)
            release_quota(user, started)
            with self.assertRaises(NeuroQuotaError):
                acquire_quota(user)

    def test_quota_429_keeps_inflight(self):
        """Чужой 429 не снимает блокировку текущего запроса."""
        from unittest import mock

        from django.test import override_settings

        from .models import NeuroSolveQuota
        from .neuro import acquire_quota
        teacher = make_teacher()
        self.client.login(username=teacher.username, password='pass12345')
        with override_settings(GEMINI_RATE_PER_MINUTE=20, GEMINI_TIMEOUT=60):
            started = acquire_quota(teacher)
            with mock.patch('problems.neuro.solve_task') as solve:
                response = self.client.post(
                    reverse('task_neuro_solve'),
                    {'text': 'Задача'},
                    content_type='application/json')
            self.assertEqual(response.status_code, 429)
            solve.assert_not_called()
            quota = NeuroSolveQuota.objects.get(user=teacher)
            self.assertEqual(quota.in_flight_at, started)

    def test_too_long_raises(self):
        from django.test import override_settings

        from .neuro import MAX_TASK_CHARS, NeuroError, solve_task
        with override_settings(GEMINI_API_KEY='k'):
            with self.assertRaises(NeuroError):
                solve_task('x' * (MAX_TASK_CHARS + 1))

    def test_apply_result_skips_filled_unless_overwrite(self):
        from .neuro import apply_result
        task = Task.objects.create(
            text_latex='Задача', answer_latex='старый', created_by=make_teacher())
        apply_result(task, {'answer': 'новый', 'solution': 'Шаг'},
                     overwrite=False)
        task.refresh_from_db()
        self.assertEqual(task.answer_latex, 'старый')
        self.assertEqual(task.solution_latex, 'Шаг')
        apply_result(task, {'answer': 'новый', 'solution': 'Другое'},
                     overwrite=True)
        task.refresh_from_db()
        self.assertEqual(task.answer_latex, 'новый')
        self.assertEqual(task.solution_latex, 'Другое')

    def test_solve_endpoint_apply_and_form_only(self):
        from unittest import mock
        teacher = make_teacher()
        self.client.login(username='teacher1', password='pass12345')
        task = Task.objects.create(text_latex='$2+2$', created_by=teacher)
        drafts = {'answer': '4', 'solution': 'Сложение.',
                  'subitem_answers': [], 'subitem_solutions': []}
        url = reverse('task_neuro_solve')
        with mock.patch('problems.neuro.solve_task', return_value=drafts):
            response = self.client.post(
                url, {'text': '$2+2$', 'subitems': []},
                content_type='application/json')
        self.assertEqual(response.status_code, 200)
        task.refresh_from_db()
        self.assertEqual(task.answer_latex, '')
        with mock.patch('problems.neuro.solve_task', return_value=drafts):
            response = self.client.post(
                url, {'task_id': task.pk, 'apply': True},
                content_type='application/json')
        self.assertEqual(response.status_code, 200)
        task.refresh_from_db()
        self.assertEqual(task.answer_latex, '4')
        self.assertEqual(task.solution_latex, 'Сложение.')

    def test_superuser_without_profile_gets_neuro_js(self):
        """Суперпользователь без профиля — учитель по get_role, скрипт должен грузиться."""
        admin = User.objects.create_superuser('admin', 'a@b.c', 'pass12345')
        task = Task.objects.create(text_latex='$2+2$', created_by=admin)
        self.client.login(username='admin', password='pass12345')
        response = self.client.get(reverse('task_detail', args=[task.pk]))
        self.assertContains(response, 'js/neuro.js')
        self.assertContains(response, 'NEURO_SOLVE_URL')


class WebTexTests(TestCase):
    """Серверный препроцессор tex → HTML для веб-страниц."""

    def render(self, text):
        from problems.web_tex import tex_to_web_html
        return str(tex_to_web_html(text))

    def test_comments_and_annot(self):
        self.assertEqual(self.render('%\\annot{}\nНайдите $x$.'),
                         'Найдите $x$.')
        self.assertEqual(
            self.render('\\annot{для устного счёта} Вычислите.'),
            '<span class="tex-annot">для устного счёта</span> Вычислите.')

    def test_line_breaks_and_spacing(self):
        self.assertEqual(self.render('Первая строка.\\\\Вторая.'),
                         'Первая строка.<br>Вторая.')
        self.assertEqual(self.render('Абзац.\\par Новый.'),
                         'Абзац.<br><br> Новый.')
        self.assertEqual(self.render('на 5~см больше'),
                         'на 5&nbsp;см больше')
        self.assertEqual(self.render('на 33\\%'), 'на 33%')

    def test_math_is_untouched(self):
        # Внутри $…$ команды не трогаем — их рендерит KaTeX
        self.assertEqual(self.render('$a~b \\\\ c$'), '$a~b \\\\ c$')

    def test_bracket_math_is_untouched(self):
        # KaTeX рендерит и \(…\)/\[…\] — внутри них \\ не превращаем в <br>
        matrix = '\\[\\begin{matrix}a\\\\b\\end{matrix}\\]'
        self.assertEqual(self.render(matrix), escape(matrix))
        inline = 'Дано \\(a~b \\\\ c\\), найдите.'
        self.assertEqual(self.render(inline), escape(inline))

    def test_commands_inside_math_are_untouched(self):
        # \annot и прочее внутри $…$ не преобразуем — KaTeX должен видеть
        # цельное выражение
        self.assertEqual(self.render('$x+\\annot{a}$'), '$x+\\annot{a}$')

    def test_margin_marks(self):
        # Семейство пометок egor.sty: \rev, \oge, \complex, \annotnoframe
        self.assertEqual(
            self.render('\\rev Повторите тему.'),
            '<span class="tex-annot tex-annot-noframe">↻</span>'
            ' Повторите тему.')
        self.assertEqual(
            self.render('\\oge Из банка заданий.'),
            '<span class="tex-annot">ОГЭ</span> Из банка заданий.')
        self.assertEqual(
            self.render('\\complex Задача со звёздочкой.'),
            '<span class="tex-annot tex-annot-noframe">★</span>'
            ' Задача со звёздочкой.')
        self.assertEqual(
            self.render('\\annotnoframe{устно} Сосчитайте.'),
            '<span class="tex-annot tex-annot-noframe">устно</span>'
            ' Сосчитайте.')

    def test_source_and_textbit(self):
        self.assertEqual(
            self.render('\\source{Ткачук, №5} Докажите.'),
            '<span class="tex-source">Ткачук, №5</span> Докажите.')
        self.assertEqual(
            self.render('\\textbit{Важно:} правило.'),
            '<b><i>Важно:</i></b> правило.')

    def test_annot_with_math_inside(self):
        # Формула внутри аргумента пометки сохраняется для KaTeX
        self.assertEqual(
            self.render('\\annot{для $x>0$} Решите.'),
            '<span class="tex-annot">для $x&gt;0$</span> Решите.')

    def test_preview_safe_truncation(self):
        from problems.web_tex import tex_preview_html
        # Обрезка не разрезает формулу: $…$ у границы уходит целиком
        text = 'Вычислите значение выражения $x^2+3x-4$ при $x=2$.'
        html = str(tex_preview_html(text, limit=32))
        self.assertNotIn('$x^2', html.replace('Вычислите значение выражения',
                                              ''))
        self.assertEqual(html.count('$') % 2, 0)
        # Недописанная команда у границы не остаётся в превью
        html = str(tex_preview_html('Смотри рисунок \\taskpic{file.pdf}', 20))
        self.assertNotIn('\\taskpi', html)
        # Короткий текст — без изменений и многоточия
        self.assertEqual(str(tex_preview_html('Коротко.', 100)), 'Коротко.')

    def test_tabular(self):
        html = self.render(
            '\\begin{tabular}{|c|c|}\\hline $x$ & 1 \\\\ $y$ & 2 '
            '\\\\ \\hline\\end{tabular}')
        self.assertIn('<table class="tex-table">', html)
        self.assertIn('<tr><td>$x$</td><td>1</td></tr>', html)
        self.assertIn('<tr><td>$y$</td><td>2</td></tr>', html)

    def test_tabular_math_with_breaks_in_cell(self):
        # \\ и & внутри формулы в ячейке — часть формулы, не разделители
        html = self.render(
            '\\begin{tabular}{|c|c|}'
            '$\\begin{matrix}a\\\\b\\end{matrix}$ & 1\\end{tabular}')
        self.assertIn(
            '<tr><td>$\\begin{matrix}a\\\\b\\end{matrix}$</td>'
            '<td>1</td></tr>', html)

    def test_preview_cut_inside_bracket_math(self):
        from problems.web_tex import tex_preview_html
        # Граница внутри \(…\) — формула откатывается целиком
        text = 'Найдите корни уравнения \\(x^2 - 5x + 6 = 0\\) устно.'
        html = str(tex_preview_html(text, limit=30))
        self.assertNotIn('\\(x^2', html)
        self.assertNotIn('\\(', html)

    def test_html_is_escaped(self):
        self.assertEqual(self.render('<script>alert(1)</script>'),
                         '&lt;script&gt;alert(1)&lt;/script&gt;')


class TaskModelTests(TestCase):
    def test_text_plain_autofill(self):
        task = Task.objects.create(text_latex=r'Найдите \emph{корни}: $x^2=4$')
        self.assertIn('Найдите', task.text_plain)
        self.assertNotIn('\\emph', task.text_plain)

    def test_topic_descendants(self):
        root = Topic.objects.create(name='Алгебра')
        child = Topic.objects.create(name='Уравнения', parent=root)
        grandchild = Topic.objects.create(name='Квадратные', parent=child)
        ids = root.descendants_ids()
        self.assertIn(child.pk, ids)
        self.assertIn(grandchild.pk, ids)

    def test_make_variant_copies_subitem_solutions(self):
        task = Task.objects.create(text_latex='Вычислите')
        task.subitems.create(
            order=10, text_latex='$1+1$', answer_latex='2',
            solution_latex='Сложение')
        variant = task.make_variant()
        self.assertNotEqual(variant.pk, task.pk)
        copy = variant.subitems.get()
        self.assertEqual(copy.text_latex, '$1+1$')
        self.assertEqual(copy.answer_latex, '2')
        self.assertEqual(copy.solution_latex, 'Сложение')
        # Оригинал не тронут
        original = task.subitems.get()
        self.assertEqual(original.solution_latex, 'Сложение')


class CatalogViewTests(TestCase):
    def setUp(self):
        self.teacher = make_teacher()
        self.student = make_student(self.teacher)
        self.topic = Topic.objects.create(name='Дроби')
        self.tag = Tag.objects.create(name='ОГЭ')
        self.task = Task.objects.create(
            text_latex='Сократите дробь $\\frac{2}{4}$',
            grade_level=6, created_by=self.teacher)
        self.task.topics.add(self.topic)
        self.task.tags.add(self.tag)

    def test_catalog_requires_teacher(self):
        self.client.login(username='student1', password='pass12345')
        response = self.client.get(reverse('task_list'))
        self.assertEqual(response.status_code, 403)

    def test_catalog_search(self):
        self.client.login(username='teacher1', password='pass12345')
        response = self.client.get(reverse('task_list'), {'q': 'дробь'})
        self.assertContains(response, 'Сократите')
        response = self.client.get(reverse('task_list'), {'q': 'логарифм'})
        self.assertNotContains(response, 'Сократите')

    def test_catalog_filters(self):
        self.client.login(username='teacher1', password='pass12345')
        response = self.client.get(reverse('task_list'),
                                   {'topic': self.topic.pk, 'grade': 6,
                                    'tag': 'ОГЭ'})
        self.assertContains(response, 'Сократите')

    def test_task_create(self):
        self.client.login(username='teacher1', password='pass12345')
        response = self.client.post(reverse('task_create'), {
            'text_latex': 'Вычислите $2+2$', 'columns': 0,
            'answer_latex': '4', 'solution_latex': '',
            'stars': 0, 'answer_type': 'number',
            **formset_management('source_refs', total=0),
            **formset_management('subitems', total=0),
            **formset_management('images', total=0),
        })
        task = Task.objects.get(answer_latex='4')
        self.assertRedirects(response, reverse('task_detail', args=[task.pk]))
        self.assertEqual(task.created_by, self.teacher)

    def test_task_create_with_subitems(self):
        self.client.login(username='teacher1', password='pass12345')
        self.client.post(reverse('task_create'), {
            'text_latex': 'Вычислите:', 'columns': 2,
            'answer_latex': '', 'solution_latex': '',
            'stars': 1, 'answer_type': 'number',
            **formset_management('source_refs', total=0),
            **formset_management('subitems', total=2),
            **formset_management('images', total=0),
            'subitems-0-order': 10, 'subitems-0-text_latex': '$1+1$;',
            'subitems-0-answer_latex': '2',
            'subitems-1-order': 20, 'subitems-1-text_latex': '$2+2$.',
            'subitems-1-answer_latex': '4',
        })
        task = Task.objects.get(text_latex='Вычислите:')
        self.assertEqual(task.subitems.count(), 2)
        self.assertEqual(task.subitems.first().answer_latex, '2')

    def test_task_create_duplicate_warning(self):
        # Условие совпадает с существующей задачей (с точностью до пробелов)
        self.client.login(username='teacher1', password='pass12345')
        data = {
            'text_latex': '  ' + self.task.text_latex + '  ', 'columns': 0,
            'answer_latex': '', 'solution_latex': '',
            'stars': 0, 'answer_type': 'number',
            **formset_management('source_refs', total=0),
            **formset_management('subitems', total=0),
            **formset_management('images', total=0),
        }
        before = Task.objects.count()
        response = self.client.post(reverse('task_create'), data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'уже есть в базе')
        self.assertContains(response, 'Всё равно создать')
        self.assertEqual(Task.objects.count(), before)
        # «Всё равно создать» обходит проверку
        response = self.client.post(
            reverse('task_create'), {**data, 'force_create': '1'})
        self.assertEqual(Task.objects.count(), before + 1)

    def test_variants_hidden_from_catalog(self):
        variant = Task.objects.create(
            text_latex='Копия', variant_of=self.task)
        self.client.login(username='teacher1', password='pass12345')
        response = self.client.get(reverse('task_list'))
        self.assertContains(response, 'Сократите')
        self.assertNotContains(response, 'Копия')
        self.assertIsNotNone(variant.pk)


def formset_management(prefix, total=0, initial=0):
    return {
        f'{prefix}-TOTAL_FORMS': total,
        f'{prefix}-INITIAL_FORMS': initial,
        f'{prefix}-MIN_NUM_FORMS': 0,
        f'{prefix}-MAX_NUM_FORMS': 1000,
    }


class QuickEntryTests(TestCase):
    """«Сохранить и добавить следующую» и массовое добавление ответов."""

    def setUp(self):
        from .models import Source, TaskSource
        self.teacher = make_teacher()
        self.topic = Topic.objects.create(name='Дроби')
        self.source = Source.objects.create(title='Задачник')
        self.client.login(username='teacher1', password='pass12345')
        self.Source, self.TaskSource = Source, TaskSource

    def test_save_and_next(self):
        response = self.client.post(reverse('task_create'), {
            'text_latex': 'Первая задача', 'columns': 0,
            'answer_latex': '', 'solution_latex': '',
            'stars': 2, 'answer_type': 'text', 'grade_level': 7,
            'topics': [self.topic.pk],
            'save_and_next': '',
            **formset_management('source_refs', total=1),
            'source_refs-0-source': self.source.pk,
            'source_refs-0-number': '5.17а',
            **formset_management('subitems', total=0),
            **formset_management('images', total=0),
        })
        task = Task.objects.get(text_latex='Первая задача')
        self.assertRedirects(
            response, reverse('task_create') + f'?from={task.pk}')

        # Форма новой задачи предзаполнена, номер источника +1
        response = self.client.get(
            reverse('task_create'), {'from': task.pk})
        self.assertEqual(response.context['form'].initial['stars'], 2)
        self.assertEqual(response.context['form'].initial['grade_level'], 7)
        self.assertIn(self.topic.pk,
                      response.context['form'].initial['topics'])
        self.assertContains(response, '5.18а')

    def test_bulk_answers(self):
        t1 = Task.objects.create(text_latex='Задача 1',
                                 created_by=self.teacher)
        t2 = Task.objects.create(text_latex='Задача 2', answer_latex='старый',
                                 created_by=self.teacher)
        self.TaskSource.objects.create(task=t1, source=self.source,
                                       number='101')
        self.TaskSource.objects.create(task=t2, source=self.source,
                                       number='102')
        url = reverse('bulk_answers')
        text = '101. 42\n102. новый\n103. 7\nмусор без номера'

        response = self.client.post(
            url, {'source': self.source.pk, 'answers': text,
                  'action': 'preview'})
        statuses = {r['number']: r['status'] for r in response.context['rows']}
        self.assertEqual(statuses['101'], 'new')
        self.assertEqual(statuses['102'], 'conflict')
        self.assertEqual(statuses['103'], 'notfound')

        # Применение: конфликт без галочки не перезаписывается
        self.client.post(url, {'source': self.source.pk, 'answers': text,
                               'action': 'apply'})
        t1.refresh_from_db()
        t2.refresh_from_db()
        self.assertEqual(t1.answer_latex, '42')
        self.assertEqual(t2.answer_latex, 'старый')

        # С галочкой «перезаписать» — обновляется
        self.client.post(url, {'source': self.source.pk, 'answers': text,
                               'action': 'apply', 'overwrite': [t2.pk]})
        t2.refresh_from_db()
        self.assertEqual(t2.answer_latex, 'новый')


class BulkUpdateTests(TestCase):
    """Массовое назначение класса/темы/звёзд из списка задач."""

    def setUp(self):
        self.teacher = make_teacher()
        self.t1 = Task.objects.create(text_latex='A', created_by=self.teacher)
        self.t2 = Task.objects.create(text_latex='B', created_by=self.teacher)
        self.topic = Topic.objects.create(name='Уравнения')
        self.client.login(username='teacher1', password='pass12345')
        self.url = reverse('task_bulk_update')

    def test_bulk_assign(self):
        response = self.client.post(self.url, {
            'ids': [self.t1.pk, self.t2.pk],
            'grade_level': '8', 'stars': '2', 'topic_id': self.topic.pk,
            'next': '/problems/?grade=8',
        })
        self.assertRedirects(response, '/problems/?grade=8')
        for task in (self.t1, self.t2):
            task.refresh_from_db()
            self.assertEqual(task.grade_level, 8)
            self.assertEqual(task.stars, 2)
            self.assertIn(self.topic, task.topics.all())

    def test_bulk_partial_and_validation(self):
        # Только звёзды: класс не трогаем
        self.client.post(self.url, {'ids': [self.t1.pk], 'stars': '1'})
        self.t1.refresh_from_db()
        self.assertEqual(self.t1.stars, 1)
        self.assertIsNone(self.t1.grade_level)
        # Недопустимый класс — ничего не меняется
        self.client.post(self.url,
                         {'ids': [self.t1.pk], 'grade_level': '99'})
        self.t1.refresh_from_db()
        self.assertIsNone(self.t1.grade_level)

    def test_bulk_delete_skips_used_tasks(self):
        from worksheets.models import Worksheet, WorksheetItem
        ws = Worksheet.objects.create(title='Листок', owner=self.teacher)
        WorksheetItem.objects.create(worksheet=ws, task=self.t1, order=10)
        response = self.client.post(self.url, {
            'ids': [self.t1.pk, self.t2.pk], 'delete': '1',
        })
        self.assertRedirects(response, reverse('task_list'))
        # Задача из листка остаётся, свободная удалена
        self.assertTrue(Task.objects.filter(pk=self.t1.pk).exists())
        self.assertFalse(Task.objects.filter(pk=self.t2.pk).exists())


class QuickUpdateTests(TestCase):
    """Горячее редактирование класса/ответа/источника из списка задач."""

    def setUp(self):
        from .models import Source
        self.teacher = make_teacher()
        self.task = Task.objects.create(
            text_latex='Задача', created_by=self.teacher)
        self.source = Source.objects.create(title='Задачник')
        self.client.login(username='teacher1', password='pass12345')
        self.url = reverse('task_quick_update', args=[self.task.pk])

    def xhr_post(self, data):
        return self.client.post(
            self.url, data, HTTP_X_REQUESTED_WITH='XMLHttpRequest')

    def test_update_grade_and_answer(self):
        response = self.xhr_post({'grade_level': '7', 'answer_latex': ' 42 '})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['ok'])
        self.task.refresh_from_db()
        self.assertEqual(self.task.grade_level, 7)
        self.assertEqual(self.task.answer_latex, '42')
        # Сброс класса пустым значением
        self.xhr_post({'grade_level': ''})
        self.task.refresh_from_db()
        self.assertIsNone(self.task.grade_level)

    def test_partial_save_does_not_touch_other_fields(self):
        # Параллельные autosave-формы: запрос с одними звёздами не должен
        # затирать ответ, изменённый соседним запросом (update_fields)
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        self.task.answer_latex = 'старый'
        self.task.save()
        with CaptureQueriesContext(connection) as ctx:
            self.xhr_post({'stars': '2'})
        updates = [q['sql'] for q in ctx.captured_queries
                   if q['sql'].startswith('UPDATE')]
        self.assertEqual(len(updates), 1)
        self.assertIn('stars', updates[0])
        self.assertNotIn('answer_latex', updates[0])
        # text_plain пересчитывается и при частичном сохранении условия
        self.xhr_post({'text_latex': 'Новое $x$'})
        self.task.refresh_from_db()
        self.assertEqual(self.task.text_plain, 'Новое x')

    def test_update_card_fields(self):
        # Поля карточки задачи: звёзды, условие, решение, темы, теги
        response = self.xhr_post({
            'stars': '2', 'text_latex': ' Новое условие ',
            'solution_latex': 'Решение.',
        })
        self.assertTrue(response.json()['ok'])
        self.task.refresh_from_db()
        self.assertEqual(self.task.stars, 2)
        self.assertEqual(self.task.text_latex, 'Новое условие')
        self.assertEqual(self.task.solution_latex, 'Решение.')
        # Пустое условие отклоняется
        response = self.xhr_post({'text_latex': '   '})
        self.assertEqual(response.status_code, 400)

        topic = Topic.objects.create(name='Дроби')
        self.xhr_post({'topics_submitted': '1', 'topics': [str(topic.pk)]})
        self.assertEqual(list(self.task.topics.all()), [topic])
        self.xhr_post({'tags_submitted': '1', 'tags': 'ОГЭ, устный счёт'})
        self.assertEqual(
            sorted(t.name for t in self.task.tags.all()),
            ['ОГЭ', 'устный счёт'])
        # Слишком длинный тег — контролируемая ошибка, а не 500 из БД
        response = self.xhr_post(
            {'tags_submitted': '1', 'tags': 'х' * 65})
        self.assertEqual(response.status_code, 400)
        # Существующий тег с запятой в имени не теряется при сохранении
        legacy = Tag.objects.create(name='алгебра, геометрия')
        self.task.tags.add(legacy)
        self.xhr_post({'tags_submitted': '1', 'tags': 'ОГЭ'})
        self.assertEqual(
            sorted(t.name for t in self.task.tags.all()),
            ['ОГЭ', 'алгебра, геометрия'])
        # Обычная (не fetch) отправка — редирект на карточку
        response = self.client.post(
            self.url, {'topics_submitted': '1'})
        self.assertRedirects(
            response, reverse('task_detail', args=[self.task.pk]))
        self.assertEqual(self.task.topics.count(), 0)

    def test_subitem_add_update_delete(self):
        add_url = reverse('task_subitem_add', args=[self.task.pk])
        response = self.client.post(
            add_url, {'text_latex': '$1+1$;', 'answer_latex': '2',
                      'solution_latex': 'Очевидно'})
        self.assertRedirects(
            response, reverse('task_detail', args=[self.task.pk]))
        subitem = self.task.subitems.get()
        self.assertEqual(subitem.answer_latex, '2')
        self.assertEqual(subitem.solution_latex, 'Очевидно')

        upd_url = reverse(
            'task_subitem_update', args=[self.task.pk, subitem.pk])
        response = self.client.post(
            upd_url, {'text_latex': '$2+2$;', 'answer_latex': '4',
                      'solution_latex': 'Считаем столбиком'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertTrue(response.json()['ok'])
        subitem.refresh_from_db()
        self.assertEqual(subitem.text_latex, '$2+2$;')
        self.assertEqual(subitem.solution_latex, 'Считаем столбиком')

        response = self.client.post(upd_url, {'delete': '1'})
        self.assertRedirects(
            response, reverse('task_detail', args=[self.task.pk]))
        self.assertEqual(self.task.subitems.count(), 0)

    def test_task_page_fields_depend_on_subitems(self):
        detail_url = reverse('task_detail', args=[self.task.pk])
        # Без подпунктов — предпросмотр и общие поля ответа/решения
        response = self.client.get(detail_url)
        self.assertContains(response, 'name="answer_latex"')
        self.assertContains(response, 'qa_answer')
        self.assertContains(response, 'править ответ')
        # С подпунктами общих полей нет даже при непустом legacy-ответе;
        # у каждого подпункта — предпросмотр и свои поля ответа/решения
        self.task.subitems.create(
            order=10, text_latex='$1+1$', answer_latex='2',
            solution_latex='Сложение')
        self.task.answer_latex = 'legacy'
        self.task.save()
        response = self.client.get(detail_url)
        self.assertContains(response, 'name="solution_latex"')
        self.assertContains(response, 'править подпункт')
        self.assertContains(response, '>Ответ<')
        self.assertContains(response, 'icon-btn')
        self.assertContains(response, 'class="btn">Добавить')
        self.assertContains(response, 'data-neuro="task-detail"')
        self.assertContains(response, 'data-task-id="%s"' % self.task.pk)
        self.assertContains(response, 'Добавить AI-решение')
        self.assertContains(response, 'js/neuro.js')
        self.assertNotContains(response, 'qa_answer')
        self.assertNotContains(response, 'устаревшие')
        self.assertNotContains(response, 'legacy')

    def test_invalid_grade_rejected(self):
        response = self.client.post(self.url, {'grade_level': '99'})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()['ok'])

    def test_source_create_update_delete(self):
        from .models import TaskSource
        # Создание первого источника
        self.client.post(
            self.url, {'source': str(self.source.pk), 'number': '101'})
        ref = TaskSource.objects.get(task=self.task)
        self.assertEqual(ref.number, '101')
        # Обновление номера
        self.client.post(
            self.url, {'source': str(self.source.pk), 'number': '102'})
        ref.refresh_from_db()
        self.assertEqual(ref.number, '102')
        # Пустой источник — удаление привязки
        self.client.post(self.url, {'source': '', 'number': ''})
        self.assertFalse(TaskSource.objects.filter(task=self.task).exists())

    def test_get_not_allowed(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 405)

    def test_student_forbidden(self):
        make_student(self.teacher)
        self.client.login(username='student1', password='pass12345')
        response = self.client.post(self.url, {'grade_level': '7'})
        self.assertEqual(response.status_code, 403)


class TemplateHygieneTests(TestCase):
    """Стражи от утечки комментариев шаблонов в HTML."""

    def test_hash_comments_are_single_line(self):
        """{# … #} в Django строго однострочный: перенос строки внутри
        превращает комментарий в видимый текст страницы."""
        templates_dir = settings.BASE_DIR / 'templates'
        problems = []
        for path in sorted(templates_dir.rglob('*.html')):
            text = path.read_text(encoding='utf-8')
            for match in re.finditer(r'\{#', text):
                end = text.find('#}', match.start())
                if end == -1 or '\n' in text[match.start():end]:
                    line = text.count('\n', 0, match.start()) + 1
                    problems.append(f'{path.relative_to(templates_dir)}:{line}')
        self.assertEqual(problems, [],
                         'Многострочные/незакрытые {# #} утекут в HTML')

    def test_task_form_has_no_leaked_comment(self):
        make_teacher()
        self.client.login(username='teacher1', password='pass12345')
        response = self.client.get(reverse('task_create'))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, '{#')
        self.assertNotContains(response, 'Тумблер')


class TaskImagePdfTests(TestCase):
    """PDF-иллюстрации: хранение без сжатия и корректная отдача файла."""

    PDF_BYTES = (b'%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\n'
                 b'trailer<</Root 1 0 R>>\n%%EOF\n')

    def test_pdf_saved_without_compression(self):
        import tempfile

        from django.core.files.base import ContentFile
        from django.test import override_settings

        with tempfile.TemporaryDirectory() as tmp:
            with override_settings(MEDIA_ROOT=tmp):
                task = Task.objects.create(text_latex='С PDF-рисунком')
                image = task.images.create(order=10)
                image.image.save('wave11-pic1.pdf',
                                 ContentFile(self.PDF_BYTES), save=True)
                self.assertTrue(image.is_pdf)
                self.assertTrue(image.filename.endswith('.pdf'))
                # Содержимое не тронуто сжатием
                with image.image.open('rb') as f:
                    self.assertEqual(f.read(), self.PDF_BYTES)

                make_teacher()
                self.client.login(username='teacher1', password='pass12345')
                response = self.client.get(
                    reverse('task_image_file', args=[image.pk]))
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers['Content-Type'],
                                 'application/pdf')
                # PDF встраивается в страницы через <object> — DENY нельзя
                self.assertEqual(response.headers['X-Frame-Options'],
                                 'SAMEORIGIN')
                response.close()

    def test_pdf_in_latex_output(self):
        from worksheets.latex import task_to_tex
        from worksheets.models import Worksheet, WorksheetItem

        teacher = make_teacher()
        task = Task.objects.create(text_latex='Волна \\taskpic{1}')
        task.images.create(image='task_images/wave11-pic1.pdf', order=10)
        worksheet = Worksheet.objects.create(title='Л', owner=teacher)
        item = WorksheetItem.objects.create(
            worksheet=worksheet, task=task, order=10)
        self.assertIn('\\taskpic{wave11-pic1.pdf}', task_to_tex(item))


class LocalVariantTests(TestCase):
    """Развилка «сохранить в базе / только в листке» при правке задачи."""

    def setUp(self):
        from worksheets.models import Worksheet, WorksheetItem
        self.teacher = make_teacher()
        self.task = Task.objects.create(
            text_latex='Оригинал', answer_latex='1', stars=1,
            created_by=self.teacher)
        self.worksheet = Worksheet.objects.create(
            title='Листок', owner=self.teacher)
        self.item = WorksheetItem.objects.create(
            worksheet=self.worksheet, task=self.task, order=10)
        self.client.login(username='teacher1', password='pass12345')

    def edit_url(self):
        return (reverse('task_edit', args=[self.task.pk])
                + f'?worksheet={self.worksheet.pk}&item={self.item.pk}')

    def post_data(self, **extra):
        data = {
            'text_latex': 'Изменённый текст', 'columns': 0,
            'answer_latex': '1', 'solution_latex': '',
            'stars': 1, 'answer_type': 'text',
            **formset_management('source_refs'),
            **formset_management('subitems'),
            **formset_management('images'),
        }
        data.update(extra)
        return data

    def test_save_to_base(self):
        response = self.client.post(self.edit_url(), self.post_data(save=''))
        self.assertRedirects(
            response, reverse('worksheet_detail', args=[self.worksheet.pk]))
        self.task.refresh_from_db()
        self.assertEqual(self.task.text_latex, 'Изменённый текст')
        self.item.refresh_from_db()
        self.assertEqual(self.item.task_id, self.task.pk)

    def test_save_local_creates_variant(self):
        response = self.client.post(
            self.edit_url(), self.post_data(save_local=''))
        self.assertRedirects(
            response, reverse('worksheet_detail', args=[self.worksheet.pk]))
        # Оригинал не изменился
        self.task.refresh_from_db()
        self.assertEqual(self.task.text_latex, 'Оригинал')
        # Элемент листка перенацелен на копию
        self.item.refresh_from_db()
        variant = self.item.task
        self.assertNotEqual(variant.pk, self.task.pk)
        self.assertEqual(variant.variant_of_id, self.task.pk)
        self.assertEqual(variant.text_latex, 'Изменённый текст')

    def test_save_local_keeps_subitem_solutions(self):
        sub = self.task.subitems.create(
            order=10, text_latex='$1+1$', answer_latex='2',
            solution_latex='Сложение')
        response = self.client.post(self.edit_url(), self.post_data(
            save_local='',
            **formset_management('subitems', total=1, initial=1),
            **{
                'subitems-0-id': sub.pk,
                'subitems-0-order': 10,
                'subitems-0-text_latex': '$1+1$',
                'subitems-0-answer_latex': '2',
                'subitems-0-solution_latex': 'Сложение',
            }))
        self.assertEqual(response.status_code, 302)
        self.item.refresh_from_db()
        variant_sub = self.item.task.subitems.get()
        self.assertEqual(variant_sub.solution_latex, 'Сложение')
        self.assertEqual(variant_sub.answer_latex, '2')
        # Оригинал не тронут
        sub.refresh_from_db()
        self.assertEqual(sub.solution_latex, 'Сложение')
