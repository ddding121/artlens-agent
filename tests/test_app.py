import io
from PIL import Image
from fastapi.testclient import TestClient
from artlens.main import app, sessions
from artlens.core import choose_identity

client = TestClient(app)


def sample():
    b = io.BytesIO()
    Image.new('RGB', (32, 32), 'blue').save(b, format='PNG')
    return b.getvalue()


def test_invalid_upload():
    assert client.post('/api/analyze', files={'file': ('x.jpg', b'not an image', 'image/jpeg')}).status_code == 400


def test_no_key_does_not_fabricate(monkeypatch):
    monkeypatch.delenv('VISION_API_KEY', raising=False)
    result = client.post('/api/analyze', files={'file': ('x.png', sample(), 'image/png')})
    assert result.status_code == 200
    data = result.json()
    assert data['model_ok'] is False
    assert data['identity'] == 'unknown'
    assert '无法确认' in data['answer']
    assert client.delete('/api/session/' + data['session_id']).status_code == 200
    assert data['session_id'] not in sessions


def test_chat_expired():
    assert client.post('/api/chat', json={'session_id': 'nonexistent-session', 'message':'作者是谁？'}).status_code == 404


def test_unknown_gate():
    assert choose_identity([{'score': .99}], None, None) == 'unknown'
    assert choose_identity([{'score': .91}, {'score': .90}], .8, .05) == 'unknown'
    assert choose_identity([{'score': .91}, {'score': .70}], .8, .05) == 'candidate'


def test_success_and_followup(monkeypatch):
    import artlens.main as main
    calls=[]
    async def fake(system,text,image=None,history=None):
        calls.append((system,text,image,history))
        return '画面观察：蓝色测试图片。'
    monkeypatch.setattr(main, 'complete', fake)
    data=client.post('/api/analyze',files={'file':('x.png',sample(),'image/png')}).json()
    assert data['model_ok']
    reply=client.post('/api/chat',json={'session_id':data['session_id'],'message':'什么颜色？'})
    assert reply.status_code==200
    assert calls[1][2] and calls[1][3]
    client.delete('/api/session/'+data['session_id'])


def test_page_and_static():
    assert 'ArtLens' in client.get('/').text
    assert client.get('/static/app.js').status_code == 200
    assert client.get('/api/health').json()['status']=='ok'


def test_chat_sources_and_context_isolation(monkeypatch):
    import json
    import time
    import asyncio
    import artlens.main as main
    token = 'citation-test-session'
    main.sessions[token] = {'created': time.monotonic(), 'image': b'picture',
        'context': json.dumps({'identity': 'unknown', 'candidates': [
            {'source_id': 1, 'title': 'Candidate', 'url': 'https://www.artic.edu/artworks/1'}]}),
        'history': [], 'lock': asyncio.Lock()}
    async def fake(system, text, image=None, history=None):
        assert 'Candidate' not in system
        assert 'Candidate' in text and 'unknown' in text
        assert '直接回答本次问题' in system
        return '候选作品资料 [1]。不存在的引用 [99]。'
    monkeypatch.setattr(main, 'complete', fake)
    try:
        response = client.post('/api/chat', json={'session_id': token, 'message': '背景？'})
        assert response.status_code == 200
        assert [s['source_id'] for s in response.json()['sources']] == [1]
        assert response.json()['warnings']
        client.delete('/api/session/' + token)
        assert client.post('/api/chat', json={'session_id': token, 'message': '继续'}).status_code == 404
    finally:
        main.sessions.pop(token, None)


def test_manual_verification_updates_context_and_caches(monkeypatch):
    import json
    import artlens.main as main
    candidates = [{'id': 'one', 'title': 'Work', 'score': .7}, {'id': 'two', 'score': .69}]
    monkeypatch.setattr(main.retriever, 'search', lambda image: [dict(r) for r in candidates])
    calls = []
    async def fake_verify(image, record):
        calls.append(record['id'])
        return {'verdict': 'same', 'reason': '共同区域一致'}
    async def fake_complete(*args, **kwargs):
        return '更新后的说明'
    monkeypatch.setattr(main, 'verify', fake_verify)
    monkeypatch.setattr(main, 'complete', fake_complete)
    data = client.post('/api/analyze', files={'file': ('x.png', sample(), 'image/png')}).json()
    token = data['session_id']
    assert data['can_verify'] and not calls
    assert len(data['diagnostics']['reasons']) == 2
    sessions[token]['history'].append({'role': 'user', 'content': 'old'})
    result = client.post('/api/verify', json={'session_id': token}).json()
    assert result['identity'] == 'likely_match'
    assert not result['can_verify']
    assert json.loads(sessions[token]['context'])['identity'] == 'likely_match'
    assert len(sessions[token]['history']) == 1
    client.post('/api/verify', json={'session_id': token})
    assert calls == ['one']
    client.delete('/api/session/' + token)
    assert client.post('/api/verify', json={'session_id': token}).status_code == 404


def test_manual_different_never_promotes(monkeypatch):
    import artlens.main as main
    monkeypatch.setattr(main.retriever, 'search', lambda image: [{'id': 'one', 'score': .1}])
    async def fake_verify(*args):
        return {'verdict': 'different', 'reason': '共同区域存在差异'}
    async def fake_complete(*args, **kwargs):
        return '未确认'
    monkeypatch.setattr(main, 'verify', fake_verify)
    monkeypatch.setattr(main, 'complete', fake_complete)
    token = client.post('/api/analyze', files={'file': ('x.png', sample(), 'image/png')}).json()['session_id']
    result = client.post('/api/verify', json={'session_id': token}).json()
    assert result['identity'] == 'unknown' and result['identified_work'] is None
    client.delete('/api/session/' + token)
