"""Сид рубрикатора и перенос старых одиночных классов в GradeBand.

Связи задач уже скопированы в TaskTopic в 0009. Старая автотаблица M2M
убирается, если вдруг осталась после замены поля.
"""

from django.db import migrations


def seed_and_migrate_grades(apps, schema_editor):
    """Сид через исторические модели — будущие поля не ломают миграцию."""
    from django.db.models import Q
    from problems.rubricator_data import (BLOCKS, EXAM_MODELS, GRADE_BANDS,
                                          LEVELS, METHODS)

    Topic = apps.get_model('problems', 'Topic')
    GradeBand = apps.get_model('problems', 'GradeBand')
    FacetType = apps.get_model('problems', 'FacetType')
    FacetValue = apps.get_model('problems', 'FacetValue')
    ExamModel = apps.get_model('problems', 'ExamModel')
    ExamItem = apps.get_model('problems', 'ExamItem')
    Task = apps.get_model('problems', 'Task')
    Worksheet = apps.get_model('worksheets', 'Worksheet')

    # Сохраняем прежние и пользовательские темы: переносим только корни
    # веток без кода под служебный узел, как делает рабочий сидер.
    uncoded_pks = set(Topic.objects.filter(
        Q(code__isnull=True) | Q(code='')).values_list('pk', flat=True))
    if uncoded_pks:
        holder, _ = Topic.objects.update_or_create(
            code='_LEGACY', defaults={
                'name': 'Прежние темы', 'parent': None, 'order': 10_000})
        for topic in Topic.objects.filter(pk__in=uncoded_pks):
            if topic.parent_id in uncoded_pks:
                continue
            topic.parent = holder
            if Topic.objects.filter(parent=holder, name=topic.name).exclude(
                    pk=topic.pk).exists():
                topic.name = '%s [%s]' % (topic.name, topic.pk)
            topic.save(update_fields=['parent', 'name'])

    for block_i, (block_code, block_name, sections) in enumerate(BLOCKS):
        block, _ = Topic.objects.update_or_create(
            code=block_code,
            defaults={'name': block_name, 'parent': None, 'order': block_i})
        for section_i, (section_code, section_name, topics) in enumerate(sections):
            section, _ = Topic.objects.update_or_create(
                code=section_code,
                defaults={'name': section_name, 'parent': block,
                          'order': section_i})
            for topic_i, (topic_code, topic_name) in enumerate(topics):
                Topic.objects.update_or_create(
                    code=topic_code,
                    defaults={'name': topic_name, 'parent': section,
                              'order': topic_i})

    for code, name, order in GRADE_BANDS:
        GradeBand.objects.update_or_create(
            code=code, defaults={'name': name, 'order': order})

    level_type, _ = FacetType.objects.update_or_create(
        code='LEVEL', defaults={
            'name': 'Уровень содержания', 'selection_mode': 'MULTIPLE',
            'order': 10})
    method_type, _ = FacetType.objects.update_or_create(
        code='METHOD', defaults={
            'name': 'Метод решения', 'selection_mode': 'MULTIPLE',
            'order': 20})
    for code, name, order in LEVELS:
        FacetValue.objects.update_or_create(
            facet_type=level_type, code=code,
            defaults={'name': name, 'order': order})
    for order, (code, name) in enumerate(METHODS):
        FacetValue.objects.update_or_create(
            facet_type=method_type, code=code,
            defaults={'name': name, 'order': order})

    for model_code, exam_type, year, name, items in EXAM_MODELS:
        model, _ = ExamModel.objects.update_or_create(
            code=model_code, defaults={
                'exam_type': exam_type, 'exam_year': year, 'name': name})
        for number, item_code, item_name in items:
            ExamItem.objects.update_or_create(
                code=item_code, defaults={
                    'exam_model': model, 'item_number': number,
                    'name': item_name, 'order': number})

    grade_codes = {
        5: 'GRADE_5', 6: 'GRADE_6', 7: 'GRADE_7', 8: 'GRADE_8',
        9: 'GRADE_9', 10: 'GRADE_10_11', 11: 'GRADE_10_11',
    }
    bands = {band.code: band for band in GradeBand.objects.all()}
    for task in Task.objects.exclude(grade_level=None).iterator():
        band = bands.get(grade_codes.get(task.grade_level))
        if band and not task.grade_bands.exists():
            task.grade_bands.add(band)
    for worksheet in Worksheet.objects.exclude(grade=None).iterator():
        band = bands.get(grade_codes.get(worksheet.grade))
        if band and not worksheet.grade_bands.exists():
            worksheet.grade_bands.add(band)


def drop_legacy_task_topics(apps, schema_editor):
    # Старый M2M без through: problems_task_topics.
    # На MySQL Django запрещает DDL через schema_editor внутри транзакции.
    table = 'problems_task_topics'
    if table not in schema_editor.connection.introspection.table_names():
        return
    schema_editor.execute('DROP TABLE IF EXISTS problems_task_topics')


class Migration(migrations.Migration):

    # MySQL не откатывает DDL — иначе DROP TABLE падает с
    # TransactionManagementError даже при IF EXISTS.
    atomic = False

    dependencies = [
        ('problems', '0009_rubricator'),
        ('worksheets', '0014_rubricator'),
    ]

    operations = [
        migrations.RunPython(drop_legacy_task_topics, migrations.RunPython.noop),
        migrations.RunPython(seed_and_migrate_grades, migrations.RunPython.noop),
    ]
