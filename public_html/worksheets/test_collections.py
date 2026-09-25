from django.test import TestCase
from django.urls import reverse

from problems.models import Source, Task, TaskSubitem, Topic
from problems.tests import make_teacher
from worksheets.latex import worksheet_to_tex
from worksheets.models import Collection, Worksheet, WorksheetItem


class CollectionTests(TestCase):
    def setUp(self):
        self.owner = make_teacher()
        self.other = make_teacher('teacher2')
        self.source = Source.objects.create(title='Задачник')
        self.worksheet = Worksheet.objects.create(
            title='Готовая тема', owner=self.owner)
        self.task = Task.objects.create(
            text_latex='Вычислите $2+2$.', author_answer_latex='4',
            author_solution_latex='$2+2=4$.', stars=0, created_by=self.owner)
        TaskSubitem.objects.create(
            task=self.task, order=10, text_latex='Поясните вычисление')
        WorksheetItem.objects.create(
            worksheet=self.worksheet, task=self.task, order=10)
        WorksheetItem.objects.create(
            worksheet=self.worksheet, text_latex='Вспомните правило.',
            text_style='memo', order=20)
        self.collection = Collection.objects.create(
            worksheet=self.worksheet, source=self.source,
            locator='chapter-1', source_path=['Глава 1'], is_published=True)

    def test_author_content_falls_back_in_pdf(self):
        tex = worksheet_to_tex(self.worksheet, 'teacher')
        self.assertIn('[{4}]', tex)
        self.assertIn('$2+2=4$.', tex)
        self.task.answer_latex = 'редакторский ответ'
        self.task.save(update_fields=['answer_latex'])
        tex = worksheet_to_tex(self.worksheet, 'answers')
        self.assertNotIn('редакторский ответ', tex)
        self.assertIn('[{4}]', tex)

    def test_use_collection_copies_all_worksheet_elements(self):
        self.client.login(username='teacher2', password='pass12345')
        response = self.client.post(
            reverse('collection_use', args=[self.collection.pk]))
        self.assertEqual(response.status_code, 302)
        copy = Worksheet.objects.get(owner=self.other)
        self.assertFalse(hasattr(copy, 'collection'))
        self.assertEqual(copy.items.count(), 2)
        self.assertEqual(copy.items.filter(task=self.task).count(), 1)
        self.assertEqual(copy.items.filter(text_style='memo').count(), 1)

    def test_collection_catalog_and_editor_render(self):
        self.client.login(username='teacher1', password='pass12345')
        catalog = self.client.get(reverse('collection_list'))
        self.assertContains(catalog, 'Задачник')
        self.assertNotContains(catalog, 'Готовая тема')
        source = self.client.get(reverse('collection_list'), {
            'source': self.source.pk,
        })
        self.assertContains(source, 'Готовая тема')
        detail = self.client.get(reverse(
            'collection_detail', args=[self.collection.pk]))
        self.assertContains(detail, 'Использовать подборку')
        self.assertContains(detail, 'Поясните вычисление')
        self.assertContains(detail, 'toggle-answers')
        self.assertContains(detail, 'ответы и решения')
        self.assertContains(detail, 'id="toggle-author-only"')
        self.assertContains(detail, 'data-answers-key="collection-show-answers"')
        self.assertContains(detail, 'id="toggle-masks"')
        self.assertContains(detail, 'data-worksheet-mask')
        self.assertContains(detail, 'id="answer-mask-dialog"')
        self.assertNotContains(detail, 'Будет создан обычный личный листок')
        # Тумблер в шапке страницы — рядом с кнопками, не внутри списка
        head = detail.content.decode().split('id="ws-items"', 1)[0]
        self.assertIn('toggle-answers', head)
        self.assertIn('toggle-masks', head)
        self.assertContains(detail, 'data-cart-form')
        editor = self.client.get(reverse(
            'collection_edit', args=[self.collection.pk]), follow=True)
        self.assertContains(editor, 'Конструктор подборки')
        self.assertContains(editor, 'Текст между задачами')

    def test_collection_hides_answer_images_until_answers_block(self):
        pictured = Task.objects.create(
            text_latex='Постройте график', created_by=self.owner)
        TaskSubitem.objects.create(
            task=pictured, order=10, text_latex='$y=x$',
            author_answer_latex='см. рис.\n\\taskpic{1}')
        image = pictured.images.create(
            image='task_images/graph-answer.png', order=10)
        WorksheetItem.objects.create(
            worksheet=self.worksheet, task=pictured, order=30)
        self.client.login(username='teacher1', password='pass12345')
        detail = self.client.get(reverse(
            'collection_detail', args=[self.collection.pk]))
        image_url = reverse('task_image_file', args=[image.pk])
        html = detail.content.decode()
        chunk = html.split('Постройте график', 1)[1]
        before_answers, after_answers = chunk.split('div class="ws-answers"', 1)
        self.assertNotIn(image_url, before_answers)
        self.assertIn(image_url, after_answers)
        self.assertIn('hidden', after_answers.split('>', 1)[0])
        self.assertIn('см. рис.', chunk)
        self.assertIn('а)&nbsp;', chunk)
        self.assertNotIn('— ответ:', html)

    def test_copied_worksheet_has_visibility_buttons(self):
        self.client.login(username='teacher2', password='pass12345')
        self.client.post(reverse('collection_use', args=[self.collection.pk]))
        copy = Worksheet.objects.get(owner=self.other)
        self.assertFalse(copy.share_links.exists())
        response = self.client.get(reverse('worksheet_detail', args=[copy.pk]))
        self.assertContains(response, 'vis-btn')
        self.assertContains(response, 'Сначала создайте публичную ссылку')

    def test_empty_group_cannot_be_copied(self):
        group_sheet = Worksheet.objects.create(
            title='Группа', owner=self.owner)
        group = Collection.objects.create(
            worksheet=group_sheet, source=self.source,
            locator='group', source_path=['Группа'])
        self.client.login(username='teacher1', password='pass12345')
        response = self.client.post(
            reverse('collection_use', args=[group.pk]), follow=True)
        self.assertContains(response, 'не содержит элементов')
        self.assertEqual(Worksheet.objects.filter(
            owner=self.owner, title='Группа').count(), 1)

    def test_catalog_shows_group_and_skips_single_child_level(self):
        group_sheet = Worksheet.objects.create(
            title='№10. Вероятности', owner=self.owner)
        group = Collection.objects.create(
            worksheet=group_sheet, source=self.source,
            locator='group', source_path=['№10. Вероятности'])
        self.collection.parent = group
        self.collection.save(update_fields=['parent'])
        self.client.login(username='teacher1', password='pass12345')

        catalog = self.client.get(reverse('collection_list'), {
            'source': self.source.pk,
        })
        self.assertContains(catalog, '№10. Вероятности')
        self.assertNotContains(catalog, 'Готовая тема')
        self.assertContains(catalog, 'collection-source-card')
        self.assertContains(catalog, '<strong>2</strong> задачи', html=True)

        detail = self.client.get(reverse(
            'collection_detail', args=[group.pk]), follow=True)
        self.assertRedirects(
            detail, reverse('collection_detail', args=[self.collection.pk]))
        self.assertContains(detail, 'Вычислите')
        self.assertNotContains(detail, 'Это раздел, который объединяет')
        self.assertNotContains(detail, 'Подборка пуста')

        self.client.logout()
        self.client.login(username='teacher2', password='pass12345')
        other_catalog = self.client.get(reverse('collection_list'), {
            'source': self.source.pk,
        })
        self.assertContains(other_catalog, '№10. Вероятности')
        self.assertRedirects(
            self.client.get(reverse('collection_detail', args=[group.pk])),
            reverse('collection_detail', args=[self.collection.pk]),
            fetch_redirect_response=False)

    def test_catalog_displays_collection_topics_in_tree_and_sidebar(self):
        topic = Topic.objects.create(code='TEST.COL', name='Алгебра')
        self.worksheet.topics.add(topic)
        self.client.login(username='teacher1', password='pass12345')

        catalog = self.client.get(reverse('collection_list'), {
            'source': self.source.pk,
        })
        self.assertContains(catalog, 'TEST.COL')
        self.assertContains(catalog, 'Алгебра')
        detail = self.client.get(reverse(
            'collection_detail', args=[self.collection.pk]))
        self.assertContains(detail, 'Темы раздела')
        self.assertContains(detail, 'TEST.COL')

    def test_large_collection_is_paginated_with_continuous_numbering(self):
        worksheet = Worksheet.objects.create(
            title='Большая подборка', owner=self.owner)
        collection = Collection.objects.create(
            worksheet=worksheet, source=self.source, locator='large',
            source_path=['Большая подборка'], is_published=True)
        for number in range(1, 31):
            task = Task.objects.create(
                text_latex=f'Задача {number}.', created_by=self.owner)
            WorksheetItem.objects.create(
                worksheet=worksheet, task=task, order=number * 10)
        self.client.login(username='teacher1', password='pass12345')

        first = self.client.get(reverse(
            'collection_detail', args=[collection.pk]))
        self.assertContains(first, 'Задача 25.')
        self.assertNotContains(first, 'Задача 26.')
        self.assertContains(first, '?page=2')
        # В корзину уходит только страница — так и написано на кнопке
        self.assertContains(first, 'Страницу в корзину · 25')
        self.assertContains(first, 'страница 1 из 2')

        second = self.client.get(
            reverse('collection_detail', args=[collection.pk]),
            {'page': 2})
        self.assertContains(second, '<span class="ws-num">26.</span>', html=True)
        self.assertContains(second, 'Задача 30.')
        self.assertNotContains(second, 'Задача 25.')


class CollectionFlatViewTests(TestCase):
    """Раздел «списком»: два уровня подборок на одной странице."""

    def setUp(self):
        self.owner = make_teacher()
        self.client.login(username='teacher1', password='pass12345')
        self.source = Source.objects.create(title='Банк')

        def make(title, parent=None, tasks=0, published=True, owner=None):
            worksheet = Worksheet.objects.create(
                title=title, owner=owner or self.owner)
            for i in range(tasks):
                task = Task.objects.create(
                    text_latex=f'{title}: задача {i + 1}.', created_by=self.owner)
                WorksheetItem.objects.create(
                    worksheet=worksheet, task=task, order=(i + 1) * 10)
            return Collection.objects.create(
                worksheet=worksheet, source=self.source, parent=parent,
                locator=title, is_published=published)

        self.make = make
        self.root = make('№5. Уравнения')
        self.sub_a = make('5.1 Линейные', self.root, tasks=1)
        self.sub_b = make('5.2 Квадратные', self.root)
        self.leaf_b1 = make('5.2.1 Прототип', self.sub_b, tasks=2)
        self.leaf_b2 = make('5.2.2 Прототип', self.sub_b)
        self.deep = make('5.2.2.1 Аналог', self.leaf_b2, tasks=1)

    def test_section_shows_two_levels_with_tasks(self):
        response = self.client.get(reverse('collection_detail', args=[self.root.pk]))
        self.assertEqual(response.status_code, 200)
        groups = response.context['flat_groups']
        self.assertEqual(
            [(g['collection'].pk, g['depth'], len(g['rows'])) for g in groups],
            [(self.sub_a.pk, 1, 1), (self.sub_b.pk, 1, 0),
             (self.leaf_b1.pk, 2, 2), (self.leaf_b2.pk, 2, 0)])
        self.assertContains(response, '5.1 Линейные: задача 1.')
        self.assertContains(response, '5.2.1 Прототип: задача 2.')
        # Третий уровень — только ссылкой «открыть раздел».
        self.assertNotContains(response, '5.2.2.1 Аналог: задача 1.')
        self.assertContains(response, 'открыть раздел')
        self.assertContains(response, 'Всё в корзину · 3')
        self.assertContains(response, 'href="?view=tree"')

    def test_tree_view_and_hidden_private_children(self):
        other = make_teacher('teacher2')
        self.make('5.3 Чужая закрытая', self.root, tasks=1,
                  published=False, owner=other)
        response = self.client.get(
            reverse('collection_detail', args=[self.root.pk]), {'view': 'tree'})
        self.assertIsNone(response.context['flat_groups'])
        self.assertContains(response, '<th>Задач</th>', html=True)
        self.assertContains(response, 'Списком')
        self.assertNotContains(response, '5.3 Чужая закрытая')
        response = self.client.get(reverse('collection_detail', args=[self.root.pk]))
        self.assertNotContains(response, 'Чужая закрытая: задача 1.')

    def test_too_many_items_falls_back_to_tree(self):
        from worksheets import views
        with self.settings():
            old = views.FLAT_ITEMS_LIMIT
            views.FLAT_ITEMS_LIMIT = 2
            try:
                response = self.client.get(
                    reverse('collection_detail', args=[self.root.pk]))
            finally:
                views.FLAT_ITEMS_LIMIT = old
        self.assertIsNone(response.context['flat_groups'])
        self.assertContains(response, 'слишком много задач')

    def test_flat_limit_fits_cart_limit(self):
        from worksheets import cart, views
        self.assertLessEqual(views.FLAT_ITEMS_LIMIT, cart.CART_ADD_MANY_LIMIT)

    def test_cart_add_many(self):
        tasks = list(Task.objects.order_by('pk'))
        response = self.client.post(reverse('cart_add_many'), {
            'task_ids': [t.pk for t in tasks[:3]],
            'next': reverse('collection_detail', args=[self.root.pk])})
        self.assertRedirects(
            response, reverse('collection_detail', args=[self.root.pk]))
        self.assertEqual(self.client.session['cart_tasks'],
                         [t.pk for t in tasks[:3]])
        # Повтор не дублирует, чужой id пропускается.
        self.client.post(reverse('cart_add_many'), {
            'task_ids': [tasks[0].pk, 999999]}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(len(self.client.session['cart_tasks']), 3)
        response = self.client.post(reverse('cart_add_many'), {},
                                    HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 400)


class CollectionTitleTests(TestCase):
    """Сортировка и заголовки дочерних подборок в разделе."""

    def setUp(self):
        self.owner = make_teacher()
        self.client.login(username='teacher1', password='pass12345')
        self.source = Source.objects.create(title='Банк')

        def make(title, parent=None, tasks=1):
            worksheet = Worksheet.objects.create(title=title, owner=self.owner)
            for i in range(tasks):
                task = Task.objects.create(
                    text_latex=f'{title}: задача {i + 1}.',
                    created_by=self.owner)
                WorksheetItem.objects.create(
                    worksheet=worksheet, task=task, order=(i + 1) * 10)
            return Collection.objects.create(
                worksheet=worksheet, source=self.source, parent=parent,
                locator=title, is_published=True)

        self.make = make
        self.root = make('№1. Планиметрия 1', tasks=0)
        for tail in ('1.10', '1.2', '1.1', '1.19', '1.20'):
            make(f'№01. Планиметрия 1 — прототип {tail}', self.root)

    def test_children_sorted_naturally_and_titled_without_parent(self):
        response = self.client.get(
            reverse('collection_detail', args=[self.root.pk]))
        groups = response.context['flat_groups']
        self.assertEqual(
            [g['collection'].short_title for g in groups],
            ['Прототип 1.1', 'Прототип 1.2', 'Прототип 1.10',
             'Прототип 1.19', 'Прототип 1.20'])
        # Заголовок раздела — из каталога, с двузначным номером
        self.assertContains(response, '<h1>№01. Планиметрия 1</h1>', html=True)
        self.assertContains(response, 'Прототип 1.1</a>')
        self.assertContains(response, '· 1 задача')
        self.assertContains(response, 'Всё в корзину · 5')
        # Панель «На этой странице» различает пункты
        sidebar = response.content.decode().split('На этой странице', 1)[1]
        self.assertIn('Прототип 1.20', sidebar)

    def test_rubric_math_is_rendered(self):
        leaf = self.make('Глава 1', tasks=1)
        WorksheetItem.objects.create(
            worksheet=leaf.worksheet, order=5,
            rubric='§ 4. Графики \\(y=f(kx)\\)')
        response = self.client.get(
            reverse('collection_detail', args=[leaf.pk]))
        self.assertContains(
            response, '<h3 class="math-content">§ 4. Графики \\(y=f(kx)\\)</h3>',
            html=True)
        self.assertContains(response, 'class="ws-collection"')


class CollectionAnswerSourceTests(TestCase):
    """Рамка «Ответ / Решение»: происхождение и второй вариант."""

    def setUp(self):
        self.owner = make_teacher()
        self.client.login(username='teacher1', password='pass12345')
        self.source = Source.objects.create(title='Задачник')
        self.worksheet = Worksheet.objects.create(
            title='Ответы', owner=self.owner)
        self.collection = Collection.objects.create(
            worksheet=self.worksheet, source=self.source,
            locator='answers', is_published=True)

    def add(self, **fields):
        task = Task.objects.create(
            text_latex='Задача.', created_by=self.owner, **fields)
        WorksheetItem.objects.create(
            worksheet=self.worksheet, task=task,
            order=10 * (self.worksheet.items.count() + 1))
        return task

    def page(self):
        return self.client.get(
            reverse('collection_detail', args=[self.collection.pk]))

    def test_author_answer_is_labelled_and_ai_variant_is_collapsed(self):
        self.add(author_answer_latex='$2; 5$',
                 answer_latex='Минимум $2$, максимум $5$')
        response = self.page()
        self.assertContains(response, 'data-src="author"')
        self.assertContains(response, 'answer-src-author')
        self.assertContains(response, '$2; 5$')
        self.assertContains(response, 'Редакторский / AI-ответ')
        self.assertContains(response, 'Минимум $2$, максимум $5$')

    def test_same_answer_up_to_period_has_no_alternative(self):
        self.add(author_answer_latex='$0$', answer_latex='$0$.')
        response = self.page()
        self.assertNotContains(response, 'answer-alt')

    def test_answer_comparison_keeps_case(self):
        # «$A$» и «$a$» — разные ответы: редакторский вариант не теряется
        self.add(author_answer_latex='$A$', answer_latex='$a$')
        response = self.page()
        self.assertContains(response, 'answer-alt')
        self.assertContains(response, '$a$')

    def test_ai_only_answer_is_labelled_ai(self):
        self.add(answer_latex='Нет.', solution_latex='По чётности.')
        response = self.page()
        self.assertContains(response, 'answer-box math-content" data-src="ai"')
        self.assertContains(response, '>AI</span>')
        self.assertNotContains(response, 'answer-src-author')

    def test_mixed_subitems_are_labelled_per_row(self):
        task = self.add()
        TaskSubitem.objects.create(
            task=task, order=10, text_latex='чётной',
            author_answer_latex='$a=1$', answer_latex='$a=1$.')
        TaskSubitem.objects.create(
            task=task, order=20, text_latex='нечётной', answer_latex='$a=-1$')
        response = self.page()
        self.assertContains(response, 'answer-box math-content" data-src="mixed"')
        self.assertContains(response, 'answer-row" data-src="author"')
        self.assertContains(response, 'answer-row" data-src="ai"')

    def test_author_hint_becomes_heading_and_keeps_full_ai_solution(self):
        self.add(author_answer_latex='$a=1$',
                 author_solution_latex='Указание. См. пример 3 в § 3.',
                 solution_latex='Левая часть чётна, поэтому корень один.')
        response = self.page()
        self.assertContains(response, '<strong>Указание:</strong>', html=True)
        self.assertContains(response, 'См. пример 3 в § 3.')
        self.assertNotContains(response, 'Указание. См. пример')
        self.assertContains(response, 'Полное решение от AI')
        self.assertContains(response, 'Левая часть чётна')

    def test_pdf_still_uses_author_material_only(self):
        self.add(author_answer_latex='4', answer_latex='четыре')
        tex = worksheet_to_tex(self.worksheet, 'answers')
        self.assertIn('[{4}]', tex)
        self.assertNotIn('четыре', tex)
