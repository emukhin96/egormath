"""Переход к соседям на странице подборки: другие варианты той же работы
и предыдущая/следующая подборка того же уровня.

Варианты в задачниках — соседние подборки с одинаковым названием
(«Самостоятельная работа III.1», варианты 1–4 у Шабунина, 1–3 в ДМ
Мерзляка); номер варианта есть только в ключе источника
(``CatalogNode.variant``). Соседи берутся из дерева каталога учителя
(``collection_catalog``): видимость и обрезка пустых ветвей там уже
учтены, лишних запросов нет.
"""


def _siblings(rows, pk):
    """Строки того же уровня, что подборка ``pk``, или None."""
    for row in rows:
        if row['collection'].pk == pk:
            return rows
        found = _siblings(row['children'], pk)
        if found is not None:
            return found
    return None


def _variant_number(node, index):
    """Подпись сегмента: «3*» из «Вариант 3*», иначе номер по порядку."""
    tail = node.variant[len('Вариант'):].strip() if node.variant else ''
    return tail or str(index)


def _same_variant(group, node, position):
    """В соседней работе — тот же вариант: по подписи, иначе по счёту."""
    if node.variant:
        for candidate in group:
            if candidate.variant.rstrip('*') == node.variant.rstrip('*'):
                return candidate
    return group[min(position, len(group) - 1)]


def collection_neighbors(source_row, pk):
    """``{'variants', 'prev', 'next', 'position', 'total'}`` или None.

    ``source_row`` — источник подборки из ``collection_catalog``.
    Одноимённые соседи подряд — одна работа в нескольких вариантах:
    ``variants`` — их сегменты, а ``prev``/``next`` ведут в соседнюю работу
    на тот же вариант (учитель, разбирающий вариант 2, идёт дальше по
    варианту 2)."""
    if source_row is None:
        return None
    rows = _siblings(source_row['roots'], pk) or []
    nodes = [row['collection'] for row in rows]
    if len(nodes) < 2:
        return None
    groups = []
    for node in nodes:
        if groups and groups[-1][0].catalog_title == node.catalog_title:
            groups[-1].append(node)
        else:
            groups.append([node])
    index = next(i for i, group in enumerate(groups)
                 if any(node.pk == pk for node in group))
    group = groups[index]
    position = next(i for i, node in enumerate(group) if node.pk == pk)
    current = group[position]
    variants = []
    if len(group) > 1:
        variants = [{'node': node, 'label': _variant_number(node, number),
                     'current': node.pk == pk}
                    for number, node in enumerate(group, start=1)]
    return {
        'variants': variants,
        'prev': (_same_variant(groups[index - 1], current, position)
                 if index > 0 else None),
        'next': (_same_variant(groups[index + 1], current, position)
                 if index + 1 < len(groups) else None),
        'position': index + 1,
        'total': len(groups),
    }
