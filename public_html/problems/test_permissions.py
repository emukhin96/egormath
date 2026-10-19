"""Политика доступа к общей базе (accounts/permissions.py): матрица прав по
точкам записи, видимость личных задач и локальные правки приглашённого.

Роли: суперпользователь без профиля, учитель-редактор базы
(``Profile.base_editor``), приглашённый учитель на своей и на общей задаче,
ученик. Для суперпользователя и редактора ничего не меняется.
"""
import json
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.permissions import (can_edit_task, catalog_tasks, editable_tasks,
                                  is_base_editor, visible_tasks)
from worksheets.models import Worksheet, WorksheetItem
from .models import Task, TaskSubitem
from .tests import formset_management, make_invited_teacher, make_student, make_teacher

FORM_TAIL = {
    'columns': 0, 'stars': 0, 'answer_latex': '', 'solution_latex': '',
    **formset_management('source_refs', total=0),
    **formset_management('subitems', total=0),
    **formset_management('images', total=0),
}


def shared_task(author, text='Общая задача'):
    """Задача общей базы (как все существующие после миграции)."""
    task = Task.objects.create(text_latex=text, created_by=author, is_shared=True)
    TaskSubitem.objects.create(task=task, order=10, text_latex='а)')
    return task


class Roles:
    """Пользователи матрицы; создаются в setUp каждого теста."""

    def make_users(self):
        self.superuser = get_user_model().objects.create_superuser('root', password='x')
        self.editor = make_teacher('editor')
        self.guest = make_invited_teacher('guest')
        self.other_guest = make_invited_teacher('guest2')
        self.student = make_student(self.editor)


class PermissionHelpersTests(Roles, TestCase):
    def setUp(self):
        self.make_users()
        self.shared = shared_task(self.editor)
        self.own = Task.new_for(self.guest, text_latex='Личная задача гостя')

    def test_is_base_editor_by_role(self):
        self.assertTrue(is_base_editor(self.superuser))
        self.assertTrue(is_base_editor(self.editor))
        self.assertFalse(is_base_editor(self.guest))
        self.assertFalse(is_base_editor(self.student))
        self.assertFalse(is_base_editor(AnonymousUser()))
        self.assertFalse(is_base_editor(None))

    def test_can_edit_task_matrix(self):
        self.assertTrue(can_edit_task(self.superuser, self.shared))
        self.assertTrue(can_edit_task(self.editor, self.shared))
        self.assertTrue(can_edit_task(self.editor, self.own))
        self.assertFalse(can_edit_task(self.guest, self.shared))
        self.assertTrue(can_edit_task(self.guest, self.own))
        self.assertFalse(can_edit_task(self.other_guest, self.own))
        # Личная задача, принятая в базу, дальше правится только редакторами
        self.own.is_shared = True
        self.assertFalse(can_edit_task(self.guest, self.own))

    def test_visible_catalog_and_editable_querysets(self):
        local = self.shared.make_variant(self.guest)
        self.assertEqual(set(visible_tasks(self.guest)), {self.shared, self.own, local})
        self.assertEqual(set(catalog_tasks(self.guest)), {self.shared, self.own})
        self.assertEqual(set(visible_tasks(self.other_guest)), {self.shared})
        self.assertEqual(set(visible_tasks(self.editor)), {self.shared, self.own, local})
        self.assertEqual(set(editable_tasks(self.guest)), {self.own, local})
        self.assertEqual(set(editable_tasks(self.superuser)), {self.shared, self.own, local})

    def test_new_for_and_variants_follow_author(self):
        self.assertTrue(Task.new_for(self.editor, text_latex='Редактора').is_shared)
        self.assertTrue(Task.new_for(self.superuser, text_latex='Егора').is_shared)
        self.assertFalse(self.own.is_shared)
        self.assertEqual(self.own.created_by, self.guest)
        copy = self.shared.make_variant(self.guest)
        self.assertEqual((copy.created_by, copy.is_shared, copy.variant_of), (self.guest, False, self.shared))
        self.assertTrue(can_edit_task(self.guest, copy))
        standalone = self.shared.make_variant(self.editor, standalone=True)
        self.assertTrue(standalone.is_shared)
        # Локальная копия — не в общей базе, чья бы она ни была
        self.assertFalse(self.shared.make_variant(self.editor).is_shared)
        self.assertFalse(self.shared.make_variant().is_shared)
        # Самостоятельная копия без автора наследует флаг оригинала
        self.assertTrue(self.shared.make_variant(standalone=True).is_shared)
        # Автор подписан отдельно от того, кто решает про общую базу
        signed = Task.new_for(self.superuser, author=self.guest, text_latex='Из партии гостя')
        self.assertEqual((signed.created_by, signed.is_shared), (self.guest, True))

    def test_author_edits_own_local_copy_even_if_flagged_shared(self):
        """Копия, помеченная общей по ошибке (данные до разделения прав),
        всё равно правится автором: она живёт только в его листке."""
        copy = self.shared.make_variant(self.guest)
        Task.objects.filter(pk=copy.pk).update(is_shared=True)
        copy.refresh_from_db()
        self.assertTrue(can_edit_task(self.guest, copy))
        self.assertFalse(can_edit_task(self.other_guest, copy))

    def test_textbook_batch_of_guest_committed_by_superuser_is_shared(self):
        from .models import TextbookTaskDraft, Topic
        from .test_textbook_import import bundle
        from .textbook_import import commit_batch, create_batch_from_bundle
        batch = create_batch_from_bundle(
            bundle(), user=self.guest, title='Партия гостя',
            source_title='Тестовый задачник', source_author='Автор')
        batch.drafts.update(status=TextbookTaskDraft.STATUS_APPROVED,
                            topic=Topic.objects.create(name='Тема партии'))
        commit_batch(batch, user=self.superuser)
        task = Task.objects.get(text_latex=bundle()['tasks'][0]['text_latex'])
        self.assertEqual((task.created_by, task.is_shared), (self.guest, True))


class WriteEndpointMatrixTests(Roles, TestCase):
    """Каждая точка записи из таблицы 4.2 плана × роль → статус."""

    def setUp(self):
        self.make_users()
        self.shared = shared_task(self.editor)
        self.own = Task.new_for(self.guest, text_latex='Личная задача гостя')
        TaskSubitem.objects.create(task=self.own, order=10, text_latex='а)')

    def login(self, user):
        self.client.logout()
        self.client.force_login(user)

    def xhr_post(self, url, data):
        return self.client.post(url, data, HTTP_X_REQUESTED_WITH='XMLHttpRequest')

    def manage(self, user, task, text):
        self.login(user)
        return self.client.post(reverse('task_manage', args=[task.pk]),
                                {'block': 'condition', 'text_latex': text})

    def test_manage_block_save(self):
        for user, expected in ((self.superuser, 200), (self.editor, 200)):
            self.assertEqual(self.manage(user, self.shared, 'Правка').status_code, expected, user)
        self.assertEqual(self.manage(self.guest, self.own, 'Своя').status_code, 200)
        response = self.manage(self.guest, self.shared, 'Чужая')
        self.assertEqual(response.status_code, 403)
        self.assertFalse(response.json()['ok'])
        self.assertIn('Общая задача', response.json()['message'])
        self.shared.refresh_from_db()
        self.assertEqual(self.shared.text_latex, 'Правка')
        self.assertEqual(self.manage(self.student, self.shared, 'Ученик').status_code, 403)
        # Чужая личная задача для гостя не существует
        self.assertEqual(self.manage(self.other_guest, self.own, 'Чужая личная').status_code, 404)

    def test_manage_masks_from_independent_work_picker(self):
        from independentworks.models import Work, Position, Candidate
        with override_settings(INDEPENDENT_WORKS_ENABLED=True):
            for user, task, expected in ((self.editor, self.shared, 200),
                                         (self.guest, self.own, 200),
                                         (self.guest, self.shared, 403)):
                work = Work.objects.create(owner=user, title='СР')
                position = Position.objects.create(work=work)
                Candidate.objects.create(position=position, task=task)
                self.login(user)
                sub = task.subitems.get()
                response = self.client.post(
                    reverse('independentworks:picker_masks', args=[position.pk, task.pk]),
                    {'block': 'masks', 'masks': json.dumps([{'id': sub.pk, 'mask': '{{number: 1}}'}])})
                self.assertEqual(response.status_code, expected, (user, task))
        self.assertEqual(self.shared.subitems.get().answer_mask, '{{number: 1}}')

    def test_quick_update(self):
        url = reverse('task_quick_update', args=[self.shared.pk])
        for user, expected in ((self.superuser, 200), (self.editor, 200), (self.guest, 403), (self.student, 403)):
            self.login(user)
            self.assertEqual(self.xhr_post(url, {'stars': '2'}).status_code, expected, user)
        self.login(self.guest)
        self.assertEqual(self.xhr_post(reverse('task_quick_update', args=[self.own.pk]), {'stars': '3'}).status_code, 200)
        self.own.refresh_from_db()
        self.shared.refresh_from_db()
        self.assertEqual((self.own.stars, self.shared.stars), (3, 2))

    def test_subitem_update_and_add(self):
        sub = self.shared.subitems.get()
        own_sub = self.own.subitems.get()
        self.login(self.guest)
        response = self.xhr_post(reverse('task_subitem_update', args=[self.shared.pk, sub.pk]), {'text_latex': 'б)'})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.client.post(reverse('task_subitem_add', args=[self.shared.pk]), {'text_latex': 'в)'}).status_code, 403)
        self.assertEqual(self.shared.subitems.count(), 1)
        self.assertEqual(self.xhr_post(reverse('task_subitem_update', args=[self.own.pk, own_sub.pk]), {'text_latex': 'б)'}).status_code, 200)
        self.assertEqual(self.client.post(reverse('task_subitem_add', args=[self.own.pk]), {'text_latex': 'в)'}).status_code, 302)
        self.assertEqual(self.own.subitems.count(), 2)
        self.login(self.editor)
        self.assertEqual(self.xhr_post(reverse('task_subitem_update', args=[self.shared.pk, sub.pk]), {'text_latex': 'б)'}).status_code, 200)
        self.assertEqual(self.client.post(reverse('task_subitem_add', args=[self.shared.pk]), {'text_latex': 'в)'}).status_code, 302)
        self.login(self.student)
        self.assertEqual(self.xhr_post(reverse('task_subitem_update', args=[self.shared.pk, sub.pk]), {'text_latex': 'г)'}).status_code, 403)

    def test_bulk_update_touches_only_editable(self):
        self.login(self.guest)
        response = self.client.post(reverse('task_bulk_update'),
                                    {'ids': [self.shared.pk, self.own.pk], 'stars': '3'})
        self.assertEqual(response.status_code, 302)
        self.shared.refresh_from_db()
        self.own.refresh_from_db()
        self.assertEqual((self.shared.stars, self.own.stars), (0, 3))
        self.client.post(reverse('task_bulk_update'), {'ids': [self.shared.pk, self.own.pk], 'delete': '1'})
        self.assertTrue(Task.objects.filter(pk=self.shared.pk).exists())
        self.assertFalse(Task.objects.filter(pk=self.own.pk).exists())
        self.login(self.editor)
        self.client.post(reverse('task_bulk_update'), {'ids': [self.shared.pk], 'stars': '1'})
        self.shared.refresh_from_db()
        self.assertEqual(self.shared.stars, 1)

    def test_delete(self):
        url = reverse('task_delete', args=[self.shared.pk])
        self.login(self.student)
        self.assertEqual(self.client.post(url).status_code, 403)
        self.login(self.guest)
        self.assertEqual(self.client.post(url).status_code, 403)
        self.assertTrue(Task.objects.filter(pk=self.shared.pk).exists())
        self.assertRedirects(self.client.post(reverse('task_delete', args=[self.own.pk])), reverse('task_list'))
        self.assertFalse(Task.objects.filter(pk=self.own.pk).exists())
        self.login(self.superuser)
        self.assertRedirects(self.client.post(url), reverse('task_list'))

    def test_full_form_post_on_existing_task(self):
        data = {'text_latex': 'Полная форма', **FORM_TAIL}
        self.login(self.guest)
        self.assertEqual(self.client.post(reverse('task_detail', args=[self.shared.pk]), data).status_code, 403)
        self.assertEqual(self.client.post(reverse('task_edit', args=[self.shared.pk]), data).status_code, 403)
        self.shared.refresh_from_db()
        self.assertEqual(self.shared.text_latex, 'Общая задача')
        self.assertEqual(self.client.post(reverse('task_detail', args=[self.own.pk]), data).status_code, 302)
        self.own.refresh_from_db()
        self.assertEqual(self.own.text_latex, 'Полная форма')
        self.login(self.editor)
        self.assertEqual(self.client.post(reverse('task_detail', args=[self.shared.pk]), data).status_code, 302)
        self.shared.refresh_from_db()
        self.assertEqual(self.shared.text_latex, 'Полная форма')

    def test_full_form_save_local_keeps_original(self):
        sheet = Worksheet.objects.create(owner=self.guest, title='Листок гостя')
        item = WorksheetItem.objects.create(worksheet=sheet, task=self.shared, order=10)
        self.login(self.guest)
        url = reverse('task_detail', args=[self.shared.pk]) + f'?worksheet={sheet.pk}&item={item.pk}'
        response = self.client.post(url, {'text_latex': 'Локально', 'save_local': '1', **FORM_TAIL})
        self.assertRedirects(response, reverse('worksheet_detail', args=[sheet.pk]))
        item.refresh_from_db()
        self.shared.refresh_from_db()
        self.assertEqual(self.shared.text_latex, 'Общая задача')
        self.assertEqual(item.task.variant_of, self.shared)
        self.assertEqual((item.task.created_by, item.task.is_shared), (self.guest, False))

    def test_neuro_only_for_editors(self):
        """Решение 5 плана пользователей: не-редактору нейрогенерация
        закрыта целиком — и запись, и черновик (подробнее test_decisions)."""
        result = {'answer': '4', 'solution': 'Решение', 'subitem_answers': ['1'], 'subitem_solutions': ['']}
        with mock.patch('problems.neuro.solve_task', return_value=result):
            self.login(self.guest)
            response = self.client.post(reverse('task_neuro_solve'), json.dumps(
                {'task_id': self.shared.pk, 'apply': True}), content_type='application/json')
            self.assertEqual(response.status_code, 403)
            response = self.client.post(reverse('task_neuro_solve'), json.dumps(
                {'task_id': self.own.pk, 'apply': True}), content_type='application/json')
            self.assertEqual(response.status_code, 403)
            response = self.client.post(reverse('task_neuro_solve'), json.dumps(
                {'task_id': self.shared.pk}), content_type='application/json')
            self.assertEqual(response.status_code, 403)
            self.assertEqual(self.shared.subitems.get().answer_latex, '')
            self.login(self.editor)
            response = self.client.post(reverse('task_neuro_solve'), json.dumps(
                {'task_id': self.shared.pk, 'apply': True}), content_type='application/json')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(self.shared.subitems.get().answer_latex, '1')

    def test_editor_only_pages(self):
        pages = [reverse('bulk_answers'), reverse('textbook_import_list'),
                 reverse('textbook_import_upload'), reverse('worksheet_corpus_list'),
                 reverse('worksheet_corpus_solutions')]
        for user, expected in ((self.superuser, 200), (self.editor, 200), (self.guest, 403), (self.student, 403)):
            self.login(user)
            for url in pages:
                self.assertEqual(self.client.get(url).status_code, expected, (user, url))
        self.login(self.guest)
        self.assertEqual(self.client.post(reverse('worksheet_corpus_approve_clean')).status_code, 403)
        self.assertEqual(self.client.post(reverse('textbook_import_commit', args=[1])).status_code, 403)

    def test_editor_only_links_hidden_from_guest(self):
        self.login(self.guest)
        response = self.client.get(reverse('task_list'))
        self.assertNotContains(response, 'Массовые ответы')
        self.assertNotContains(response, 'Импорт задачников')
        self.assertNotContains(self.client.get(reverse('worksheet_list')), 'Сверка корпуса')
        self.login(self.editor)
        response = self.client.get(reverse('task_list'))
        self.assertContains(response, 'Массовые ответы')
        self.assertContains(response, 'Импорт задачников')
        self.assertContains(self.client.get(reverse('worksheet_list')), 'Сверка корпуса')


class VisibilityTests(Roles, TestCase):
    def setUp(self):
        self.make_users()
        self.shared = shared_task(self.editor, 'Общая про уравнения')
        self.personal = Task.new_for(self.guest, text_latex='Личная про уравнения')

    def test_catalog_search_and_detail(self):
        self.client.force_login(self.other_guest)
        response = self.client.get(reverse('task_list'))
        self.assertEqual(list(response.context['page']), [self.shared])
        self.assertEqual(list(self.client.get(reverse('task_list'), {'q': f'#{self.personal.pk}'}).context['page']), [])
        self.assertEqual(self.client.get(reverse('task_detail', args=[self.personal.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse('task_duplicate', args=[self.personal.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse('task_manage', args=[self.personal.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse('cart_add'), {'task_id': self.personal.pk}).status_code, 404)
        self.assertEqual(self.client.post(reverse('worksheet_add_task', args=[
            Worksheet.objects.create(owner=self.other_guest, title='Л').pk]), {'task_id': self.personal.pk}).status_code, 404)
        self.client.force_login(self.guest)
        self.assertIn(self.personal, self.client.get(reverse('task_list')).context['page'])
        # Редактору чужая задача не из общих по ссылке открывается всегда, а в
        # каталоге — только при включённом тумблере (решение 1, test_decisions)
        for user in (self.guest, self.editor, self.superuser):
            self.client.force_login(user)
            self.assertEqual(self.client.get(reverse('task_detail', args=[self.personal.pk])).status_code, 200)
        self.assertNotIn(self.personal, self.client.get(reverse('task_list')).context['page'])

    def test_personal_badge(self):
        # Решение 6: автору — «моя», редактору — чья задача; слова «личная» нет
        self.client.force_login(self.guest)
        self.assertContains(self.client.get(reverse('task_detail', args=[self.personal.pk])), '>моя<')
        self.client.force_login(self.editor)
        self.assertContains(self.client.get(reverse('task_detail', args=[self.personal.pk])), 'задача Иван Учителев')
        self.assertNotContains(self.client.get(reverse('task_detail', args=[self.shared.pk])), '>моя<')

    def test_import_deduplication_ignores_foreign_personal_tasks(self):
        """Дубль ищется среди общих и своих задач — и у редактора тоже,
        иначе импорт в базу допишет ответы в чужую личную задачу."""
        from worksheets.import_tex import find_existing_task
        self.assertIsNone(find_existing_task('Личная про уравнения', user=self.other_guest))
        self.assertIsNone(find_existing_task('Личная про уравнения'))
        self.assertEqual(find_existing_task('Личная про уравнения', user=self.guest), self.personal.pk)
        self.assertIsNone(find_existing_task('Личная про уравнения', user=self.editor))
        self.assertIsNone(find_existing_task('Личная про уравнения', user=self.superuser))
        self.assertEqual(find_existing_task('Общая про уравнения', ['а)'], user=self.editor), self.shared.pk)
        self.assertEqual(find_existing_task('Общая про уравнения', ['а)'], user=self.other_guest), self.shared.pk)

    def test_independent_work_picker_excludes_foreign_personal(self):
        from independentworks.models import Work, Position, Candidate, Family
        family = Family.objects.create(title='Семья')
        family.tasks.add(self.shared, self.personal)
        base = Task.objects.create(text_latex='База', is_shared=True)
        family.tasks.add(base)
        work = Work.objects.create(owner=self.other_guest, title='СР')
        position = Position.objects.create(work=work)
        Candidate.objects.create(position=position, task=base)
        self.client.force_login(self.other_guest)
        with override_settings(INDEPENDENT_WORKS_ENABLED=True):
            response = self.client.get(reverse('independentworks:pick', args=[position.pk]))
            self.assertEqual(response.context['recommended'], [self.shared])
            self.assertEqual(self.client.post(reverse('independentworks:pick', args=[position.pk]),
                                              {'task': self.personal.pk, 'parts_mode': 'all'}).status_code, 404)

    def test_collection_with_editor_local_copy_taken_by_guest(self):
        """«Взять как листок» копирует подборку вместе с локальной копией
        редактора: приглашённый видит её в своём листке и правит через
        собственную копию, копия редактора не меняется."""
        from worksheets.models import Collection
        from .models import Source
        editor_copy = self.shared.make_variant(self.editor)
        editor_copy.text_latex = 'Версия редактора для подборки'
        editor_copy.save()
        sheet = Worksheet.objects.create(owner=self.editor, title='Подборка редактора')
        WorksheetItem.objects.create(worksheet=sheet, task=editor_copy, order=10)
        collection = Collection.objects.create(
            worksheet=sheet, source=Source.objects.create(title='Книга'),
            locator='kniga/1', is_published=True)
        self.client.force_login(self.other_guest)
        # Чужая локальная копия не из своего листка — невидима
        self.assertEqual(self.client.get(reverse('task_detail', args=[editor_copy.pk])).status_code, 404)
        response = self.client.post(reverse('collection_use', args=[collection.pk]))
        mine = Worksheet.objects.get(owner=self.other_guest)
        self.assertRedirects(response, reverse('worksheet_detail', args=[mine.pk]))
        item = mine.items.get()
        self.assertEqual(item.task, editor_copy)
        context = f'?worksheet={mine.pk}&item={item.pk}'
        self.assertEqual(self.client.get(reverse('task_detail', args=[editor_copy.pk]) + context).status_code, 200)
        self.assertEqual(self.client.get(reverse('task_detail', args=[editor_copy.pk])).status_code, 200)
        response = self.client.post(reverse('task_manage', args=[editor_copy.pk]) + context,
                                    {'block': 'condition', 'text_latex': 'Моя версия', 'scope': 'local'})
        self.assertEqual(response.status_code, 200, response.content)
        item.refresh_from_db()
        self.assertNotEqual(item.task, editor_copy)
        self.assertEqual((item.task.created_by, item.task.is_shared, item.task.variant_of, item.task.text_latex),
                         (self.other_guest, False, self.shared, 'Моя версия'))
        editor_copy.refresh_from_db()
        self.assertEqual(editor_copy.text_latex, 'Версия редактора для подборки')
        self.assertEqual(sheet.items.get().task, editor_copy)

    def test_taxonomy_counts_ignore_personal_tasks(self):
        from .models import TaskTopic, Topic
        from .rubricator import taxonomy_catalog
        topic = Topic.objects.get(code='ALG.07.03')
        before = next(row['count'] for row in taxonomy_catalog()['topics'] if row['id'] == topic.pk)
        TaskTopic.objects.create(task=self.personal, topic=topic)
        after = next(row['count'] for row in taxonomy_catalog()['topics'] if row['id'] == topic.pk)
        self.assertEqual(after, before)
        TaskTopic.objects.create(task=self.shared, topic=topic)
        after = next(row['count'] for row in taxonomy_catalog()['topics'] if row['id'] == topic.pk)
        self.assertEqual(after, before + 1)

    def test_dashboard_counts_visible_tasks(self):
        self.client.force_login(self.other_guest)
        self.assertEqual(self.client.get(reverse('dashboard')).context['tasks_total'], 1)
        # Редактору чужая задача не из общих считается только при включённом тумблере
        self.client.force_login(self.editor)
        self.assertEqual(self.client.get(reverse('dashboard')).context['tasks_total'], 1)
        self.editor.profile.show_foreign_tasks = True
        self.editor.profile.save(update_fields=['show_foreign_tasks'])
        self.assertEqual(self.client.get(reverse('dashboard')).context['tasks_total'], 2)


class GuestLocalEditTests(Roles, TestCase):
    """Приглашённый на общей задаче: карточка только для чтения без листка,
    а из листка правки уходят в локальную копию."""

    def setUp(self):
        self.make_users()
        self.shared = shared_task(self.editor)
        self.sheet = Worksheet.objects.create(owner=self.guest, title='Листок гостя')
        self.item = WorksheetItem.objects.create(worksheet=self.sheet, task=self.shared, order=10)
        self.client.force_login(self.guest)
        self.context = f'?worksheet={self.sheet.pk}&item={self.item.pk}'

    def test_card_without_worksheet_is_read_only(self):
        response = self.client.get(reverse('task_detail', args=[self.shared.pk]))
        self.assertContains(response, 'data-base-locked="1"')
        self.assertContains(response, 'Общая задача · правки только для листка')
        self.assertNotContains(response, 'data-editor-form')
        self.assertNotContains(response, 'data-mask-edit')
        self.assertNotContains(response, 'Удалить задачу')
        self.assertNotContains(response, 'увидят все учителя')
        self.assertContains(response, 'id="base-locked-dialog"')

    def test_card_in_worksheet_keeps_forms_but_locks_scope(self):
        response = self.client.get(reverse('task_detail', args=[self.shared.pk]) + self.context)
        self.assertContains(response, 'data-base-locked="1"')
        self.assertContains(response, 'data-editor-form')
        self.assertNotContains(response, 'Удалить задачу')
        self.assertNotContains(response, 'увидят все учителя')

    def test_editor_card_is_unchanged(self):
        self.client.force_login(self.editor)
        response = self.client.get(reverse('task_detail', args=[self.shared.pk]))
        self.assertNotContains(response, 'data-base-locked="1"')
        self.assertContains(response, 'data-editor-form')
        self.assertContains(response, 'Удалить задачу')
        self.assertContains(response, 'увидят все учителя')

    def answer_block(self, response):
        """Разметка блока «Ответ ученика» единственного подпункта."""
        html = response.content.decode()
        start = html.index('<section class="problem-answer"')
        return html[start:html.index('</section>', start)]

    def test_read_only_card_shows_student_form_instead_of_mask(self):
        """Решение R12-1 обхода экранов: приглашённому вместо сырой маски —
        форма ученика с «Проверить как ученик», код маски — под «показать маску»."""
        import re
        sub = self.shared.subitems.get()
        sub.answer_mask = '$x=${{number:3}}'
        sub.save(update_fields=['answer_mask'])
        response = self.client.get(reverse('task_detail', args=[self.shared.pk]))
        block = self.answer_block(response)
        self.assertIn('data-mask-check', block)
        self.assertIn('Проверить как ученик', block)
        self.assertIn('data-mask-reset', block)
        self.assertIn(f'name="preview_{sub.pk}_s1"', block)
        self.assertIn(f'data-check="preview_{sub.pk}"', block)
        self.assertIn('<summary>показать маску</summary>', block)
        # Сырой маски в видимой разметке нет: только в скрытом поле формы и под «показать маску»
        visible = re.sub(r'<input type="hidden"[^>]*>|<details [^>]*problem-mask-source.*?</details>',
                         '', block, flags=re.S)
        self.assertNotIn('{{', visible)
        self.assertIn('{{number:3}}', block)
        self.assertNotContains(response, 'data-mask-preview')
        self.assertNotContains(response, 'data-mask-edit')
        self.assertContains(response, 'data-check-url="/problems/mask/check/"')
        # Без маски формы нет, остаётся подсказка про фото
        sub.answer_mask = ''
        sub.save(update_fields=['answer_mask'])
        block = self.answer_block(self.client.get(reverse('task_detail', args=[self.shared.pk])))
        self.assertNotIn('data-mask-check', block)
        self.assertNotIn('показать маску', block)
        self.assertIn('Пока ученик может прислать только фото решения.', block)

    def test_editor_card_keeps_mask_code_and_preview_button(self):
        sub = self.shared.subitems.get()
        sub.answer_mask = '$x=${{number:3}}'
        sub.save(update_fields=['answer_mask'])
        self.client.force_login(self.editor)
        block = self.answer_block(self.client.get(reverse('task_detail', args=[self.shared.pk])))
        self.assertIn('<div class="problem-mask-code math-content">', block)
        self.assertIn('data-mask-preview', block)
        self.assertIn('data-mask-edit', block)
        self.assertNotIn('data-mask-check', block)
        self.assertNotIn('показать маску', block)

    def test_catalog_row_has_no_inline_form_for_shared(self):
        own = Task.new_for(self.guest, text_latex='Своя')
        response = self.client.get(reverse('task_list'))
        html = response.content.decode()
        self.assertEqual(html.count('<details class="row-edit" data-row-edit>'), 1)
        self.assertIn(f'value="{own.pk}" form="task-bulk-form"', html)
        self.assertNotIn(f'value="{self.shared.pk}" form="task-bulk-form"', html)
        self.assertIn('row-edit-static', html)
        # Редактор видит задачу гостя в каталоге только при включённом тумблере (решение 1)
        self.editor.profile.show_foreign_tasks = True
        self.editor.profile.save(update_fields=['show_foreign_tasks'])
        self.client.force_login(self.editor)
        html = self.client.get(reverse('task_list')).content.decode()
        self.assertEqual(html.count('<details class="row-edit" data-row-edit>'), 2)
        self.assertNotIn('row-edit-static', html)

    def test_local_scope_creates_copy_and_original_stays(self):
        url = reverse('task_manage', args=[self.shared.pk]) + self.context
        response = self.client.post(url, {'block': 'condition', 'text_latex': 'Моя версия', 'scope': 'local'})
        self.assertEqual(response.status_code, 200, response.content)
        copy = Task.objects.get(variant_of=self.shared)
        self.assertEqual((copy.created_by, copy.is_shared, copy.text_latex), (self.guest, False, 'Моя версия'))
        self.shared.refresh_from_db()
        self.assertEqual(self.shared.text_latex, 'Общая задача')
        self.item.refresh_from_db()
        self.assertEqual(self.item.task, copy)
        data = response.json()
        self.assertEqual(data['task_id'], copy.pk)
        self.assertNotIn('data-base-locked', data['html'])
        self.assertIn('Удалить задачу', data['sidebar'])
        # Дальше копия правится напрямую, в том числе маски
        response = self.client.post(reverse('task_manage', args=[copy.pk]) + f'?worksheet={self.sheet.pk}&item={self.item.pk}',
                                    {'block': 'masks', 'scope': 'global',
                                     'masks': json.dumps([{'id': copy.subitems.get().pk, 'mask': '{{number: 2}}'}])})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(self.shared.subitems.get().answer_mask, '')

    def test_global_scope_is_refused_even_from_worksheet(self):
        url = reverse('task_manage', args=[self.shared.pk]) + self.context
        response = self.client.post(url, {'block': 'condition', 'text_latex': 'Взлом', 'scope': 'global'})
        self.assertEqual(response.status_code, 403)
        # Без явной области — тоже локальная копия, а не запись в базу
        response = self.client.post(url, {'block': 'condition', 'text_latex': 'Без области'})
        self.assertEqual(response.status_code, 200)
        self.shared.refresh_from_db()
        self.assertEqual(self.shared.text_latex, 'Общая задача')
        self.assertTrue(Task.objects.filter(variant_of=self.shared, text_latex='Без области').exists())

    def test_duplicate_and_quick_task_become_personal(self):
        response = self.client.post(reverse('task_duplicate', args=[self.shared.pk]))
        copy = Task.objects.exclude(pk=self.shared.pk).get(variant_of__isnull=True)
        self.assertRedirects(response, reverse('task_detail', args=[copy.pk]))
        self.assertEqual((copy.created_by, copy.is_shared), (self.guest, False))
        self.client.post(reverse('worksheet_quick_task', args=[self.sheet.pk]), {'text_latex': 'Быстрая задача'})
        quick = Task.objects.get(text_latex='Быстрая задача')
        self.assertEqual((quick.created_by, quick.is_shared), (self.guest, False))
        self.client.post(reverse('task_create'), {'text_latex': 'Через форму', **FORM_TAIL})
        self.assertFalse(Task.objects.get(text_latex='Через форму').is_shared)
        self.client.force_login(self.editor)
        self.client.post(reverse('task_create'), {'text_latex': 'От редактора', **FORM_TAIL})
        self.assertTrue(Task.objects.get(text_latex='От редактора').is_shared)

    def test_tex_import_creates_personal_tasks_and_keeps_shared_answers(self):
        from worksheets.import_tex import create_worksheet, parse_tex
        plain = Task.objects.create(text_latex='Общая без подпунктов', created_by=self.editor, is_shared=True)
        tex = ('\\begin{document}\\bighead{Листок}{8 класс}{Автор}\n'
               '\\task{1}{0}{Общая без подпунктов}\n\\task{2}{0}{Новая из импорта}\n\\end{document}')
        parsed = parse_tex(tex)
        worksheet, _ = create_worksheet(parsed, self.guest, overrides={0: {'answer': '42'}, 1: {'answer': '7'}})
        plain.refresh_from_db()
        self.assertEqual(plain.answer_latex, '')
        new = Task.objects.get(text_latex='Новая из импорта')
        self.assertEqual((new.created_by, new.is_shared, new.answer_latex), (self.guest, False, '7'))
        # Правка ответа у совпавшей общей задачи не теряется: листок получает
        # локальную копию с этим ответом
        first = worksheet.items.order_by('order').first().task
        self.assertEqual((first.variant_of, first.created_by, first.is_shared, first.answer_latex),
                         (plain, self.guest, False, '42'))
        # Без правок совпавшая общая задача ставится в листок как есть
        again, _ = create_worksheet(parsed, self.guest, overrides={1: {'skip': True}})
        self.assertEqual(again.items.get().task, plain)
        # Редактор при импорте дописывает ответ и в существующую общую задачу
        create_worksheet(parsed, self.editor, overrides={0: {'answer': '42'}, 1: {'skip': True}})
        plain.refresh_from_db()
        self.assertEqual(plain.answer_latex, '42')
