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


def attach_issued_to(worksheets):
    """«Кому выдан» в списке листков: ``issued_groups`` — названия групп,
    ``issued_students`` — ученики, получившие листок не через группу.

    Учеников группы поимённо не перечисляем. Группы — только владельца
    листка (у суперпользователя в списке листки разных учителей). Назначения
    берутся из ``prefetch_related('assignments__student',
    'assignments__source_groups')`` списка; группы — одним запросом.
    """
    from accounts.models import StudentGroup

    worksheets = list(worksheets)
    owner_ids = {w.owner_id for w in worksheets if getattr(w, 'was_assigned', True)}
    groups = {}
    for group in (StudentGroup.objects.filter(teacher_id__in=owner_ids)
                  .prefetch_related('students')):
        groups.setdefault(group.teacher_id, []).append(group)
    for worksheet in worksheets:
        assignments = list(worksheet.assignments.all())
        sections, individual = assignment_sections(
            assignments, groups.get(worksheet.owner_id, []))
        worksheet.issued_groups = [section['group'].name for section in sections]
        worksheet.issued_students = sorted(
            (a.student.get_full_name() or a.student.username for a in individual),
            key=str.casefold)


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
