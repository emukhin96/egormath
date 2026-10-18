"""Очередь предложений исправлений (problems/proposals.py): создание трёх
видов со снимком, запреты, счётчики в шапке и кабинете, почта, применение
выбранных полей, отклонение с причиной, доступ к страницам."""
from unittest import mock

from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from worksheets.models import Worksheet, WorksheetItem
from .models import Task, TaskProposal, TaskSubitem
from .proposals import ProposalError, apply_proposal, create_proposal, snapshot_of
from .test_permissions import Roles, shared_task


class ProposalBase(Roles, TestCase):
    def setUp(self):
        self.make_users()
        self.shared = shared_task(self.editor)
        sub = self.shared.subitems.get()
        sub.author_answer_latex = '5'
        sub.answer_mask = '{{number: 5}}'
        sub.save()
        self.own = Task.new_for(self.guest, text_latex='Личная задача гостя')
        self.sheet = Worksheet.objects.create(owner=self.guest, title='Листок гостя')
        self.item = WorksheetItem.objects.create(worksheet=self.sheet, task=self.shared, order=10)

    def make_copy(self, text='Исправленное условие', answer='7', mask='{{number: 7}}'):
        """Локальная копия гостя с отличающимися условием, ответом и маской."""
        copy = self.shared.make_variant(self.guest)
        copy.text_latex = text
        copy.save()
        sub = copy.subitems.get()
        sub.author_answer_latex = answer
        sub.answer_mask = mask
        sub.save()
        return copy

    def propose(self, task, data=None, user=None):
        self.client.force_login(user or self.guest)
        return self.client.post(reverse('task_propose', args=[task.pk]), data or {})

    def fix_with_copy(self, **kwargs):
        copy = self.make_copy(**kwargs)
        return create_proposal(self.guest, self.shared, kind=TaskProposal.KIND_FIX,
                               message='Опечатка', variant=copy), copy


class CreateTests(ProposalBase):
    def test_fix_with_text_only(self):
        response = self.propose(self.shared, {'message': 'В условии опечатка'})
        self.assertRedirects(response, reverse('task_detail', args=[self.shared.pk]))
        proposal = TaskProposal.objects.get()
        self.assertEqual((proposal.kind, proposal.author, proposal.task, proposal.variant, proposal.status),
                         ('fix', self.guest, self.shared, None, 'new'))
        self.assertEqual(proposal.snapshot, {})
        self.assertFalse(proposal.has_snapshot)

    def test_fix_with_variant_keeps_snapshot(self):
        copy = self.make_copy()
        response = self.propose(self.shared, {'message': 'Так лучше', 'variant': copy.pk,
                                              'next': f'/worksheets/{self.sheet.pk}/'})
        self.assertRedirects(response, f'/worksheets/{self.sheet.pk}/', fetch_redirect_response=False)
        proposal = TaskProposal.objects.get()
        self.assertEqual(proposal.variant, copy)
        self.assertEqual(proposal.snapshot['text_latex'], 'Исправленное условие')
        self.assertEqual(proposal.snapshot['subitems'][0]['author_answer_latex'], '7')
        self.assertEqual(proposal.snapshot['subitems'][0]['answer_mask'], '{{number: 7}}')
        self.assertEqual(proposal.snapshot['subitems'][0]['text_latex'], 'а)')
        # Копию можно править дальше — снимок не меняется
        copy.text_latex = 'Ещё правка'
        copy.save()
        proposal.refresh_from_db()
        self.assertEqual(proposal.snapshot['text_latex'], 'Исправленное условие')

    def test_new_kind_for_own_personal_task(self):
        TaskSubitem.objects.create(task=self.own, order=10, text_latex='а)', answer_latex='1')
        response = self.propose(self.own, {'message': 'Из моего задачника'})
        self.assertEqual(response.status_code, 302)
        proposal = TaskProposal.objects.get()
        self.assertEqual((proposal.kind, proposal.task, proposal.variant), ('new', self.own, None))
        self.assertEqual(proposal.snapshot, snapshot_of(self.own))
        self.assertEqual(proposal.snapshot['subitems'][0]['answer_latex'], '1')
        self.own.refresh_from_db()
        self.assertFalse(self.own.is_shared)

    def test_unsafe_next_falls_back_to_card(self):
        response = self.propose(self.shared, {'message': 'Опечатка', 'next': 'https://evil.example/'})
        self.assertRedirects(response, reverse('task_detail', args=[self.shared.pk]))

    def test_foreign_copy_is_refused(self):
        foreign = self.shared.make_variant(self.other_guest)
        response = self.propose(self.shared, {'message': 'Чужая копия', 'variant': foreign.pk})
        self.assertEqual(response.status_code, 404)
        self.assertFalse(TaskProposal.objects.exists())

    def test_fix_without_text_and_copy_is_refused(self):
        response = self.propose(self.shared, {'message': '   '}, )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(TaskProposal.objects.exists())
        page = self.client.get(reverse('task_detail', args=[self.shared.pk]))
        self.assertContains(page, 'Напишите, что исправить')

    def test_kind_mismatch_is_refused_at_model_level(self):
        with self.assertRaises(ProposalError):
            create_proposal(self.guest, self.own, kind=TaskProposal.KIND_FIX, message='x')
        with self.assertRaises(ProposalError):
            create_proposal(self.guest, self.shared, kind=TaskProposal.KIND_NEW, message='x')
        with self.assertRaises(ProposalError):
            create_proposal(self.other_guest, self.own, kind=TaskProposal.KIND_NEW, message='x')
        copy = self.make_copy()
        with self.assertRaises(ProposalError):
            create_proposal(self.guest, copy, kind=TaskProposal.KIND_NEW, message='x')
        self.assertFalse(TaskProposal.objects.exists())

    def test_foreign_personal_task_is_not_found(self):
        response = self.propose(self.own, {'message': 'Чужая'}, user=self.other_guest)
        self.assertEqual(response.status_code, 404)

    def test_duplicate_open_proposal_gives_message(self):
        self.propose(self.shared, {'message': 'Первое'})
        response = self.propose(self.shared, {'message': 'Второе'}, )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(TaskProposal.objects.count(), 1)
        page = self.client.get(reverse('task_detail', args=[self.shared.pk]))
        self.assertContains(page, 'уже ждёт ответа')
        # После решения можно предложить снова
        TaskProposal.objects.update(status=TaskProposal.STATUS_REJECTED)
        self.propose(self.shared, {'message': 'Третье'})
        self.assertEqual(TaskProposal.objects.count(), 2)

    def test_editor_has_no_button_but_may_post(self):
        self.client.force_login(self.editor)
        page = self.client.get(reverse('task_detail', args=[self.shared.pk]))
        self.assertNotContains(page, 'propose-dialog')
        self.assertNotContains(page, 'Предложить исправление')
        response = self.propose(self.shared, {'message': 'От редактора'}, user=self.editor)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(TaskProposal.objects.get().author, self.editor)

    def test_card_buttons_by_task_kind(self):
        self.client.force_login(self.guest)
        page = self.client.get(reverse('task_detail', args=[self.shared.pk]))
        self.assertContains(page, 'data-dialog-open="propose-dialog">Предложить исправление')
        self.assertContains(page, 'id="propose-dialog"')
        self.assertContains(page, 'name="message"')
        self.assertContains(page, 'data-propose-link')
        page = self.client.get(reverse('task_detail', args=[self.own.pk]))
        self.assertContains(page, 'Предложить задачу в общую базу')
        copy = self.make_copy()
        page = self.client.get(reverse('task_detail', args=[copy.pk]))
        self.assertContains(page, 'Предложить эту версию в базу')
        self.assertContains(page, f'action="{reverse("task_propose", args=[self.shared.pk])}"')
        self.assertContains(page, f'name="variant" value="{copy.pk}"')
        # На карточке общей задачи копия предлагается чекбоксом
        page = self.client.get(reverse('task_detail', args=[self.shared.pk]))
        self.assertContains(page, f'Приложить мою локальную копию #{copy.pk}')
        self.propose(self.shared, {'message': 'Отправлено'})
        page = self.client.get(reverse('task_detail', args=[self.shared.pk]))
        self.assertContains(page, 'Предложение отправлено')
        self.assertNotContains(page, 'id="propose-dialog"')

    def test_propose_page_prefills_mask_text(self):
        self.client.force_login(self.guest)
        response = self.client.get(reverse('task_propose', args=[self.shared.pk]) + '?mask=1&next=/problems/')
        self.assertContains(response, 'Предлагаю маску ответа')
        self.assertContains(response, 'value="/problems/"')
        # Редактору страница тоже открывается (запрета нет)
        self.client.force_login(self.editor)
        self.assertEqual(self.client.get(reverse('task_propose', args=[self.shared.pk])).status_code, 200)
        # Копия чужой личной задачи — предлагать нечего
        personal_copy = self.own.make_variant(self.guest)
        self.client.force_login(self.guest)
        self.assertEqual(self.client.get(reverse('task_propose', args=[personal_copy.pk])).status_code, 403)

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
        self.assertContains(response, 'Предложения · 1')
        self.assertContains(response, 'Предложения исправлений')
        self.assertContains(response, f'Задача #{self.shared.pk}')
        self.assertEqual(list(response.context['proposals']), [TaskProposal.objects.get()])

    def test_guest_has_no_editor_counters(self):
        self.propose(self.shared, {'message': 'Опечатка'})
        response = self.client.get(reverse('dashboard'))
        self.assertNotIn('proposals_new', response.context)
        self.assertNotContains(response, 'nav-count')
        self.assertNotContains(response, 'Предложения исправлений')
        self.assertContains(response, 'Мои предложения')
        self.assertIsNone(response.context['proposals'])

    def test_author_reply_counter_and_seen_mark(self):
        self.propose(self.shared, {'message': 'Опечатка'})
        proposal = TaskProposal.objects.get()
        self.client.force_login(self.editor)
        self.client.post(reverse('proposal_reject', args=[proposal.pk]), {'note': 'Нет, всё верно'})
        self.client.force_login(self.guest)
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.context['proposals_replies'], 1)
        self.assertContains(response, 'Мои предложения · 1')
        response = self.client.get(reverse('proposals_mine'))
        self.assertContains(response, 'proposal-unread')
        self.assertContains(response, 'Нет, всё верно')
        proposal.refresh_from_db()
        self.assertIsNotNone(proposal.seen_by_author_at)
        response = self.client.get(reverse('proposals_mine'))
        self.assertNotContains(response, 'proposal-unread')
        self.assertEqual(response.context['proposals_replies'], 0)


class MineLimitTests(ProposalBase):
    def test_only_shown_replies_are_marked_seen(self):
        """Ответ за пределами списка не отмечается просмотренным и остаётся
        в счётчике, пока автор его не увидит."""
        older = create_proposal(self.guest, self.shared, kind='fix', message='Старое')
        TaskProposal.objects.filter(pk=older.pk).update(status=TaskProposal.STATUS_REJECTED)
        newer = create_proposal(self.guest, self.own, kind='new', message='Новое')
        TaskProposal.objects.filter(pk=newer.pk).update(status=TaskProposal.STATUS_ACCEPTED)
        self.client.force_login(self.guest)
        with mock.patch('problems.proposals.MINE_LIMIT', 1):
            response = self.client.get(reverse('proposals_mine'))
        self.assertEqual([p.pk for p in response.context['proposals']], [newer.pk])
        older.refresh_from_db()
        newer.refresh_from_db()
        self.assertIsNone(older.seen_by_author_at)
        self.assertIsNotNone(newer.seen_by_author_at)
        self.assertEqual(self.client.get(reverse('dashboard')).context['proposals_replies'], 1)
        # Решивший редактор удалён (SET_NULL) — страницы не падают
        response = self.client.get(reverse('proposals_mine'))
        self.assertContains(response, 'редактор базы')
        self.client.force_login(self.editor)
        self.assertContains(self.client.get(reverse('proposal_detail', args=[older.pk])), 'редактор базы')


# Адреса редакторов по умолчанию пустые: локальный local_settings.py (стенд)
# не должен подмешивать письмо о новом предложении в проверки ответов автору.
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
        proposal = create_proposal(self.guest, self.shared, kind='fix', message='x')
        self.assertFalse(notify_new_proposal(proposal))

    def test_resolution_mails_author_with_email(self):
        self.guest.email = 'guest@example.com'
        self.guest.save()
        self.propose(self.shared, {'message': 'Опечатка'})
        proposal = TaskProposal.objects.get()
        self.client.force_login(self.editor)
        self.client.post(reverse('proposal_reject', args=[proposal.pk]), {'note': 'Условие верное'})
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['guest@example.com'])
        self.assertIn('отклонено', mail.outbox[0].subject)
        self.assertIn('Условие верное', mail.outbox[0].body)

    def test_resolution_without_author_email_is_skipped(self):
        self.propose(self.shared, {'message': 'Опечатка'})
        proposal = TaskProposal.objects.get()
        self.client.force_login(self.editor)
        self.client.post(reverse('proposal_apply', args=[proposal.pk]), {'note': 'Исправил вручную'})
        self.assertEqual(mail.outbox, [])
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, TaskProposal.STATUS_ACCEPTED)


class ApplyTests(ProposalBase):
    def apply(self, proposal, sections=(), note='', user=None):
        self.client.force_login(user or self.editor)
        return self.client.post(reverse('proposal_apply', args=[proposal.pk]),
                                {'sections': list(sections), 'note': note})

    def test_apply_selected_fields_only(self):
        proposal, copy = self.fix_with_copy()
        before = self.shared.updated_at
        response = self.apply(proposal, ['condition'], note='Спасибо')
        self.assertRedirects(response, reverse('proposal_detail', args=[proposal.pk]))
        self.shared.refresh_from_db()
        sub = self.shared.subitems.get()
        self.assertEqual(self.shared.text_latex, 'Исправленное условие')
        self.assertEqual((sub.author_answer_latex, sub.answer_mask), ('5', '{{number: 5}}'))
        self.assertGreater(self.shared.updated_at, before)
        proposal.refresh_from_db()
        self.assertEqual((proposal.status, proposal.resolved_by, proposal.resolution_note),
                         (TaskProposal.STATUS_ACCEPTED, self.editor, 'Спасибо'))
        self.assertIsNotNone(proposal.resolved_at)
        self.assertIsNone(proposal.seen_by_author_at)
        # Копия автора не тронута
        copy.refresh_from_db()
        self.assertEqual(copy.text_latex, 'Исправленное условие')

    def test_apply_answer_and_mask_to_subitems_by_order(self):
        proposal, _ = self.fix_with_copy()
        self.apply(proposal, ['answer', 'mask'])
        self.shared.refresh_from_db()
        sub = self.shared.subitems.get()
        self.assertEqual(self.shared.text_latex, 'Общая задача')
        self.assertEqual((sub.author_answer_latex, sub.answer_mask), ('7', '{{number: 7}}'))

    def test_apply_subitems_structure(self):
        copy = self.make_copy()
        sub = copy.subitems.get()
        sub.text_latex = 'а) новое'
        sub.save()
        TaskSubitem.objects.create(task=copy, order=20, text_latex='б)', author_answer_latex='9')
        proposal = create_proposal(self.guest, self.shared, kind='fix', message='Добавил пункт', variant=copy)
        # Ответы без структуры: число подпунктов отличается — отказ, ничего не меняется
        self.apply(proposal, ['answer'])
        self.shared.refresh_from_db()
        self.assertEqual(self.shared.subitems.count(), 1)
        self.assertEqual(self.shared.subitems.get().author_answer_latex, '5')
        proposal.refresh_from_db()
        self.assertTrue(proposal.is_open)
        page = self.client.get(reverse('proposal_detail', args=[proposal.pk]))
        self.assertContains(page, 'Число подпунктов')
        # Со структурой: подпункты по порядку, ответы к ним
        self.apply(proposal, ['subitems', 'answer'])
        subs = list(self.shared.subitems.all())
        self.assertEqual([s.text_latex for s in subs], ['а) новое', 'б)'])
        self.assertEqual([s.author_answer_latex for s in subs], ['7', '9'])
        self.assertEqual([s.order for s in subs], [10, 20])
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, TaskProposal.STATUS_ACCEPTED)

    def test_apply_removes_extra_subitems(self):
        TaskSubitem.objects.create(task=self.shared, order=20, text_latex='б)')
        copy = self.shared.make_variant(self.guest)
        copy.subitems.filter(order=20).delete()
        proposal = create_proposal(self.guest, self.shared, kind='fix', message='Лишний пункт', variant=copy)
        self.apply(proposal, ['subitems'])
        self.assertEqual([s.text_latex for s in self.shared.subitems.all()], ['а)'])

    def test_invalid_mask_rolls_back_everything(self):
        proposal, _ = self.fix_with_copy()
        proposal.snapshot['subitems'][0]['answer_mask'] = '{{number: }}'
        proposal.save()
        response = self.apply(proposal, ['condition', 'mask'])
        self.assertEqual(response.status_code, 302)
        self.shared.refresh_from_db()
        self.assertEqual(self.shared.text_latex, 'Общая задача')
        self.assertEqual(self.shared.subitems.get().answer_mask, '{{number: 5}}')
        proposal.refresh_from_db()
        self.assertTrue(proposal.is_open)

    def test_new_kind_makes_task_shared(self):
        proposal = create_proposal(self.guest, self.own, kind='new', message='В базу')
        self.apply(proposal, [], note='Принято')
        self.own.refresh_from_db()
        self.assertTrue(self.own.is_shared)
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, TaskProposal.STATUS_ACCEPTED)
        # Дальше задачу правят только редакторы
        from accounts.permissions import can_edit_task
        self.assertFalse(can_edit_task(self.guest, self.own))

    def test_text_only_proposal_is_marked_accepted(self):
        proposal = create_proposal(self.guest, self.shared, kind='fix', message='Опечатка')
        with self.assertRaises(ProposalError):
            apply_proposal(proposal, ['condition'], self.editor)
        self.apply(proposal, [], note='Исправил')
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, TaskProposal.STATUS_ACCEPTED)

    def test_reject_requires_note(self):
        proposal, _ = self.fix_with_copy()
        self.client.force_login(self.editor)
        self.client.post(reverse('proposal_reject', args=[proposal.pk]), {'note': ' '})
        proposal.refresh_from_db()
        self.assertTrue(proposal.is_open)
        self.client.post(reverse('proposal_reject', args=[proposal.pk]), {'note': 'Ответ в книге верный'})
        proposal.refresh_from_db()
        self.assertEqual((proposal.status, proposal.resolution_note, proposal.resolved_by),
                         (TaskProposal.STATUS_REJECTED, 'Ответ в книге верный', self.editor))
        self.shared.refresh_from_db()
        self.assertEqual(self.shared.text_latex, 'Общая задача')
        # Повторно не применить и не отклонить
        self.apply(proposal, ['condition'])
        self.shared.refresh_from_db()
        self.assertEqual(self.shared.text_latex, 'Общая задача')
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, TaskProposal.STATUS_REJECTED)

    def test_detail_page_highlights_differences(self):
        proposal, copy = self.fix_with_copy()
        self.client.force_login(self.editor)
        response = self.client.get(reverse('proposal_detail', args=[proposal.pk]))
        self.assertContains(response, 'is-changed')
        self.assertContains(response, 'Условие · отличается')
        self.assertContains(response, 'Маска ответа · отличается')
        self.assertContains(response, 'value="condition" checked')
        self.assertContains(response, 'value="solution"><')
        self.assertContains(response, 'Исправленное условие')
        self.assertContains(response, reverse('task_detail', args=[copy.pk]))
        self.assertContains(response, 'Открыть копию автора')


class AccessTests(ProposalBase):
    def test_editor_pages_are_for_editors_only(self):
        proposal, _ = self.fix_with_copy()
        for user in (self.guest, self.other_guest, self.student):
            self.client.force_login(user)
            self.assertEqual(self.client.get(reverse('proposal_list')).status_code, 403, user)
            self.assertEqual(self.client.get(reverse('proposal_detail', args=[proposal.pk])).status_code, 403, user)
            self.assertEqual(self.client.post(reverse('proposal_apply', args=[proposal.pk]), {'sections': ['condition']}).status_code, 403, user)
            self.assertEqual(self.client.post(reverse('proposal_reject', args=[proposal.pk]), {'note': 'x'}).status_code, 403, user)
        proposal.refresh_from_db()
        self.assertTrue(proposal.is_open)
        for user in (self.editor, self.superuser):
            self.client.force_login(user)
            response = self.client.get(reverse('proposal_list'))
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, f'Задача #{self.shared.pk}')
            self.assertEqual(self.client.get(reverse('proposal_detail', args=[proposal.pk])).status_code, 200)

    def test_list_filter_new_and_all(self):
        proposal, _ = self.fix_with_copy()
        other = create_proposal(self.other_guest, self.shared, kind='fix', message='Другое')
        TaskProposal.objects.filter(pk=other.pk).update(status=TaskProposal.STATUS_REJECTED)
        self.client.force_login(self.editor)
        response = self.client.get(reverse('proposal_list'))
        self.assertEqual([p.pk for p in response.context['page']], [proposal.pk])
        response = self.client.get(reverse('proposal_list') + '?status=all')
        self.assertEqual({p.pk for p in response.context['page']}, {proposal.pk, other.pk})

    def test_mine_shows_only_own(self):
        mine, _ = self.fix_with_copy()
        other = create_proposal(self.other_guest, self.shared, kind='fix', message='Чужое предложение')
        self.client.force_login(self.guest)
        response = self.client.get(reverse('proposals_mine'))
        self.assertEqual([p.pk for p in response.context['proposals']], [mine.pk])
        self.assertNotContains(response, 'Чужое предложение')
        self.client.force_login(self.student)
        self.assertEqual(self.client.get(reverse('proposals_mine')).status_code, 403)
