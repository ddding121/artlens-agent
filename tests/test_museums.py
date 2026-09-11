import json
from argparse import Namespace
import numpy as np
import pytest
from PIL import Image
from scripts import import_museums as m
from scripts import import_famous as f
from artlens import verification


def met():
    return {'objectID':42,'isPublicDomain':True,'classification':'Paintings','title':'Example','artistPrefix':'Possibly by','artistDisplayName':'Artist', 'primaryImageSmall':'https://images.metmuseum.org/example.jpg'}


def test_met_qualifier_and_licence():
    r=m.normalize('met',met())
    assert r['id']=='met_42' and r['artist']=='Possibly by Artist'
    d=met();d['isPublicDomain']=False
    assert m.normalize('met',d) is None


def test_aic_existing_ids_preserved():
    r=m.normalize('aic',{'id':12,'is_public_domain':True,'artwork_type_title':'Painting','image_id':'abc-12','title':'A'})
    assert r['id']=='12'


def test_cma_cc0_and_web():
    d={'id':12,'share_license_status':'CC0','type':'Painting','title':'A','url':'https://www.clevelandart.org/art/12','images':{'web':{'url':'https://openaccess-cdn.clevelandart.org/a.jpg'}}}
    assert m.normalize('cma',d)['id']=='cma_12'
    d['share_license_status']='Copyrighted'
    assert m.normalize('cma',d) is None


def test_hosts_and_reference_paths():
    with pytest.raises(ValueError):m.image_url('met','https://images.metmuseum.org.evil.test/a.jpg')
    assert verification.reference_path({'id':'met_42'}).name=='met_42.jpg'
    assert verification.reference_path({'id':'cma_42'}).name=='cma_42.jpg'
    with pytest.raises(ValueError):verification.reference_path({'id':'met_../secret'})


def test_incremental_resume_preserves_existing(tmp_path,monkeypatch):
    monkeypatch.setattr(m,'DATA',tmp_path);monkeypatch.setattr(f,'DATA',tmp_path)
    monkeypatch.setattr(m.time,'sleep',lambda _:None)
    (tmp_path/'images').mkdir()
    old={'model':'test','records':[{'id':'1','title':'old'}]}
    (tmp_path/'index.json').write_text(json.dumps(old));np.save(tmp_path/'vectors.npy',np.array([[1.,0.]]))
    class Engine:
        def load(self):
            doc=json.loads((tmp_path/'index.json').read_text());self.vectors=np.load(tmp_path/doc.get('vectors_file','vectors.npy'));return True
        def encode(self,image):return np.array([0.,1.])
    class API:
        def page(self,source,offset):return [42] if offset==0 else []
        def detail(self,*args):return met()
        def download(self,*args):return Image.new('RGB',(5,5)),b'fixture'
    monkeypatch.setattr(m,'Retriever',Engine)
    args=Namespace(sources=['met'],limit=1,max_scan=100)
    m.run(API(),args)
    first=json.loads((tmp_path/'index.json').read_text())
    assert [r['id'] for r in first['records']]==['1','met_42']
    m.run(API(),args)
    second=json.loads((tmp_path/'index.json').read_text())
    assert len(second['records'])==2
    assert np.load(tmp_path/second['vectors_file']).shape==(2,2)
    assert (tmp_path/'vectors.npy').exists()


def test_403_stops_source_and_continues_next(tmp_path,monkeypatch):
    import httpx
    monkeypatch.setattr(m,'DATA',tmp_path);monkeypatch.setattr(f,'DATA',tmp_path)
    monkeypatch.setattr(m.time,'sleep',lambda _:None)
    (tmp_path/'images').mkdir()
    (tmp_path/'index.json').write_text(json.dumps({'model':'test','records':[{'id':'1'}]}),encoding='utf-8')
    np.save(tmp_path/'vectors.npy',np.array([[1.,0.]]))
    class Engine:
        def load(self):self.vectors=np.array([[1.,0.]]);return True
        def encode(self,image):return np.array([0.,1.])
    class API:
        attempts=0
        def page(self,source,offset):return [42,43,44] if source=='met' else [{'id':12,'share_license_status':'CC0','type':'Painting','title':'画作','url':'https://www.clevelandart.org/art/12','images':{'web':{'url':'https://openaccess-cdn.clevelandart.org/a.jpg'}}}]
        def detail(self,source,value):
            if source=='met':
                self.attempts+=1
                r=httpx.Response(403,request=httpx.Request('GET','https://collectionapi.metmuseum.org/test'))
                r.raise_for_status()
            return value
        def download(self,*args):return Image.new('RGB',(5,5)),b'fixture'
    monkeypatch.setattr(m,'Retriever',Engine)
    api=API()
    with pytest.raises(SystemExit):m.run(api,Namespace(sources=['met','cma'],limit=1,max_scan=100))
    assert api.attempts==1
    doc=json.loads((tmp_path/'index.json').read_text(encoding='utf-8'))
    assert doc['records'][-1]['id']=='cma_12'
