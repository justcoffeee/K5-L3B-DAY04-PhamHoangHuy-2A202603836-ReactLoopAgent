"""Các provider cùng một interface. Không chứa agent loop."""
import json
import os
import urllib.error
import urllib.request
import urllib.parse
import uuid
import math
import sys
import time
from email.utils import parsedate_to_datetime

CONFIG = {
    'deepseek': ('DEEPSEEK_API_KEY', 'https://api.deepseek.com/chat/completions'),
    'nvidia': ('NVIDIA_API_KEY', 'https://integrate.api.nvidia.com/v1/chat/completions'),
    'groq': ('GROQ_API_KEY', 'https://api.groq.com/openai/v1/chat/completions'),
    'openai': ('OPENAI_API_KEY', 'https://api.openai.com/v1/chat/completions'),
    'gemini': ('GEMINI_API_KEY', 'https://generativelanguage.googleapis.com/v1beta/openai/chat/completions'),
    'openrouter': ('OPENROUTER_API_KEY', 'https://openrouter.ai/api/v1/chat/completions'),
    'anthropic': ('ANTHROPIC_API_KEY', 'https://api.anthropic.com/v1/messages'),
}


class ProviderHTTPError(RuntimeError):
    """Lỗi có mã HTTP, không chứa response body hoặc thông tin xác thực."""

    def __init__(self, status, retry_after=None, error_kind=None):
        self.http_status = status
        self.retry_after = retry_after
        self.error_kind = error_kind
        super().__init__(f'Provider trả HTTP {status} ({error_kind or "unknown"}); kiểm tra model, key và quota.')


def classify_http_error(exc):
    """Chỉ lưu phân loại, không lưu body có thể chứa thông tin nhạy cảm."""
    if exc.code != 429:
        return 'authentication' if exc.code == 401 else 'http_error'
    try:
        error = json.loads(exc.read(16384)).get('error', {})
        metadata = error.get('metadata') or {}
        text = str(error.get('message', '')).lower()
        if 'per-day' in text or 'per day' in text or 'daily' in text:
            return 'daily_quota'
        if metadata.get('provider_name') or metadata.get('provider_code') or 'upstream' in text:
            return 'upstream_rate_limit'
        return 'rate_limit'
    except (ValueError, TypeError, AttributeError, OSError):
        return 'rate_limit'


def retry_delay(value, attempt):
    """Ưu tiên Retry-After (giây hoặc HTTP date), fallback exponential backoff."""
    if value is not None:
        try:
            seconds = float(value)
        except (TypeError, ValueError):
            try:
                seconds = parsedate_to_datetime(value).timestamp() - time.time()
            except (TypeError, ValueError, OverflowError):
                seconds = float('nan')
        if math.isfinite(seconds):
            return max(1.0, seconds)
    return min(10 * (2 ** attempt), 60)


def post_json(url, headers, payload):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json', **headers})
    # Tối đa 5 requests và tổng 180 giây chờ cho mỗi model call.
    waited = 0
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=60) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            status = exc.code
            error_kind = classify_http_error(exc)
            delay = retry_delay(exc.headers.get('Retry-After'), attempt) if status == 429 else None
            exc.close()
            # Không retry lỗi xác thực; không rút ngắn thời gian server yêu cầu.
            if (status != 429 or error_kind == 'daily_quota' or attempt == 4
                    or delay > 60 or waited + delay > 180):
                raise ProviderHTTPError(status, delay, error_kind) from exc
            print(f'Provider HTTP 429: chờ {delay:g}s rồi thử lại ({attempt + 1}/4).',
                  file=sys.stderr, flush=True)
            time.sleep(delay)
            waited += delay
        except urllib.error.URLError as exc:
            raise RuntimeError(f'Không kết nối được provider: {exc.reason}') from exc


class Provider:
    """complete(messages, schemas) -> {message, calls, finish, usage}.

    messages: system/user/assistant/tool theo format Chat Completions. message trả về
    cần được append nguyên vẹn; tool result có role, tool_call_id, content (JSON string).
    """
    def __init__(self, name, model):
        if name not in CONFIG:
            raise ValueError(f'Provider không hợp lệ: {name}')
        if not model:
            raise ValueError('Cần đặt MODEL là model có hỗ trợ tool calling.')
        self.name, self.model = name, model
        key_name, self.url = CONFIG[name]
        # Endpoint tùy chỉnh dùng cùng giao thức Chat Completions.
        if name == 'openai' and os.getenv('API_ENDPOINT'):
            endpoint = os.environ['API_ENDPOINT'].rstrip('/')
            if not endpoint.startswith('https://'):
                raise ValueError('API_ENDPOINT phải dùng HTTPS.')
            self.url = endpoint + '/chat/completions'
            key_name = 'API_KEY'
        self.key = os.getenv(key_name)
        if not self.key:
            raise ValueError(f'Thiếu {key_name}; xem README.md.')
        # Một Provider được tạo cho mỗi conversation trong run.py/eval runner.
        self.session_id = str(uuid.uuid4())

    def complete(self, messages, schemas):
        if self.name == 'anthropic':
            return self._anthropic(messages, schemas)
        payload = {'model': self.model, 'messages': messages}
        if self.name == 'deepseek':
            payload.update({'stream': False, 'thinking': {'type': 'disabled'}})
        if self.name == 'nvidia':
            payload['stream'] = False
        if schemas:
            payload['tools'] = schemas
        headers = {'Authorization': f'Bearer {self.key}'}
        if self.name in ('groq', 'openrouter', 'nvidia', 'deepseek'):
            headers['User-Agent'] = 'StatusAgentLab/1.0'
        if urllib.parse.urlparse(self.url).hostname == 'opencode.ai':
            headers.update({'User-Agent': 'StatusAgentLab/1.0',
                            'x-opencode-session': self.session_id})
        data = post_json(self.url, headers, payload)
        choice = data['choices'][0]
        message = choice['message']
        calls = [{'id': c['id'], 'name': c['function']['name'], 'arguments': c['function']['arguments']} for c in message.get('tool_calls', [])]
        return {'message': message, 'calls': calls, 'finish': choice.get('finish_reason'), 'usage': data.get('usage', {})}

    def _anthropic(self, messages, schemas):
        system = '\n'.join(m['content'] for m in messages if m['role'] == 'system')
        native = []
        for m in messages:
            if m['role'] == 'system':
                continue
            if m['role'] == 'assistant':
                blocks = []
                if m.get('content'):
                    blocks.append({'type': 'text', 'text': m['content']})
                for call in m.get('tool_calls', []):
                    blocks.append({'type': 'tool_use', 'id': call['id'], 'name': call['function']['name'], 'input': json.loads(call['function']['arguments'])})
                native.append({'role': 'assistant', 'content': blocks})
            elif m['role'] == 'tool':
                block = {'type': 'tool_result', 'tool_use_id': m['tool_call_id'], 'content': m['content']}
                if native and native[-1]['role'] == 'user' and isinstance(native[-1]['content'], list):
                    native[-1]['content'].append(block)
                else:
                    native.append({'role': 'user', 'content': [block]})
            else:
                native.append({'role': 'user', 'content': m['content']})
        tools = [{'name': x['function']['name'], 'description': x['function']['description'], 'input_schema': x['function']['parameters']} for x in schemas]
        payload = {'model': self.model, 'max_tokens': 1024, 'system': system, 'messages': native}
        if tools:
            payload['tools'] = tools
        data = post_json(self.url, {'x-api-key': self.key, 'anthropic-version': '2023-06-01'}, payload)
        blocks = data['content']
        calls = [{'id': b['id'], 'name': b['name'], 'arguments': json.dumps(b['input'], ensure_ascii=False)} for b in blocks if b['type'] == 'tool_use']
        text = '\n'.join(b['text'] for b in blocks if b['type'] == 'text')
        message = {'role': 'assistant', 'content': text or None}
        if calls:
            message['tool_calls'] = [{'id': c['id'], 'type': 'function', 'function': {'name': c['name'], 'arguments': c['arguments']}} for c in calls]
        reason = {'end_turn': 'stop', 'tool_use': 'tool_calls', 'max_tokens': 'length'}.get(data.get('stop_reason'), data.get('stop_reason'))
        return {'message': message, 'calls': calls, 'finish': reason, 'usage': data.get('usage', {})}
