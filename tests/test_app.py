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
