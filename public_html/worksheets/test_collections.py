from django.test import TestCase
from django.urls import reverse

from problems.models import Source, Task
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
        self.assertIn('редакторский ответ', tex)
        self.assertNotIn('[{4}]', tex)

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
        self.assertContains(self.client.get(reverse(
            'collection_detail', args=[self.collection.pk])),
            'Использовать подборку')
        editor = self.client.get(reverse(
            'collection_edit', args=[self.collection.pk]), follow=True)
        self.assertContains(editor, 'Конструктор подборки')
        self.assertContains(editor, 'Текст между задачами')
