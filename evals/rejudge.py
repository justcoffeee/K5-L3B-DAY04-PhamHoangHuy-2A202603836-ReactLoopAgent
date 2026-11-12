"""Chấm lại case unscored từ answer/trace đã lưu, không chạy lại agent."""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from providers import Provider
from grading import grade_case, summarize


def load_env():
    """Chỉ nạp credentials/config cục bộ; judge lấy từ report, không từ .env."""
    path = ROOT / '.env'
    if not path.exists():
        return
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


def rejudge(report, definitions, selected, judge, save):
    """Mỗi case một lần chấm; lưu grade cũ và checkpoint sau mỗi kết quả."""
    revised = deepcopy(report)
    by_id = {case['id']: case for case in revised['cases']}
    # Kiểm tra toàn bộ trước khi tiêu tốn request API.
    for case_id in selected:
        if case_id not in by_id or case_id not in definitions:
            raise ValueError(f'Không tìm thấy case {case_id}.')
        item, definition = by_id[case_id], definitions[case_id]
        if item['grade'].get('score') is not None:
            raise ValueError(f'{case_id} đã có điểm; không chấm lại để chọn điểm cao hơn.')
        if item['result'].get('status') != 'completed':
            raise ValueError(f'{case_id}: agent chưa completed, cần chạy lại agent.')
        for key in ('question', 'expected'):
            if item[key] != definition[key]:
                raise ValueError(f'{case_id}: {key} khác dataset gốc.')
    for case_id in selected:
        item = by_id[case_id]
        original_grade = deepcopy(item['grade'])
        print(f'Chấm lại {case_id} (chỉ judge)...', flush=True)
        item['grade'] = grade_case(definitions[case_id], item['result'], judge)
        item.setdefault('rejudge_history', []).append({
            'at': datetime.now(timezone.utc).isoformat(),
            'previous_grade': original_grade,
            'judge_provider': revised['config']['judge_provider'],
            'judge_model': revised['config']['judge_model'],
        })
        revised['summary'] = summarize(revised['cases'])
        save(revised)
        print(f"{case_id}: {item['grade']['score']} ({item['grade']['status']})", flush=True)
    return revised


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', default='eval_before_deepseek.json')
    parser.add_argument('--output', default='eval_before_deepseek_rejudged.json')
    parser.add_argument('--cases', nargs='+', default=['A6', 'A8', 'H3'])
    args = parser.parse_args()
    source, target = Path(args.input), Path(args.output)
    if source.resolve() == target.resolve() or target.exists():
        parser.error('Output phải là file mới, khác input; không ghi đè kết quả cũ.')
    report = json.loads(source.read_text(encoding='utf-8-sig'))
    if report['config'].get('dataset') != 'core':
        parser.error('Script này chỉ dùng dataset core.')
    definitions = {case['id']: case for case in json.loads(
        (ROOT / 'evals' / 'cases.json').read_text(encoding='utf-8'))}
    load_env()
    config = report['config']
    judge = Provider(config['judge_provider'], config['judge_model'])

    def save(revised):
        temporary = target.with_name(target.name + '.tmp')
        temporary.write_text(json.dumps(revised, ensure_ascii=False, indent=2) + '\n',
                             encoding='utf-8')
        temporary.replace(target)

    try:
        revised = rejudge(report, definitions, list(dict.fromkeys(
            case_id.upper() for case_id in args.cases)), judge, save)
    except ValueError as exc:
        parser.error(str(exc))
    print('Summary:', json.dumps(revised['summary']), flush=True)
    print('File:', target)
    return 0 if revised['summary']['unscored_cases'] == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
