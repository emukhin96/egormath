"""Фасет «Содержание» (CONTENT) в каталоге и поиске задач: фильтр
``?content=КОД`` (группа раскрывается в значения), счётчики панели и выбор
в форме поиска — каталог «Задачи» и подбор в конструкторе листка."""
from django.test import TestCase
from django.urls import reverse

from worksheets.models import Worksheet

from . import content_tags as ct
from .catalog_counts import catalog_content, content_counts
from .models import Task
from .rubricator import content_choices, content_value_ids, seed_content_facet
from .test_permissions import Roles, shared_task
from .views import filter_tasks


class ContentCatalogTests(Roles, TestCase):
    def setUp(self):
        self.make_users()
        seed_content_facet()
        self.abs_eq = shared_task(self.editor, '$|x-1|=2$')
        self.both = shared_task(self.editor, '$|x|<1$ и $|x|=2$')
        self.trap = shared_task(self.editor, 'Трапеция')
        self.plain = shared_task(self.editor, 'Без меток')
        ct.apply_labels({self.abs_eq.pk: ['ABS_EQ'],
                         self.both.pk: ['ABS_EQ', 'ABS_INEQ'],
                         self.trap.pk: ['QUAD_TRAPEZOID']})

    def found(self, **params):
        return set(filter_tasks(params, self.editor).values_list('pk', flat=True))

    def test_filter_by_value_and_group(self):
        self.assertEqual(self.found(content='ABS_INEQ'), {self.both.pk})
        self.assertEqual(self.found(content='ABS'), {self.abs_eq.pk, self.both.pk})
        self.assertEqual(self.found(content='НЕТ_ТАКОГО'), set())
        self.assertEqual(len(self.found()), 4)

    def test_group_code_expands_to_values(self):
        ids = content_value_ids(['ABS'])
        self.assertEqual(len(ids), 5)
        self.assertNotIn(None, ids)

    def test_counts_group_once_per_task(self):
        counts = content_counts(self.editor)
        groups = {g['code']: g for g in content_choices()}
        self.assertEqual(counts[groups['ABS']['id']], 2)       # не 3
        self.assertEqual(counts[groups['QUAD']['id']], 1)
        rows = catalog_content({'content': 'ABS_EQ'}, self.editor)
        self.assertEqual([g['code'] for g in rows], ['ABS', 'QUAD'])
        abs_group = rows[0]
        self.assertEqual({v['code']: v['count'] for v in abs_group['values']},
                         {'ABS_EQ': 2, 'ABS_INEQ': 1})
        self.assertTrue(next(v for v in abs_group['values']
                             if v['code'] == 'ABS_EQ')['is_current'])
        self.assertEqual(rows[1]['values'], [])   # чужая группа свёрнута

    def test_catalog_page_sidebar_and_select(self):
        self.client.force_login(self.editor)
        response = self.client.get(reverse('task_list'), {'content': 'ABS'})
        self.assertContains(response, 'Содержание')
        self.assertContains(response, 'href="?content=ABS_INEQ"')
        self.assertContains(response, 'name="content"')
        self.assertContains(response, '<option value="ABS" selected>')
        page_ids = {t.pk for t in response.context['page']}
        self.assertEqual(page_ids, {self.abs_eq.pk, self.both.pk})

    def test_builder_picker_has_select_and_filters(self):
        worksheet = Worksheet.objects.create(owner=self.editor, title='Листок')
        self.client.force_login(self.editor)
        response = self.client.get(reverse('worksheet_detail', args=[worksheet.pk]),
                                   {'q': '', 'content': 'QUAD_TRAPEZOID'})
        self.assertContains(response, 'id="f_content_card"')
        self.assertContains(response, '<option value="QUAD_TRAPEZOID" selected>')
        # Подбор запускается одним выбором «Содержания», без слов поиска
        self.assertEqual([t.pk for t in response.context['found_tasks']],
                         [self.trap.pk])

    def test_no_section_without_labels(self):
        Task.facet_values.through.objects.all().delete()
        self.assertEqual(catalog_content({}, self.editor), [])


class ContentSelectWithoutFacetTests(Roles, TestCase):
    """Без словаря CONTENT (сид не запускали) в форме поиска нет ни поля,
    ни подписи «Содержание» — подпись не ссылается на несуществующий id."""

    def test_card_form_has_no_orphan_label(self):
        self.make_users()
        worksheet = Worksheet.objects.create(owner=self.editor, title='Листок')
        self.client.force_login(self.editor)
        response = self.client.get(reverse('worksheet_detail', args=[worksheet.pk]))
        self.assertNotContains(response, 'f_content_card')
        self.assertNotContains(response, '>Содержание</label>')
