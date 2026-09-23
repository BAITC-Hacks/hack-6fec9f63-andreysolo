from types import SimpleNamespace
from unittest.mock import patch
from django.test import TestCase, override_settings
from .models import Task, Account
from .quality import assess_quality, QualityReview, EvidenceAudit, FIELD_WEIGHTS, baseline
from .services import breakdown


@override_settings(OPENAI_API_KEY='test-key', OPENAI_MODEL='gpt-5.4-mini')
class QualityTests(TestCase):
    def setUp(self):
        self.task = Task(title='Задача', industry='Тема', confirmed=True, need='Рекомендации нужны для групп коров. Обновление ежедневно.')
        self.questions = [{'field': 'need', 'text': 'Уточните уровень рекомендаций.'}, {'field': 'need', 'text': 'Укажите частоту пересчёта.'}]

    def response(self, resolved, gaps=None, meaningful=True):
        return SimpleNamespace(status='completed', output_parsed=QualityReview(fields=[{'field': 'need', 'meaningful': meaningful, 'resolved': resolved, 'gaps': gaps or []}]))

    @patch('projects.quality.OpenAI')
    def test_partial_full_and_invalid_evidence(self, factory):
        client = factory.return_value.__enter__.return_value
        client.responses.parse.side_effect = [self.response([{'index': 0, 'evidence': 'для групп коров'}]), SimpleNamespace(status='completed', output_parsed=EvidenceAudit(accepted_indices=[0]))]
        partial = assess_quality(self.task, ['need'], self.questions)
        self.assertEqual(partial['need']['percent'], 75)
        client.responses.parse.side_effect = [self.response([{'index': 0, 'evidence': 'для групп коров'}, {'index': 1, 'evidence': 'ежедневно'}]), SimpleNamespace(status='completed', output_parsed=EvidenceAudit(accepted_indices=[0, 1]))]
        self.assertEqual(assess_quality(self.task, ['need'], self.questions)['need']['percent'], 100)
        client.responses.parse.side_effect = [self.response([{'index': 0, 'evidence': 'выдуманная цитата'}]), SimpleNamespace(status='completed', output_parsed=EvidenceAudit(accepted_indices=[0]))]
        self.assertEqual(assess_quality(self.task, ['need'], self.questions)['need']['percent'], 50)

    @patch('projects.quality.OpenAI')
    def test_no_questions_is_not_automatically_full(self, factory):
        client = factory.return_value.__enter__.return_value
        client.responses.parse.return_value = self.response([], gaps=['Добавьте уровень рекомендаций.'])
        self.assertEqual(assess_quality(self.task, ['need'], [])['need']['percent'], 50)
        client.responses.parse.return_value = self.response([])
        self.assertEqual(assess_quality(self.task, ['need'], [])['need']['percent'], 100)
        client.responses.parse.return_value = self.response([], meaningful=False)
        self.assertEqual(assess_quality(self.task, ['need'], [])['need']['percent'], 0)

    @override_settings(OPENAI_API_KEY='')
    def test_offline_empty_and_edited_text(self):
        self.assertEqual(assess_quality(self.task, ['need'], [])['need']['percent'], 50)
        self.task.quality_reviews = baseline(self.task, ['need'])
        self.task.quality_reviews['need'].update(source='openai', percent=100)
        self.assertEqual(breakdown(self.task)[0]['earned'], 10)
        self.task.need = 'Другой текст'
        self.assertEqual(breakdown(self.task)[0]['earned'], 5)
        self.task.need = ''
        self.assertEqual(breakdown(self.task)[0]['earned'], 0)

    def test_full_total_requires_verified_fields(self):
        for field in FIELD_WEIGHTS:
            setattr(self.task, field, 'Подробное описание')
        self.assertEqual(sum(row['earned'] for row in breakdown(self.task)), 49)
        self.task.quality_reviews = baseline(self.task, FIELD_WEIGHTS)
        for review in self.task.quality_reviews.values():
            review.update(source='openai', percent=100)
        self.assertEqual(sum(row['earned'] for row in breakdown(self.task)), 100)
        self.task.confirmed = False
        self.assertEqual(sum(row['earned'] for row in breakdown(self.task)), 0)

    @patch('projects.views.assess_quality')
    @patch('projects.views.generate_questions')
    def test_recheck_preserves_questions_and_persists_verified_score(self, generate, assess):
        from django.contrib.auth import get_user_model
        from .forms import TaskForm
        from .wizard import STEPS
        from .question_scopes import SCOPE_VERSION
        from .quality import QUALITY_VERSION
        owner = get_user_model().objects.create_user('review-owner')
        Account.objects.create(user=owner, role=Account.Role.BUSINESS)
        self.task.owner = owner
        self.task.save()
        self.client.force_login(owner)
        key = f'task_wizard_{self.task.pk}'
        session = self.client.session
        session[key] = {'step': 2, 'values': {name: getattr(self.task, name) for name in TaskForm.Meta.fields}, 'analysis': None, 'scope_version': SCOPE_VERSION, 'quality_version': QUALITY_VERSION}
        session.save()
        url = f'/tasks/{self.task.pk}/edit/'
        generate.return_value = {'questions': self.questions, 'source': 'OpenAI', 'notice': 'Уточните описание'}
        self.client.post(url, {'step': 2, 'action': 'next', 'need': self.task.need})
        # Rerunning generation must not erase unanswered questions even if it returns none.
        generate.return_value = {'questions': [], 'source': 'OpenAI', 'notice': 'Нет новых подсказок'}
        self.client.post(url, {'step': 2, 'action': 'analyze', 'need': self.task.need})
        updated = self.task.need + ' Дополнительное уточнение.'
        self.task.need = updated
        reviews = baseline(self.task, ['need'])
        reviews['need'].update(source='openai', percent=75, reason='Закрыто 1 из 2')
        assess.return_value = reviews
        self.client.post(url, {'step': 2, 'action': 'continue', 'need': updated})
        self.assertEqual(assess.call_args.args[2], self.questions)
        self.assertEqual(self.client.session[key]['quality_reviews']['need']['percent'], 75)
        self.task.refresh_from_db()
        self.assertEqual(self.task.quality_reviews, {})
        session = self.client.session
        state = session[key]
        state['step'] = len(STEPS)
        session[key] = state
        session.save()
        self.client.post(url, {'step': len(STEPS), 'action': 'save', 'confirm': 'on'})
        self.task.refresh_from_db()
        self.assertEqual(self.task.quality_reviews['need']['percent'], 75)
        self.assertEqual(self.task.score, 7)

    @patch('projects.views.assess_quality')
    @patch('projects.views.generate_questions')
    def test_continue_without_additions_does_not_get_full_marks(self, generate, assess):
        from django.contrib.auth import get_user_model
        from .forms import TaskForm
        owner = get_user_model().objects.create_user('skip-owner')
        Account.objects.create(user=owner, role=Account.Role.BUSINESS)
        self.task.owner = owner
        self.task.save()
        self.client.force_login(owner)
        key = f'task_wizard_{self.task.pk}'
        session = self.client.session
        session[key] = {'step': 2, 'values': {name: getattr(self.task, name) for name in TaskForm.Meta.fields}, 'analysis': None}
        session.save()
        generate.return_value = {'questions': self.questions, 'source': 'OpenAI', 'notice': 'Уточните'}
        url = f'/tasks/{self.task.pk}/edit/'
        self.client.post(url, {'step': 2, 'action': 'next', 'need': self.task.need})
        self.client.post(url, {'step': 2, 'action': 'continue', 'need': self.task.need})
        assess.assert_not_called()
        self.assertEqual(self.client.session[key]['quality_reviews']['need']['percent'], 50)

    @patch('projects.quality.OpenAI')
    def test_related_quote_without_answer_is_rejected(self, factory):
        client = factory.return_value.__enter__.return_value
        self.task.need = 'Система должна рекомендовать рацион.'
        client.responses.parse.side_effect = [
            self.response([{'index': 0, 'evidence': self.task.need}]),
            SimpleNamespace(status='completed', output_parsed=EvidenceAudit(accepted_indices=[])),
        ]
        result = assess_quality(self.task, ['need'], self.questions)
        self.assertEqual(result['need']['percent'], 50)
