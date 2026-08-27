"""Совместимость: прежний seed_topics теперь загружает новый рубрикатор."""

from django.core.management.base import BaseCommand

from problems.rubricator import seed_rubricator


class Command(BaseCommand):
    help = 'Создаёт рубрикатор тем, классов, фасетов и экзаменационных линий'

    def handle(self, *args, **options):
        created = seed_rubricator()
        self.stdout.write(self.style.SUCCESS(
            f'Готово: новых тем {created}'))
