from django.core.management.base import BaseCommand, CommandError
from projects.ai import generate_questions
from projects.models import Task


class Command(BaseCommand):
    help = 'Make one real API request using synthetic data; no database writes.'

    def add_arguments(self, parser):
        parser.add_argument('--cattle', action='store_true')
        parser.add_argument('--field', choices=['context', 'need', 'users', 'data', 'constraints', 'result', 'success'])

    def handle(self, *args, **options):
        task = Task(title='Учёт заказов кофейни', industry='Ритейл', draft='Заказы на торты теряются между мессенджерами.', context='Небольшая кофейня принимает заказы в двух мессенджерах.')
        if options.get('cattle'):
            task.title = 'Анализ рационов и удоев'
            task.industry = 'Животноводство'
            task.draft = task.context = 'Нужно анализировать историю рационов для скота и размер удоев, выявлять закономерности, какой ингредиент больше влияет на удои. Есть история рационов и удоев за 1 год, в килограммах корма и литрах молока. Сейчас сотрудники рассчитывают это вручную на глаз.'
            task.need = 'Нужно чтобы система сама выявляла корреляции и формировала рекомендуемый рацион'
        result = generate_questions(task, focus_fields=[options['field']] if options.get('field') else None)
        if result['source'] != 'OpenAI':
            raise CommandError(result['notice'])
        self.stdout.write(self.style.SUCCESS(f"OpenAI OK: {len(result['questions'])} questions received and validated."))

        if options.get('cattle'):
            for question in result['questions']:
                self.stdout.write(question['text'])
