"""Правила семей аналогов по вариантам работ и автосвязывание при загрузке.

Локаторы синтетические, в форматах парсеров: Зив, Феоктистов, Высоцкий,
методическое пособие Шабунина и договор будущего профиля «ДМ Мерзляка»
(``ДМ.В{k}/{N}``, ``КР{n}.В{k}/{m}``, решение 07.11.2026).
"""
from django.test import TestCase

from problems.models import Source, Task, TaskSource
from problems.tests import make_teacher
from .analogs import (ANALOG_PROFILES, VARIANT_RULES, ZIV, similar_groups,
                      sync_families, task_family_keys, variant_identity)
from .models import Family, FamilyMember

# Образцы локаторов каждого правила: (правило, локатор).
SAMPLES = [
    ('ziv', 'sr/03/v5/2'), ('ziv', 'kr/1/v8/7'), ('ziv', 'pr/12/v2/3'),
    ('feoktistov', 'sr/01/prep/001'), ('feoktistov', 'kr/07/v3/002'),
    ('feoktistov', 'test/13/v2/006'), ('feoktistov', 'sr/01/v1/001'),
    ('vysotsky', 'С1.2/3'), ('vysotsky', 'КI.3/4'), ('vysotsky', 'КIII.2/1'),
    ('shabunin_method', 'КРII.1.В5/3'), ('shabunin_method', 'ДКРIV.1.В1/10'),
    ('shabunin_method', 'СРIX.2/1'),
    ('merzlyak_dm', 'ДМ.В1/170'), ('merzlyak_dm', 'ДМ.В4/1'),
    ('merzlyak_dm', 'КР3.В2/4'), ('merzlyak_dm', 'КР10.В1/12'),
]
# Не варианты работ: карточки Высоцкого, задачники, банки, «v0» Зива.
NOT_VARIANTS = ['И1.1/2', 'П2.5', 'С9.7', '1.1', '1.1.2', 'I.1.П3', 'IV.12',
                '1970.ВМК.1', 'sr/00/v0/3', 'sr/01/v0/5', '1.2.A01', 'ДМ.В1',
                'КР3/4', 'sr/01/prep', '9 класс/лист#90']


class RuleContractTests(TestCase):
    """Форматы правил не пересекаются: локатор определяет одно правило."""

    def test_each_sample_matches_exactly_one_rule(self):
        for name, locator in SAMPLES:
            matched = [r.name for r in VARIANT_RULES if r.pattern.fullmatch(locator)]
            self.assertEqual(matched, [name], locator)
            self.assertEqual(variant_identity(1, locator)[3].name, name)

    def test_other_locators_are_not_variants(self):
        for locator in NOT_VARIANTS:
            self.assertIsNone(variant_identity(1, locator), locator)

    def test_profiles_with_rules_link_on_import(self):
        self.assertLessEqual({r.name for r in VARIANT_RULES}, ANALOG_PROFILES)
        self.assertLessEqual({'ostromogilsky', 'ostromogilsky_ege'}, ANALOG_PROFILES)

    def test_keys_of_existing_families_are_stable(self):
        # Семьи Высоцкого и Шабунина уже на проде: ключи прежние.
        self.assertEqual(variant_identity(13, 'КI.3/4')[:2],
                         ('variants:13:КI:1:4', 'КI · варианты 3–4 · №4'))
        self.assertEqual(variant_identity(15, 'КРII.1.В5/3')[:2],
                         ('variants:15:КРII.1:all:3', 'КРII.1 · все варианты · №3'))
        self.assertEqual(variant_identity(1, 'sr/03/v5/2')[:2],
                         ('ziv:1:sr:03:2:2', 'sr/03 · варианты 5–6 · №2'))
        self.assertEqual(variant_identity(16, 'kr/01/prep/002')[:2],
                         ('variants:16:kr/01:all:002', 'КР 1 · все варианты · №2'))

    def test_ziv_wizard_does_not_take_feoktistov(self):
        self.assertTrue(ZIV.fullmatch('sr/03/v5/2'))
        self.assertFalse(ZIV.fullmatch('sr/01/v1/001'))


class VariantFamilyTests(TestCase):
    def setUp(self):
        self.source = Source.objects.create(title='Книга')

    def ref(self, locator, source=None):
        task = Task.objects.create(text_latex=locator)
        TaskSource.objects.create(source=source or self.source, task=task, locator=locator)
        return task

    def families(self):
        return {frozenset(f.tasks.all()) for f in Family.objects.all()}

    def test_feoktistov_preparatory_and_three_variants(self):
        sr = [self.ref(f'sr/01/{v}/001') for v in ('prep', 'v1', 'v2', 'v3')]
        test = [self.ref(f'test/02/v{v}/006') for v in (1, 2)]
        lonely = self.ref('kr/01/v3/002')
        report = sync_families(report=True)
        self.assertEqual(self.families(), {frozenset(sr), frozenset(test)})
        self.assertEqual(len(report['incomplete']), 1)
        self.assertFalse(lonely.analog_families.exists())
        self.assertEqual(Family.objects.get(tasks=sr[0]).title,
                         'Книга · СР 1 · все варианты · №1')

    def test_ziv_pairs_are_difficulty_levels(self):
        tasks = {v: self.ref(f'sr/03/v{v}/2') for v in range(1, 9)}
        report = sync_families(report=True)
        self.assertEqual(self.families(), {frozenset({tasks[v], tasks[v + 1]}) for v in (1, 3, 5, 7)})
        self.assertFalse(report['incomplete'])

    def test_ziv_unknown_variant_is_reported_not_linked(self):
        unknown = self.ref('sr/02/v0/5')
        v2 = self.ref('sr/02/v2/5')
        report = sync_families(report=True)
        self.assertFalse(unknown.analog_families.exists())
        self.assertTrue(any('sr/02/v0/5' in m for m in report['ambiguous']), report['ambiguous'])
        self.assertEqual(len(report['incomplete']), 1)
        self.assertFalse(v2.analog_families.exists())

    def test_shabunin_work_without_variant_label(self):
        alone = self.ref('СРIX.2/1')
        self.ref('СРIX.2/2')
        # Работа без вариантов — не неполная пара: в отчёт не попадает.
        report = sync_families(report=True)
        self.assertEqual((report['incomplete'], report['ambiguous']), ([], []))
        self.assertFalse(Family.objects.exists())
        # Вариант без «.В» — первый: подпись потеряна, другие варианты есть.
        second = self.ref('СРIX.2.В2/1')
        sync_families()
        self.assertEqual(self.families(), {frozenset({alone, second})})

    def test_shabunin_unlabeled_and_first_variant_are_ambiguous(self):
        self.ref('СРIX.2/1')
        self.ref('СРIX.2.В1/1')
        self.ref('СРIX.2.В2/1')
        report = sync_families(report=True)
        self.assertFalse(Family.objects.exists())
        self.assertEqual(len(report['ambiguous']), 1)

    def test_merzlyak_dm_contract(self):
        exercise = [self.ref(f'ДМ.В{k}/170') for k in range(1, 5)]
        test = [self.ref(f'КР3.В{k}/4') for k in (1, 2)]
        other_work = self.ref('КР4.В1/4')
        other_number = self.ref('ДМ.В1/171')
        report = sync_families(report=True)
        self.assertEqual(self.families(), {frozenset(exercise), frozenset(test)})
        self.assertEqual(len(report['incomplete']), 2)
        self.assertFalse(other_work.analog_families.exists())
        self.assertFalse(other_number.analog_families.exists())
        self.assertEqual(report['by_source'], [
            {'id': self.source.pk, 'title': 'Книга', 'families': 2, 'created': 2, 'members_added': 6}])

    def test_same_locator_in_other_source_is_other_family(self):
        other = Source.objects.create(title='Другая книга')
        self.ref('ДМ.В1/1')
        self.ref('ДМ.В2/1', source=other)
        report = sync_families(report=True)
        self.assertFalse(Family.objects.exists())
        self.assertEqual(len(report['incomplete']), 2)

    def test_only_additions_manual_and_evidence_kept(self):
        first, second = self.ref('ДМ.В1/5'), self.ref('ДМ.В2/5')
        family = Family.objects.create(key=variant_identity(self.source.pk, 'ДМ.В1/5')[0],
                                       title='Название редактора', origin='source')
        FamilyMember.objects.create(family=family, task=first, origin='manual', evidence=[{'note': 'вручную'}])
        manual = Family.objects.create(key='manual:analog:1', title='Ручная', origin='manual')
        FamilyMember.objects.create(family=manual, task=second, origin='manual')
        report = sync_families(report=True)
        self.assertEqual((report['created'], report['members_added']), (0, 1))
        family.refresh_from_db()
        self.assertEqual(family.title, 'Название редактора')
        kept = family.familymember_set.get(task=first)
        self.assertEqual((kept.origin, kept.evidence), ('manual', [{'note': 'вручную'}]))
        self.assertEqual(family.familymember_set.get(task=second).origin, 'source')
        self.assertEqual(list(manual.tasks.all()), [second])
        self.assertEqual(sync_families(report=True)['members_added'], 0)


class CartFamilyKeysTests(TestCase):
    """Корзина: локальная копия листка — в семье исходной задачи."""

    def test_local_copy_inherits_family_and_source_keys(self):
        source = Source.objects.create(title='Книга')
        original = Task.objects.create(text_latex='Исходная')
        sibling = Task.objects.create(text_latex='Вариант 2')
        TaskSource.objects.create(source=source, task=original, locator='КРII.1.В1/3')
        TaskSource.objects.create(source=source, task=sibling, locator='КРII.1.В2/3')
        copy = Task.objects.create(text_latex='Копия в листке', variant_of=original)
        keys = task_family_keys([copy.pk, sibling.pk])
        self.assertIn(f'variants:{source.pk}:КРII.1:all:3', keys[copy.pk])
        groups = similar_groups([copy.pk, sibling.pk])
        self.assertEqual(groups[copy.pk], groups[sibling.pk])

        manual_peer = Task.objects.create(text_latex='Ручной аналог')
        family = Family.objects.create(key='manual:analog:7', title='Ручная', origin='manual')
        family.tasks.add(original, manual_peer)
        groups = similar_groups([manual_peer.pk, copy.pk])
        self.assertEqual(groups[manual_peer.pk], groups[copy.pk])


class ImportAutolinkTests(TestCase):
    """«Загрузить в каталог» связывает варианты для объявленных профилей."""

    def setUp(self):
        self.user = make_teacher()

    def commit(self, profile, locators):
        from problems.models import TextbookTaskDraft, Topic
        from problems.textbook_import import commit_batch, create_batch_from_bundle
        tasks = [{
            'external_id': locator, 'source_number': locator.rsplit('/', 1)[-1],
            'source_path': ['Работы', locator.rsplit('/', 1)[0]],
            'collection_key': locator.rsplit('/', 1)[0], 'collection_title': 'Работа',
            'topic_original': 'Работа', 'text_latex': f'Условие {locator}.', 'subitems': [],
            'author_answer_latex': '', 'author_solution_latex': '', 'confidence': 1, 'warnings': [],
        } for locator in locators]
        batch = create_batch_from_bundle(
            {'schema_version': 1, 'profile': profile, 'diagnostics': {}, 'tasks': tasks},
            user=self.user, title='Проба', source_title=f'Книга {profile}')
        batch.drafts.update(status=TextbookTaskDraft.STATUS_APPROVED,
                            topic=Topic.objects.get_or_create(name='Тема проверки')[0])
        return batch, commit_batch(batch, user=self.user)

    def test_declared_profiles_link_on_commit(self):
        for profile, locators, members in [
            ('merzlyak_dm', ['ДМ.В1/1', 'ДМ.В2/1', 'ДМ.В3/1', 'ДМ.В4/1'], 4),
            ('feoktistov', ['sr/02/prep/003', 'sr/02/v1/003', 'sr/02/v2/003'], 3),
            ('ziv', ['kr/04/v1/2', 'kr/04/v2/2'], 2),
        ]:
            with self.subTest(profile):
                batch, result = self.commit(profile, locators)
                self.assertEqual((result['analog_families'], result['analog_members']), (1, members))
                family = Family.objects.filter(familymember__task__source_refs__source=batch.source).distinct().get()
                self.assertEqual(family.tasks.count(), members)
                again = self.commit_again(batch)
                self.assertFalse(any(again.values()), again)

    def commit_again(self, batch):
        from problems.textbook_import import commit_batch
        return commit_batch(batch, user=self.user)

    def test_undeclared_profile_is_not_linked(self):
        _batch, result = self.commit('merzlyak', ['ДМ.В1/9', 'ДМ.В2/9'])
        self.assertNotIn('analog_families', result)
        self.assertFalse(Family.objects.exists())
