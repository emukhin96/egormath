from django.test import SimpleTestCase

from problems.ostromogilsky_apartment_tables import normalize_apartment_tables
from problems.ostromogilsky_parser import _clean_body, normalize_oge_choices


class ApartmentTablesTests(SimpleTestCase):
    def test_washing_machine_cells_survive_split_and_unknown_rows_stay(self):
        header = r'Модель & Вместимость барабана, кг & Тип загрузки & Цена, руб. & Стоимость подключения, руб. & Стоимость доставки, \% & Высота × ширина × глубина, см'
        rows = [f'{label} & 6,5 & верт. & {28000+i} & {1700+i} & бесплатно & 85 × 60 × 45'
                for i, label in enumerate(['А', 'Б', 'В', r'$\Gamma$', 'Д', 'E', 'Ж', '3', 'И', 'K'])]
        source = ('Планируется купить стиральную машину.\n' + r'\begin{tabular}{|l|l|l|l|l|l|l|}'
                  + '\n' + ' \\\\\n'.join([header, *rows]) + '\n' + r'\end{tabular}')
        result = normalize_apartment_tables(source)
        self.assertEqual(result.count(r'\begin{tabular}'), 2)
        self.assertEqual(result.count('$6{,}5$'), 10)
        self.assertEqual(result.count('бесплатно'), 10)
        for i in range(10):
            self.assertIn(f'${28000+i}$', result)
            self.assertIn(f'${1700+i}$', result)
        self.assertEqual(normalize_apartment_tables(result), result)
        for old, new in [('K &', 'Х &'), ('85 × 60 × 45', '85 × ? × 45'), ('верт.', 'неясно')]:
            unknown = source.replace(old, new)
            self.assertEqual(normalize_apartment_tables(unknown), unknown)

    def test_tariff_table_is_idempotent(self):
        source = ('В квартире планируется подключить интернет.\n'
                  + r'\begin{tabular}{|l|l|l|}' + '\nТарифный план & Абонентская плата & Плата за трафик \\\\\n'
                  + 'А & 900 руб. & 1,5 руб. \\\\\nБ & 800 руб. & 2 руб. \\\\\nВ & 700 руб. & 3 руб.\n'
                  + r'\end{tabular}')
        result = normalize_apartment_tables(source)
        self.assertIn('$1{,}5$', result)
        self.assertEqual(normalize_apartment_tables(result), result)

    def test_single_dash_and_blank_cell_do_not_become_lists(self):
        source = r'В треугольнике $BM$' + '\n\n' + r'\begin{itemize}\item[-] медиана.\end{itemize}'
        result = normalize_oge_choices(source)
        self.assertNotIn('itemize', result)
        self.assertIn('— медиана.', result)
        unlabelled = r'В треугольнике $BM$ \begin{itemize}\item медиана, $BM=48$.\taskpic{1}\end{itemize}'
        self.assertEqual(normalize_oge_choices(unlabelled), r'В треугольнике $BM$ — медиана, $BM=48$.\taskpic{1}')
        blank = r'Найдите $2+3$.' + '\n\n' + r'\begin{itemize}\item □\\\end{itemize}'
        self.assertEqual(_clean_body(blank), r'Найдите $2+3$.')
        numbered = r'\begin{itemize}\item[1)] Настоящий пункт.\end{itemize}'
        self.assertEqual(normalize_oge_choices(numbered), numbered)
