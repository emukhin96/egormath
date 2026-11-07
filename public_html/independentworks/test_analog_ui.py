"""Аналоги учителю (ROADMAP 11.2026, п. 2б): блок на карточке, указатель и
быстрые действия в конструкторе, значок в каталоге, ручная семья редактора.

Видны только задачи из ``catalog_tasks``: чужая личная задача не
показывается и не считается; отвязанное редактором не возвращает
``sync_families``.
"""
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from accounts.models import Profile
from problems.models import Source, Task, TaskSource
from problems.tests import make_invited_teacher, make_teacher
from worksheets.models import Worksheet
from .analog_lists import analog_ids, link, unlink
from .analogs import sync_families
from .models import Family, FamilyExclusion, FamilyMember


def family(*tasks, key=None):
    fam = Family.objects.create(key=key or f'test:{"-".join(str(t.pk) for t in tasks)}', title='Тест')
    for task in tasks:
        FamilyMember.objects.create(family=fam, task=task, origin='source')
    return fam


class AnalogBase(TestCase):
    def setUp(self):
        self.editor = make_teacher('editor')
        self.guest = make_invited_teacher('guest')
        self.other = make_invited_teacher('guest2')
        self.source = Source.objects.create(title='Зив, 9 класс')
        self.a = self.shared('Задача А', 'sr/03/v1/2')
        self.b = self.shared('Задача Б', 'sr/03/v2/2')
        # Чужая личная задача в той же семье — не видна и не считается
        self.foreign = Task.new_for(self.other, text_latex='Чужая личная')
        self.family = family(self.a, self.b, self.foreign)

    def shared(self, text, locator=''):
        task = Task.objects.create(text_latex=text, created_by=self.editor, is_shared=True, stars=1)
        if locator:
            TaskSource.objects.create(source=self.source, task=task, locator=locator, number=locator)
        return task


class AnalogIdsTests(AnalogBase):
    def test_guest_sees_only_visible_analogs(self):
        self.assertEqual(analog_ids(self.guest, [self.a]), {self.a.pk: [self.b.pk]})

    def test_editor_foreign_tasks_follow_toggle(self):
        self.assertEqual(analog_ids(self.editor, [self.a])[self.a.pk], [self.b.pk])
        Profile.objects.filter(user=self.editor).update(show_foreign_tasks=True)
        self.editor.refresh_from_db()
        self.assertEqual(analog_ids(self.editor, [self.a])[self.a.pk], [self.b.pk, self.foreign.pk])

    def test_local_copy_uses_original_families(self):
        copy = self.a.make_variant(self.guest)
        # Сама копия и её оригинал — не аналоги; чужие локальные копии в
        # списке не показываются.
        self.assertEqual(analog_ids(self.guest, [copy]), {copy.pk: [self.b.pk]})
        self.assertNotIn(copy.pk, analog_ids(self.guest, [self.b])[self.b.pk])

    def test_no_family_no_entry(self):
        lonely = self.shared('Одна')
        self.assertEqual(analog_ids(self.guest, [lonely]), {})


class CardTests(AnalogBase):
    def test_card_block_lists_analogs_with_actions(self):
        self.client.force_login(self.guest)
        html = self.client.get(reverse('task_detail', args=[self.a.pk])).content.decode()
        self.assertIn('id="analogs"', html)
        self.assertIn('Задача Б', html)
        self.assertIn('Зив, 9 класс', html)
        self.assertIn('data-task-actions', html)
        self.assertNotIn('Чужая личная', html)
        # Приглашённому — без редакторских действий
        self.assertNotIn(reverse('task_analog_unlink', args=[self.a.pk]), html)
        self.assertNotIn(reverse('task_analog_link', args=[self.a.pk]), html)

    def test_empty_block_hidden_editor_gets_link_form(self):
        lonely = self.shared('Одна')
        self.client.force_login(self.guest)
        html = self.client.get(reverse('task_detail', args=[lonely.pk])).content.decode()
        self.assertNotIn('id="analogs"', html)
        self.client.force_login(self.editor)
        html = self.client.get(reverse('task_detail', args=[lonely.pk])).content.decode()
        self.assertIn(reverse('task_analog_link', args=[lonely.pk]), html)
        self.assertNotIn('analog-row', html)


class CatalogTests(AnalogBase):
    def test_badge_and_constant_queries(self):
        self.client.force_login(self.guest)
        url = reverse('task_list')
        html = self.client.get(url).content.decode()
        self.assertIn(f'href="{reverse("task_detail", args=[self.a.pk])}#analogs"', html)
        self.assertIn('1 аналог<', html)
        with CaptureQueriesContext(connection) as before:
            self.client.get(url)
        for i in range(4):
            family(self.shared(f'Ещё {i}'), self.shared(f'Пара {i}'))
        with CaptureQueriesContext(connection) as after:
            html = self.client.get(url).content.decode()
        self.assertEqual(html.count('badge-analogs'), 10)
        self.assertEqual(len(after), len(before))


class BuilderTests(AnalogBase):
    def setUp(self):
        super().setUp()
        self.sheet = Worksheet.objects.create(owner=self.guest, title='Листок')
        self.first = self.sheet.items.create(task=self.shared('Первая'), order=10)
        self.row = self.sheet.items.create(task=self.a, order=20, stars_override=None)
        self.last = self.sheet.items.create(task=self.shared('Последняя'), order=30)
        self.client.force_login(self.guest)

    def url(self, name):
        return reverse(name, args=[self.sheet.pk, self.row.pk])

    def test_counter_and_fragment(self):
        html = self.client.get(reverse('worksheet_detail', args=[self.sheet.pk])).content.decode()
        self.assertIn(self.url('worksheet_item_analogs'), html)
        self.assertIn('1 аналог<', html)
        fragment = self.client.get(self.url('worksheet_item_analogs')).content.decode()
        self.assertIn('Задача Б', fragment)
        self.assertIn(self.url('worksheet_item_analog_replace'), fragment)
        self.assertIn(self.url('worksheet_item_analog_after'), fragment)
        self.assertIn('data-task-actions', fragment)
        self.assertNotIn('Чужая личная', fragment)

    def test_builder_queries_do_not_grow_with_analogs(self):
        url = reverse('worksheet_detail', args=[self.sheet.pk])
        for i in range(3):
            task = self.shared(f'Строка {i}')
            family(task, self.shared(f'Аналог {i}'))
            self.sheet.items.create(task=task, order=40 + i)
        self.client.get(url)
        with CaptureQueriesContext(connection) as with_analogs:
            html = self.client.get(url).content.decode()
        self.assertEqual(html.count('data-analogs-toggle'), 4)
        # Те же строки без семей: счётчики — один лишний запрос на листок,
        # а не на строку.
        FamilyMember.objects.all().delete()
        self.client.get(url)
        with CaptureQueriesContext(connection) as without:
            html = self.client.get(url).content.decode()
        self.assertNotIn('data-analogs-toggle', html)
        self.assertLessEqual(len(with_analogs) - len(without), 1)

    def test_replace_keeps_position_and_stars(self):
        self.b.stars = 3
        self.b.save()
        response = self.client.post(self.url('worksheet_item_analog_replace'), {'task': self.b.pk}, follow=True)
        self.row.refresh_from_db()
        self.assertEqual(self.row.task, self.b)
        self.assertEqual(self.row.order, 20)
        self.assertEqual(self.row.effective_stars, 1)
        self.assertTrue(self.row.all_subitems)
        self.assertContains(response, f'заменена в листке на #{self.b.pk}')
        self.assertEqual([i.task for i in self.sheet.ordered_items()],
                         [self.first.task, self.b, self.last.task])

    def test_add_after(self):
        self.client.post(self.url('worksheet_item_analog_after'), {'task': self.b.pk})
        self.assertEqual([i.task for i in self.sheet.ordered_items()],
                         [self.first.task, self.a, self.b, self.last.task])

    def test_rejects_non_analog_and_duplicates(self):
        stranger = self.shared('Не аналог')
        self.assertEqual(self.client.post(self.url('worksheet_item_analog_after'),
                                          {'task': stranger.pk}).status_code, 404)
        self.assertEqual(self.client.post(self.url('worksheet_item_analog_replace'),
                                          {'task': self.foreign.pk}).status_code, 404)
        self.sheet.items.create(task=self.b, order=40)
        self.client.post(self.url('worksheet_item_analog_replace'), {'task': self.b.pk})
        self.row.refresh_from_db()
        self.assertEqual(self.row.task, self.a)

    def test_foreign_worksheet_is_404(self):
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(self.url('worksheet_item_analogs')).status_code, 404)
        self.assertEqual(self.client.post(self.url('worksheet_item_analog_replace'),
                                          {'task': self.b.pk}).status_code, 404)


class EditorFamilyTests(AnalogBase):
    def test_unlink_survives_sync(self):
        # Семья по локаторам Зива (пара v1–v2 одной работы)
        Family.objects.all().delete()
        sync_families()
        self.assertEqual(analog_ids(self.editor, [self.a])[self.a.pk], [self.b.pk])
        self.client.force_login(self.editor)
        self.client.post(reverse('task_analog_unlink', args=[self.a.pk]), {'task': self.b.pk})
        self.assertEqual(analog_ids(self.editor, [self.a]), {})
        self.assertTrue(FamilyExclusion.objects.filter(task=self.b).exists())
        report = sync_families(report=True)
        self.assertEqual(report['members_added'], 0)
        self.assertEqual(analog_ids(self.editor, [self.a]), {})

    def test_link_creates_manual_family_and_lifts_exclusion(self):
        one, two = self.shared('Один'), self.shared('Два')
        self.client.force_login(self.editor)
        response = self.client.post(reverse('task_analog_link', args=[one.pk]), {'target': f'№{two.pk}'})
        self.assertRedirects(response, reverse('task_detail', args=[one.pk]) + '#analogs',
                             fetch_redirect_response=False)
        fam = Family.objects.get(familymember__task=one)
        self.assertEqual(fam.origin, 'manual')
        self.assertEqual(set(fam.familymember_set.values_list('origin', flat=True)), {'manual'})
        self.assertEqual(analog_ids(self.editor, [one])[one.pk], [two.pk])
        unlink(self.a, self.b, self.editor)
        link(self.a, self.b, self.editor)
        self.assertFalse(FamilyExclusion.objects.filter(task=self.b).exists())
        self.assertEqual(analog_ids(self.editor, [self.a])[self.a.pk], [self.b.pk])

    def test_link_joins_existing_family(self):
        newcomer = self.shared('Новая')
        link(newcomer, self.a, self.editor)
        self.assertEqual(analog_ids(self.guest, [newcomer])[newcomer.pk], [self.a.pk, self.b.pk])

    def test_guest_cannot_edit_families(self):
        self.client.force_login(self.guest)
        self.assertEqual(self.client.post(reverse('task_analog_unlink', args=[self.a.pk]),
                                          {'task': self.b.pk}).status_code, 403)
        self.assertEqual(self.client.post(reverse('task_analog_link', args=[self.a.pk]),
                                          {'target': self.b.pk}).status_code, 403)
        self.assertEqual(analog_ids(self.guest, [self.a])[self.a.pk], [self.b.pk])

    def test_link_rejects_unknown_and_same_task(self):
        self.client.force_login(self.editor)
        self.client.post(reverse('task_analog_link', args=[self.a.pk]), {'target': '999999'})
        copy = self.a.make_variant(self.guest)
        self.client.post(reverse('task_analog_link', args=[self.a.pk]), {'target': copy.pk})
        self.assertEqual(FamilyMember.objects.count(), 3)
