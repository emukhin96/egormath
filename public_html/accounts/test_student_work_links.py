"""Переходы из кабинета ученика сохраняют доступ к своей проверенной работе."""
from html.parser import HTMLParser

from django.test import TestCase
from django.urls import reverse

from assignments.models import Assignment
from assignments.tests import make_assignment
from problems.tests import make_student, make_teacher


class LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self.links.append(dict(attrs).get('href', ''))


class StudentWorkLinksTests(TestCase):
    def test_reviewed_work_opens_from_dashboard_only_for_owner(self):
        teacher = make_teacher()
        student = make_student(teacher)
        other = make_student(teacher, 'other-student')
        assignment = make_assignment(teacher, student, status=Assignment.STATUS_REVIEWED)
        self.client.force_login(student)
        page = self.client.get(reverse('dashboard'))
        parser = LinkParser()
        parser.feed(page.content.decode())
        detail = reverse('assignment_detail', args=[assignment.pk])
        self.assertIn(detail, parser.links)
        self.assertNotIn(reverse('review_assignment', args=[assignment.pk]), parser.links)
        self.assertEqual(self.client.get(detail).status_code, 200)
        self.client.force_login(other)
        self.assertEqual(self.client.get(detail).status_code, 404)
