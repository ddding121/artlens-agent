"""评估独立查询集的检索结果；未实测时不生成示例分数。
JSONL 每行：{"image":"queries/a.jpg","expected_id":"123"}
未知作品 expected_id 为 null。阈值必须提前在验证集确定。
"""
import argparse
import json
from pathlib import Path
from artlens.core import Retriever, decode_image, choose_identity


def main():
    p = argparse.ArgumentParser()
    p.add_argument('queries', type=Path)
    p.add_argument('--min-score', type=float, required=True)
    p.add_argument('--min-margin', type=float, required=True)
    p.add_argument('--output', type=Path, default=Path('evaluation.json'))
    a = p.parse_args()
    engine = Retriever()
    if not engine.load():
        raise SystemExit('请先构建检索索引。')
    counts = dict(known=0, unknown=0, top1_hits=0, top5_hits=0, unknown_false_matches=0)
    rows = []
    for line in a.queries.read_text(encoding='utf-8').splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        image, _ = decode_image((a.queries.parent / item['image']).read_bytes())
        results = engine.search(image)
        ids = [x['id'] for x in results]
        decision = choose_identity(results, a.min_score, a.min_margin)
        expected = item['expected_id']
        if expected is None:
            counts['unknown'] += 1
            counts['unknown_false_matches'] += decision == 'candidate'
        else:
            counts['known'] += 1
            counts['top1_hits'] += bool(ids and ids[0] == str(expected))
            counts['top5_hits'] += str(expected) in ids
        rows.append({'image': item['image'], 'expected_id': expected, 'ranked_ids': ids, 'decision': decision})
    rate = lambda n, d: n / d if d else None
    report = {'counts': counts, 'top1_accuracy': rate(counts['top1_hits'],counts['known']),
        'top5_recall': rate(counts['top5_hits'],counts['known']),
        'unknown_false_match_rate': rate(counts['unknown_false_matches'],counts['unknown']),
        'thresholds': {'score': a.min_score,'margin': a.min_margin}, 'results': rows}
    a.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('评估已写入', a.output)

if __name__ == '__main__':
    main()
