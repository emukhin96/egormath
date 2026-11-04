"""Экран «Задачи»: строка каталога, фильтры, карточка задачи, импорт
задачников (ревизия интерфейса 03.11, T1–T4)."""
from datetime import timedelta

from django.test import SimpleTestCase
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Source
from .models import Task
from .models import TaskSource
from .models import TaskTopic
from .models import TextbookImportBatch
from .models import TextbookTaskDraft
from .models import Topic
from .templatetags.task_extras import path_tail
from .templatetags.task_extras import section_path
from .test_permissions import Roles
from .test_permissions import shared_task

FILE_PART = '7 класс/matvert7-alg-dist3.tex'


class SourcePathFilterTests(SimpleTestCase):
    def test_file_parts_are_dropped(self):
        self.assertEqual(path_tail([FILE_PART]), [])
        self.assertEqual(section_path(['Глава 1.', FILE_PART, '§ 2']), ['Глава 1', '§ 2'])
        self.assertEqual(path_tail(['Глава X', 'ДКР', 'Вариант 5']), ['…', 'ДКР', 'Вариант 5'])


class CatalogRowTests(Roles, TestCase):
    def setUp(self):
        self.make_users()
        self.task = shared_task(self.editor, 'Решите уравнение')
        source = Source.objects.create(title='Авторские листки')
        TaskSource.objects.create(task=self.task, source=source, number='14',
                                  source_path=[FILE_PART])
        topic = Topic.objects.create(code='UIT.02.03', name='Формулы сокращённого умножения')
        TaskTopic.objects.create(task=self.task, topic=topic, role=TaskTopic.ROLE_PRIMARY)

    def row(self, user):
        self.client.force_login(user)
        html = self.client.get(reverse('task_list')).content.decode()
        return html, html.split('data-task-row>', 1)[1].split('</tr>', 1)[0]

    def test_source_without_file_path(self):
        _, row = self.row(self.guest)
        self.assertIn('>Авторские листки, № 14</span>', row)
        self.assertNotIn('matvert7', row)
        # Редактору путь к файлу — только в подсказке
        _, row = self.row(self.editor)
        self.assertIn('>Авторские листки, № 14</span>', row)
        self.assertIn(f'title="Авторские листки, № 14 › {FILE_PART}"', row)

    def test_topic_by_name_with_code_in_title(self):
        for user in (self.guest, self.editor):
            _, row = self.row(user)
            self.assertIn('<span title="UIT.02.03">Формулы сокращённого ум…</span>', row)

    def test_rare_actions_in_row_menu(self):
        _, row = self.row(self.editor)
        menu = row.split('<details class="more-menu on-hover">', 1)[1].split('</details>', 1)[0]
        self.assertIn('data-task-png', menu)
        self.assertIn(f'data-quick-clone="{reverse("task_clone", args=[self.task.pk])}"', menu)
        self.assertIn(reverse('task_duplicate', args=[self.task.pk]), menu)
        # «+» в корзину — в своей колонке, не в меню
        self.assertNotIn('cart-btn', menu)
        self.assertIn('cart-btn', row)

    def test_filters_one_row_and_count_once(self):
        html, _ = self.row(self.editor)
        head = html.split('<div class="page-head">', 1)[1].split('id="task-filters"', 1)[0]
        self.assertNotIn('Массовые ответы', head)
        self.assertNotIn('Задачи <span class="muted">(', html)
        more = html.split('catalog-more', 1)[1].split('</details>', 1)[0]
        self.assertIn('name="show_foreign_tasks" value="1" form="task-list-prefs"', more)
        self.assertIn('<form id="task-list-prefs"', html)
        html, _ = self.row(self.guest)
        self.assertNotIn('show_foreign_tasks', html)

    def test_foreign_toggle_still_saves(self):
        self.client.force_login(self.editor)
        response = self.client.post(reverse('task_list_prefs'),
                                    {'show_foreign_tasks': '1', 'next': reverse('task_list')})
        self.assertRedirects(response, reverse('task_list'), fetch_redirect_response=False)
        self.editor.profile.refresh_from_db()
        self.assertTrue(self.editor.profile.show_foreign_tasks)
        html = self.client.get(reverse('task_list')).content.decode()
        self.assertIn('catalog-more is-set', html)


class TaskCardTests(Roles, TestCase):
    def setUp(self):
        self.make_users()
        self.task = shared_task(self.editor, 'Условие карточки')

    def test_editor_card(self):
        self.client.force_login(self.editor)
        html = self.client.get(reverse('task_detail', args=[self.task.pk])).content.decode()
        self.assertNotIn('Метаданные', html)
        title_row = html.split('class="task-title-row"', 1)[1].split('class="page-meta"', 1)[0]
        self.assertIn('data-ai-menu', title_row)
        self.assertIn('cart-btn', title_row)
        menu = title_row.split('more-menu is-head', 1)[1]
        self.assertIn(reverse('task_delete', args=[self.task.pk]), menu)
        self.assertIn('aria-label="Править условие"', html)
        self.assertIn('aria-label="Править ответ и источники"', html)
        self.assertNotIn('<summary>Править условие</summary>', html)
        # Пояснения — «?», а не постоянные абзацы
        self.assertNotIn('<p class="helptext">Для краткого ответа нужна маска', html)
        self.assertIn('help-tip-body"><p>Для краткого ответа нужна маска', html)
        self.assertIn('help-tip-body"><p>Авторские ответ и решение имеют приоритет', html)

    def test_sidebar_only_classification(self):
        self.client.force_login(self.editor)
        url = reverse('task_detail', args=[self.task.pk])
        self.assertNotContains(self.client.get(url), 'sidebar-section')
        topic = Topic.objects.create(code='T.1', name='Тема карточки')
        TaskTopic.objects.create(task=self.task, topic=topic, role=TaskTopic.ROLE_PRIMARY)
        response = self.client.get(url)
        self.assertContains(response, 'Классификация')
        self.assertNotContains(response, 'Создана:')

    def test_guest_shared_card_read_only_with_proposal(self):
        self.client.force_login(self.guest)
        html = self.client.get(reverse('task_detail', args=[self.task.pk])).content.decode()
        self.assertIn('data-dialog-open="propose-dialog"', html)
        self.assertNotIn('Удалить задачу', html)
        self.assertNotIn('edit-pen', html)
        self.assertNotIn('data-editor-form', html)


class ImportListTests(Roles, TestCase):
    def setUp(self):
        self.make_users()
        self.now = timezone.now()

    def batch(self, source, title, days_ago, drafts=1, status=TextbookImportBatch.STATUS_REVIEW,
              imported=0):
        batch = TextbookImportBatch.objects.create(
            title=title, profile='test', source=source, created_by=self.superuser, status=status)
        TextbookImportBatch.objects.filter(pk=batch.pk).update(
            created_at=self.now - timedelta(days=days_ago))
        for number in range(drafts):
            TextbookTaskDraft.objects.create(
                batch=batch, external_id=str(number), source_number=str(number),
                text_latex='Черновик',
                status=(TextbookTaskDraft.STATUS_IMPORTED if number < imported
                        else TextbookTaskDraft.STATUS_REVIEW))
        return batch

    def test_groups_by_book_and_archives_trials(self):
        ziv = Source.objects.create(title='Алгебра 9', author='Зив', short_title='Зив-9')
        ziv_copy = Source.objects.create(title='Алгебра 9 (повтор)', short_title='Зив-9')
        old = self.batch(ziv, 'Зив тест', 9, drafts=2)
        loaded = self.batch(ziv_copy, 'Зив v10', 5, drafts=3, imported=3)
        newer = self.batch(ziv, 'Зив v11 после загрузки', 1, drafts=3)
        empty = self.batch(ziv, 'Пустая', 0, drafts=0)
        book = Source.objects.create(title='Задачник')
        trial = self.batch(book, 'Проба', 3, drafts=2)
        full = self.batch(book, 'Полная', 4, drafts=5)

        self.client.force_login(self.superuser)
        response = self.client.get(reverse('textbook_import_list'))
        active = {b.short: [x.pk for x in b.batches] for b in response.context['active_books']}
        archive = {b.short: [x.pk for x in b.batches] for b in response.context['archive_books']}
        self.assertEqual(active, {'Зив-9': [newer.pk, loaded.pk], 'Задачник': [full.pk]})
        self.assertEqual(archive, {'Зив-9': [empty.pk, old.pk], 'Задачник': [trial.pk]})
        html = response.content.decode()
        # Название книги — один раз в строке-заголовке, архив свёрнут
        self.assertEqual(html.count('<span class="import-book-short">Зив-9</span>'), 2)
        self.assertIn('<details class="import-archive">', html)
        self.assertIn('Архив: 3 партии', html)
        self.assertIn('badge badge-submitted">На проверке<', html)
