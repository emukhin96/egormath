"""Проверки неделимости блока при работе через HTTP и сервис листка."""
from django.test import TestCase
from django.urls import reverse
from problems.models import Source, Task, TaskBlock
from problems.tests import make_teacher
from worksheets.models import Worksheet
from worksheets.views import append_task, soft_remove_item
from worksheets.cart import SESSION_KEY


class TaskBlockTests(TestCase):
    def setUp(self):
        self.teacher = make_teacher()
        self.client.force_login(self.teacher)
        self.block = TaskBlock.objects.create(source=Source.objects.create(title='ОГЭ'),
                                              key='test', title='Общее условие')
        self.tasks = [Task.objects.create(text_latex=f'Вопрос {n}', created_by=self.teacher,
                                         block=self.block, block_position=n) for n in range(1, 6)]
        self.ws = Worksheet.objects.create(title='Блок', owner=self.teacher)

    def ids(self):
        return list(self.ws.ordered_items().values_list('task_id', flat=True))

    def test_cart_adds_and_removes_whole_block(self):
        self.client.post(reverse('cart_add'), {'task_id': self.tasks[2].pk})
        self.assertEqual(self.client.session[SESSION_KEY], [t.pk for t in self.tasks])
        self.client.post(reverse('cart_add'), {'task_id': self.tasks[0].pk})
        self.assertEqual(len(self.client.session[SESSION_KEY]), 5)
        self.client.post(reverse('cart_remove'), {'task_id': self.tasks[3].pk})
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_append_remove_restore_block(self):
        append_task(self.ws, self.tasks[3])
        self.assertEqual(self.ids(), [t.pk for t in self.tasks])
        append_task(self.ws, self.tasks[0])
        self.assertEqual(len(self.ids()), 5)
        soft_remove_item(self.ws, self.ws.ordered_items()[2])
        self.assertEqual(self.ids(), [])
        append_task(self.ws, self.tasks[4])
        self.assertEqual(self.ids(), [t.pk for t in self.tasks])

    def test_reorder_cannot_split_or_reverse_block(self):
        append_task(self.ws, self.tasks[0])
        items = list(self.ws.ordered_items())
        response = self.client.post(reverse('worksheet_reorder', args=[self.ws.pk]),
                                    {'order': ','.join(str(i.pk) for i in reversed(items))})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.ids(), [t.pk for t in self.tasks])

    def test_incomplete_block_is_not_added(self):
        self.tasks[-1].delete()
        response = self.client.post(reverse('cart_add'), {'task_id': self.tasks[0].pk},
                                    HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 400)
        append_task(self.ws, self.tasks[0])
        self.assertEqual(self.ids(), [])

    def test_move_and_undo_preserve_all_five(self):
        append_task(self.ws, self.tasks[0])
        single = Task.objects.create(text_latex='Отдельная', created_by=self.teacher)
        append_task(self.ws, single)
        first = self.ws.ordered_items().first()
        self.client.post(reverse('worksheet_move_item', args=[self.ws.pk, first.pk, 'down']))
        self.assertEqual(self.ids(), [single.pk] + [t.pk for t in self.tasks])
        member = self.ws.ordered_items()[3]
        self.client.post(reverse('worksheet_remove_item', args=[self.ws.pk, member.pk]))
        self.assertEqual(self.ids(), [single.pk])
        self.client.post(reverse('worksheet_restore_item', args=[self.ws.pk]))
        self.assertEqual(self.ids(), [single.pk] + [t.pk for t in self.tasks])

    def test_independent_copy_has_own_complete_block(self):
        copy = self.tasks[2].make_variant(self.teacher, standalone=True)
        self.assertNotEqual(copy.block_id, self.block.pk)
        self.assertEqual(copy.block.tasks.count(), 5)
        self.assertEqual(self.block.tasks.count(), 5)
        append_task(self.ws, copy)
        self.assertEqual(list(self.ws.ordered_items().values_list('task__block_position', flat=True)),
                         [1, 2, 3, 4, 5])

    def test_local_copy_replaces_all_block_members(self):
        from problems.editor import local_copy
        append_task(self.ws, self.tasks[0])
        item = self.ws.ordered_items()[2]
        copy, mapping = local_copy(self.tasks[2], item, self.teacher)
        self.assertEqual(self.ids(), [mapping['block_tasks'][t.pk] for t in self.tasks])
        self.assertEqual(copy.block.tasks.count(), 5)
        self.assertEqual(self.block.tasks.count(), 5)


class CommonBlockOutputTests(TestCase):
    def setUp(self):
        self.teacher = make_teacher()
        self.block = TaskBlock.objects.create(source=Source.objects.create(title='ОГЭ'),
                                              key='print', title='План участка')
        self.ws = Worksheet.objects.create(title='Пять вопросов', owner=self.teacher)
        self.common = 'План показывает участок, дом, дорожки и хозяйственные постройки. ' * 4
        words = ['Первый', 'Второй', 'Третий', 'Четвёртый', 'Пятый']
        self.tasks = [Task.objects.create(text_latex=self.common + '\n' + word + ' вопрос.',
                                         author_answer_latex=str(n), created_by=self.teacher,
                                         block=self.block, block_position=n)
                      for n, word in enumerate(words, 1)]
        append_task(self.ws, self.tasks[0])

    def test_full_block_has_one_condition_and_five_numbered_answers(self):
        from worksheets.latex import worksheet_to_tex
        for variant in ['student', 'answers', 'teacher']:
            tex = worksheet_to_tex(self.ws, variant)
            self.assertEqual(tex.count('План показывает'), 4)
            self.assertEqual(tex.count('\\task{'), 5)
            for n in range(1, 6):
                self.assertIn('[{%s}]' % n, tex)

    def test_partial_block_keeps_the_complete_condition(self):
        from worksheets.latex import worksheet_to_tex
        first = self.ws.ordered_items().first()
        tex = worksheet_to_tex(self.ws, exclude_ids={first.pk})
        self.assertEqual(tex.count('План показывает'), 16)
        self.assertNotIn('Общее условие к следующим', tex)

    def test_equal_files_with_different_names_are_combined(self):
        import tempfile
        from pathlib import Path
        from django.test import override_settings
        from problems.models import TaskImage
        from worksheets.latex import worksheet_to_tex
        with tempfile.TemporaryDirectory() as root, override_settings(MEDIA_ROOT=root):
            for index, task in enumerate(self.tasks):
                name = f'plan-{index}.png'
                Path(root, name).write_bytes(b'identical-image')
                TaskImage.objects.create(task=task, image=name)
                task.text_latex = '\\taskpic{1}\n\\\\\n' + task.text_latex
                task.save(update_fields=['text_latex'])
            tex = worksheet_to_tex(self.ws)
            self.assertEqual(tex.count('\\includegraphics['), 1)
            self.assertNotIn('\\par\n\\\\', tex)
            self.assertNotIn('\\taskpic{plan-', tex)
            Path(root, 'plan-3.png').write_bytes(b'different-image')
            tex = worksheet_to_tex(self.ws)
            self.assertEqual(tex.count('План показывает'), 20)
            self.assertEqual(tex.count('\\taskpic{plan-'), 5)
            Path(root, 'plan-3.png').unlink()
            self.assertEqual(worksheet_to_tex(self.ws).count('План показывает'), 20)

    def test_builder_shows_common_condition_once(self):
        self.client.force_login(self.teacher)
        response = self.client.get(reverse('worksheet_detail', args=[self.ws.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'План показывает', count=4)
        self.assertContains(response, 'Общее условие к следующим пяти заданиям', count=1)
        for word in ['Первый', 'Второй', 'Третий', 'Четвёртый', 'Пятый']:
            self.assertContains(response, word + ' вопрос.')

    def test_student_public_and_review_keep_five_questions(self):
        from problems.tests import make_student
        from assignments.models import Assignment
        from worksheets.models import ShareLink, Collection
        student = make_student(self.teacher)
        assignment = Assignment.objects.create(worksheet=self.ws, student=student, assigned_by=self.teacher)
        link = ShareLink.objects.create(worksheet=self.ws)
        collection = Collection.objects.create(worksheet=self.ws, source=self.block.source,
                                                locator='qa-output')
        self.client.force_login(student)
        urls = [reverse('assignment_detail', args=[assignment.pk]),
                reverse('public_worksheet', args=[link.token])]
        for url in urls:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, 'План показывает', count=4)
            self.assertContains(response, 'Пятый вопрос.')
        self.client.force_login(self.teacher)
        for url in [reverse('review_assignment', args=[assignment.pk]),
                    reverse('collection_detail', args=[collection.pk])]:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, 'План показывает', count=4)
            self.assertContains(response, 'Пятый вопрос.')
