from django.core.management.base import BaseCommand, CommandError
from projects.ai import generate_questions
from projects.models import Task


class Command(BaseCommand):
    help = 'Make one real API request using synthetic data; no database writes.'

    def handle(self, *args, **options):
        task = Task(title='Учёт заказов кофейни', industry='Ритейл', draft='Заказы на торты теряются между мессенджерами.', context='Небольшая кофейня принимает заказы в двух мессенджерах.')
        result = generate_questions(task)
        if result['source'] != 'OpenAI':
            raise CommandError(result['notice'])
        self.stdout.write(self.style.SUCCESS(f"OpenAI OK: {len(result['questions'])} questions received and validated."))
