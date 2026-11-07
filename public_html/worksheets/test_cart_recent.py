"""Меню корзины: «последние листки» без подборок — тот же состав, что у
``collection__isnull=True``, и индекс по ``updated_at`` у листков и
самостоятельных (аудит быстродействия 06.11.2026)."""
from django.contrib.auth.models import User
from django.test import TestCase

from accounts.models import Profile
from independentworks.models import Work
from problems.models import Source
from worksheets.cart import personal_worksheets
from worksheets.models import Collection, Worksheet


def make_teacher(username, **profile_fields):
    user = User.objects.create_user(username=username, password='pass12345')
    Profile.objects.create(user=user, role=Profile.ROLE_TEACHER, **profile_fields)
    return user


class PersonalWorksheetsTests(TestCase):
    def setUp(self):
        self.teacher = make_teacher('teacher1', base_editor=True)
        self.other = make_teacher('teacher2')
        self.admin = User.objects.create_superuser('admin', 'a@example.com', 'pass12345')
        source = Source.objects.create(title='Учебник')
        self.own = [Worksheet.objects.create(owner=self.teacher, title=f'Свой {i}')
                    for i in range(3)]
        self.foreign = Worksheet.objects.create(owner=self.other, title='Чужой')
        for i, owner in enumerate((self.teacher, self.other)):
            backing = Worksheet.objects.create(owner=owner, title=f'Подборка {i}')
            Collection.objects.create(worksheet=backing, source=source,
                                      locator=f'ch{i}', source_path=['Глава'])

    @staticmethod
    def legacy(user):
        return Worksheet.visible_to(user).filter(collection__isnull=True)

    def test_same_rows_as_left_join(self):
        for user in (self.teacher, self.other, self.admin):
            with self.subTest(user=user.username):
                self.assertEqual(
                    list(personal_worksheets(user).order_by('-updated_at', '-pk')
                         .values_list('pk', flat=True)),
                    list(self.legacy(user).order_by('-updated_at', '-pk')
                         .values_list('pk', flat=True)))

    def test_collections_and_foreign_excluded(self):
        pks = set(personal_worksheets(self.teacher).values_list('pk', flat=True))
        self.assertEqual(pks, {w.pk for w in self.own})
        self.assertEqual(
            set(personal_worksheets(self.admin).values_list('pk', flat=True)),
            {w.pk for w in self.own} | {self.foreign.pk})

    def test_no_join_in_sql(self):
        sql = str(personal_worksheets(self.admin).order_by('-updated_at').query)
        self.assertNotIn('JOIN', sql.upper())
        self.assertIn('NOT EXISTS', sql.upper())


class UpdatedAtIndexTests(TestCase):
    def test_models_declare_updated_at_index(self):
        for model, name in ((Worksheet, 'worksheet_updated_at_idx'),
                            (Work, 'iw_work_updated_at_idx')):
            with self.subTest(model=model.__name__):
                index = next(i for i in model._meta.indexes if i.name == name)
                self.assertEqual(index.fields, ['updated_at'])
