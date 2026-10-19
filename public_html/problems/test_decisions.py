"""Решения 1, 3, 5, 6 плана пользователей (docs/USERS_PLAN.md, раздел 12,
18.10.2026): тумблер редактора «Показывать задачи других учителей», фильтр
«Мои задачи» и бейдж «моя», нейрогенерация только редакторам, слова
интерфейса без «общая база» / «личная». Публикация подборок (решение 3) —
worksheets/test_authored.py, PublishPermissionTests.
"""
import json
import re
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from accounts.models import Profile
from accounts.permissions import (cart_tasks, catalog_tasks, own_personal_tasks,
                                  shows_foreign_tasks, visible_tasks)
from worksheets.models import Worksheet
from .models import Task, TaskTopic, Topic
from .test_permissions import Roles, shared_task

NEURO_HINT = 'Нейрогенерация доступна только редакторам'


def set_toggle(user, value):
    profile = Profile.for_teacher(user)
    profile.show_foreign_tasks = value
    profile.save(update_fields=['show_foreign_tasks'])


class ForeignTasksToggleTests(Roles, TestCase):
    """Решение 1: редактор базы по умолчанию не видит чужие задачи не из общих
    в каталоге, поиске, фасетах и подборе; по ссылке — открывает всегда."""

    def setUp(self):
        self.make_users()
        self.shared = shared_task(self.editor, 'Общая про дроби')
        self.foreign = Task.new_for(self.guest, text_latex='Гостевая про дроби')
        # Своя задача редактора не из общих (например, до назначения редактором)
        self.own = Task.objects.create(text_latex='Своя не общая', created_by=self.editor, is_shared=False)
        self.topic = Topic.objects.get(code='ALG.07.03')
        TaskTopic.objects.create(task=self.foreign, topic=self.topic)
        self.client.force_login(self.editor)

    def catalog(self, **params):
        return list(self.client.get(reverse('task_list'), params).context['page'])

    def test_querysets_follow_toggle(self):
        self.assertEqual(set(catalog_tasks(self.editor)), {self.shared, self.own})
        # Задача без автора (created_by=NULL) — не «другого учителя»: видна без тумблера
        orphan = Task.objects.create(text_latex='Без автора')
        self.assertIn(orphan, catalog_tasks(self.editor))
        self.assertNotIn(self.foreign, catalog_tasks(self.editor))
        orphan.delete()
        self.assertEqual(set(visible_tasks(self.editor)), {self.shared, self.own, self.foreign})
        self.assertEqual(set(cart_tasks(self.editor)), {self.shared, self.own, self.foreign})
        self.assertFalse(shows_foreign_tasks(self.editor))
        set_toggle(self.editor, True)
        self.assertEqual(set(catalog_tasks(self.editor)), {self.shared, self.own, self.foreign})
        # Тумблер не касается приглашённого: чужие задачи не из общих ему не видны и так
        set_toggle(self.other_guest, True)
        self.assertEqual(set(catalog_tasks(self.other_guest)), {self.shared})
        self.assertEqual(set(own_personal_tasks(self.editor)), {self.own})

    def test_superuser_without_profile_sees_only_shared(self):
        # Без профиля тумблер считается выключенным: чужие (и редактора) не из общих скрыты
        self.assertFalse(Profile.objects.filter(user=self.superuser).exists())
        self.assertFalse(shows_foreign_tasks(self.superuser))
        self.assertEqual(set(catalog_tasks(self.superuser)), {self.shared})
        self.assertEqual(set(visible_tasks(self.superuser)), {self.shared, self.own, self.foreign})

    def test_catalog_search_facets_and_dashboard(self):
        self.assertEqual(set(self.catalog()), {self.shared, self.own})
        self.assertEqual(self.catalog(q='Гостевая'), [])
        self.assertEqual(self.catalog(q=f'#{self.foreign.pk}'), [])
        response = self.client.get(reverse('task_list'))
        root = next(t for t in response.context['topics'] if self.topic.pk in t.subtree_ids)
        self.assertEqual(root.task_total, 0)
        self.assertEqual(self.client.get(reverse('dashboard')).context['tasks_total'], 2)
        set_toggle(self.editor, True)
        self.assertEqual(set(self.catalog()), {self.shared, self.own, self.foreign})
        self.assertEqual(self.catalog(q='Гостевая'), [self.foreign])
        response = self.client.get(reverse('task_list'))
        root = next(t for t in response.context['topics'] if self.topic.pk in t.subtree_ids)
        self.assertEqual(root.task_total, 1)
        self.assertEqual(self.client.get(reverse('dashboard')).context['tasks_total'], 3)

    def test_candidate_picker_follows_toggle(self):
        from independentworks.models import Candidate, Family, Position, Work
        family = Family.objects.create(title='Семья')
        base = Task.objects.create(text_latex='База', is_shared=True)
        family.tasks.add(self.shared, self.foreign, base)
        work = Work.objects.create(owner=self.editor, title='СР')
        position = Position.objects.create(work=work)
        Candidate.objects.create(position=position, task=base)
        with override_settings(INDEPENDENT_WORKS_ENABLED=True):
            response = self.client.get(reverse('independentworks:pick', args=[position.pk]))
            self.assertEqual(set(response.context['recommended']), {self.shared})
            set_toggle(self.editor, True)
            response = self.client.get(reverse('independentworks:pick', args=[position.pk]))
            self.assertEqual(set(response.context['recommended']), {self.shared, self.foreign})

    def test_direct_link_cart_and_proposal_work_without_toggle(self):
        self.assertEqual(self.client.get(reverse('task_detail', args=[self.foreign.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse('task_manage', args=[self.foreign.pk])).status_code, 200)
        response = self.client.post(reverse('cart_add'), {'task_id': self.foreign.pk})
        self.assertIn(response.status_code, (200, 302))
        self.assertIn(self.foreign.pk, self.client.session.get('cart_tasks', []))
        sheet = Worksheet.objects.create(owner=self.editor, title='Листок редактора')
        self.assertIn(self.client.post(reverse('worksheet_add_task', args=[sheet.pk]),
                                       {'task_id': self.foreign.pk}).status_code, (200, 302))
        from .proposals import create_proposal
        proposal = create_proposal(self.guest, self.shared, 'Опечатка в общей')
        response = self.client.get(reverse('proposal_detail', args=[proposal.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Опечатка в общей')

    def test_toggle_markup_and_prefs_view(self):
        response = self.client.get(reverse('task_list'), {'q': 'дроби'})
        self.assertContains(response, 'name="show_foreign_tasks" value="1" form="task-list-prefs" data-autosubmit>')
        self.assertContains(response, 'Показывать задачи других учителей')
        self.assertContains(response, 'id="task-list-prefs"')
        next_url = reverse('task_list') + '?q=%D0%B4%D1%80%D0%BE%D0%B1%D0%B8'
        response = self.client.post(reverse('task_list_prefs'), {'show_foreign_tasks': '1', 'next': next_url})
        self.assertRedirects(response, next_url, fetch_redirect_response=False)
        self.editor.profile.refresh_from_db()
        self.assertTrue(self.editor.profile.show_foreign_tasks)
        self.assertContains(self.client.get(reverse('task_list')), 'form="task-list-prefs" data-autosubmit checked>')
        # Без значения — выключить (явное значение, не инверсия); чужой next — в каталог
        response = self.client.post(reverse('task_list_prefs'), {'next': 'https://evil.example/x'})
        self.assertRedirects(response, reverse('task_list'), fetch_redirect_response=False)
        self.editor.profile.refresh_from_db()
        self.assertFalse(self.editor.profile.show_foreign_tasks)
        self.assertEqual(self.client.get(reverse('task_list_prefs')).status_code, 405)

    def test_prefs_view_only_for_editors_and_creates_superuser_profile(self):
        self.client.force_login(self.guest)
        self.assertEqual(self.client.post(reverse('task_list_prefs'), {'show_foreign_tasks': '1'}).status_code, 403)
        self.assertNotContains(self.client.get(reverse('task_list')), 'show_foreign_tasks')
        self.client.force_login(self.superuser)
        response = self.client.post(reverse('task_list_prefs'), {'show_foreign_tasks': '1'})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Profile.objects.get(user=self.superuser).show_foreign_tasks)
        self.assertEqual(set(catalog_tasks(self.superuser)), {self.shared, self.own, self.foreign})


class MineFilterAndBadgeTests(Roles, TestCase):
    """Решение 6: чип «Мои задачи» (?mine=1) и бейдж «моя» / «задача Имя Фамилия»."""

    def setUp(self):
        self.make_users()
        self.shared = shared_task(self.editor)
        self.mine = Task.new_for(self.guest, text_latex='Моя гостевая')
        self.foreign = Task.new_for(self.other_guest, text_latex='Чужая гостевая')
        self.local = self.shared.make_variant(self.guest)

    def test_mine_filter_shows_only_own_non_shared(self):
        self.client.force_login(self.guest)
        response = self.client.get(reverse('task_list'))
        self.assertEqual(set(response.context['page']), {self.shared, self.mine})
        # R41-1: фильтр включает только mine=1; «mine=0» и прочее — не включает
        for value in ('0', 'yes', ''):
            response = self.client.get(reverse('task_list'), {'mine': value})
            self.assertEqual(set(response.context['page']), {self.shared, self.mine}, value)
            self.assertNotContains(response, 'data-autosubmit checked>')
        # Чип — галочка формы фильтров: живой поиск берёт её из FormData вместе с q и классом
        self.assertContains(response, '<input type="checkbox" name="mine" value="1" data-autosubmit>')
        self.assertContains(response, 'Мои задачи')
        response = self.client.get(reverse('task_list'), {'mine': '1', 'q': 'гостевая'})
        self.assertEqual(list(response.context['page']), [self.mine])
        self.assertContains(response, 'name="mine" value="1" data-autosubmit checked>')
        # Задача, принятая в общие, из «Моих» уходит
        self.mine.is_shared = True
        self.mine.save(update_fields=['is_shared'])
        self.assertEqual(list(self.client.get(reverse('task_list'), {'mine': '1'}).context['page']), [])

    def test_chip_only_when_own_tasks_exist(self):
        self.client.force_login(self.editor)
        self.assertNotContains(self.client.get(reverse('task_list')), 'Мои задачи')
        # Включённый фильтр без задач: чип остаётся, чтобы его снять
        response = self.client.get(reverse('task_list'), {'mine': '1'})
        self.assertContains(response, 'Мои задачи')
        self.assertEqual(list(response.context['page']), [])
        Task.objects.create(text_latex='Своя', created_by=self.editor, is_shared=False)
        self.assertContains(self.client.get(reverse('task_list')), 'Мои задачи')

    def test_authorless_task_renders_without_badge_error(self):
        """Задача без автора (created_by=NULL, как в фикстурах) в каталоге
        редактора: бейдж не падает на task.created_by.username."""
        orphan = Task.objects.create(text_latex='Без автора')
        self.client.force_login(self.editor)
        response = self.client.get(reverse('task_list'), {'q': f'#{orphan.pk}'})
        self.assertEqual(list(response.context['page']), [orphan])
        self.assertContains(response, '>не общая</span>')
        self.assertContains(self.client.get(reverse('task_detail', args=[orphan.pk])), '>не общая</span>')

    def test_badges_in_catalog_and_card(self):
        self.client.force_login(self.guest)
        html = self.client.get(reverse('task_list')).content.decode()
        self.assertEqual(html.count('>моя</span>'), 1)
        self.assertNotIn('личная', html)
        self.assertContains(self.client.get(reverse('task_detail', args=[self.mine.pk])), 'title="Моя задача: её вижу я и редакторы">моя<')
        set_toggle(self.editor, True)
        self.client.force_login(self.editor)
        html = self.client.get(reverse('task_list')).content.decode()
        # R44-1: имя после «автор:» — в именительном падеже без склонения
        self.assertEqual(html.count('>автор: Иван Учителев</span>'), 2)
        self.assertNotIn('>задача Иван', html)
        self.assertNotIn('>моя<', html)
        response = self.client.get(reverse('task_detail', args=[self.foreign.pk]))
        self.assertContains(response, 'Задача учителя Иван Учителев, не общая: видна автору и редакторам"')
        self.assertNotContains(self.client.get(reverse('task_detail', args=[self.shared.pk])), 'badge-assigned" title="Моя задача')


class NeuroEditorsOnlyTests(Roles, TestCase):
    """Решение 5: нейрогенерация закрыта не-редакторам целиком, кнопки AI у них
    приглушены (disabled + подсказка), у редакторов — как раньше."""

    RESULT = {'answer': '4', 'solution': 'Решение', 'subitem_answers': ['1'], 'subitem_solutions': ['']}

    def setUp(self):
        self.make_users()
        self.shared = shared_task(self.editor)
        self.own = Task.new_for(self.guest, text_latex='Своя задача гостя')

    def solve(self, payload):
        return self.client.post(reverse('task_neuro_solve'), json.dumps(payload), content_type='application/json')

    def test_endpoint_403_for_guest_even_for_draft(self):
        with mock.patch('problems.neuro.solve_task', return_value=self.RESULT) as solver:
            self.client.force_login(self.guest)
            for payload in ({'text': 'Сколько будет 2+2?', 'subitems': []},
                            {'task_id': self.own.pk}, {'task_id': self.shared.pk, 'apply': True}):
                response = self.solve(payload)
                self.assertEqual(response.status_code, 403, payload)
                self.assertEqual(response.json()['error'], NEURO_HINT + '.')
            self.assertEqual(self.client.post(reverse('worksheet_import_solve'), json.dumps(
                {'text': 'x', 'subitems': []}), content_type='application/json').status_code, 403)
            solver.assert_not_called()
            self.client.force_login(self.student)
            self.assertEqual(self.solve({'text': 'x', 'subitems': []}).status_code, 403)
            for user in (self.editor, self.superuser):
                self.client.force_login(user)
                response = self.solve({'text': 'Сколько будет 2+2?', 'subitems': []})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()['answer'], '4')
            response = self.solve({'task_id': self.shared.pk, 'apply': True})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(self.shared.subitems.get().answer_latex, '1')

    def test_menu_disabled_for_guest(self):
        """R15-1: одна приглушённая кнопка «AI» с подсказкой, без пунктов
        генерации в разметке — на карточке, в форме задачи и в конструкторе."""
        self.client.force_login(self.guest)
        disabled = f'disabled title="{NEURO_HINT}">AI<'
        sheet = Worksheet.objects.create(owner=self.guest, title='Листок гостя')
        for url in (reverse('task_detail', args=[self.own.pk]), reverse('task_create'),
                    reverse('worksheet_detail', args=[sheet.pk])):
            response = self.client.get(url)
            self.assertContains(response, disabled, msg_prefix=url)
            self.assertNotContains(response, 'data-editor-ai=', msg_prefix=url)
            self.assertNotContains(response, 'data-neuro=', msg_prefix=url)
            self.assertNotContains(response, 'ai-menu', msg_prefix=url)
            self.assertNotContains(response, 'NEURO_SOLVE_URL', msg_prefix=url)
        self.assertEqual(self.client.get(reverse('worksheet_import')).status_code, 200)

    def test_menu_active_for_editor(self):
        """Редактору — меню «AI» (details) с пунктами, которые слушают
        neuro.js (data-neuro) и problem_editor.js (data-editor-ai)."""
        self.client.force_login(self.editor)
        response = self.client.get(reverse('task_detail', args=[self.shared.pk]))
        self.assertContains(response, '<details class="ai-menu" data-ai-menu>')
        self.assertContains(response, 'data-editor-ai="answer">Дописать AI-ответ')
        self.assertContains(response, 'data-editor-ai="solution">Добавить AI-решение')
        self.assertContains(response, 'NEURO_SOLVE_URL')
        self.assertNotContains(response, NEURO_HINT)
        response = self.client.get(reverse('task_create'))
        self.assertContains(response, 'data-neuro="task-form-answer">Дописать AI-ответ')
        self.assertContains(response, 'data-neuro="task-form">Добавить AI-решение')
        self.assertNotContains(response, NEURO_HINT)
        sheet = Worksheet.objects.create(owner=self.editor, title='Листок редактора')
        response = self.client.get(reverse('worksheet_detail', args=[sheet.pk]))
        self.assertContains(response, 'data-neuro="apply-answers" title=')
        self.assertContains(response, 'data-neuro="apply-all" title=')
        self.assertNotContains(response, NEURO_HINT)
        # Без прав карточка только для чтения — меню нет вовсе
        self.client.force_login(self.guest)
        self.assertNotContains(self.client.get(reverse('task_detail', args=[self.shared.pk])), '>AI<')


class InterfaceWordingTests(SimpleTestCase):
    """Решение 6: в шаблонах и JS, которые видит пользователь, нет слов
    «общая база» / «общей базы» / «общую базу» и «личная» / «личной» —
    только «общая задача» / «моя задача». Роль называется «редактор» без
    «базы» (G-1 от 19.10.2026): «редактор базы», «редакторы базы»,
    «редакторам базы» запрещены. Комментарии ({# … #}, {% comment %},
    // и /* */) не считаются: там термины допустимы."""

    BANNED = re.compile(r'общ(ая|ей|ую)\s+баз|(?<![а-яё])личн(ая|ой)(?![а-яё])|редактор[а-яё]*\s+базы', re.IGNORECASE)
    TEMPLATE_COMMENTS = re.compile(r'{#.*?#}|{%\s*comment\s*%}.*?{%\s*endcomment\s*%}', re.DOTALL)
    JS_COMMENTS = re.compile(r'/\*.*?\*/|(?<![:\'"])//[^\n]*', re.DOTALL)

    def offenders(self, root, pattern, comments):
        found = []
        for path in sorted(root.rglob(pattern)):
            text = comments.sub(lambda m: '\n' * m.group(0).count('\n'), path.read_text(encoding='utf-8'))
            for number, line in enumerate(text.splitlines(), 1):
                if self.BANNED.search(line):
                    found.append(f'{path.relative_to(settings.BASE_DIR)}:{number}: {line.strip()}')
        return found

    def test_templates_and_js_are_clean(self):
        base = Path(settings.BASE_DIR)
        self.assertEqual(self.offenders(base / 'templates', '*.html', self.TEMPLATE_COMMENTS), [])
        self.assertEqual(self.offenders(base / 'static' / 'js', '*.js', self.JS_COMMENTS), [])

    def test_pattern_catches_and_skips_as_intended(self):
        self.assertTrue(self.BANNED.search('Это задача общей базы'))
        self.assertTrue(self.BANNED.search('>Личная<'))
        self.assertFalse(self.BANNED.search('Публичная ссылка'))
        self.assertFalse(self.BANNED.search('общая задача'))
        for phrase in ('редактор базы', 'Редакторы базы', 'редакторам базы', 'редактора  базы'):
            self.assertTrue(self.BANNED.search(phrase), phrase)
        for phrase in ('редактор', 'редакторам', 'Можно ред. базу', 'редакторский ответ'):
            self.assertFalse(self.BANNED.search(phrase), phrase)


class SimpleAnswerFieldsTests(Roles, TestCase):
    """R22-1: не-редактору в форме задачи и на карточке — одно поле «Ответ» и
    «Решение» (редакторские поля), авторские скрыты; редактору — как раньше.
    Авторские поля остаются видны, если они у задачи уже заполнены или есть
    источник-задачник: иначе спрятанный авторский ответ был бы в приоритете."""

    def setUp(self):
        self.make_users()
        self.shared = shared_task(self.editor)
        self.own = Task.new_for(self.guest, text_latex='Своя задача гостя')

    def test_task_form_fields_by_role(self):
        self.client.force_login(self.guest)
        response = self.client.get(reverse('task_create'))
        self.assertTrue(response.context['simple_answers'])
        self.assertContains(response, '>Ответ</label>')
        self.assertContains(response, '>Решение</label>')
        self.assertNotContains(response, 'name="author_answer_latex"')
        self.assertNotContains(response, 'Авторский ответ')
        self.assertNotContains(response, 'Редакторский / AI')
        self.client.force_login(self.editor)
        response = self.client.get(reverse('task_create'))
        self.assertFalse(response.context['simple_answers'])
        self.assertContains(response, 'name="author_answer_latex"')
        # R22-2: подписи без двоеточий
        self.assertContains(response, '>Авторский ответ (LaTeX)</label>')
        self.assertNotContains(response, '(LaTeX):')

    def test_card_single_field_writes_editor_answer(self):
        self.client.force_login(self.guest)
        response = self.client.get(reverse('task_detail', args=[self.own.pk]))
        self.assertTrue(response.context['simple_answers'])
        self.assertContains(response, 'name="answer_latex"')
        self.assertContains(response, 'name="solution_latex"')
        self.assertNotContains(response, 'name="author_answer_latex"')
        self.assertNotContains(response, 'name="author_solution_latex"')
        self.assertContains(response, '>Ответ</label>')
        self.assertNotContains(response, 'Авторский ответ')
        self.assertNotContains(response, 'Основной — авторский')
        self.assertNotContains(response, 'Авторские ответ и решение имеют приоритет')
        response = self.client.post(reverse('task_manage', args=[self.own.pk]),
                                    {'block': 'answer', 'answer_latex': '42'})
        self.assertEqual(response.status_code, 200, response.content)
        self.own.refresh_from_db()
        self.assertEqual((self.own.answer_latex, self.own.author_answer_latex), ('42', ''))
        self.assertEqual(self.own.effective_answer_latex, '42')
        response = self.client.post(reverse('task_manage', args=[self.own.pk]),
                                    {'block': 'solution', 'solution_latex': 'Решение гостя'})
        self.assertEqual(response.status_code, 200, response.content)
        self.own.refresh_from_db()
        self.assertEqual(self.own.effective_solution_latex, 'Решение гостя')

    def test_author_fields_stay_when_task_has_them(self):
        # Локальная копия задачи из задачника несёт авторский ответ — поле видно
        sub = self.shared.subitems.get()
        sub.author_answer_latex = '5'
        sub.save()
        copy = self.shared.make_variant(self.guest)
        self.client.force_login(self.guest)
        response = self.client.get(reverse('task_detail', args=[copy.pk]))
        self.assertFalse(response.context['simple_answers'])
        self.assertContains(response, 'name="author_answer_latex"')
        # Источник-задачник без ответов — тоже полный набор полей
        from .models import Source, TaskSource
        source = Source.objects.create(title='Задачник')
        TaskSource.objects.create(task=self.own, source=source, number='1')
        response = self.client.get(reverse('task_detail', args=[self.own.pk]))
        self.assertFalse(response.context['simple_answers'])
        self.assertContains(response, 'name="author_answer_latex"')
        # Редактору на любой задаче — полный набор
        self.client.force_login(self.editor)
        response = self.client.get(reverse('task_detail', args=[self.shared.pk]))
        self.assertFalse(response.context['simple_answers'])
        self.assertContains(response, 'name="author_answer_latex"')
        self.assertContains(response, 'Основной — авторский ответ')


class ClonesAndBadgesTests(Roles, TestCase):
    """R10-2: у не-редактора «клон» и «дублировать» общей задачи подписаны
    «Создать локальную копию задачи»; R17-1: бейдж локальной копии — класс
    badge-local, не badge-returned."""

    def setUp(self):
        self.make_users()
        self.shared = shared_task(self.editor)

    def test_clone_titles_for_guest_and_editor(self):
        self.client.force_login(self.guest)
        response = self.client.get(reverse('task_list'), {'q': f'#{self.shared.pk}'})
        self.assertContains(response, 'title="Создать локальную копию задачи">клон<')
        self.assertContains(response, 'title="Создать локальную копию задачи">дублировать<')
        self.client.force_login(self.editor)
        response = self.client.get(reverse('task_list'), {'q': f'#{self.shared.pk}'})
        self.assertNotContains(response, 'Создать локальную копию задачи')
        self.assertContains(response, 'title="Новая задача с другими числами — не уходя со страницы">клон<')

    def test_local_copy_badge_is_purple(self):
        copy = self.shared.make_variant(self.guest)
        sheet = Worksheet.objects.create(owner=self.guest, title='Листок гостя')
        sheet.items.create(task=copy, order=10)
        self.client.force_login(self.guest)
        response = self.client.get(reverse('task_detail', args=[copy.pk]))
        self.assertContains(response, f'<span class="badge badge-local">Локальная копия #{self.shared.pk}</span>')
        response = self.client.get(reverse('worksheet_detail', args=[sheet.pk]))
        self.assertContains(response, 'class="badge badge-local" title="Локальная копия задачи')
        self.assertNotContains(response, 'badge-returned" title="Локальная копия')
