"""Заменяет активную модель профильного ЕГЭ на проект КИМ 2027 года."""

from django.db import migrations


EGE_PROFILE_2027_ITEMS = [
    (0, 'EGE_PROFILE_2027', 'ЕГЭ профиль (без номера задания)'),
    (1, 'EGE_PROFILE_2027_01', 'ЕГЭ профиль. Задание 1 (планиметрия)'),
    (2, 'EGE_PROFILE_2027_02', 'ЕГЭ профиль. Задание 2 (векторы на плоскости)'),
    (3, 'EGE_PROFILE_2027_03', 'ЕГЭ профиль. Задание 3 (стереометрия)'),
    (4, 'EGE_PROFILE_2027_04', 'ЕГЭ профиль. Задание 4 (базовая вероятность)'),
    (5, 'EGE_PROFILE_2027_05', 'ЕГЭ профиль. Задание 5 (сложение и умножение вероятностей)'),
    (6, 'EGE_PROFILE_2027_06', 'ЕГЭ профиль. Задание 6 (случайные величины)'),
    (7, 'EGE_PROFILE_2027_07', 'ЕГЭ профиль. Задание 7 (уравнения)'),
    (8, 'EGE_PROFILE_2027_08', 'ЕГЭ профиль. Задание 8 (вычисления и преобразования выражений)'),
    (9, 'EGE_PROFILE_2027_09', 'ЕГЭ профиль. Задание 9 (производная и чтение графика)'),
    (10, 'EGE_PROFILE_2027_10', 'ЕГЭ профиль. Задание 10 (прикладная задача и вычисления по формуле)'),
    (11, 'EGE_PROFILE_2027_11', 'ЕГЭ профиль. Задание 11 (текстовая задача)'),
    (12, 'EGE_PROFILE_2027_12', 'ЕГЭ профиль. Задание 12 (анализ графиков функций)'),
    (13, 'EGE_PROFILE_2027_13', 'ЕГЭ профиль. Задание 13 (финансовая математика)'),
    (14, 'EGE_PROFILE_2027_14', 'ЕГЭ профиль. Задание 14 (уравнение с отбором корней)'),
    (15, 'EGE_PROFILE_2027_15', 'ЕГЭ профиль. Задание 15 (стереометрическая задача с развёрнутым решением)'),
    (16, 'EGE_PROFILE_2027_16', 'ЕГЭ профиль. Задание 16 (неравенства)'),
    (17, 'EGE_PROFILE_2027_17', 'ЕГЭ профиль. Задание 17 (экстремальная текстовая задача)'),
    (18, 'EGE_PROFILE_2027_18', 'ЕГЭ профиль. Задание 18 (планиметрическая задача с развёрнутым решением)'),
    (19, 'EGE_PROFILE_2027_19', 'ЕГЭ профиль. Задание 19 (задача с параметром)'),
    (20, 'EGE_PROFILE_2027_20', 'ЕГЭ профиль. Задание 20 (целые числа, делимость и дискретные конструкции)'),
]


def install_ege_profile_2027(apps, schema_editor):
    """Добавляет 2027 и удаляет метки без ссылок задач или черновиков."""
    ExamModel = apps.get_model('problems', 'ExamModel')
    ExamItem = apps.get_model('problems', 'ExamItem')
    TextbookTaskDraft = apps.get_model('problems', 'TextbookTaskDraft')

    model, _ = ExamModel.objects.update_or_create(
        code='EXAM_EGE_PROFILE_2027',
        defaults={
            'exam_type': 'EGE_PROFILE',
            'exam_year': 2027,
            'name': 'ЕГЭ по математике, профильный уровень — 2027',
        })
    for number, code, name in EGE_PROFILE_2027_ITEMS:
        ExamItem.objects.update_or_create(
            code=code,
            defaults={
                'exam_model': model,
                'item_number': number,
                'name': name,
                'order': number,
            })

    draft_codes = set()
    for codes in TextbookTaskDraft.objects.values_list(
            'exam_item_codes', flat=True).iterator():
        if isinstance(codes, list):
            draft_codes.update(code for code in codes if isinstance(code, str))

    old_models = ExamModel.objects.filter(exam_type='EGE_PROFILE').exclude(
        pk=model.pk)
    for old_model in old_models:
        for item in old_model.items.all():
            if not item.tasks.exists() and item.code not in draft_codes:
                item.delete()
        if not old_model.items.exists():
            old_model.delete()


class Migration(migrations.Migration):

    dependencies = [
        ('problems', '0024_textbook_transfer_key'),
    ]

    operations = [
        migrations.RunPython(install_ege_profile_2027, migrations.RunPython.noop),
    ]
