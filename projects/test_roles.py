from django.contrib.auth import get_user_model
from django.test import TestCase
from .models import Account, Task, Team, Proposal


class RoleTests(TestCase):
    def setUp(self):
        self.business = get_user_model().objects.create_user('business-owner')
        self.student = get_user_model().objects.create_user('student-team')
        Account.objects.create(user=self.business, role=Account.Role.BUSINESS)
        Account.objects.create(user=self.student, role=Account.Role.STUDENT)
        self.team = Team.objects.create(user=self.student, name='Команда')
        self.task = Task.objects.create(owner=self.business, title='Тест', industry='IT', draft='Описание', confirmed=True, published=True)
        self.proposal = Proposal.objects.create(task=self.task, team=self.team, idea='Идея', plan='План', duration='Неделя')

    def test_student_cannot_create_even_by_post(self):
        self.client.force_login(self.student)
        for method in (self.client.get, self.client.post):
            self.assertEqual(method('/tasks/new/', {'title': 'Обход', 'industry': 'IT', 'draft': 'Текст'}).status_code, 403)
        self.assertEqual(Task.objects.count(), 1)
        for url in ['/', '/workspace/']:
            response = self.client.get(url)
            self.assertNotContains(response, 'href="/tasks/new/"')
            self.assertContains(response, 'Студенческая команда')
        self.assertEqual(self.client.get(f'/tasks/{self.task.pk}/propose/').status_code, 200)

    def test_student_cannot_manage_even_legacy_owned_task(self):
        self.task.owner = self.student
        self.task.save()
        for url in [f'/tasks/{self.task.pk}/edit/', f'/tasks/{self.task.pk}/publish/', f'/proposals/{self.proposal.pk}/decide/']:
            self.client.force_login(self.student)
            self.assertEqual(self.client.post(url, {'action': 'selected'}).status_code, 403)

    def test_business_can_create_but_cannot_propose_even_with_team(self):
        self.client.force_login(self.business)
        self.assertContains(self.client.get('/'), 'href="/tasks/new/"')
        self.assertEqual(self.client.get('/tasks/new/').status_code, 200)
        self.assertEqual(self.client.post('/tasks/new/', {'title': 'Новая', 'industry': 'IT', 'draft': 'Описание'}).status_code, 302)
        Team.objects.create(user=self.business, name='Старый профиль команды')
        self.assertEqual(self.client.post(f'/tasks/{self.task.pk}/propose/', {'idea': 'x', 'plan': 'x', 'duration': 'x'}).status_code, 403)
        self.assertEqual(self.client.get(f'/proposals/{self.proposal.pk}/evidence/').status_code, 403)

    def test_unassigned_and_anonymous(self):
        self.assertEqual(self.client.get('/tasks/new/').status_code, 302)
        user = get_user_model().objects.create_user('unassigned')
        self.client.force_login(user)
        self.assertEqual(self.client.get('/tasks/new/').status_code, 403)
        self.assertContains(self.client.get('/workspace/'), 'Тип пользователя ещё не назначен')

    def test_business_role_does_not_grant_access_to_another_owner(self):
        other = get_user_model().objects.create_user('other-business')
        Account.objects.create(user=other, role=Account.Role.BUSINESS)
        self.client.force_login(other)
        for url in [f'/tasks/{self.task.pk}/edit/', f'/tasks/{self.task.pk}/publish/', f'/proposals/{self.proposal.pk}/decide/']:
            self.assertEqual(self.client.post(url, {'action': 'selected'}).status_code, 404)
