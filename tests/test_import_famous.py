import json
import numpy as np
import pytest
from scripts import import_famous as imp


def test_append_manifest_and_old_vectors_survive(tmp_path,monkeypatch):
    monkeypatch.setattr(imp,'DATA',tmp_path)
    old=np.array([[1.,0.]])
    np.save(tmp_path/'vectors.npy',old)
    doc={'model':'example','records':[{'id':'1'}]}
    (tmp_path/'index.json').write_text(json.dumps(doc))
    imp.commit_index({**doc,'records':[{'id':'1'},{'id':'wd_Q12418'}]},np.array([[1.,0.],[0.,1.]]))
    updated=json.loads((tmp_path/'index.json').read_text())
    assert len(updated['records'])==2
    assert np.load(tmp_path/updated['vectors_file']).shape==(2,2)
    assert np.array_equal(np.load(tmp_path/'vectors.npy'),old)


def test_invalid_index_preserves_manifest(tmp_path,monkeypatch):
    monkeypatch.setattr(imp,'DATA',tmp_path)
    p=tmp_path/'index.json';p.write_text('original')
    with pytest.raises(ValueError):imp.commit_index({'records':[{}]},np.zeros((2,3)))
    assert p.read_text()=='original'


def test_ambiguous_names_are_not_guessed(monkeypatch):
    source=imp.Source(None)
    monkeypatch.setattr(source,'get',lambda *a,**k:{'search':[{'label':'The Kiss','id':'Q1'},{'label':'The Kiss','id':'Q2'}]})
    with pytest.raises(ValueError):source.resolve('The Kiss')
    assert source.resolve('Q12418')=='Q12418'


@pytest.mark.parametrize('name,expected',[('Public domain',True),('CC BY-SA 4.0',True),('CC BY-NC 4.0',False),('CC BY-ND 4.0',False),('',False)])
def test_license(name,expected):assert imp.supported_license(name)==expected


def test_download_host():
    assert imp.allowed_image('https://upload.wikimedia.org/a.jpg')
    assert not imp.allowed_image('https://upload.wikimedia.org.evil.example/a.jpg')
    assert not imp.allowed_image('http://127.0.0.1/a.jpg')


def test_protocol_relative_and_http_normalization():
    assert imp.normalize_image_url('//upload.wikimedia.org/a.jpg')=='https://upload.wikimedia.org/a.jpg'
    assert imp.normalize_image_url('http://upload.wikimedia.org/a.jpg')=='https://upload.wikimedia.org/a.jpg'


def test_original_fallback():
    assert imp.select_image_url({'thumburl':'https://example.com/a.jpg','url':'https://upload.wikimedia.org/b.jpg'})=='https://upload.wikimedia.org/b.jpg'


def test_unknown_host_diagnostic():
    with pytest.raises(ValueError,match='host=example.com'):
        imp.select_image_url({'url':'https://example.com/a.jpg?secret=should-not-print'})


def test_credentials_and_bad_port():
    for url in ['https://user:pass@upload.wikimedia.org/a.jpg','https://upload.wikimedia.org:8888/a.jpg']:
        assert not imp.allowed_image(url)


def test_large_reference_is_compressed_without_relaxing_upload_limit():
    import io
    from PIL import Image
    from artlens.core import decode_image
    b=io.BytesIO();Image.new('RGB',(2000,1800),'blue').save(b,format='JPEG')
    raw=b.getvalue()+b'\0'*(11*1024*1024)
    old=Image.MAX_IMAGE_PIXELS
    image,normalized=imp.prepare_reference(raw)
    assert max(image.size)<=1600
    assert len(normalized)<10*1024*1024
    assert Image.MAX_IMAGE_PIXELS==old
    with pytest.raises(ValueError):decode_image(raw)


def test_bad_reference_restores_pixel_limit():
    from PIL import Image
    old=Image.MAX_IMAGE_PIXELS
    with pytest.raises(ValueError):imp.prepare_reference(b'not image')
    assert Image.MAX_IMAGE_PIXELS==old
