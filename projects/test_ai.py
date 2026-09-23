from types import SimpleNamespace
from unittest.mock import patch
from django.test import TestCase, override_settings
from django.contrib.auth import get_user_model
from openai import OpenAIError
from .ai import generate_questions, Questions
from .models import Task


@override_settings(OPENAI_API_KEY='test-only', OPENAI_MODEL='gpt-5.4-mini')
class AITests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('owner')
        self.task = Task.objects.create(owner=self.user, title='Coffee', industry='Retail', draft='Orders get lost', contact='private@example.test')

    @patch('projects.ai.OpenAI')
    def test_success(self, factory):
        client = factory.return_value.__enter__.return_value
        client.responses.parse.return_value = SimpleNamespace(status='completed', output_parsed=Questions(questions=[{'field': 'context', 'text': 'Какие заявки теряются?'}, {'field': 'data', 'text': 'Какие данные доступны?'}, {'field': 'success', 'text': 'Кто примет результат?'}]))
        result = generate_questions(self.task)
        self.assertEqual(result['source'], 'OpenAI')
        args = client.responses.parse.call_args.kwargs
        self.assertNotIn(self.task.contact, args['input'][1]['content'])
        self.assertFalse(args['store'])
        self.assertEqual(args['model'], 'gpt-5.4-mini')

    @patch('projects.ai.OpenAI')
    def test_errors_and_refusals_fallback(self, factory):
        client = factory.return_value.__enter__.return_value
        for response in [SimpleNamespace(status='incomplete', output_parsed=None), SimpleNamespace(status='completed', output_parsed=None), SimpleNamespace(status='completed', output_parsed=Questions(questions=[{'field': 'context', 'text': 'same question'}] * 3))]:
            client.responses.parse.return_value = response
            self.assertEqual(generate_questions(self.task)['source'], 'Локальный помощник')
        client.responses.parse.side_effect = OpenAIError('secret error details')
        result = generate_questions(self.task)
        self.assertNotIn('secret', result['notice'])
        self.assertGreaterEqual(len(result['questions']), 3)

    @patch('projects.ai.OpenAI')
    def test_missing_key_and_large_input_do_not_call(self, factory):
        with override_settings(OPENAI_API_KEY=''):
            self.assertEqual(generate_questions(self.task)['source'], 'Локальный помощник')
        self.task.context = 'x' * 25000
        self.assertEqual(generate_questions(self.task)['source'], 'Локальный помощник')
        factory.assert_not_called()

    @patch('projects.views.generate_questions')
    def test_explicit_action_preserves_unsaved_input(self, generate):
        generate.return_value = {'questions': [{'field': 'need', 'text': 'Первый вопрос?'}, {'field': 'data', 'text': 'Второй вопрос?'}, {'field': 'success', 'text': 'Третий вопрос?'}], 'source': 'OpenAI', 'notice': 'Ready'}
        self.client.force_login(self.user)
        url = f'/tasks/{self.task.pk}/edit/'
        self.client.get(url)
        generate.assert_not_called()
        response = self.client.post(url, {'action': 'analyze', 'title': 'New title', 'industry': 'Retail', 'need': 'New need'})
        self.assertContains(response, 'OpenAI')
        blocks = {block['field'].name: block['questions'] for block in response.context['field_blocks']}
        self.assertEqual(blocks['need'], ['Первый вопрос?'])
        self.assertEqual(blocks['data'], ['Второй вопрос?'])
        self.assertEqual(blocks['context'], [])
        self.assertEqual(generate.call_args.args[0].need, 'New need')
        self.task.refresh_from_db()
        self.assertEqual(self.task.title, 'Coffee')
        self.assertFalse(self.task.confirmed)
        self.assertEqual(self.task.score, 0)
        generate.reset_mock()
        self.client.post(url, {'title': 'New title', 'industry': 'Retail', 'confirm': 'on'})
        generate.assert_not_called()
        self.client.force_login(get_user_model().objects.create_user('stranger'))
        self.assertEqual(self.client.post(url, {'action': 'analyze'}).status_code, 404)
        generate.assert_not_called()
