"""Kiểm tra endpoint tùy chỉnh bằng request giả, không gọi mạng."""
import os
import unittest
import uuid
from unittest.mock import patch

from providers import Provider
from status_tools import SCHEMAS


class CustomProviderTests(unittest.TestCase):
    @patch.dict(os.environ, {
        'DEEPSEEK_API_KEY': 'deepseek-test-key',
        'API_ENDPOINT': 'https://opencode.ai/inference/go/openai/v1',
        'API_KEY': 'old-key',
    }, clear=True)
    @patch('providers.post_json')
    def test_deepseek_uses_direct_endpoint_and_key(self, post):
        post.return_value = {'choices': [{
            'message': {'role': 'assistant', 'content': 'OK'},
            'finish_reason': 'stop',
        }]}
        Provider('deepseek', 'deepseek-flash').complete(
            [{'role': 'user', 'content': 'Check status'}], SCHEMAS)
        url, headers, payload = post.call_args.args
        self.assertEqual(url, 'https://api.deepseek.com/chat/completions')
        self.assertEqual(headers['Authorization'], 'Bearer deepseek-test-key')
        self.assertEqual(payload['model'], 'deepseek-flash')
        self.assertEqual(payload['thinking'], {'type': 'disabled'})
        self.assertEqual(payload['tools'], SCHEMAS)

    @patch.dict(os.environ, {
        'NVIDIA_API_KEY': 'nvidia-test-key',
        'API_ENDPOINT': 'https://opencode.ai/inference/go/openai/v1',
        'API_KEY': 'old-key',
    }, clear=True)
    @patch('providers.post_json')
    def test_nvidia_uses_nim_endpoint_and_key(self, post):
        post.return_value = {'choices': [{
            'message': {'role': 'assistant', 'content': 'OK'},
            'finish_reason': 'stop',
        }]}
        model = 'nvidia/nemotron-3.5-lightning-30b-a3b'
        Provider('nvidia', model).complete(
            [{'role': 'user', 'content': 'Check status'}], SCHEMAS)
        url, headers, payload = post.call_args.args
        self.assertEqual(url, 'https://integrate.api.nvidia.com/v1/chat/completions')
        self.assertEqual(headers['Authorization'], 'Bearer nvidia-test-key')
        self.assertEqual(headers['User-Agent'], 'StatusAgentLab/1.0')
        self.assertEqual(payload['model'], model)
        self.assertIs(payload['stream'], False)
        self.assertEqual(payload['tools'], SCHEMAS)
        self.assertNotIn('x-opencode-session', headers)

    @patch.dict(os.environ, {
        'GROQ_API_KEY': 'groq-test-key',
        'API_ENDPOINT': 'https://opencode.ai/inference/go/openai/v1',
        'API_KEY': 'old-key',
    }, clear=True)
    @patch('providers.post_json')
    def test_groq_uses_own_endpoint_and_key(self, post):
        post.return_value = {'choices': [{
            'message': {'role': 'assistant', 'content': 'OK'},
            'finish_reason': 'stop',
        }]}
        Provider('groq', 'openai/gpt-oss-20b').complete(
            [{'role': 'user', 'content': 'Check status'}], SCHEMAS)
        url, headers, payload = post.call_args.args
        self.assertEqual(url, 'https://api.groq.com/openai/v1/chat/completions')
        self.assertEqual(headers['Authorization'], 'Bearer groq-test-key')
        self.assertEqual(headers['User-Agent'], 'StatusAgentLab/1.0')
        self.assertNotIn('x-opencode-session', headers)
        self.assertEqual(payload['model'], 'openai/gpt-oss-20b')
        self.assertEqual(payload['tools'], SCHEMAS)

    @patch.dict(os.environ, {
        'API_ENDPOINT': 'https://opencode.ai/inference/go/openai/v1/',
        'API_KEY': 'test-key',
    }, clear=True)
    @patch('providers.post_json')
    def test_endpoint_key_model_and_tools(self, post):
        post.return_value = {
            'choices': [{'message': {'role': 'assistant', 'content': 'OK'},
                         'finish_reason': 'stop'}],
        }
        client = Provider('openai', 'deepseek-v4.1-flash')
        response = client.complete(
            [{'role': 'user', 'content': 'Check status'}], SCHEMAS)
        url, headers, payload = post.call_args.args
        self.assertEqual(url, 'https://opencode.ai/inference/go/openai/v1/chat/completions')
        self.assertEqual(headers['Authorization'], 'Bearer test-key')
        self.assertEqual(headers['User-Agent'], 'StatusAgentLab/1.0')
        self.assertEqual(str(uuid.UUID(headers['x-opencode-session'])), client.session_id)
        self.assertEqual(payload['model'], 'deepseek-v4.1-flash')
        self.assertEqual(payload['tools'], SCHEMAS)
        self.assertEqual(response['finish'], 'stop')
        client.complete([{'role': 'user', 'content': 'Next turn'}], SCHEMAS)
        self.assertEqual(post.call_args.args[1]['x-opencode-session'],
                         headers['x-opencode-session'])
        self.assertNotEqual(Provider('openai', 'deepseek-v4.1-flash').session_id,
                            client.session_id)

    @patch.dict(os.environ, {'API_ENDPOINT': 'https://example.com/v1'}, clear=True)
    def test_missing_custom_key(self):
        with self.assertRaisesRegex(ValueError, 'API_KEY'):
            Provider('openai', 'test-model')
