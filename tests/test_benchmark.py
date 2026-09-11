import json
from pathlib import Path
import httpx
import pytest
from scripts import benchmark as b


def item(expected):
    return {'image': 'q.jpg', 'group': 'manual', 'expected_ids': expected}


def result(identity, work=None):
    return {'identity': identity, 'identified_work': {'id': work} if work else None,
            'candidates': [{'id': '1'}, {'id': '2'}], 'model_ok': True}


def test_metrics_separate_abstentions_errors_unknown_and_aliases():
    rows = [b.measure(item(['1', 'duplicate']), result('likely_match', 'duplicate'), 2),
            b.measure(item(['2']), result('unknown'), 4),
            b.measure(item([]), result('likely_match', '1'), 6),
            {'status': 'error'}]
    report = b.summarize(rows)
    assert report['errors'] == 1
    assert report['verified_known_accuracy'] == .5
    assert report['known_abstention_rate'] == .5
    assert report['top5_recall'] == 1
    assert report['unknown_false_match_rate'] == 1
    assert report['median_seconds'] == 4
    assert b.summarize([])['unknown_false_match_rate'] is None


def test_full_runner_releases_session_and_writes_report(tmp_path, monkeypatch):
    (tmp_path / 'q.jpg').write_bytes(b'test')
    queries = tmp_path / 'queries.jsonl'
    queries.write_text(json.dumps(item(['1']))+'\n', encoding='utf-8')
    deleted = []
    def handler(request):
        if request.url.path == '/api/health':
            return httpx.Response(200, json={'model_configured': True, 'index_ready': True})
        if request.method == 'DELETE':
            deleted.append(request.url.path)
            return httpx.Response(200, json={})
        return httpx.Response(200, json={**result('likely_match', '1'), 'session_id': 'abc'})
    real_client = httpx.Client
    monkeypatch.setattr(b.httpx, 'Client', lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs))
    output = tmp_path / 'report'
    b.run(queries, output)
    assert deleted == ['/api/session/abc']
    assert json.loads((output/'report.json').read_text())['summary']['verified_known_accuracy'] == 1
    assert '无样本，不计算' in (output/'report.md').read_text()


def test_missing_label_does_not_silently_become_unknown(tmp_path):
    path = tmp_path / 'q.jsonl'
    path.write_text('{"image":"q.jpg"}\n')
    with pytest.raises(ValueError, match='expected_ids'):
        b.load_queries(path)


def test_prepare_creates_reproducible_labeled_crops(tmp_path, monkeypatch):
    from PIL import Image
    Image.new('RGB', (100, 80), 'blue').save(tmp_path/'ref.jpg')
    (tmp_path/'index.json').write_text(json.dumps({'records': [{'id': '1', 'title': 'Test'}]}))
    monkeypatch.setattr(b, 'DATA', tmp_path)
    monkeypatch.setattr(b, 'reference_path', lambda record: tmp_path/'ref.jpg')
    output = tmp_path/'smoke'
    b.prepare(output, 5, 42)
    rows = b.load_queries(output/'queries.jsonl')
    assert len(rows) == 2 and rows[1]['expected_ids'] == ['1']
    with Image.open(rows[1]['_file']) as crop:
        assert crop.size == (80, 64)
    with pytest.raises(FileExistsError):
        b.prepare(output, 5, 42)
