"""Загрузка стартового рубрикатора тем и базовых тегов.

Идемпотентна: существующие темы/теги не дублируются.
"""

from django.core.management.base import BaseCommand

from problems.models import Tag, Topic

TOPICS = {
    'Арифметика': [
        'Натуральные числа', 'Обыкновенные дроби', 'Десятичные дроби',
        'Проценты', 'Пропорции', 'Делимость',
    ],
    'Алгебра': [
        'Алгебраические выражения', 'Линейные уравнения',
        'Квадратные уравнения', 'Системы уравнений', 'Неравенства',
        'Функции и графики', 'Последовательности и прогрессии',
        'Степени и корни', 'Логарифмы', 'Тригонометрия',
    ],
    'Геометрия': [
        'Треугольники', 'Четырёхугольники', 'Окружность',
        'Подобие', 'Площади', 'Векторы и координаты',
        'Стереометрия',
    ],
    'Текстовые задачи': [
        'Задачи на движение', 'Задачи на работу', 'Задачи на смеси и сплавы',
    ],
    'Комбинаторика и вероятность': [
        'Комбинаторика', 'Теория вероятностей', 'Статистика',
    ],
    'Начала анализа': [
        'Производная', 'Первообразная и интеграл',
    ],
    'Олимпиадные задачи': [
        'Логика', 'Инварианты', 'Принцип Дирихле', 'Раскраски',
    ],
}

TAGS = ['ОГЭ', 'ЕГЭ (база)', 'ЕГЭ (профиль)', 'МЦКО', 'ВПР', 'Олимпиада', 'Устный счёт']


class Command(BaseCommand):
    help = 'Создаёт стартовый рубрикатор тем и базовые теги'

    def handle(self, *args, **options):
        created_topics = 0
        for parent_name, children in TOPICS.items():
            parent, was_created = Topic.objects.get_or_create(
                name=parent_name, parent=None)
            created_topics += was_created
            for i, child_name in enumerate(children):
                _, was_created = Topic.objects.get_or_create(
                    name=child_name, parent=parent, defaults={'order': i})
                created_topics += was_created

        created_tags = 0
        for tag_name in TAGS:
            _, was_created = Tag.objects.get_or_create(name=tag_name)
            created_tags += was_created

        self.stdout.write(self.style.SUCCESS(
            f'Готово: новых тем {created_topics}, новых тегов {created_tags}'))
