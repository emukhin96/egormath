from django.test import SimpleTestCase
from problems.block_text import split_common_condition


class CommonConditionTests(SimpleTestCase):
    def setUp(self):
        self.common = ('Описание общего плана местности и условий движения. ' * 4
                       + r'\taskpic{1}' + '\n\nСторона клетки равна $2$ км.')
        self.questions = ['Первый вопрос.', 'Второй вопрос.', 'Третий вопрос.',
                          'Четвёртый вопрос.', 'Пятый вопрос.']
        self.texts = [self.common + '\n\n' + q for q in self.questions]

    def test_reconstructs_every_original_including_whitespace(self):
        self.texts[1] = self.texts[1].replace(' $2$ ', ' 2 ')
        result = split_common_condition(self.texts, [['plan']] * 5)
        self.assertIsNotNone(result)
        self.assertEqual(result.image_positions, (1,))
        self.assertEqual([a + b for a, b in zip(result.prefixes, result.questions)], self.texts)
        self.assertEqual([q.strip() for q in result.questions], self.questions)

    def test_different_or_missing_plan_prevents_deduplication(self):
        for keys in [[['plan']] * 4 + [['other']], [['plan']] * 4 + [[]]]:
            self.assertIsNone(split_common_condition(self.texts, keys))

    def test_partial_sentence_or_incomplete_block_is_not_cut(self):
        self.assertIsNone(split_common_condition(self.texts[:4], [['plan']] * 4))
        texts = [self.common + '\n\nОбщий вопрос ' + q for q in self.questions]
        self.assertIsNone(split_common_condition(texts, [['plan']] * 5))

    def test_open_math_or_table_is_not_cut(self):
        for opener in ['$', r'\begin{tabular}{l}']:
            texts = [opener + text for text in self.texts]
            self.assertIsNone(split_common_condition(texts, [['plan']] * 5))
