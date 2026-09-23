from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from projects.models import Task, Team, Proposal, Account
from projects.services import breakdown


class Command(BaseCommand):
    help = 'Create synthetic local demo data; preserve existing records.'

    @transaction.atomic
    def handle(self, *args, **options):
        def account(name):
            user, created = get_user_model().objects.get_or_create(username=name)
            if created:
                user.set_password('AlemDemo2026!')
                user.save()
            return user
        owner = account('business')
        Account.objects.get_or_create(user=owner, defaults={'role': Account.Role.BUSINESS})
        examples = [
            ('Умный учёт заявок для кофейни', 'Ритейл', 'Теряем заказы на торты в мессенджерах. Нужен единый список заявок.'),
            ('Прогноз спроса на городские велосипеды', 'Транспорт', 'Хотим заранее видеть, на каких станциях закончатся велосипеды.'),
            ('Навигатор стажировок для студентов', 'Образование', 'Студентам сложно найти стажировку по своим навыкам.'),
            ('Дашборд расхода воды в теплице', 'Агротех', 'Собираем показания вручную и поздно замечаем перерасход.'),
            ('Помощник для записи в мастерскую', 'Сервисы', 'Нужна удобная запись клиентов на ремонт.'),
        ]
        for i, (title, industry, draft) in enumerate(examples):
            task, created = Task.objects.get_or_create(owner=owner, title=title, defaults={'industry': industry, 'draft': draft, 'context': draft, 'need': draft, 'users': 'Сотрудники и клиенты организации', 'data': 'Синтетическая CSV-выгрузка за три месяца.' if i < 3 else '', 'constraints': 'Прототип за две недели, без платных сервисов.' if i < 4 else '', 'result': 'Работающий веб-прототип и инструкция.' if i < 4 else '', 'success': 'Пять тестовых сценариев выполняются без ошибок; время операции менее минуты.' if i < 2 else '', 'contact': 'demo@example.test' if i < 3 else '', 'interaction': 'Встреча с бизнесом раз в неделю.' if i < 3 else '', 'confirmed': True, 'published': True})
            if created:
                task.score = sum(r['earned'] for r in breakdown(task))
                task.save()
            team, _ = Team.objects.get_or_create(user=account(f'team{i+1}'), defaults={'name': ['Steppe Coders', 'Data Nomads', 'Qadam', 'Green Stack', 'Jas AI'][i], 'interests': industry, 'skills': 'Python, Django, SQL, UX'})
            Account.objects.get_or_create(user=team.user, defaults={'role': Account.Role.STUDENT})
            if not Proposal.objects.filter(task=task, team=team).exists():
                Proposal.objects.create(task=task, team=team, idea='Проверим пользовательский сценарий и соберём прототип.', plan='Интервью → макет → реализация → проверка.', duration='2 недели', prototype='https://example.com/demo')
        self.stdout.write(self.style.SUCCESS('Demo ready: business, team1..team5 / AlemDemo2026!'))
