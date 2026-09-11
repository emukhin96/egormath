"""Узкие таблицы квартир с сохранением каждой ячейки исходной таблицы."""
import re


def _table(headers, rows, widths):
    result = r'\begin{tabular}{|' + '|'.join('p{' + w + 'cm}' for w in widths) + '|}\n'
    for row in [headers, *rows]:
        result += '\\hline\n' + ' & '.join(row) + ' \\\\\n'
    return result + '\\hline\n' + r'\end{tabular}'


def _format_cell(value):
    value = value.strip().replace('$', '').replace(r'\times', r' $\times$ ').replace('×', r' $\times$ ')
    return re.sub(r'\d+(?:,\d+)?', lambda m: '$' + m[0].replace(',', '{,}') + '$', value)


def normalize_apartment_tables(text):
    """Меняет только узнаваемые целые таблицы стиральных машин и интернета."""
    if not ('стиральную машину' in text or 'квартире планируется подключить интернет' in text):
        return text

    def replace(match):
        original = match[0]
        if original.count(r'\begin{tabular}') != 1:
            return original
        lines = [line for line in original.splitlines() if '&' in line]
        if not lines:
            return original
        headers, *rows = [[c.strip() for c in line.rstrip('\\ ').split('&')] for line in lines]
        if headers == ['Тарифный план', 'Абонентская плата', 'Плата за трафик']:
            if r'{|p{2.7cm}|p{2.7cm}|p{2.8cm}|}' in original:
                return original
            if len(rows) == 3 and all(len(row) == 3 for row in rows):
                return _table(headers, [[_format_cell(c) for c in row] for row in rows], ['2.7', '2.7', '2.8'])
            return original
        expected = ['Модель', 'Вместимость барабана, кг', 'Тип загрузки', 'Цена, руб.',
                    'Стоимость подключения, руб.', r'Стоимость доставки, \%', 'Высота × ширина × глубина, см']
        if headers != expected or len(rows) != 10 or any(len(row) != 7 for row in rows):
            return original
        aliases = {'А': {'А'}, 'Б': {'Б'}, 'В': {'В'}, 'Г': {'Г', r'$\Gamma$'},
                   'Д': {'Д'}, 'Е': {'Е', 'E'}, 'Ж': {'Ж'}, 'З': {'З', '3'},
                   'И': {'И'}, 'К': {'К', 'K'}}
        for (label, spellings), row in zip(aliases.items(), rows):
            if row[0] not in spellings or row[2] not in {'верт.', 'фронт.'}:
                return original
            if any(not re.fullmatch(r'\d+(?:,\d+)?', row[i].strip('$')) for i in [1, 3, 4]):
                return original
            if not re.fullmatch(r'(?:\d+(?:,\d+)?|бесплатно)', row[5].strip('$')):
                return original
            dimensions = row[6].replace('$', '').replace(r'\times', '×')
            if not re.fullmatch(r'\s*\d+\s*×\s*\d+\s*×\s*\d+\s*', dimensions):
                return original
            row[0] = label
        technical = [[r[0], _format_cell(r[1]), r[2], _format_cell(r[6])] for r in rows]
        costs = [[r[0], *[_format_cell(c) for c in r[3:6]]] for r in rows]
        return ('Размеры указаны в порядке: высота, ширина, глубина.\n\n'
                + _table(['Модель', 'Барабан, кг', 'Загрузка', 'Размеры, см'], technical, ['1.3', '1.5', '1.7', '3.2'])
                + '\n\n' + _table(['Модель', 'Цена, руб.', 'Подключение, руб.', r'Доставка, \%'], costs, ['1.3', '1.8', '2.5', '2']))

    return re.sub(r'\\begin\{tabular\}.*?\\end\{tabular\}', replace, text, flags=re.DOTALL)
