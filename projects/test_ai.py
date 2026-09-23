from types import SimpleNamespace
from unittest.mock import patch
from django.test import TestCase, override_settings
from django.contrib.auth import get_user_model
from openai import OpenAIError
from .ai import generate_questions, Questions, BlockQuestions, ScopeReview
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

    @patch('projects.ai.OpenAI')
    def test_block_scope_and_current_text(self, factory):
        client = factory.return_value.__enter__.return_value
        self.task.context = 'Заказы теряются между двумя мессенджерами'
        client.responses.parse.side_effect = [SimpleNamespace(status='completed', output_parsed=BlockQuestions(questions=[{'field': 'context', 'text': 'Как часто теряются заказы?'}])), SimpleNamespace(status='completed', output_parsed=ScopeReview(accepted_indices=[0]))]
        result = generate_questions(self.task, focus_fields=['context'])
        self.assertEqual(result['source'], 'OpenAI')
        args = client.responses.parse.call_args_list[0].kwargs
        self.assertIn(self.task.context, args['input'][1]['content'])
        self.assertIn('current_block_fields', args['input'][1]['content'])
        self.assertEqual(args['text_format'], BlockQuestions)
        client.responses.parse.side_effect = [SimpleNamespace(status='completed', output_parsed=BlockQuestions(questions=[{'field': 'data', 'text': 'Какие данные доступны?'}])), SimpleNamespace(status='completed', output_parsed=ScopeReview(accepted_indices=[0]))]
        fallback = generate_questions(self.task, focus_fields=['context'])
        self.assertEqual(fallback['source'], 'Локальный помощник')
        self.assertTrue(all(q['field'] == 'context' for q in fallback['questions']))

    @override_settings(OPENAI_API_KEY='')
    @patch('projects.views.generate_questions')
    def test_wizard_requires_questions_before_next_step(self, generate):
        generate.return_value = {'questions': [{'field': 'title', 'text': 'Что должно отражать название?'}], 'source': 'OpenAI', 'notice': 'Ready'}
        self.client.force_login(self.user)
        url = f'/tasks/{self.task.pk}/edit/'
        self.client.get(url)
        generate.assert_not_called()
        data = {'step': 0, 'title': 'New title', 'industry': 'Retail'}
        response = self.client.post(url, {**data, 'action': 'continue'}, follow=True)
        self.assertEqual(response.context['index'], 0)
        generate.assert_not_called()
        response = self.client.post(url, {**data, 'action': 'next'}, follow=True)
        self.assertContains(response, 'Что должно отражать название?')
        self.assertEqual(response.context['index'], 0)
        self.assertEqual(generate.call_args.args[0].title, 'New title')
        self.assertEqual(generate.call_args.kwargs['focus_fields'], ['title', 'industry'])
        self.task.refresh_from_db()
        self.assertEqual(self.task.title, 'Coffee')
        self.assertFalse(self.task.confirmed)
        generate.reset_mock()
        self.client.get(url)
        generate.assert_not_called()
        response = self.client.post(url, {**data, 'title': 'Уточнённое название', 'action': 'continue'}, follow=True)
        self.assertEqual(response.context['index'], 1)
        generate.assert_not_called()
        self.assertEqual(self.client.session[f'task_wizard_{self.task.pk}']['values']['title'], 'Уточнённое название')
        # A stale tab cannot submit values into the next step.
        response = self.client.post(url, {**data, 'action': 'next'}, follow=True)
        self.assertEqual(response.context['index'], 1)
        generate.assert_not_called()
        response = self.client.post(url, {'step': 1, 'action': 'back', 'context': 'Сохранённый контекст'}, follow=True)
        self.assertEqual(response.context['index'], 0)
        self.assertContains(response, 'Уточнённое название')
        self.assertEqual(self.client.session[f'task_wizard_{self.task.pk}']['values']['context'], 'Сохранённый контекст')
        self.client.force_login(get_user_model().objects.create_user('stranger'))
        self.assertEqual(self.client.post(url, {**data, 'action': 'next'}).status_code, 404)
        generate.assert_not_called()

    @patch('projects.ai.OpenAI')
    def test_context_rejects_future_need_even_with_context_label(self, factory):
        client = factory.return_value.__enter__.return_value
        self.task.context = 'Есть история рационов и удоев за год в килограммах и литрах. Сотрудники оценивают связь на глаз.'
        premature = 'Нужно только выявить влияние ингредиентов на удой или ещё предлагать оптимальный рацион?'
        relevant = 'Как сотрудники сейчас оценивают связь рациона с удоями?'
        client.responses.parse.side_effect = [
            SimpleNamespace(status='completed', output_parsed=BlockQuestions(questions=[{'field': 'context', 'text': premature}, {'field': 'context', 'text': relevant}])),
            SimpleNamespace(status='completed', output_parsed=ScopeReview(accepted_indices=[1])),
        ]
        result = generate_questions(self.task, focus_fields=['context'])
        self.assertEqual(result['questions'], [{'field': 'context', 'text': relevant}])
        self.assertNotIn(premature, str(result))

    @patch('projects.ai.OpenAI')
    def test_no_questions_and_review_failure(self, factory):
        client = factory.return_value.__enter__.return_value
        client.responses.parse.return_value = SimpleNamespace(status='completed', output_parsed=BlockQuestions(questions=[]))
        result = generate_questions(self.task, focus_fields=['context'])
        self.assertEqual(result['questions'], [])
        self.assertIn('Можно переходить', result['notice'])
        self.assertEqual(client.responses.parse.call_count, 1)
        client.responses.parse.side_effect = [
            SimpleNamespace(status='completed', output_parsed=BlockQuestions(questions=[{'field': 'context', 'text': 'Нужно ли рекомендовать рацион?'}])),
            OpenAIError('review failed'),
        ]
        result = generate_questions(self.task, focus_fields=['context'])
        self.assertEqual(result['source'], 'Локальный помощник')
        self.assertNotIn('рекомендовать рацион', str(result))

    @patch('projects.ai.OpenAI')
    def test_need_suggestions_extend_text_without_reconfirming_functions(self, factory):
        client = factory.return_value.__enter__.return_value
        self.task.need = 'Нужно чтобы система сама выявляла корреляции и формировала рекомендуемый рацион'
        repeated = 'Правильно ли я понимаю, что нужен анализ влияния ингредиентов или ещё рекомендация рациона?'
        addition = 'Уточните, для отдельных животных или для групп нужно формировать рекомендуемый рацион.'
        client.responses.parse.side_effect = [
            SimpleNamespace(status='completed', output_parsed=BlockQuestions(questions=[{'field': 'need', 'text': repeated}, {'field': 'need', 'text': addition}])),
            SimpleNamespace(status='completed', output_parsed=ScopeReview(accepted_indices=[1])),
        ]
        result = generate_questions(self.task, focus_fields=['need'])
        self.assertEqual(result['questions'], [{'field': 'need', 'text': addition}])
        self.assertIn('связными предложениями', result['notice'])
        self.assertEqual(self.task.need, 'Нужно чтобы система сама выявляла корреляции и формировала рекомендуемый рацион')

    @override_settings(OPENAI_API_KEY='')
    def test_offline_does_not_ask_to_repeat_filled_need(self):
        self.task.need = 'Выявлять корреляции и рекомендовать рацион'
        result = generate_questions(self.task, focus_fields=['need'])
        self.assertEqual(result['questions'], [])
        self.assertEqual(result['source'], 'Локальный помощник')
