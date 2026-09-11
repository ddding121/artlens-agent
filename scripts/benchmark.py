"""通过本地服务评测完整识别流程。所有结果来自实际请求，不生成示例分数。"""
import argparse
import hashlib
import json
import random
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from PIL import Image
from artlens.core import DATA
from artlens.verification import reference_path


def prepare(output, count, seed):
    """生成图库原图/裁剪回归集；不是独立泛化测试集。"""
    doc = json.loads((DATA / 'index.json').read_text(encoding='utf-8'))
    pool = []
    for record in doc['records']:
        try:
            if reference_path(record).is_file():
                pool.append(record)
        except ValueError:
            continue
    if not pool:
        raise ValueError('没有可用本地参考图，请先导入图库。')
    selected = random.Random(seed).sample(pool, min(count, len(pool)))
    output.mkdir(parents=True, exist_ok=False)
    rows = []
    for i, record in enumerate(selected):
        with Image.open(reference_path(record)) as src:
            image = src.convert('RGB')
            image.thumbnail((1200, 1200))
        w, h = image.size
        for kind, query in [('reference', image), ('crop', image.crop((w//10, h//10, w-w//10, h-h//10)))]:
            name = f'{i:03d}-{kind}.jpg'
            query.save(output / name, quality=85)
            rows.append({'image': name, 'expected_ids': [str(record['id'])], 'group': kind,
                         'title': record.get('title', ''), 'dataset': 'reference-derived-regression'})
    (output / 'queries.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False)+'\n' for r in rows), encoding='utf-8')
    print(f'生成 {len(rows)} 张测试图：{output / "queries.jsonl"}。这是图库派生回归集，不代表独立识别准确率。')


def load_queries(path):
    items = []
    for number, line in enumerate(path.read_text(encoding='utf-8-sig').splitlines(), 1):
        if not line.strip():
            continue
        item = json.loads(line)
        expected = item.get('expected_ids')
        if not isinstance(expected, list) or any(not isinstance(x, (str, int)) or isinstance(x, bool) for x in expected):
            raise ValueError(f'第{number}行 expected_ids 必须是ID列表；库外作品用 []。')
        file = (path.parent / item['image']).resolve()
        if not file.is_file() or file.stat().st_size > 10*1024*1024:
            raise ValueError(f'第{number}行图片不存在或超过10 MB。')
        items.append({**item, 'expected_ids': [str(x) for x in expected], '_file': file,
                      'group': str(item.get('group', 'manual'))})
    if not items:
        raise ValueError('测试清单为空。')
    return items


def measure(item, data, elapsed):
    expected = item['expected_ids']
    identity = data['identity']
    if identity not in ('likely_match', 'candidate', 'unknown') or not isinstance(data['candidates'], list):
        raise ValueError('分析接口返回了不兼容的识别结果。')
    predicted = str((data.get('identified_work') or {}).get('id', '')) if identity == 'likely_match' else None
    if identity == 'likely_match' and not predicted:
        raise ValueError('匹配结果缺少作品ID。')
    ranked = [str(r['id']) for r in data['candidates']]
    known = bool(expected)
    return {'image': item['image'], 'group': item['group'], 'expected_ids': expected,
            'status': 'ok', 'identity': identity, 'predicted_id': predicted,
            'ranked_ids': ranked, 'top1_hit': bool(ranked and ranked[0] in expected) if known else None,
            'top5_hit': bool(set(ranked[:5]) & set(expected)) if known else None,
            'correct_match': predicted in expected if known else None,
            'wrong_match': predicted is not None and predicted not in expected,
            'abstained': predicted is None, 'elapsed_seconds': round(elapsed, 3),
            'model_ok': data.get('model_ok'), 'warnings': data.get('warnings', []),
            'verification': data.get('verification', {}), 'diagnostics': data.get('diagnostics', {})}


def summarize(rows):
    ok = [r for r in rows if r['status'] == 'ok']
    known = [r for r in ok if r['expected_ids']]
    unknown = [r for r in ok if not r['expected_ids']]
    ratio = lambda n, d: n / d if d else None
    return {'attempted': len(rows), 'completed': len(ok), 'errors': len(rows)-len(ok),
            'known_completed': len(known), 'unknown_completed': len(unknown),
            'top1_accuracy': ratio(sum(r['top1_hit'] for r in known), len(known)),
            'top5_recall': ratio(sum(r['top5_hit'] for r in known), len(known)),
            'verified_known_accuracy': ratio(sum(r['correct_match'] for r in known), len(known)),
            'known_wrong_match_rate': ratio(sum(r['wrong_match'] for r in known), len(known)),
            'known_abstention_rate': ratio(sum(r['abstained'] for r in known), len(known)),
            'unknown_false_match_rate': ratio(sum(r['wrong_match'] for r in unknown), len(unknown)),
            'median_seconds': statistics.median([r['elapsed_seconds'] for r in ok]) if ok else None,
            'explanation_failures': sum(r.get('model_ok') is False for r in ok)}


def write_report(output, rows, metadata):
    report = {**metadata, 'summary': summarize(rows), 'groups': {
        g: summarize([r for r in rows if r['group'] == g]) for g in sorted({r['group'] for r in rows})}, 'results': rows}
    (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    summary = report['summary']
    labels = {'top1_accuracy': '检索第一名正确率', 'top5_recall': '检索前五召回率',
              'verified_known_accuracy': '已知作品核验后正确识别率', 'known_wrong_match_rate': '已知作品误认率',
              'known_abstention_rate': '已知作品未确认率', 'unknown_false_match_rate': '库外作品误认率'}
    lines = ['# ArtLens 识别评测', '', '本报告只评估作品身份，不评估讲解事实或艺术解读质量。', '',
             f'请求 {summary["attempted"]}；完成 {summary["completed"]}；错误 {summary["errors"]}。',
             f'完成的已知样本 {summary["known_completed"]}；库外样本 {summary["unknown_completed"]}。', '',
             '| 指标 | 结果 |', '|---|---|']
    for key, label in labels.items():
        value = summary[key]
        lines.append(f'| {label} | '+(f'{value:.1%}' if value is not None else '无样本，不计算')+' |')
    lines.extend(['', f'完成请求耗时中位数（秒）：{summary["median_seconds"]}', '',
                  '分母为相应类别中成功完成接口请求的样本；请求错误单独统计，不能当作正确拒识。',
                  'candidate 和 unknown 均计为未确认；只有 likely_match 计为系统确认匹配。',
                  '讲解不可用次数：'+str(summary['explanation_failures'])+'。具体核验状态和警告见 report.json。', '',
                  '图库原图及其裁剪仅用于回归测试；不能以此宣称对任意照片的泛化准确率。',
                  '库外作品需人工确认在整个图库中不存在；同一作品跨馆或重复条目的ID应全部列入 expected_ids。',
                  '分组统计、逐图结果和失败原因见 report.json；实时记录见 results.jsonl。'])
    (output / 'report.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')


def run(queries, output):
    items = load_queries(queries)
    with httpx.Client(base_url='http://127.0.0.1:8000', timeout=300, trust_env=False) as client:
        response = client.get('/api/health'); response.raise_for_status()
        health = response.json()
        if not health.get('model_configured') or not health.get('index_ready'):
            raise ValueError('请先配置视觉模型、建立图库并重启服务。')
        output.mkdir(parents=True, exist_ok=False)
        metadata = {'created_utc': datetime.now(timezone.utc).isoformat(), 'health': health,
                    'query_manifest_sha256': hashlib.sha256(queries.read_bytes()).hexdigest(),
                    'datasets': sorted({str(i.get('dataset', 'manual')) for i in items}),
                    'interrupted': False}
        rows = []
        try:
            for item in items:
                token = None
                started = time.perf_counter()
                try:
                    with item['_file'].open('rb') as f:
                        response = client.post('/api/analyze', files={'file': (item['_file'].name, f)})
                    response.raise_for_status()
                    data = response.json(); token = data.get('session_id')
                    row = measure(item, data, time.perf_counter()-started)
                except (httpx.HTTPError, ValueError, KeyError, TypeError, OSError) as exc:
                    row = {'image': item['image'], 'group': item['group'], 'expected_ids': item['expected_ids'],
                           'status': 'error', 'reason': str(exc)[:500]}
                finally:
                    if token:
                        try:
                            client.delete('/api/session/'+token, timeout=10)
                        except httpx.HTTPError:
                            pass
                rows.append(row)
                with (output / 'results.jsonl').open('a', encoding='utf-8') as f:
                    f.write(json.dumps(row, ensure_ascii=False)+'\n')
                write_report(output, rows, metadata)
                print(json.dumps({'done': len(rows), 'total': len(items), 'image': item['image'],
                                  'status': row['status'], 'prediction': row.get('predicted_id')}, ensure_ascii=False), flush=True)
        except KeyboardInterrupt:
            metadata['interrupted'] = True
        finally:
            write_report(output, rows, metadata)
        print('评测报告：', output / 'report.md')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    prep = commands.add_parser('prepare'); prep.add_argument('--count', type=int, default=5)
    prep.add_argument('--seed', type=int, default=42)
    prep.add_argument('--output', type=Path, default=Path('evaluation/smoke'))
    execute = commands.add_parser('run'); execute.add_argument('queries', type=Path)
    execute.add_argument('--output', type=Path, default=Path('evaluation/run-'+datetime.now().strftime('%Y%m%d-%H%M%S')))
    args = parser.parse_args()
    try:
        if args.command == 'prepare':
            if args.count < 1: raise ValueError('count 必须大于0。')
            prepare(args.output, args.count, args.seed)
        else:
            run(args.queries, args.output)
    except (ValueError, OSError, httpx.HTTPError) as exc:
        raise SystemExit('评测未完成：'+str(exc))


if __name__ == '__main__':
    main()
