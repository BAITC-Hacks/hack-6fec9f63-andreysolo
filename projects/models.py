from django.conf import settings
from django.db import models


class Account(models.Model):
    class Role(models.TextChoices):
        BUSINESS = 'business', 'Бизнес'
        STUDENT = 'student', 'Студенческая команда'
        UNASSIGNED = 'unassigned', 'Тип не назначен'

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='account')
    role = models.CharField('Тип пользователя', max_length=12, choices=Role.choices, default=Role.UNASSIGNED)

    def __str__(self):
        return f'{self.user} · {self.get_role_display()}'


class Task(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    title = models.CharField('Название', max_length=180)
    industry = models.CharField('Тема', max_length=80)
    draft = models.TextField('Первоначальное описание')
    context = models.TextField('Контекст', blank=True)
    need = models.TextField('Потребность', blank=True)
    users = models.TextField('Пользователи', blank=True)
    data = models.TextField('Данные и материалы', blank=True)
    constraints = models.TextField('Ограничения', blank=True)
    result = models.TextField('Ожидаемый результат', blank=True)
    success = models.TextField('Критерии успеха', blank=True)
    contact = models.CharField('Контакт', max_length=250, blank=True)
    interaction = models.TextField('Формат взаимодействия', blank=True)
    confirmed = models.BooleanField(default=False)
    published = models.BooleanField(default=False)
    score = models.PositiveSmallIntegerField(default=0)
    quality_reviews = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-score', '-updated_at']

    @property
    def level(self):
        return 'Приоритетная' if self.score >= 90 else 'Готовая' if self.score >= 70 else 'Рабочая' if self.score >= 40 else 'Черновик'

    def __str__(self):
        return self.title


class Team(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    name = models.CharField('Команда', max_length=120)
    interests = models.CharField('Интересы', max_length=250)
    skills = models.CharField('Навыки и технологии', max_length=250)

    @property
    def points(self):
        return self.proposals.filter(progress_confirmed=True).count() * 25

    def __str__(self):
        return self.name


class Proposal(models.Model):
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name='proposals')
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='proposals')
    idea = models.TextField('Идея решения')
    plan = models.TextField('План работы')
    duration = models.CharField('Срок', max_length=120)
    prototype = models.URLField('Ссылка на прототип', blank=True)
    status = models.CharField(max_length=12, default='pending', choices=[('pending', 'На рассмотрении'), ('selected', 'Выбрана'), ('rejected', 'Отклонена')])
    evidence = models.TextField('Результат этапа / ссылка на работу', blank=True)
    progress_confirmed = models.BooleanField(default=False)
