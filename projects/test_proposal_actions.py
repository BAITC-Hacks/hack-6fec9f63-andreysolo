from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from .models import Account, Task, Team, Proposal


class ProposalActionTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user('owner')
        Account.objects.create(user=self.owner, role=Account.Role.BUSINESS)
        student = get_user_model().objects.create_user('student')
        Account.objects.create(user=student, role=Account.Role.STUDENT)
        team = Team.objects.create(user=student, name='Команда')
        self.task = Task.objects.create(owner=self.owner, title='Задача', industry='IT', draft='Описание')
        self.proposal = Proposal.objects.create(task=self.task, team=team, idea='Идея', plan='План', duration='Неделя', evidence='Готовый прототип')
        self.url = f'/proposals/{self.proposal.pk}/decide/'
        self.client.force_login(self.owner)

    def test_json_decisions_and_progress(self):
        for status, label in [('selected', 'Выбрана'), ('rejected', 'Отклонена'), ('selected', 'Выбрана')]:
            response = self.client.post(self.url, {'action': status}, HTTP_ACCEPT='application/json')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['status'], status)
            self.assertEqual(response.json()['status_label'], label)
            self.assertEqual(response.json()['can_confirm_progress'], status == 'selected')
            self.proposal.refresh_from_db()
            self.assertEqual(self.proposal.status, status)
        response = self.client.post(self.url, {'action': 'progress'}, HTTP_ACCEPT='application/json')
        self.assertTrue(response.json()['progress_confirmed'])
        self.assertFalse(response.json()['can_confirm_progress'])
        response = self.client.post(self.url, {'action': 'rejected'}, HTTP_ACCEPT='application/json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('error', response.json())

    def test_ajax_keeps_csrf_and_owner_checks(self):
        secured = Client(enforce_csrf_checks=True)
        secured.force_login(self.owner)
        self.assertEqual(secured.post(self.url, {'action': 'selected'}, HTTP_ACCEPT='application/json').status_code, 403)
        self.client.force_login(self.proposal.team.user)
        self.assertEqual(self.client.post(self.url, {'action': 'selected'}, HTTP_ACCEPT='application/json').status_code, 403)
        self.proposal.refresh_from_db()
        self.assertEqual(self.proposal.status, 'pending')

    def test_bad_action_and_initial_status_markup(self):
        self.assertEqual(self.client.post(self.url, {'action': 'invalid'}, HTTP_ACCEPT='application/json').status_code, 400)
        response = self.client.get(f'/tasks/{self.task.pk}/')
        self.assertContains(response, 'proposal-status--pending')
        self.assertContains(response, 'data-proposal-form')
        self.assertContains(response, 'proposals.js')
        self.assertEqual(self.client.post(self.url, {'action': 'selected'}).status_code, 302)
