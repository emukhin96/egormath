"""Очередь предложений исправлений (problems/proposals.py): предложение —
только текст по общей задаче (решение 7 от 19.10.2026); запреты, счётчики
в шапке и кабинете, почта, статусы «Принято» / «Отклонено» без применения
по полям, доступ к страницам."""
from unittest import mock

from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from worksheets.models import Worksheet, WorksheetItem
from .models import Task, TaskProposal
from .proposals import ProposalError, create_proposal, resolve_proposal
from .test_permissions import Roles, shared_task


class ProposalBase(Roles, TestCase):
    def setUp(self):
        self.make_users()
        self.shared = shared_task(self.editor)
        self.own = Task.new_for(self.guest, text_latex='Личная задача гостя')
        self.sheet = Worksheet.objects.create(owner=self.guest, title='Листок гостя')
        self.item = WorksheetItem.objects.create(worksheet=self.sheet, task=self.shared, order=10)

    def propose(self, task, data=None, user=None):
        self.client.force_login(user or self.guest)
        return self.client.post(reverse('task_propose', args=[task.pk]), data or {})

    def resolve(self, proposal, name, user=None):
        self.client.force_login(user or self.editor)
        return self.client.post(reverse(name, args=[proposal.pk]))


class CreateTests(ProposalBase):
    def test_text_proposal_for_shared_task(self):
        response = self.propose(self.shared, {'message': '  В условии опечатка  '})
        self.assertRedirects(response, reverse('task_detail', args=[self.shared.pk]))
        proposal = TaskProposal.objects.get()
        self.assertEqual((proposal.author, proposal.task, proposal.message, proposal.status),
                         (self.guest, self.shared, 'В условии опечатка', 'new'))
        self.assertTrue(proposal.is_open)
        self.assertIsNone(proposal.resolved_at)

    def test_next_returns_to_origin(self):
        response = self.propose(self.shared, {'message': 'Так лучше', 'next': f'/worksheets/{self.sheet.pk}/'})
        self.assertRedirects(response, f'/worksheets/{self.sheet.pk}/', fetch_redirect_response=False)
        # Чужой адрес — обратно на карточку
        response = self.propose(self.other_guest_task(), {'message': 'x', 'next': 'https://evil.example/'})
        self.assertRedirects(response, reverse('task_detail', args=[self.shared.pk]))

    def other_guest_task(self):
        """Та же общая задача, но предложение от второго гостя — без дубликата."""
        self.client.force_login(self.other_guest)
        return self.shared

    def test_empty_text_is_refused(self):
        response = self.propose(self.shared, {'message': '   '})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(TaskProposal.objects.exists())
        page = self.client.get(reverse('task_detail', args=[self.shared.pk]))
        self.assertContains(page, 'Напишите, что исправить')

    def test_mask_prefill_alone_is_not_a_message(self):
        """Со ссылки «Предложить маску» поле заполнено заготовкой: отправка без
        самой маски — пустое предложение, не создаётся (перенос 7bc2877)."""
        from .proposals import MASK_PREFILL
        for text in (MASK_PREFILL, MASK_PREFILL.strip(), '  ' + MASK_PREFILL + '\n'):
            self.propose(self.shared, {'message': text})
            self.assertFalse(TaskProposal.objects.exists(), repr(text))
        page = self.client.get(reverse('task_detail', args=[self.shared.pk]))
        self.assertContains(page, 'Напишите, что исправить')
        self.propose(self.shared, {'message': MASK_PREFILL + '{{number: 5}}'})
        self.assertEqual(TaskProposal.objects.get().message, MASK_PREFILL + '{{number: 5}}')

    def test_only_shared_tasks_take_proposals(self):
        # Своя задача и локальная копия правятся напрямую — предложение не предусмотрено
        self.assertEqual(self.propose(self.own, {'message': 'В общие'}).status_code, 403)
        copy = self.shared.make_variant(self.guest)
        self.assertEqual(self.propose(copy, {'message': 'Версия'}).status_code, 403)
        self.assertEqual(self.client.get(reverse('task_propose', args=[copy.pk])).status_code, 403)
        self.assertFalse(TaskProposal.objects.exists())
        with self.assertRaises(ProposalError):
            create_proposal(self.guest, self.own, 'x')
        with self.assertRaises(ProposalError):
            create_proposal(self.guest, copy, 'x')
        with self.assertRaises(ProposalError):
            create_proposal(self.guest, self.shared, ' ')

    def test_foreign_personal_task_is_not_found(self):
        response = self.propose(self.own, {'message': 'Чужая'}, user=self.other_guest)
        self.assertEqual(response.status_code, 404)

    def test_duplicate_open_proposal_gives_message(self):
        self.propose(self.shared, {'message': 'Первое'})
        response = self.propose(self.shared, {'message': 'Второе'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(TaskProposal.objects.count(), 1)
        page = self.client.get(reverse('task_detail', args=[self.shared.pk]))
        self.assertContains(page, 'уже ждёт ответа')
        # Другой автор — своё предложение; после решения можно предложить снова
        self.propose(self.shared, {'message': 'От второго'}, user=self.other_guest)
        self.assertEqual(TaskProposal.objects.count(), 2)
        TaskProposal.objects.update(status=TaskProposal.STATUS_REJECTED)
        self.propose(self.shared, {'message': 'Третье'})
        self.assertEqual(TaskProposal.objects.count(), 3)

    def test_editor_has_no_button_but_may_post(self):
        self.client.force_login(self.editor)
        page = self.client.get(reverse('task_detail', args=[self.shared.pk]))
        self.assertNotContains(page, 'propose-dialog')
        self.assertNotContains(page, 'Предложить исправление')
        response = self.propose(self.shared, {'message': 'От редактора'}, user=self.editor)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(TaskProposal.objects.get().author, self.editor)

    def test_card_button_and_dialog(self):
        self.client.force_login(self.guest)
        page = self.client.get(reverse('task_detail', args=[self.shared.pk]))
        self.assertContains(page, 'data-dialog-open="propose-dialog">Предложить исправление')
        self.assertContains(page, 'id="propose-dialog"')
        self.assertContains(page, 'name="message"')
        self.assertContains(page, 'статус появится в «Мои предложения»')
        self.assertContains(page, 'data-propose-link')
        self.assertNotContains(page, 'name="variant"')
        # Своя задача и локальная копия — без кнопки предложения
        for task in (self.own, self.shared.make_variant(self.guest)):
            page = self.client.get(reverse('task_detail', args=[task.pk]))
            self.assertNotContains(page, 'propose-dialog')
            self.assertNotContains(page, 'Предложить эту версию')
            self.assertNotContains(page, 'Предложить в общие')
        self.propose(self.shared, {'message': 'Отправлено'})
        page = self.client.get(reverse('task_detail', args=[self.shared.pk]))
        self.assertContains(page, 'Предложение отправлено')
        self.assertContains(page, 'ждёт ответа редактора"')
        self.assertNotContains(page, 'id="propose-dialog"')

    def test_card_rerenders_without_button_after_local_copy(self):
        """Карточка общей задачи из листка: после сохранения в локальную копию
        новая разметка — уже копии, у которой предложения нет."""
        self.client.force_login(self.guest)
        context = f'?worksheet={self.sheet.pk}&item={self.item.pk}'
        page = self.client.get(reverse('task_detail', args=[self.shared.pk]) + context)
        self.assertContains(page, 'id="propose-dialog"')
        response = self.client.post(reverse('task_manage', args=[self.shared.pk]) + context,
                                    {'block': 'condition', 'text_latex': 'Моя версия', 'scope': 'local'})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(Task.objects.filter(variant_of=self.shared).exists())
        html = response.json()['html']
        self.assertNotIn('propose-dialog', html)
        self.assertNotIn('Предложить', html)

    def test_propose_page_prefills_mask_text(self):
        self.client.force_login(self.guest)
        response = self.client.get(reverse('task_propose', args=[self.shared.pk]) + '?mask=1&next=/problems/')
        self.assertContains(response, 'Предлагаю маску ответа')
        self.assertContains(response, 'value="/problems/"')
        self.assertContains(response, 'статус появится в «Мои предложения»')
        # Редактору страница тоже открывается (запрета нет)
        self.client.force_login(self.editor)
        self.assertEqual(self.client.get(reverse('task_propose', args=[self.shared.pk])).status_code, 200)

    def test_propose_page_drops_unsafe_next(self):
        """Адрес возврата из GET попадает в ссылку «Отмена» и скрытое поле
        только с нашего хоста: javascript: и чужой домен отбрасываются."""
        self.client.force_login(self.guest)
        url = reverse('task_propose', args=[self.shared.pk])
        for bad in ('javascript:alert(1)', 'https://evil.example/x', '//evil.example/x'):
            response = self.client.get(url + '?next=' + bad)
            self.assertEqual(response.status_code, 200)
            self.assertNotContains(response, bad)
            self.assertContains(response, f'href="{reverse("task_detail", args=[self.shared.pk])}">Отмена')
        response = self.client.get(url + '?next=/problems/')
        self.assertContains(response, 'href="/problems/">Отмена')

    def test_independent_work_picker_offers_mask_proposal(self):
        from independentworks.models import Work, Position, Candidate
        with override_settings(INDEPENDENT_WORKS_ENABLED=True):
            work = Work.objects.create(owner=self.guest, title='СР')
            position = Position.objects.create(work=work)
            Candidate.objects.create(position=position, task=self.shared)
            self.client.force_login(self.guest)
            response = self.client.get(reverse('independentworks:pick', args=[position.pk]))
            self.assertContains(response, 'data-mask-readonly="1"')
            self.assertContains(response, f'data-propose-url="{reverse("task_propose", args=[self.shared.pk])}?mask=1')
            work.owner = self.editor
            work.save()
            self.client.force_login(self.editor)
            response = self.client.get(reverse('independentworks:pick', args=[position.pk]))
            self.assertNotContains(response, 'data-propose-url')


class CounterTests(ProposalBase):
    def test_editor_sees_counters_and_dashboard_card(self):
        self.propose(self.shared, {'message': 'Опечатка'})
        self.client.force_login(self.editor)
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.context['proposals_new'], 1)
        self.assertContains(response, 'nav-count')
        self.assertContains(response, 'Предложения исправлений · 1')
        self.assertContains(response, f'Задача #{self.shared.pk}')
        self.assertContains(response, 'Опечатка')
        self.assertEqual(list(response.context['proposals']), [TaskProposal.objects.get()])

    def test_guest_has_no_editor_counters(self):
        self.propose(self.shared, {'message': 'Опечатка'})
        response = self.client.get(reverse('dashboard'))
        self.assertNotIn('proposals_new', response.context)
        self.assertNotContains(response, 'nav-count')
        self.assertNotContains(response, 'Предложения исправлений')
        self.assertContains(response, 'Мои предложения')
        self.assertIsNone(response.context['proposals'])

    def test_author_status_counter_and_seen_mark(self):
        self.propose(self.shared, {'message': 'Опечатка'})
        proposal = TaskProposal.objects.get()
        self.resolve(proposal, 'proposal_reject')
        self.client.force_login(self.guest)
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.context['proposals_replies'], 1)
        self.assertContains(response, 'Мои предложения · 1')
        response = self.client.get(reverse('proposals_mine'))
        self.assertContains(response, 'proposal-unread')
        self.assertContains(response, 'Отклонено')
        self.assertNotContains(response, 'Ответ редактора')
        proposal.refresh_from_db()
        self.assertIsNotNone(proposal.seen_by_author_at)
        response = self.client.get(reverse('proposals_mine'))
        self.assertNotContains(response, 'proposal-unread')
        self.assertEqual(response.context['proposals_replies'], 0)


class MinePageTests(ProposalBase):
    def test_unread_block_is_complete_and_pages_are_stable(self):
        """Все непросмотренные статусы — отдельным блоком независимо от
        страницы и даты; общий список постраничный по дате отправки, его
        порядок от отметки просмотра не меняется."""
        older = create_proposal(self.guest, self.shared, 'Старое')
        TaskProposal.objects.filter(pk=older.pk).update(status=TaskProposal.STATUS_REJECTED)
        second = shared_task(self.editor, 'Вторая общая')
        newer = create_proposal(self.guest, second, 'Новое')
        TaskProposal.objects.filter(pk=newer.pk).update(status=TaskProposal.STATUS_ACCEPTED)
        self.client.force_login(self.guest)
        with mock.patch('problems.proposals.MINE_PAGE', 1):
            response = self.client.get(reverse('proposals_mine'))
        # Старый статус не влез на страницу списка, но виден в блоке новых
        self.assertEqual({p.pk for p in response.context['unread']}, {older.pk, newer.pk})
        self.assertEqual([p.pk for p in response.context['proposals']], [newer.pk])
        self.assertTrue(response.context['page'].has_next())
        self.assertContains(response, 'Новые статусы')
        self.assertEqual(response.content.decode().count('proposal-unread'), 3)
        older.refresh_from_db()
        newer.refresh_from_db()
        self.assertIsNotNone(older.seen_by_author_at)
        self.assertIsNotNone(newer.seen_by_author_at)
        self.assertEqual(self.client.get(reverse('dashboard')).context['proposals_replies'], 0)
        # Страница 2 — тот же порядок по дате, блока новых статусов больше нет
        with mock.patch('problems.proposals.MINE_PAGE', 1):
            response = self.client.get(reverse('proposals_mine') + '?page=2')
        self.assertEqual([p.pk for p in response.context['proposals']], [older.pk])
        self.assertEqual(response.context['unread'], [])
        self.assertNotContains(response, 'Новые статусы')
        self.assertNotContains(response, 'proposal-unread')
        # Решивший редактор удалён (SET_NULL) — страницы не падают
        self.client.force_login(self.editor)
        response = self.client.get(reverse('proposal_detail', args=[older.pk]))
        self.assertContains(response, 'редактор ·')
        self.assertNotContains(response, 'редактор базы')


# Адреса редакторов по умолчанию пустые: локальный local_settings.py (стенд)
# не должен подмешивать письмо о новом предложении в проверки статусов автору.
@override_settings(PROPOSAL_NOTIFY_EMAILS=[])
class MailTests(ProposalBase):
    @override_settings(PROPOSAL_NOTIFY_EMAILS=['editor@example.com', 'root@example.com'])
    def test_new_proposal_mails_editors(self):
        self.propose(self.shared, {'message': 'В ответе ошибка'})
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, ['editor@example.com', 'root@example.com'])
        self.assertIn(f'#{self.shared.pk}', message.subject)
        self.assertIn('В ответе ошибка', message.body)
        self.assertIn(reverse('proposal_detail', args=[TaskProposal.objects.get().pk]), message.body)

    @override_settings(PROPOSAL_NOTIFY_EMAILS=[])
    def test_no_addresses_no_mail(self):
        self.propose(self.shared, {'message': 'Опечатка'})
        self.assertEqual(TaskProposal.objects.count(), 1)
        self.assertEqual(mail.outbox, [])

    @override_settings(PROPOSAL_NOTIFY_EMAILS=['editor@example.com'],
                       EMAIL_BACKEND='django.core.mail.backends.smtp.EmailBackend',
                       EMAIL_HOST='')
    def test_smtp_without_host_is_skipped_silently(self):
        from .notifications import mail_enabled, notify_new_proposal
        self.assertFalse(mail_enabled())
        proposal = create_proposal(self.guest, self.shared, 'x')
        self.assertFalse(notify_new_proposal(proposal))

    def test_resolution_mails_author_with_email(self):
        self.guest.email = 'guest@example.com'
        self.guest.save()
        self.propose(self.shared, {'message': 'Опечатка'})
        proposal = TaskProposal.objects.get()
        self.resolve(proposal, 'proposal_reject')
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['guest@example.com'])
        self.assertIn('отклонено', mail.outbox[0].subject)
        self.assertIn(reverse('proposals_mine'), mail.outbox[0].body)

    def test_resolution_without_author_email_is_skipped(self):
        self.propose(self.shared, {'message': 'Опечатка'})
        proposal = TaskProposal.objects.get()
        self.resolve(proposal, 'proposal_accept')
        self.assertEqual(mail.outbox, [])
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, TaskProposal.STATUS_ACCEPTED)


class ResolveTests(ProposalBase):
    def test_accept_and_reject_set_status_only(self):
        """Статус, кто и когда решил; сама задача не меняется — правку
        редактор вносит на карточке сам."""
        accepted = create_proposal(self.guest, self.shared, 'Опечатка')
        before = self.shared.updated_at
        response = self.resolve(accepted, 'proposal_accept')
        self.assertRedirects(response, reverse('proposal_detail', args=[accepted.pk]))
        accepted.refresh_from_db()
        self.assertEqual((accepted.status, accepted.resolved_by), (TaskProposal.STATUS_ACCEPTED, self.editor))
        self.assertIsNotNone(accepted.resolved_at)
        self.assertIsNone(accepted.seen_by_author_at)
        self.shared.refresh_from_db()
        self.assertEqual((self.shared.text_latex, self.shared.updated_at), ('Общая задача', before))
        rejected = create_proposal(self.other_guest, self.shared, 'Неверно')
        self.resolve(rejected, 'proposal_reject', user=self.superuser)
        rejected.refresh_from_db()
        self.assertEqual((rejected.status, rejected.resolved_by), (TaskProposal.STATUS_REJECTED, self.superuser))

    def test_resolved_proposal_is_final(self):
        proposal = create_proposal(self.guest, self.shared, 'Опечатка')
        self.resolve(proposal, 'proposal_reject')
        self.resolve(proposal, 'proposal_accept')
        proposal.refresh_from_db()
        self.assertEqual((proposal.status, proposal.resolved_by), (TaskProposal.STATUS_REJECTED, self.editor))
        page = self.client.get(reverse('proposal_detail', args=[proposal.pk]))
        self.assertContains(page, 'уже обработано')
        self.assertNotContains(page, f'action="{reverse("proposal_accept", args=[proposal.pk])}"')
        with self.assertRaises(ProposalError):
            resolve_proposal(proposal, TaskProposal.STATUS_ACCEPTED, self.editor)
        with self.assertRaises(ProposalError):
            resolve_proposal(create_proposal(self.other_guest, self.shared, 'x'), 'new', self.editor)

    def test_detail_page_shows_text_task_and_buttons(self):
        proposal = create_proposal(self.guest, self.shared, 'В ответе должно быть 7')
        self.client.force_login(self.editor)
        response = self.client.get(reverse('proposal_detail', args=[proposal.pk]))
        self.assertContains(response, 'В ответе должно быть 7')
        self.assertContains(response, 'Общая задача')
        self.assertContains(response, f'href="{reverse("task_detail", args=[self.shared.pk])}">Открыть задачу')
        self.assertContains(response, f'action="{reverse("proposal_accept", args=[proposal.pk])}"')
        self.assertContains(response, f'action="{reverse("proposal_reject", args=[proposal.pk])}"')
        self.assertContains(response, '>Принято</button>')
        self.assertContains(response, '>Отклонено</button>')
        self.assertNotContains(response, 'name="note"')
        self.assertNotContains(response, 'name="sections"')
        self.assertEqual(self.client.get(reverse('proposal_accept', args=[proposal.pk])).status_code, 405)


class AccessTests(ProposalBase):
    def test_editor_pages_are_for_editors_only(self):
        proposal = create_proposal(self.guest, self.shared, 'Опечатка')
        for user in (self.guest, self.other_guest, self.student):
            self.client.force_login(user)
            self.assertEqual(self.client.get(reverse('proposal_list')).status_code, 403, user)
            self.assertEqual(self.client.get(reverse('proposal_detail', args=[proposal.pk])).status_code, 403, user)
            self.assertEqual(self.client.post(reverse('proposal_accept', args=[proposal.pk])).status_code, 403, user)
            self.assertEqual(self.client.post(reverse('proposal_reject', args=[proposal.pk])).status_code, 403, user)
        proposal.refresh_from_db()
        self.assertTrue(proposal.is_open)
        for user in (self.editor, self.superuser):
            self.client.force_login(user)
            response = self.client.get(reverse('proposal_list'))
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, f'Задача #{self.shared.pk}')
            self.assertContains(response, 'Опечатка')
            self.assertEqual(self.client.get(reverse('proposal_detail', args=[proposal.pk])).status_code, 200)

    def test_list_filter_new_and_all(self):
        proposal = create_proposal(self.guest, self.shared, 'Первое')
        other = create_proposal(self.other_guest, self.shared, 'Другое')
        TaskProposal.objects.filter(pk=other.pk).update(status=TaskProposal.STATUS_REJECTED)
        self.client.force_login(self.editor)
        response = self.client.get(reverse('proposal_list'))
        self.assertEqual([p.pk for p in response.context['page']], [proposal.pk])
        response = self.client.get(reverse('proposal_list') + '?status=all')
        self.assertEqual({p.pk for p in response.context['page']}, {proposal.pk, other.pk})

    def test_mine_shows_only_own(self):
        mine = create_proposal(self.guest, self.shared, 'Моё предложение')
        create_proposal(self.other_guest, self.shared, 'Чужое предложение')
        self.client.force_login(self.guest)
        response = self.client.get(reverse('proposals_mine'))
        self.assertEqual([p.pk for p in response.context['proposals']], [mine.pk])
        self.assertContains(response, 'Моё предложение')
        self.assertNotContains(response, 'Чужое предложение')
        self.client.force_login(self.student)
        self.assertEqual(self.client.get(reverse('proposals_mine')).status_code, 403)
