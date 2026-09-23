from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from .models import Task, Team, Proposal, Account
from .services import RUBRIC, analyze, breakdown


class WorkflowTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user('business', password='test')
        Account.objects.create(user=self.owner, role=Account.Role.BUSINESS)
        self.student = get_user_model().objects.create_user('student', password='test')
        Account.objects.create(user=self.student, role=Account.Role.STUDENT)
        self.team = Team.objects.create(user=self.student, name='Team', interests='IT', skills='Python')
        self.task = Task.objects.create(owner=self.owner, title='Заявки', industry='IT', draft='Теряем заявки')

    @override_settings(OPENAI_API_KEY="")
    def test_complete_workflow(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.post(reverse('publish', args=[self.task.pk])).status_code, 400)
        fields = {f: 'Подтверждённые сведения' for _, _, names, _ in RUBRIC for f in names}
        fields.update(title='Заявки', industry='IT', confirm='on')
        from .wizard import STEPS
        url = reverse('edit', args=[self.task.pk])
        self.client.get(url)
        for index, (_, names) in enumerate(STEPS):
            data = {name: fields[name] for name in names}
            response = self.client.post(url, {**data, 'step': index, 'action': 'next'}, follow=True)
            self.assertEqual(response.context['index'], index)
            self.assertTrue(response.context['analysis'])
            self.client.post(url, {**data, 'step': index, 'action': 'continue'})
        self.assertContains(self.client.get(url), 'Проверьте карточку')
        self.client.post(url, {'step': len(STEPS), 'action': 'save'})
        self.task.refresh_from_db()
        self.assertFalse(self.task.confirmed)
        self.assertRedirects(self.client.post(url, {'step': len(STEPS), 'action': 'save', 'confirm': 'on'}), reverse('detail', args=[self.task.pk]))
        self.task.refresh_from_db()
        self.assertEqual(self.task.score, 49)
        self.client.post(reverse('publish', args=[self.task.pk]))
        self.client.force_login(self.student)
        self.client.post(reverse('propose', args=[self.task.pk]), {'idea': 'Решение', 'plan': 'План', 'duration': '2 недели'})
        proposal = Proposal.objects.get()
        self.assertEqual(proposal.status, 'pending')
        self.assertEqual(self.client.post(reverse('decide', args=[proposal.pk]), {'action': 'selected'}).status_code, 403)
        self.client.force_login(self.owner)
        self.client.post(reverse('decide', args=[proposal.pk]), {'action': 'selected'})
        self.assertEqual(self.client.post(reverse('decide', args=[proposal.pk]), {'action': 'progress'}).status_code, 400)
        self.client.force_login(self.student)
        self.client.post(reverse('evidence', args=[proposal.pk]), {'evidence': 'Прототип готов, проверены пять сценариев.'})
        self.client.force_login(self.owner)
        for _ in range(2):
            self.client.post(reverse('decide', args=[proposal.pk]), {'action': 'progress'})
        self.assertEqual(self.team.points, 25)
        self.assertEqual(self.client.post(reverse('decide', args=[proposal.pk]), {'action': 'rejected'}).status_code, 400)

    def test_permissions(self):
        self.assertEqual(self.client.get(reverse('detail', args=[self.task.pk])).status_code, 403)
        self.client.force_login(self.student)
        self.assertEqual(self.client.get(reverse('edit', args=[self.task.pk])).status_code, 403)
        self.assertEqual(self.client.post(reverse('publish', args=[self.task.pk])).status_code, 403)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(reverse('publish', args=[self.task.pk])).status_code, 405)

    def test_low_score_accepts_proposals(self):
        self.task.confirmed = self.task.published = True
        self.task.save()
        self.assertContains(self.client.get('/'), 'Заявки')
        self.client.force_login(self.student)
        self.client.post(reverse('propose', args=[self.task.pk]), {'idea': 'Идея', 'plan': 'План', 'duration': 'Неделя'})
        self.assertEqual(Proposal.objects.count(), 1)

    def test_rubric_and_fallback(self):
        self.task.context = self.task.need = 'Текст'
        self.assertEqual(sum(r['earned'] for r in breakdown(self.task)), 0)
        self.task.confirmed = True
        self.assertEqual(sum(r['earned'] for r in breakdown(self.task)), 10)
        self.task.need = '   '
        self.assertEqual(sum(r['earned'] for r in breakdown(self.task)), 5)
        for response in ['garbage', '{}', '{"questions": [1,2,3]}', '{"questions": "wrong"}']:
            self.assertGreaterEqual(len(analyze(self.task, response)), 3)

    def test_pages(self):
        self.task.published = True
        self.task.save()
        for url in ['/', '/?q=missing', '/?level=draft', '/?industry=IT', '/login/']:
            self.assertEqual(self.client.get(url).status_code, 200)
        self.client.force_login(self.owner)
        for url in ['/workspace/', '/tasks/new/', f'/tasks/{self.task.pk}/', f'/tasks/{self.task.pk}/edit/']:
            self.assertEqual(self.client.get(url).status_code, 200)
