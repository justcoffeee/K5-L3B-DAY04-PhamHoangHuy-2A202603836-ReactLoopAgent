"""Chạy: python test_api.py. Tự nạp .env cạnh file, không in API key."""
import json
import os
from pathlib import Path

from providers import Provider, ProviderHTTPError


def test_api(env_path=None):
    """Gửi một câu hỏi ngắn; trả dict có ok, model, finish hoặc lỗi an toàn."""
    path = Path(env_path) if env_path else Path(__file__).resolve().with_name('.env')
    try:
        for raw in path.read_text(encoding='utf-8-sig').splitlines():
            line = raw.strip()
            if not line or line.startswith('#'):
                continue
            name, separator, value = line.removeprefix('export ').partition('=')
            if separator:
                value = value.strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                    value = value[1:-1]
                os.environ[name.strip()] = value
        model = os.getenv('API_MODEL') or os.getenv('MODEL')
        client = Provider(os.getenv('PROVIDER', 'openai'), model)
        response = client.complete(
            [{'role': 'user', 'content': 'Reply with exactly: OK'}], [])
        answer = response['message'].get('content') or ''
        # Không in raw response hay nội dung exception có thể chứa credentials.
        return {'ok': response['finish'] == 'stop' and answer.strip() == 'OK',
                'model': model, 'finish': response['finish'],
                'reply_is_ok': answer.strip() == 'OK', 'usage': response['usage']}
    except ProviderHTTPError as exc:
        hints = {
            401: 'Server không chấp nhận credential.',
            403: 'Server từ chối quyền truy cập hoặc loại client này.',
            404: 'Kiểm tra endpoint và tên model.',
            429: 'Đã hết budget retry; kiểm tra quota và Retry-After.',
        }
        return {'ok': False, 'http_status': exc.http_status,
                'retry_after': exc.retry_after,
                'error_kind': exc.error_kind,
                'error': hints.get(exc.http_status, 'Provider trả lỗi HTTP.')}
    except FileNotFoundError:
        return {'ok': False, 'error': 'Không tìm thấy file .env.'}
    except ValueError:
        return {'ok': False, 'error': 'Kiểm tra PROVIDER, API_ENDPOINT, API_MODEL và API_KEY trong .env.'}
    except Exception as exc:
        return {'ok': False, 'error': type(exc).__name__,
                'hint': 'Kiểm tra kết nối và định dạng response của provider.'}


if __name__ == '__main__':
    result = test_api()
    print(json.dumps(result, ensure_ascii=True, indent=2))
    raise SystemExit(0 if result['ok'] else 1)
