import asyncio
import pytest
from PIL import Image
from artlens import verification as v
from artlens import main
from test_app import client, sample

@pytest.mark.parametrize('verdict,expected', [('same','likely_match'),('different','unknown'),('uncertain','candidate')])
def test_identity_flow(monkeypatch, verdict, expected):
    monkeypatch.setenv('MATCH_MIN_SCORE', '0.95')
    monkeypatch.setenv('MATCH_MIN_MARGIN', '0.03')
    monkeypatch.setattr(main.retriever, 'search', lambda im: [
        {'id':'1','score':.999,'title':'A','artist':'Artist'}, {'id':'2','score':.862,'title':'B','artist':'Other'}])
    async def verify(*args): return {'verdict':verdict,'reason':'test'}
    async def answer(*args): return '测试解读'
    monkeypatch.setattr(main, 'verify', verify)
    monkeypatch.setattr(main, 'complete', answer)
    r=client.post('/api/analyze',files={'file':('x.png',sample(),'image/png')}).json()
    assert r['identity']==expected
    assert bool(r['identified_work'])==(expected=='likely_match')
    assert r['candidates'][0]['thumbnail_url']=='/api/reference/1'
    client.delete('/api/session/'+r['session_id'])

@pytest.mark.parametrize('payload,expected',[
 ('{"verdict":"same","matches":["姿态相同","构图相同"],"contradictions":[],"region":"中央区域"}', 'same'),
 ('{"verdict":"same","matches":["风格相同"],"contradictions":[],"region":"中央区域"}', 'uncertain'),
 ('{"verdict":"same","matches":["a","b"],"contradictions":[{"location":"中央","upload":"左手","reference":"右手","both_visible":true}],"region":"中央区域"}', 'uncertain'),
 ('not json', 'uncertain')])
def test_pair_validation(monkeypatch,tmp_path,payload,expected):
    monkeypatch.setattr(v,'DATA',tmp_path)
    (tmp_path/'images').mkdir()
    Image.new('RGB',(32,32)).save(tmp_path/'images'/'1.jpg')
    async def answer(system,text,images):
        assert len(images)==2
        return payload
    monkeypatch.setattr(v,'complete',answer)
    assert asyncio.run(v.verify(sample(),{'id':'1'}))['verdict']==expected


def test_missing_reference_and_path(monkeypatch,tmp_path):
    monkeypatch.setattr(v,'DATA',tmp_path)
    assert asyncio.run(v.verify(sample(),{'id':'1'}))['verdict']=='uncertain'
    with pytest.raises(ValueError): v.reference_path({'id':'../secrets'})


def test_local_thumbnail(monkeypatch,tmp_path):
    monkeypatch.setattr(v,'DATA',tmp_path)
    (tmp_path/'images').mkdir()
    Image.new('RGB',(32,32)).save(tmp_path/'images'/'1.jpg')
    assert client.get('/api/reference/1').status_code==200
    assert client.get('/api/reference/2').status_code==404


def test_verified_identity_survives_explanation_failure(monkeypatch):
    from artlens.provider import ModelUnavailable
    monkeypatch.setattr(main.retriever,'search',lambda im:[
        {'id':'1','score':.999,'title':'A','artist':'Artist'},
        {'id':'2','score':.862,'title':'B','artist':'Other'}])
    async def verified(*args): return {'verdict':'same','reason':'match'}
    async def fail(*args): raise ModelUnavailable('服务不可用')
    monkeypatch.setattr(main,'verify',verified)
    monkeypatch.setattr(main,'complete',fail)
    r=client.post('/api/analyze',files={'file':('x.png',sample(),'image/png')}).json()
    assert r['identity']=='likely_match'
    assert r['identified_work']['artist']=='Artist'
    assert '无法确认' not in r['answer']
    assert r['elapsed_seconds'] >= 0 and r['retrieval_gap']==.137
    assert not r['model_ok']
    client.delete('/api/session/'+r['session_id'])


def test_crop_omissions_are_not_conflicts():
    result = v.normalize_verification({'verdict':'same', 'region':'左上区域',
        'matches':['同一位置手臂姿态相同','同一位置衣纹相同'],
        'outside_crop':['下方第三人未出现在裁剪范围内'], 'contradictions':[]})
    assert result['verdict']=='same'
    assert not result['differences']
    assert result['outside_crop']


def test_rejection_without_shared_visible_conflict_is_uncertain():
    result = v.normalize_verification({'verdict':'different', 'region':'左上区域',
        'matches':[], 'outside_crop':['下方人物缺失'],
        'contradictions':[{'location':'下方','upload':'未显示','reference':'人物','both_visible':False}]})
    assert result['verdict']=='uncertain'
    assert not result['differences']


def test_real_shared_conflict_stays_different():
    result = v.normalize_verification({'verdict':'different', 'region':'中央区域',
        'matches':[], 'outside_crop':[],
        'contradictions':[{'location':'同一只手','upload':'举起','reference':'放下','both_visible':True}]})
    assert result['verdict']=='different'
    assert result['differences']
