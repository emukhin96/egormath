"""Рисунок, на который ссылается только подпункт, на веб-страницах стоит под ним.

В PDF ``\\taskpic`` внутри ``\\item`` печатает рисунок на месте; на сайте
``web_text`` маркер вырезает, поэтому раньше все рисунки уходили в общую
галерею условия, а подпункты «только рисунок» оставались пустыми строками.
"""
from django.template import Context, Template
from django.test import TestCase
from django.urls import reverse

from problems.models import Task, TaskSubitem
from problems.task_images import images_for_group
from problems.task_images import subitem_image_map
from problems.templatetags.task_extras import subitem_tail
from problems.tests import make_teacher
from worksheets.block_presentation import decorate_block_rows
from worksheets.models import Worksheet, WorksheetItem


class SubitemImageTests(TestCase):
    def setUp(self):
        self.task = Task.objects.create(
            text_latex=r'Постройте сечение куба. \taskpic{1}')
        self.pics = [self.task.images.create(image=f'task_images/cube{i}.png', order=i * 10)
                     for i in range(1, 5)]
        self.sub_a = TaskSubitem.objects.create(
            task=self.task, order=10, text_latex=r'\taskpic{2}')
        # Рисунок 1 есть и в общем условии — остаётся в галерее
        self.sub_b = TaskSubitem.objects.create(
            task=self.task, order=20, text_latex=r'\taskpic{3} \taskpic{1}' '\n\n' r'$M \in (ABC)$')

    def url(self, image):
        return reverse('task_image_file', args=[image.pk])

    def test_map_and_main_gallery(self):
        one, two, three, four = self.pics
        self.assertEqual(subitem_image_map(self.task),
                         {self.sub_a.pk: [two], self.sub_b.pk: [three]})
        # Рисунок без ссылок (4) по-прежнему в условии
        self.assertEqual(images_for_group(self.task, 'main'), [one, four])
        self.assertEqual(images_for_group(self.task), self.pics)

    def test_task_card_places_picture_under_subitem(self):
        self.client.force_login(make_teacher())
        page = self.client.get(reverse('task_detail', args=[self.task.pk])).content.decode()
        # Блок «Условие» карточки (ниже — список файлов в «Изображения и источники»)
        html = page[page.index('data-task-png-root'):]
        html = html[:html.index('</section>')]
        subitems = html[html.index('<ol class="subitems">'):]
        subitems = subitems[:subitems.index('</ol>')]
        first, second = subitems.split('</li>')[:2]
        self.assertIn(self.url(self.pics[1]), first)
        self.assertIn(self.url(self.pics[2]), second)
        for image in self.pics:
            self.assertEqual(html.count(self.url(image)), 1, image.image.name)

    def test_subitems_include_and_tag(self):
        rendered = Template(
            "{% load task_extras %}{% include 'problems/_subitems.html' with pics_task=task %}"
        ).render(Context({'task': self.task, 'subitems': self.task.subitems.all()}))
        self.assertIn(self.url(self.pics[1]), rendered)
        self.assertNotIn(self.url(self.pics[0]), rendered)
        # Без pics_task — как раньше, только текст
        plain = Template("{% include 'problems/_subitems.html' %}").render(
            Context({'task': self.task, 'subitems': self.task.subitems.all()}))
        self.assertNotIn('<img', plain)
        by_pk = Template('{% load task_extras %}{% subitem_images task pk %}').render(
            Context({'task': self.task, 'pk': self.sub_a.pk}))
        self.assertIn(self.url(self.pics[1]), by_pk)

    def test_worksheet_rows_leave_subitem_pictures_out_of_gallery(self):
        worksheet = Worksheet.objects.create(title='Сечения', owner=make_teacher())
        item = WorksheetItem.objects.create(worksheet=worksheet, task=self.task, order=10)
        row = decorate_block_rows([{'item': item}])[0]
        self.assertEqual(row['statement_images'], [self.pics[0], self.pics[3]])
        self.assertEqual(row['review_images'], [self.pics[0], self.pics[3]])


class SubitemTailTests(TestCase):
    def test_picture_only_subitem_gets_no_punctuation(self):
        self.assertEqual(subitem_tail(r'\taskpic{3}', False), '')
        self.assertEqual(subitem_tail(r'\taskpic{3}' '\n\n' r'$M \in (ABC)$', True), '.')
        self.assertEqual(subitem_tail('Найдите $x$', False), ';')
