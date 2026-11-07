"""Входы на экран «Доски учеников»: ссылка сразу на доску (?task=&open=),
значок доски в карте ответов, ссылки на проверке и в окнах карты, права."""
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from accounts.models import StudentGroup
from assignments.models import Assignment, Submission
from problems.tests import make_student, make_teacher
from worksheets.models import WorksheetItem
from worksheets.tests import make_worksheet

from . import boards, services
from .models import CanvasPage


class BoardsEntryTests(TestCase):
    def setUp(self):
        self.teacher = make_teacher()
        self.worksheet = make_worksheet(self.teacher, n_tasks=2)
        self.items = list(WorksheetItem.objects.filter(worksheet=self.worksheet).order_by('order'))
        self.task1, self.task2 = (item.task for item in self.items)
        self.students = [make_student(self.teacher, username=f's{i}') for i in range(3)]
        for i, user in enumerate(self.students):
            user.last_name = f'Фамилия{i}'
            user.save(update_fields=['last_name'])
        self.assignments = [Assignment.objects.create(worksheet=self.worksheet, student=s, assigned_by=self.teacher)
                            for s in self.students]
        self.client.force_login(self.teacher)

    def board(self, assignment, task, minutes_ago=0):
        submission, _ = Submission.objects.get_or_create(assignment=assignment, task=task)
        return CanvasPage.objects.create(submission=submission, number=1,
                                         student_elements=[{'id': 'a1', 't': 'path', 'c': '#111827', 'w': 3, 'p': [[100, 100], [400, 300]]}],
                                         student_updated_at=timezone.now() - timezone.timedelta(minutes=minutes_ago))

    def boards_page(self, **params):
        return self.client.get(reverse('worksheet_boards', args=[self.worksheet.pk]), params)

    def live(self, **params):
        return self.client.get(reverse('worksheet_boards_live', args=[self.worksheet.pk]), params).json()

    # --- ссылка сразу на доску -------------------------------------------------

    def test_open_param_marks_dialog_and_keeps_live_query(self):
        target = self.assignments[1]
        page = self.boards_page(task=self.task2.pk, open=target.pk)
        self.assertContains(page, f'data-open="{target.pk}"')
        self.assertContains(page, f'data-task="{self.task2.pk}"')
        # живой опрос держит открытого ученика на экране тем же параметром
        self.assertContains(page, f'open={target.pk}')
        self.assertContains(page, 'data-canvas-url="/assignments/0/canvas/0/"')
        # подсказка клавиш и кнопки соседей в диалоге
        self.assertContains(page, 'data-dialog-step="-1"')
        self.assertContains(page, '1–9 задача')

    def test_open_outside_first_boards_max(self):
        """Ученик вне первых BOARDS_MAX: его карточку сервер всё равно ставит
        на экран, «не поместилось» уменьшается."""
        fresh, _, stale = self.assignments
        self.board(fresh, self.task1)
        self.board(self.assignments[1], self.task1, minutes_ago=5)
        original, boards.BOARDS_MAX = boards.BOARDS_MAX, 1
        try:
            plain = self.live()
            opened = self.live(open=stale.pk)
            page = self.boards_page(open=stale.pk)
        finally:
            boards.BOARDS_MAX = original
        self.assertEqual([s['assignment'] for s in plain['states']], [fresh.pk])
        self.assertEqual(plain['overflow'], 2)
        self.assertEqual([s['assignment'] for s in opened['states']], [fresh.pk, stale.pk])
        self.assertEqual(opened['overflow'], 1)
        self.assertContains(page, f'data-board="{stale.pk}"')
        self.assertContains(page, f'data-open="{stale.pk}"')

    def test_open_with_group(self):
        """С группой: ученик группы открывается как обычно, ученик вне группы
        тоже на экране — его доску открыли по ссылке."""
        group = StudentGroup.objects.create(name='8А', teacher=self.teacher)
        group.students.add(self.students[0])
        ids = [s['assignment'] for s in self.live(group=group.pk, open=self.assignments[0].pk)['states']]
        self.assertEqual(ids, [self.assignments[0].pk])
        ids = [s['assignment'] for s in self.live(group=group.pk, open=self.assignments[2].pk)['states']]
        self.assertEqual(sorted(ids), sorted([self.assignments[0].pk, self.assignments[2].pk]))

    def test_open_ignores_foreign_and_garbage(self):
        """Учитель видит доски только своих учеников: чужое назначение в ?open=
        не попадает ни на экран, ни в опрос."""
        other = make_teacher('teacher2')
        foreign = Assignment.objects.create(worksheet=make_worksheet(other, n_tasks=1),
                                            student=make_student(other, username='alien'), assigned_by=other)
        self.board(foreign, foreign.worksheet.items.first().task)
        for value in (foreign.pk, 'abc', 999999):
            page = self.boards_page(open=value)
            self.assertNotContains(page, 'data-open=')
            self.assertNotContains(page, f'data-board="{foreign.pk}"')
            self.assertNotIn(foreign.pk, [s['assignment'] for s in self.live(open=value)['states']])
        # и саму доску чужого ученика не отдают
        self.assertEqual(self.client.get(reverse('canvas:pages', args=[foreign.pk, foreign.worksheet.items.first().task_id])).status_code, 404)
        # чужой листок — 404 и для экрана досок
        self.assertEqual(self.client.get(reverse('worksheet_boards', args=[foreign.worksheet_id]),
                                         {'open': foreign.pk}).status_code, 404)

    # --- карта ответов ---------------------------------------------------------

    def progress(self, **params):
        return self.client.get(reverse('worksheet_progress', args=[self.worksheet.pk]), params)

    def test_progress_cell_board_icon_and_row_link(self):
        with_board, without = self.assignments[0], self.assignments[1]
        self.board(with_board, self.task2)
        page = self.progress()
        url = reverse('worksheet_boards', args=[self.worksheet.pk])
        self.assertContains(page, f'href="{url}?task={self.task2.pk}&amp;open={with_board.pk}"', count=1)
        self.assertContains(page, f'href="{url}?open={with_board.pk}"', count=1)
        self.assertNotContains(page, f'open={without.pk}')
        self.assertContains(page, 'class="live-board"', count=1)
        self.assertContains(page, 'aria-label="Доска: ', count=1)

    def test_progress_board_link_keeps_group(self):
        group = StudentGroup.objects.create(name='8А', teacher=self.teacher)
        group.students.add(*self.students)
        self.board(self.assignments[0], self.task1)
        self.assertContains(self.progress(group=group.pk), f'open={self.assignments[0].pk}&amp;group={group.pk}')

    def test_board_tasks_single_query(self):
        for assignment in self.assignments:
            self.board(assignment, self.task1)
            self.board(assignment, self.task2)
        with CaptureQueriesContext(connection) as queries:
            result = services.board_tasks(Assignment.objects.filter(worksheet=self.worksheet))
        self.assertEqual(len(queries), 1)
        self.assertEqual(result, {a.pk: {self.task1.pk, self.task2.pk} for a in self.assignments})

    def test_progress_queries_do_not_grow_with_boards(self):
        """Значок без N+1: доски у всех учеников не добавляют запросов."""
        for assignment in self.assignments:  # ответы есть заранее: сравниваем только доски
            Submission.objects.create(assignment=assignment, task=self.task1)
        self.progress()  # прогрев кешей
        with CaptureQueriesContext(connection) as before:
            self.progress()
        for assignment in self.assignments:
            self.board(assignment, self.task1)
        with CaptureQueriesContext(connection) as after:
            page = self.progress()
        self.assertContains(page, 'class="live-board"', count=3)
        self.assertLessEqual(len(after), len(before) + 1)

    def test_fragment_etag_changes_with_new_board(self):
        first = self.progress(fragment=1)
        etag = first['ETag']
        self.assertEqual(self.client.get(reverse('worksheet_progress', args=[self.worksheet.pk]),
                                         {'fragment': 1}, HTTP_IF_NONE_MATCH=etag).status_code, 304)
        self.board(self.assignments[0], self.task1)
        fresh = self.client.get(reverse('worksheet_progress', args=[self.worksheet.pk]),
                                {'fragment': 1}, HTTP_IF_NONE_MATCH=etag)
        self.assertEqual(fresh.status_code, 200)
        self.assertContains(fresh, 'class="live-board"')

    def test_detail_window_thumb(self):
        assignment = self.assignments[0]
        self.board(assignment, self.task1)
        url = reverse('task_attempts', args=[assignment.pk, self.task1.pk]) + f'?item={self.items[0].pk}'
        page = self.client.get(url)
        self.assertContains(page, 'data-board-thumb')
        self.assertContains(page, reverse('canvas:pages', args=[assignment.pk, self.task1.pk]))
        self.assertContains(page, f'?task={self.task1.pk}&amp;open={assignment.pk}')
        # без доски блока нет
        url = reverse('task_attempts', args=[assignment.pk, self.task2.pk]) + f'?item={self.items[1].pk}'
        self.assertNotContains(self.client.get(url), 'data-board-thumb')

    def test_thumb_script_with_detail_window(self):
        """Скрипт миниатюры идёт вместе с окном ответа: и на карте ответов, и на
        экране досок, и на страницах без canvas.js (ревью #332), и только при
        включённых досках."""
        for url in (reverse('worksheet_progress', args=[self.worksheet.pk]),
                    reverse('worksheet_boards', args=[self.worksheet.pk]),
                    reverse('assignment_timeline', args=[self.assignments[0].pk])):
            page = self.client.get(url)
            self.assertContains(page, 'js/board_thumbs.js', count=1)
            # где canvas.js нет (хронология), скрипт подгрузит его сам — адрес передаётся
            self.assertContains(page, 'data-canvas-src="/static/js/canvas.js')
            with self.settings(CANVAS_ENABLED=False):
                self.assertNotContains(self.client.get(url), 'js/board_thumbs.js')

    def test_task_window_links(self):
        self.board(self.assignments[2], self.task1)
        page = self.client.get(reverse('worksheet_task_window', args=[self.worksheet.pk, self.items[0].pk]))
        boards_url = reverse('worksheet_boards', args=[self.worksheet.pk])
        self.assertContains(page, f'href="{boards_url}?task={self.task1.pk}">Доски по задаче')
        self.assertContains(page, f'?task={self.task1.pk}&amp;open={self.assignments[2].pk}')

    # --- проверка работы -------------------------------------------------------

    def test_review_links(self):
        assignment = self.assignments[0]
        self.board(assignment, self.task1)
        page = self.client.get(reverse('review_assignment', args=[assignment.pk]))
        boards_url = reverse('worksheet_boards', args=[self.worksheet.pk])
        self.assertContains(page, f'href="{boards_url}?task={self.task1.pk}&amp;open={assignment.pk}"', count=1)
        # «Все доски по задаче» — у каждой задачи, «На экране досок» — только где доска есть
        self.assertContains(page, 'Все доски по задаче', count=2)
        self.assertContains(page, '>На экране досок</a>', count=1)

    def test_canvas_disabled_hides_entries(self):
        self.board(self.assignments[0], self.task1)
        with self.settings(CANVAS_ENABLED=False):
            self.assertNotContains(self.progress(), 'class="live-board"')
            self.assertNotContains(self.client.get(reverse('review_assignment', args=[self.assignments[0].pk])),
                                   'Все доски по задаче')
