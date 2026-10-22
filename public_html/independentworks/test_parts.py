"""Подробный вид: выбор подпунктов кандидата и разделение на кандидатов."""
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from accounts.models import Profile
from problems.models import Task, TaskSubitem
from . import services as svc
from .models import Work, Position, Candidate

AJAX = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}


@override_settings(INDEPENDENT_WORKS_ENABLED=True)
class CandidatePartsTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.teacher = User.objects.create_user('parts_teacher')
        Profile.objects.create(user=self.teacher, role='teacher')
        self.client.force_login(self.teacher)
        self.work = Work.objects.create(owner=self.teacher, title='С-4')
        self.task = Task.objects.create(text_latex='Решите уравнения')
        self.parts = [TaskSubitem.objects.create(task=self.task, order=i, text_latex=f'$x={i}$', answer_latex=str(i))
                      for i in range(3)]
        self.other = Task.objects.create(text_latex='Отдельная задача', answer_latex='5')
        self.p1 = Position.objects.create(work=self.work, order=1)
        self.p2 = Position.objects.create(work=self.work, order=2)
        self.c1 = Candidate.objects.create(position=self.p1, task=self.task)
        self.c2 = Candidate.objects.create(position=self.p2, task=self.other)
        self.url = reverse('independentworks:candidate_parts', args=[self.work.pk])

    def post(self, mode, *parts, candidate=None):
        return self.client.post(self.url, {'candidate': candidate or self.c1.pk, 'mode': mode,
                                           'parts': [p.pk for p in parts]}, **AJAX)

    def test_keep_selected_parts_like_worksheet(self):
        response = self.post('keep', self.parts[1], self.parts[2])
        self.assertEqual(response.status_code, 200)
        self.c1.refresh_from_db()
        self.assertEqual(self.c1.subitem_ids, [self.parts[1].pk, self.parts[2].pk])
        # Все отмеченные — снова вся задача.
        self.post('keep', *self.parts)
        self.c1.refresh_from_db()
        self.assertEqual(self.c1.subitem_ids, [])
        self.assertEqual(self.post('keep').status_code, 400)

    def test_split_makes_one_candidate_per_part(self):
        response = self.post('split', self.parts[1], self.parts[2])
        self.assertEqual(response.status_code, 200)
        rows = list(self.p1.candidates.order_by('pk'))
        self.assertEqual([c.subitem_ids for c in rows], [[self.parts[1].pk], [self.parts[2].pk]])
        self.assertEqual(rows[0].pk, self.c1.pk)
        # Варианты получают разные подпункты одной задачи.
        variants, _, _ = svc.generate(svc.material(self.work), 2, 1)
        labels = sorted(p['source_key'] for rows in variants for p in rows if p['position'] == 1)
        self.assertEqual(labels, [f't{self.task.pk}:s{self.parts[1].pk}', f't{self.task.pk}:s{self.parts[2].pk}'])
        self.assertEqual(self.post('split', self.parts[0]).status_code, 400)

    def test_split_piece_moves_to_other_position(self):
        self.post('split', *self.parts)
        piece = self.p1.candidates.order_by('pk').last()
        response = self.client.post(reverse('independentworks:move_candidate', args=[self.work.pk]),
                                    {'candidate': piece.pk, 'target': self.p2.pk}, **AJAX)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.p2.candidates.count(), 2)
        self.assertEqual(self.p1.candidates.count(), 2)

    def test_separate_task_dragged_into_position(self):
        response = self.client.post(reverse('independentworks:move_candidate', args=[self.work.pk]),
                                    {'candidate': self.c2.pk, 'target': self.p1.pk}, **AJAX)
        self.assertEqual(response.status_code, 200)
        self.assertEqual({c.task_id for c in self.p1.candidates.all()}, {self.task.pk, self.other.pk})
        self.assertFalse(Position.objects.filter(pk=self.p2.pk).exists())

    def test_edit_page_shows_part_choices_and_grip(self):
        page = self.client.get(reverse('independentworks:edit', args=[self.work.pk]))
        self.assertContains(page, 'data-iw-detail-parts')
        self.assertContains(page, 'Разделить на кандидаты')
        self.assertContains(page, 'iw-detail-grip')

    def test_foreign_work_is_404(self):
        User = get_user_model()
        stranger = User.objects.create_user('parts_stranger')
        Profile.objects.create(user=stranger, role='teacher')
        self.client.force_login(stranger)
        self.assertEqual(self.post('split', *self.parts).status_code, 404)
