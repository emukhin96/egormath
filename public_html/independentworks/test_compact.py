"""Компактный вид конструктора: перенос плашек, объединение номеров, отмена."""
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from accounts.models import Profile
from problems.models import Task, TaskSubitem, TaskSource, Source, TaskBlock
from .models import Work, Position, Candidate, Family

AJAX = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}


@override_settings(INDEPENDENT_WORKS_ENABLED=True)
class CompactBuilderTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.teacher = User.objects.create_user('compact_teacher')
        Profile.objects.create(user=self.teacher, role='teacher')
        self.client.force_login(self.teacher)
        self.work = Work.objects.create(owner=self.teacher, title='С-3')
        self.tasks = [Task.objects.create(text_latex=f'Решите $x^2={n * n}$', answer_latex=f'\\pm {n}')
                      for n in range(1, 5)]
        # №1: задачи 0 и 1; №2: задача 2; №3: задача 3.
        self.p1 = Position.objects.create(work=self.work, order=1)
        self.p2 = Position.objects.create(work=self.work, order=2)
        self.p3 = Position.objects.create(work=self.work, order=3)
        self.c0 = Candidate.objects.create(position=self.p1, task=self.tasks[0])
        self.c1 = Candidate.objects.create(position=self.p1, task=self.tasks[1])
        self.c2 = Candidate.objects.create(position=self.p2, task=self.tasks[2])
        self.c3 = Candidate.objects.create(position=self.p3, task=self.tasks[3])

    def url(self, name):
        return reverse(f'independentworks:{name}', args=[self.work.pk])

    def layout(self):
        """Состав: список номеров, у каждого — множество id задач."""
        return [{c.task_id for c in p.candidates.all()} for p in self.work.positions.all()]

    def ids(self, *indexes):
        return {self.tasks[i].pk for i in indexes}

    def undo(self):
        token = self.client.session['iw_undo']['token']
        return self.client.post(self.url('undo_compact'), {'token': token}, **AJAX)

    def test_move_to_other_position_removes_empty_and_renumbers(self):
        response = self.client.post(self.url('move_candidate'), {'candidate': self.c2.pk, 'target': self.p3.pk}, **AJAX)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['message'], 'Объединено в №2')
        self.assertFalse(Position.objects.filter(pk=self.p2.pk).exists())
        self.assertEqual(self.layout(), [self.ids(0, 1), self.ids(2, 3)])
        self.assertEqual(list(self.work.positions.values_list('order', flat=True)), [1, 2])
        # Тост с «Отменить» показывается один раз — на следующей странице.
        page = self.client.get(self.url('edit'))
        self.assertContains(page, 'id="iw-undo"')
        self.assertContains(page, 'data-message="Объединено в №2"')
        self.assertNotContains(self.client.get(self.url('edit')), 'id="iw-undo"')

    def test_move_into_gap_creates_position_in_place(self):
        response = self.client.post(self.url('move_candidate'), {'candidate': self.c1.pk, 'before': self.p3.pk}, **AJAX)
        self.assertEqual(response.json()['message'], 'Вынесено в отдельный №3')
        self.assertEqual(self.layout(), [self.ids(0), self.ids(2), self.ids(1), self.ids(3)])
        response = self.client.post(self.url('move_candidate'), {'candidate': self.c0.pk, 'before': ''}, **AJAX)
        self.assertEqual(self.layout(), [self.ids(2), self.ids(1), self.ids(3), self.ids(0)])
        # Единственная задача номера рядом со своим местом — без изменений.
        last = self.work.positions.last()
        response = self.client.post(self.url('move_candidate'), {'candidate': self.c0.pk, 'before': last.pk}, **AJAX)
        self.assertFalse(response.json()['changed'])
        self.assertTrue(Position.objects.filter(pk=last.pk).exists())

    def test_note_position_survives_and_does_not_accept_tasks(self):
        self.p2.text = 'Пояснение к номеру'
        self.p2.save()
        self.client.post(self.url('move_candidate'), {'candidate': self.c2.pk, 'target': self.p1.pk}, **AJAX)
        self.p2.refresh_from_db()
        self.assertEqual(self.p2.text, 'Пояснение к номеру')
        self.assertFalse(self.p2.candidates.exists())
        response = self.client.post(self.url('move_candidate'), {'candidate': self.c3.pk, 'target': self.p2.pk}, **AJAX)
        self.assertEqual(response.status_code, 400)
        self.assertIn('Пояснение', response.json()['message'])

    def test_block_task_is_not_moved_alone(self):
        source = Source.objects.create(title='Блоки')
        block = TaskBlock.objects.create(source=source, key='b', title='Блок', size=2)
        member = Task.objects.create(text_latex='Вопрос 1', block=block, block_position=1)
        position = Position.objects.create(work=self.work, order=4)
        candidate = Candidate.objects.create(position=position, task=member)
        response = self.client.post(self.url('move_candidate'), {'candidate': candidate.pk, 'target': self.p1.pk}, **AJAX)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['message'], 'Задачи блока переносятся только вместе.')
        response = self.client.post(self.url('move_candidate'), {'candidate': self.c3.pk, 'target': position.pk}, **AJAX)
        self.assertEqual(response.status_code, 400)
        candidate.refresh_from_db()
        self.assertEqual(candidate.position_id, position.pk)
        page = self.client.get(self.url('edit'))
        self.assertContains(page, 'title="Задачи блока переносятся только вместе"')
        self.assertContains(page, 'data-closed="1"')

    def test_same_task_parts_cannot_meet_in_one_position(self):
        task = Task.objects.create(text_latex='С подпунктами')
        a = TaskSubitem.objects.create(task=task, text_latex='а', order=1)
        b = TaskSubitem.objects.create(task=task, text_latex='б', order=2)
        Candidate.objects.create(position=self.p2, task=task, subitem_ids=[a.pk])
        other = Candidate.objects.create(position=self.p3, task=task, subitem_ids=[b.pk])
        response = self.client.post(self.url('move_candidate'), {'candidate': other.pk, 'target': self.p2.pk}, **AJAX)
        self.assertEqual(response.status_code, 400)
        response = self.client.post(self.url('merge_positions'), {'ids': f'{self.p2.pk},{self.p3.pk}'}, **AJAX)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.work.positions.count(), 3)

    def test_foreign_work_is_not_found(self):
        stranger = get_user_model().objects.create_user('compact_stranger')
        Profile.objects.create(user=stranger, role='teacher')
        self.client.force_login(stranger)
        for name, data in [('move_candidate', {'candidate': self.c2.pk, 'target': self.p3.pk}),
                           ('merge_positions', {'ids': f'{self.p2.pk},{self.p3.pk}'}),
                           ('undo_compact', {'token': 'x'})]:
            self.assertEqual(self.client.post(self.url(name), data, **AJAX).status_code, 404)
        # Чужой кандидат в своей работе — тоже 404.
        own = Work.objects.create(owner=stranger, title='Своя')
        target = Position.objects.create(work=own)
        response = self.client.post(reverse('independentworks:move_candidate', args=[own.pk]),
                                    {'candidate': self.c2.pk, 'target': target.pk}, **AJAX)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(Candidate.objects.get(pk=self.c2.pk).position_id, self.p2.pk)

    def test_merge_keeps_first_number_and_notes(self):
        self.p3.text = 'Указание к третьему'
        self.p3.save()
        response = self.client.post(self.url('merge_positions'), {'ids': f'{self.p3.pk},{self.p2.pk}'}, **AJAX)
        self.assertEqual(response.json()['message'], 'Объединено в №2')
        self.assertEqual(self.layout(), [self.ids(0, 1), self.ids(2, 3)])
        self.p2.refresh_from_db()
        self.assertEqual(self.p2.text, 'Указание к третьему')
        self.assertEqual(self.client.post(self.url('merge_positions'), {'ids': str(self.p1.pk)}, **AJAX).status_code, 400)

    def test_undo_restores_deleted_position_with_text_and_flags(self):
        self.p3.text = 'Указание'
        self.p3.mismatch_confirmed = True
        self.p3.confirmed_composition = 'abc'
        self.p3.save()
        self.client.post(self.url('merge_positions'), {'ids': f'{self.p2.pk},{self.p3.pk}'}, **AJAX)
        self.assertFalse(Position.objects.filter(pk=self.p3.pk).exists())
        response = self.undo()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.layout(), [self.ids(0, 1), self.ids(2), self.ids(3)])
        restored = Position.objects.get(pk=self.p3.pk)
        self.assertEqual((restored.order, restored.text, restored.mismatch_confirmed, restored.confirmed_composition),
                         (3, 'Указание', True, 'abc'))
        self.p2.refresh_from_db()
        self.assertEqual(self.p2.text, '')
        # Токен одноразовый.
        response = self.client.post(self.url('undo_compact'), {'token': 'used'}, **AJAX)
        self.assertEqual(response.status_code, 409)

    def test_undo_gap_move_and_refuses_after_other_change(self):
        self.client.post(self.url('move_candidate'), {'candidate': self.c0.pk, 'before': ''}, **AJAX)
        self.assertEqual(self.work.positions.count(), 4)
        self.undo()
        self.assertEqual(self.layout(), [self.ids(0, 1), self.ids(2), self.ids(3)])
        self.client.post(self.url('move_candidate'), {'candidate': self.c2.pk, 'target': self.p1.pk}, **AJAX)
        self.client.post(self.url('edit'), {'action': 'candidate_remove', 'candidate': self.c3.pk})
        response = self.undo()
        self.assertEqual(response.status_code, 409)
        self.assertFalse(Position.objects.filter(pk=self.p2.pk).exists())

    def test_similar_hint_for_neighbours_from_one_family(self):
        family = Family.objects.create(key='manual:roots', title='неполные квадратные')
        family.tasks.add(self.tasks[2], self.tasks[3])
        source = Source.objects.create(title='Мерзляк 8')
        TaskSource.objects.create(task=self.tasks[2], source=source, number='398')
        page = self.client.get(self.url('edit'))
        hints = page.context['similar_hints']
        self.assertEqual([(h['first'].pk, h['second'].pk) for h in hints], [(self.p2.pk, self.p3.pk)])
        self.assertContains(page, 'Похожи:</b> №2 и №3 — обе из семьи «неполные квадратные»')
        self.assertContains(page, f'data-merge="{self.p2.pk},{self.p3.pk}"')
        self.assertContains(page, 'Мерзляк 8, №398')
        self.assertContains(page, f'Задача #{self.tasks[3].pk}')
        # №1 с двумя кандидатами подсказку не получает.
        family.tasks.add(self.tasks[0])
        self.assertEqual(len(self.client.get(self.url('edit')).context['similar_hints']), 1)
