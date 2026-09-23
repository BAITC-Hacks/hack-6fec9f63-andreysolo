from django.core.management.base import BaseCommand, CommandError
from projects.models import Task
from projects.quality import assess_quality


class Command(BaseCommand):
    help = 'Check AI rating on a synthetic clarification and its answer (two requests).'

    def handle(self, *args, **options):
        task = Task(title='Рационы и удои', industry='Животноводство', need='Система должна выявлять корреляции и формировать рекомендуемый рацион.')
        questions = [{'field': 'need', 'text': 'Уточните, для каких животных или групп животных нужно формировать рекомендуемый рацион.'}]
        before = assess_quality(task, ['need'], questions)['need']
        task.need += ' Рацион нужно рекомендовать для каждой группы дойных коров, с целью повышения удоев.'
        after = assess_quality(task, ['need'], questions)['need']
        if before['source'] != 'openai' or after['source'] != 'openai':
            raise CommandError('AI rating check unavailable; fallback was used.')
        self.stdout.write(f"Before: {before['percent']}% — {before['reason']}")
        self.stdout.write(f"After: {after['percent']}% — {after['reason']}")
        self.stdout.write(str(before['questions']))
        self.stdout.write(str(after['questions']))
        if before['percent'] >= 100 or not any(q['resolved'] for q in after['questions'] if q['text'] == questions[0]['text']):
            raise CommandError('AI did not correctly distinguish the missing clarification from its answer.')
