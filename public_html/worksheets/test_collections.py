from django.test import TestCase
from django.urls import reverse

from problems.models import Source, Task, TaskSubitem
from problems.tests import make_teacher
from worksheets.latex import worksheet_to_tex
from worksheets.models import Collection, Worksheet, WorksheetItem


class CollectionTests(TestCase):
    def setUp(self):
        self.owner = make_teacher()
        self.other = make_teacher('teacher2')
        self.source = Source.objects.create(title='Задачник')
        self.worksheet = Worksheet.objects.create(
            title='Готовая тема', owner=self.owner)
        self.task = Task.objects.create(
            text_latex='Вычислите $2+2$.', author_answer_latex='4',
            author_solution_latex='$2+2=4$.', stars=0, created_by=self.owner)
        TaskSubitem.objects.create(
            task=self.task, order=10, text_latex='Поясните вычисление')
        WorksheetItem.objects.create(
            worksheet=self.worksheet, task=self.task, order=10)
        WorksheetItem.objects.create(
            worksheet=self.worksheet, text_latex='Вспомните правило.',
            text_style='memo', order=20)
        self.collection = Collection.objects.create(
            worksheet=self.worksheet, source=self.source,
            locator='chapter-1', source_path=['Глава 1'], is_published=True)

    def test_author_content_falls_back_in_pdf(self):
        tex = worksheet_to_tex(self.worksheet, 'teacher')
        self.assertIn('[{4}]', tex)
        self.assertIn('$2+2=4$.', tex)
        self.task.answer_latex = 'редакторский ответ'
        self.task.save(update_fields=['answer_latex'])
        tex = worksheet_to_tex(self.worksheet, 'answers')
        self.assertNotIn('редакторский ответ', tex)
        self.assertIn('[{4}]', tex)

    def test_use_collection_copies_all_worksheet_elements(self):
        self.client.login(username='teacher2', password='pass12345')
        response = self.client.post(
            reverse('collection_use', args=[self.collection.pk]))
        self.assertEqual(response.status_code, 302)
        copy = Worksheet.objects.get(owner=self.other)
        self.assertFalse(hasattr(copy, 'collection'))
        self.assertEqual(copy.items.count(), 2)
        self.assertEqual(copy.items.filter(task=self.task).count(), 1)
        self.assertEqual(copy.items.filter(text_style='memo').count(), 1)

    def test_collection_catalog_and_editor_render(self):
        self.client.login(username='teacher1', password='pass12345')
        self.assertContains(self.client.get(reverse('collection_list')),
                            'Готовая тема')
        detail = self.client.get(reverse(
            'collection_detail', args=[self.collection.pk]))
        self.assertContains(detail, 'Использовать подборку')
        self.assertContains(detail, 'Поясните вычисление')
        self.assertContains(detail, 'toggle-answers')
        self.assertContains(detail, 'показать ответы и решения')
        self.assertContains(detail, 'data-answers-key="collection-show-answers"')
        # Тумблер в шапке страницы — рядом с кнопками, не внутри списка
        head = detail.content.decode().split('id="ws-items"', 1)[0]
        self.assertIn('toggle-answers', head)
        self.assertContains(detail, 'data-cart-form')
        editor = self.client.get(reverse(
            'collection_edit', args=[self.collection.pk]), follow=True)
        self.assertContains(editor, 'Конструктор подборки')
        self.assertContains(editor, 'Текст между задачами')

    def test_collection_hides_answer_images_until_answers_block(self):
        pictured = Task.objects.create(
            text_latex='Постройте график', created_by=self.owner)
        TaskSubitem.objects.create(
            task=pictured, order=10, text_latex='$y=x$',
            author_answer_latex='см. рис.\n\\taskpic{1}')
        image = pictured.images.create(
            image='task_images/graph-answer.png', order=10)
        WorksheetItem.objects.create(
            worksheet=self.worksheet, task=pictured, order=30)
        self.client.login(username='teacher1', password='pass12345')
        detail = self.client.get(reverse(
            'collection_detail', args=[self.collection.pk]))
        image_url = reverse('task_image_file', args=[image.pk])
        html = detail.content.decode()
        chunk = html.split('Постройте график', 1)[1]
        before_answers, after_answers = chunk.split('div class="ws-answers"', 1)
        self.assertNotIn(image_url, before_answers)
        self.assertIn(image_url, after_answers)
        self.assertIn('hidden', after_answers.split('>', 1)[0])
        self.assertIn('см. рис.', chunk)
        self.assertIn('а)&nbsp;', chunk)
        self.assertNotIn('— ответ:', html)

    def test_copied_worksheet_has_visibility_buttons(self):
        self.client.login(username='teacher2', password='pass12345')
        self.client.post(reverse('collection_use', args=[self.collection.pk]))
        copy = Worksheet.objects.get(owner=self.other)
        self.assertFalse(copy.share_links.exists())
        response = self.client.get(reverse('worksheet_detail', args=[copy.pk]))
        self.assertContains(response, 'vis-btn')
        self.assertContains(response, 'Сначала создайте публичную ссылку')

    def test_empty_group_cannot_be_copied(self):
        group_sheet = Worksheet.objects.create(
            title='Группа', owner=self.owner)
        group = Collection.objects.create(
            worksheet=group_sheet, source=self.source,
            locator='group', source_path=['Группа'])
        self.client.login(username='teacher1', password='pass12345')
        response = self.client.post(
            reverse('collection_use', args=[group.pk]), follow=True)
        self.assertContains(response, 'не содержит элементов')
        self.assertEqual(Worksheet.objects.filter(
            owner=self.owner, title='Группа').count(), 1)

    def test_catalog_hides_empty_group_and_group_links_to_child(self):
        group_sheet = Worksheet.objects.create(
            title='№10. Вероятности', owner=self.owner)
        group = Collection.objects.create(
            worksheet=group_sheet, source=self.source,
            locator='group', source_path=['№10. Вероятности'])
        self.collection.parent = group
        self.collection.save(update_fields=['parent'])
        self.client.login(username='teacher1', password='pass12345')

        catalog = self.client.get(reverse('collection_list'))
        self.assertNotContains(catalog, '№10. Вероятности')
        self.assertContains(catalog, 'Готовая тема')

        detail = self.client.get(reverse(
            'collection_detail', args=[group.pk]))
        self.assertContains(detail, 'Это раздел, который объединяет')
        self.assertContains(detail, 'Готовая тема')
        self.assertContains(detail, 'Открыть подборку')
        self.assertNotContains(detail, 'Подборка пуста')
