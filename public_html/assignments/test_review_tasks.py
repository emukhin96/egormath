"""Проверка по задачам (макет D_Review, assignments/review_tasks.py):
очередь, группы ответов, оценка группе «Всем N», вкладка «Ученики», входы."""
from django.test import TestCase
from django.urls import reverse

from problems.models import Task
from problems.tests import make_student, make_teacher
from worksheets.models import WorksheetItem
from worksheets.tests import make_worksheet
from .models import Assignment, Review, Submission, SubmissionCheckAttempt


class ReviewTasksTests(TestCase):
    def setUp(self):
        self.teacher = make_teacher()
        self.worksheet = make_worksheet(self.teacher)
        WorksheetItem.objects.filter(worksheet=self.worksheet).delete()
        self.tasks = [Task.objects.create(text_latex=f'Найдите площадь {n}', answer_mask='S = {{number: 30}}') for n in (1, 2)]
        self.items = [WorksheetItem.objects.create(worksheet=self.worksheet, task=t, order=n) for n, t in enumerate(self.tasks, 1)]
        self.assignments = {}
        for username, last, value, result in [('anna', 'Белова', '30', 'ok'), ('ilya', 'Громов', '30', 'ok'),
                                               ('oleg', 'Жуков', '23', 'wrong'), ('dasha', 'Ким', '23', 'wrong'),
                                               ('petr', 'Фомин', '2', 'wrong'), ('nika', 'Морозова', None, None)]:
            student = make_student(self.teacher, username=username)
            student.last_name = last
            student.save()
            assignment = Assignment.objects.create(worksheet=self.worksheet, student=student, assigned_by=self.teacher)
            self.assignments[username] = assignment
            if value:
                sub = Submission.objects.create(assignment=assignment, task=self.tasks[0], answer_json={'s1': value})
                SubmissionCheckAttempt.objects.create(submission=sub, number=1, result=result, snapshot={
                    'targets': [{'kind': 'task', 'id': self.tasks[0].pk, 'answer': f'S = {value}', 'result': result}]})
        self.url = reverse('assignment_review_queue', args=[self.worksheet.pk])
        self.client.force_login(self.teacher)

    def test_queue_and_groups(self):
        response = self.client.get(self.url)
        self.assertEqual(response.context['current']['item'], self.items[0])
        self.assertEqual([(t['number'], t['pending']) for t in response.context['tasks']], [(1, 5), (2, 0)])
        groups = response.context['groups']
        self.assertEqual([(g['kind'], g['verdict'], len(g['rows'])) for g in groups],
                         [('wrong', 'Неверно по автосверке, частая ошибка', 2), ('wrong', 'Неверно по автосверке', 1),
                          ('ok', 'Верно по автосверке', 2)])
        self.assertEqual(groups[2]['suggested'], '+')
        self.assertContains(response, 'class="is-suggested"')
        self.assertContains(response, reverse('grade_task', args=[self.assignments['oleg'].pk, self.tasks[0].pk]))
        self.assertContains(response, 'Оценено <span data-review-graded data-base="0">0</span> ответов из 5')
        self.assertNotContains(response, '·')
        # «Дальше» нет: других задач с ответами без оценки нет
        self.assertIsNone(response.context['next'])

    def test_group_grade(self):
        url = reverse('assignment_review_group_grade', args=[self.worksheet.pk, self.items[0].pk])
        ids = f"{self.assignments['anna'].pk},{self.assignments['ilya'].pk}"
        result = self.client.post(url, {'grade': '+', 'assignments': ids}).json()
        self.assertEqual(len(result['urls']), 2)
        self.assertEqual(set(Review.objects.values_list('grade', flat=True)), {'+'})
        self.assertEqual(self.assignments['anna'].result()['done'], 1)
        # чужой листок и неизвестная оценка
        other = Assignment.objects.create(worksheet=make_worksheet(self.teacher), student=make_student(self.teacher, username='x'))
        self.assertEqual(self.client.post(url, {'grade': '-', 'assignments': str(other.pk)}).json()['urls'], [])
        self.assertEqual(self.client.post(url, {'grade': 'excellent', 'assignments': ids}).status_code, 400)
        response = self.client.get(self.url)
        self.assertEqual(response.context['tasks'][0]['pending'], 3)
        self.assertEqual(response.context['groups'][2]['grade'], '+')

    def test_students_tab(self):
        Review.objects.create(submission=Submission.objects.get(assignment=self.assignments['oleg']), grade='-+')
        response = self.client.get(self.url, {'view': 'students'})
        rows = {s['person']['assignment'].student.username: (s['answered'], s['graded']) for s in response.context['students']}
        self.assertEqual(rows['oleg'], (1, 1))
        self.assertEqual(rows['nika'], (0, 0))
        self.assertContains(response, reverse('review_assignment', args=[self.assignments['oleg'].pk]))

    def test_entry_points_and_access(self):
        oleg = self.assignments['oleg']
        oleg.status = Assignment.STATUS_SUBMITTED
        oleg.save()
        self.assertContains(self.client.get(reverse('worksheet_progress', args=[self.worksheet.pk])), self.url)
        self.assertContains(self.client.get(reverse('dashboard')), self.url)
        stranger = make_teacher('stranger')
        self.client.force_login(stranger)
        self.assertEqual(self.client.get(self.url).status_code, 404)


class PartialSubitemsTests(TestCase):
    """Ревью #281: пустой подпункт не делает верный ответ «без автосверки»."""

    def test_partial_answer_is_ok_group(self):
        from .review_tasks import answer_groups
        ok = {'status': 'ok', 'hidden': False, 'answer': '3'}
        empty = {'status': 'empty', 'hidden': False, 'answer': ''}
        row = lambda cells: {'cells': cells, 'grade': '', 'person': {'assignment': type('A', (), {'pk': id(cells)})()}}
        groups = answer_groups([row([ok, empty]), row([dict(ok), dict(ok)])])
        self.assertEqual([(g['kind'], g['verdict'], g['suggested']) for g in groups],
                         [('ok', 'Верно по автосверке', '+'), ('ok', 'Верно по автосверке, не все подпункты', '')])
