from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from accounts.models import Profile

from .latex_utils import escape_latex, strip_latex
from .models import Tag, Task, Topic


def make_teacher(username='teacher1'):
    user = User.objects.create_user(username=username, password='pass12345',
                                    first_name='Иван', last_name='Учителев')
    Profile.objects.create(user=user, role=Profile.ROLE_TEACHER)
    return user


def make_student(teacher, username='student1'):
    user = User.objects.create_user(username=username, password='pass12345',
                                    first_name='Петя', last_name='Ученик/ов')
    Profile.objects.create(user=user, role=Profile.ROLE_STUDENT,
                           grade=8, teacher=teacher)
    return user


class LatexUtilsTests(TestCase):
    def test_escape_latex(self):
        self.assertEqual(escape_latex('50% & #1'), r'50\% \& \#1')
        self.assertIn(r'\textbackslash', escape_latex('a\\b'))

    def test_strip_latex(self):
        s = strip_latex(r'Решите уравнение $x^2-5x+6=0$ \textbf{устно}')
        self.assertIn('Решите уравнение', s)
        self.assertNotIn('\\textbf', s)


class TaskModelTests(TestCase):
    def test_text_plain_autofill(self):
        task = Task.objects.create(text_latex=r'Найдите \emph{корни}: $x^2=4$')
        self.assertIn('Найдите', task.text_plain)
        self.assertNotIn('\\emph', task.text_plain)

    def test_topic_descendants(self):
        root = Topic.objects.create(name='Алгебра')
        child = Topic.objects.create(name='Уравнения', parent=root)
        grandchild = Topic.objects.create(name='Квадратные', parent=child)
        ids = root.descendants_ids()
        self.assertIn(child.pk, ids)
        self.assertIn(grandchild.pk, ids)


class CatalogViewTests(TestCase):
    def setUp(self):
        self.teacher = make_teacher()
        self.student = make_student(self.teacher)
        self.topic = Topic.objects.create(name='Дроби')
        self.tag = Tag.objects.create(name='ОГЭ')
        self.task = Task.objects.create(
            text_latex='Сократите дробь $\\frac{2}{4}$',
            grade_level=6, created_by=self.teacher)
        self.task.topics.add(self.topic)
        self.task.tags.add(self.tag)

    def test_catalog_requires_teacher(self):
        self.client.login(username='student1', password='pass12345')
        response = self.client.get(reverse('task_list'))
        self.assertEqual(response.status_code, 403)

    def test_catalog_search(self):
        self.client.login(username='teacher1', password='pass12345')
        response = self.client.get(reverse('task_list'), {'q': 'дробь'})
        self.assertContains(response, 'Сократите')
        response = self.client.get(reverse('task_list'), {'q': 'логарифм'})
        self.assertNotContains(response, 'Сократите')

    def test_catalog_filters(self):
        self.client.login(username='teacher1', password='pass12345')
        response = self.client.get(reverse('task_list'),
                                   {'topic': self.topic.pk, 'grade': 6,
                                    'tag': 'ОГЭ'})
        self.assertContains(response, 'Сократите')

    def test_task_create(self):
        self.client.login(username='teacher1', password='pass12345')
        response = self.client.post(reverse('task_create'), {
            'text_latex': 'Вычислите $2+2$',
            'subitems_latex': '', 'columns': 0,
            'answer_latex': '4', 'solution_latex': '',
            'stars': 0, 'answer_type': 'number',
            'source_refs-TOTAL_FORMS': 1,
            'source_refs-INITIAL_FORMS': 0,
            'source_refs-MIN_NUM_FORMS': 0,
            'source_refs-MAX_NUM_FORMS': 1000,
        })
        task = Task.objects.get(answer_latex='4')
        self.assertRedirects(response, reverse('task_detail', args=[task.pk]))
        self.assertEqual(task.created_by, self.teacher)
