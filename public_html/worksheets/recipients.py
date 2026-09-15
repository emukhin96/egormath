"""Получатели листка и выбор видимых задач целиком, включая общие блоки."""


def assignment_sections(assignments, groups):
    """Новые выдачи — по сохранённым группам, старые — по полному составу."""
    assigned_students = {a.student_id for a in assignments}
    by_group = {}
    individual = []
    complete_groups = [g for g in groups
                       if (members := {s.pk for s in g.students.all()})
                       and members <= assigned_students]
    for assignment in assignments:
        selected = list(assignment.source_groups.all())
        if not assignment.recipient_origin_known:
            selected = [g for g in complete_groups
                        if assignment.student_id in {s.pk for s in g.students.all()}]
        if not selected:
            individual.append(assignment)
        for group in selected:
            section = by_group.setdefault(group.pk, {'group': group, 'assignments': []})
            section['assignments'].append(assignment)
    return sorted(by_group.values(), key=lambda section: section['group'].name), individual


def visibility_options(worksheet, recipient):
    """Одна галочка на общий блок: его вопросы нельзя раздавать по отдельности."""
    hidden = set(recipient.hidden_items.values_list('pk', flat=True))
    options, blocks = [], {}
    number = 0
    for item in worksheet.ordered_items():
        if not item.task_id:
            continue
        number += 1
        block_id = item.task.block_id
        option = blocks.get(block_id) if block_id else None
        if option is None:
            option = {'value': item.pk, 'item_ids': [], 'numbers': [], 'visible': True,
                      'block': bool(block_id)}
            options.append(option)
            if block_id:
                blocks[block_id] = option
        option['item_ids'].append(item.pk)
        option['numbers'].append(str(number))
        option['visible'] = option['visible'] and item.pk not in hidden
    for option in options:
        option['label'] = '№ ' + ', '.join(option['numbers'])
    return options
