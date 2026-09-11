"""增量导入 Wikidata / Commons 名画。运行前停止服务。"""
import argparse
import io
import hashlib
import json
import re
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse
from html import unescape
import httpx
import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError
from artlens.core import DATA, Retriever, decode_image

TITLES = ['Mona Lisa','The Starry Night','Girl with a Pearl Earring','The Birth of Venus',
'The Last Supper','The Scream','The Night Watch','The Kiss','Las Meninas',
'The School of Athens','The Creation of Adam','The Arnolfini Portrait',
'The Garden of Earthly Delights','Liberty Leading the People','The Third of May 1808',
'The Swing','The Gleaners','The Angelus','Impression, Sunrise','The Great Wave off Kanagawa',
'A Sunday Afternoon on the Island of La Grande Jatte','American Gothic',
'Whistler\'s Mother','The Hay Wain','Wanderer above the Sea of Fog']
UA = 'ArtLens/0.1.4 (https://github.com/ddding121/artlens-agent; educational artwork retrieval)'


def values(entity, prop):
    claims = [c for c in entity.get('claims',{}).get(prop,[]) if c.get('rank')!='deprecated']
    preferred = [c for c in claims if c.get('rank')=='preferred']
    return [c['mainsnak']['datavalue']['value'] for c in (preferred or claims)
            if c.get('mainsnak',{}).get('snaktype')=='value']


def text_label(entity):
    labels=entity.get('labels',{})
    return labels.get('en',labels.get('zh',{})).get('value',entity.get('id','Unknown'))


def normalize_image_url(url):
    if not isinstance(url,str):
        raise ValueError('缺少图片地址')
    url=unescape(url).strip()
    if url.startswith('//'):
        url='https:'+url
    parsed=urlparse(url)
    if parsed.hostname!='upload.wikimedia.org' or parsed.username or parsed.password or parsed.port not in (None,80,443):
        raise ValueError('不支持的图片主机')
    if parsed.scheme not in ('http','https'):
        raise ValueError('不支持的图片协议')
    return parsed._replace(scheme='https',netloc='upload.wikimedia.org').geturl()


def allowed_image(url):
    try:
        normalize_image_url(url)
        return True
    except ValueError:
        return False


def select_image_url(media):
    diagnostics=[]
    for key in ('thumburl','url'):
        candidate=media.get(key)
        if not candidate:continue
        try:
            return normalize_image_url(candidate)
        except ValueError:
            try:
                p=urlparse(str(candidate))
                diagnostics.append(f'{key}: scheme={p.scheme or "空"}, host={p.hostname or "空"}')
            except ValueError:
                diagnostics.append(key+': 地址格式无效')
    raise ValueError('图片地址均未通过校验；'+ '; '.join(diagnostics)+'。请提供此诊断信息，不要删除域名检查。')


# 馆藏原图与网页用户上传使用不同限制；本函数仅由离线导入脚本调用。
MAX_REFERENCE_BYTES = 80 * 1024 * 1024
MAX_REFERENCE_PIXELS = 120_000_000


def prepare_reference(raw):
    if not raw or len(raw) > MAX_REFERENCE_BYTES:
        raise ValueError('馆藏原图超过 80 MB 下载上限，请使用较小的授权图片')
    previous = Image.MAX_IMAGE_PIXELS
    try:
        Image.MAX_IMAGE_PIXELS = MAX_REFERENCE_PIXELS
        with Image.open(io.BytesIO(raw)) as src:
            if src.format not in {'JPEG','PNG','WEBP'}:
                raise ValueError('馆藏图片格式不支持，仅支持 JPEG、PNG、WebP')
            if src.width * src.height > MAX_REFERENCE_PIXELS:
                raise ValueError('馆藏原图超过 1.2 亿像素上限')
            # JPEG 可在解码时降采样，降低高分辨率原图的内存占用。
            src.draft('RGB',(1600,1600))
            image = ImageOps.exif_transpose(src)
            image.thumbnail((1600,1600))
            image = image.convert('RGB')
        buffer = io.BytesIO()
        image.save(buffer, format='JPEG', quality=90)
        # 保存后再走统一校验，确保推理与双图核验读取的文件仍符合 10 MB 限制。
        return decode_image(buffer.getvalue())
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError('馆藏图片无法解码或尺寸过大') from exc
    finally:
        Image.MAX_IMAGE_PIXELS = previous


def supported_license(name):
    name=name.strip().lower().replace('-', ' ')
    return bool(re.fullmatch(r'(?:public domain|cc0(?: 1\.0)?|cc by(?: sa)?(?: [1-4]\.0)?)',name))


def commit_index(doc, vectors):
    """先写独立向量文件，最后原子替换清单；中断不会破坏旧清单。"""
    if vectors.ndim != 2 or len(vectors) != len(doc['records']) or not np.isfinite(vectors).all():
        raise ValueError('索引行数或向量数据无效，未修改旧索引')
    generation='vectors-'+uuid.uuid4().hex+'.npy'
    np.save(DATA/generation, vectors)
    updated={**doc,'vectors_file':generation}
    temporary=DATA/'index.pending.json'
    temporary.write_text(json.dumps(updated,ensure_ascii=False,indent=2),encoding='utf-8')
    temporary.replace(DATA/'index.json')


class Source:
    def __init__(self,client): self.client=client; self.cache={}
    def get(self,url,**kwargs):
        r=self.client.get(url,**kwargs);r.raise_for_status();return r.json()
    def entity(self,qid):
        if not re.fullmatch(r'Q\d+',qid): raise ValueError('无效 Wikidata ID')
        if qid not in self.cache:
            self.cache[qid]=self.get('https://www.wikidata.org/wiki/Special:EntityData/'+qid+'.json')['entities'][qid]
        return self.cache[qid]
    def resolve(self,title):
        if re.fullmatch(r'Q\d+',title):return title
        result=self.get('https://www.wikidata.org/w/api.php',params={
            'action':'wbsearchentities','search':title,'language':'en','limit':10,'format':'json'})
        exact=[x for x in result.get('search',[]) if x.get('label','').casefold()==title.casefold()]
        if len(exact)!=1:raise ValueError('名称不唯一或未精确匹配，请在 Wikidata 确认作品 Q 编号后用 --qid 导入')
        return exact[0]['id']
    def record(self,qid):
        e=self.entity(qid);images=values(e,'P18');authors=values(e,'P170')
        if len(images)!=1 or not authors:raise ValueError('缺少唯一主图或作者资料，需要人工核对条目')
        info=self.get('https://commons.wikimedia.org/w/api.php',params={
            'action':'query','titles':'File:'+images[0],'prop':'imageinfo',
            'iiprop':'url|extmetadata','iiurlwidth':1000,'format':'json'})
        pages=list(info.get('query',{}).get('pages',{}).values())
        media=pages[0]['imageinfo'][0]
        meta=media.get('extmetadata',{})
        plain=lambda key: unescape(re.sub('<[^>]+>',' ',meta.get(key,{}).get('value',''))).strip()
        license_name=plain('LicenseShortName')
        if not supported_license(license_name):
            raise ValueError('图片许可未明确属于支持的开放许可，跳过：'+license_name)
        url=select_image_url(media)
        author_names=[text_label(self.entity(a['id'])) for a in authors]
        dates=values(e,'P571')
        date=' / '.join(d.get('time','')[:5].lstrip('+') for d in dates) or '未记录'
        return {'id':'wd_'+qid,'title':text_label(e),'artist':' / '.join(author_names)+'（归属以来源条目为准）',
            'date':date,'description':'资料来自 Wikidata；创作时间可能为近似值，作者归属及限定条件请查看来源条目。',
            'source':'Wikidata / Wikimedia Commons','url':'https://www.wikidata.org/wiki/'+qid,
            'image_url':url,'image_source_url':media['descriptionurl'],
            'license':license_name,'license_url':plain('LicenseUrl'),
            'attribution':plain('Artist')+'; '+plain('Credit'),
            'wikidata_id':qid,'image_path':'images/wd_'+qid+'.jpg'},url


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--qid',nargs='+',help='明确的作品 Q 编号；未填写则使用内置的 25 个名画名称')
    p.add_argument('--check-source',action='store_true',help='只检查来源，不加载 CLIP、不下载图片、不改索引')
    a=p.parse_args()
    if a.check_source:
        with httpx.Client(headers={'User-Agent':UA},timeout=45,follow_redirects=False) as client:
            source=Source(client)
            for title in (a.qid or ['Q12418']):
                try:
                    qid=source.resolve(title);record,url=source.record(qid)
                    print(json.dumps({'qid':qid,'title':record['title'],'image_host':urlparse(url).hostname,'status':'source_ok'},ensure_ascii=False))
                except (httpx.HTTPError,ValueError,KeyError,IndexError,OSError) as exc:
                    print(json.dumps({'requested':title,'status':'source_failed','reason':str(exc)[:500]},ensure_ascii=False))
        return
    if not (DATA/'index.json').exists():raise SystemExit('请先运行 scripts.build_index 建立基础馆藏。')
    lock=DATA/'import.lock'
    try: lock.touch(exist_ok=False)
    except FileExistsError:raise SystemExit('已有导入锁。确认没有导入进程后再删除 data/import.lock。')
    try: run(a.qid or TITLES)
    finally: lock.unlink(missing_ok=True)


def run(titles):
    engine=Retriever()
    if not engine.load():raise ValueError('基础索引不可用')
    doc=json.loads((DATA/'index.json').read_text(encoding='utf-8'))
    stamp=time.strftime('%Y%m%d-%H%M%S')
    (DATA/('index.backup-'+stamp+'.json')).write_text(json.dumps(doc,ensure_ascii=False,indent=2),encoding='utf-8')
    records=list(doc['records']);vectors=engine.vectors.copy();existing={str(r['id']) for r in records}
    report=[]
    with httpx.Client(headers={'User-Agent':UA},timeout=45,follow_redirects=False) as client:
        source=Source(client)
        for title in titles:
            item={'requested':title}
            try:
                qid=source.resolve(title);ident='wd_'+qid;item['qid']=qid
                if ident in existing:
                    item['status']='already_present'
                else:
                    record,url=source.record(qid)
                    # 限制下载大小；不自动跟随重定向到其他域名。
                    with client.stream('GET',url) as response:
                        response.raise_for_status();raw=bytearray()
                        for chunk in response.iter_bytes():
                            raw.extend(chunk)
                            if len(raw)>MAX_REFERENCE_BYTES:raise ValueError('馆藏原图超过 80 MB 下载上限')
                    image,normalized=prepare_reference(bytes(raw))
                    vector=engine.encode(image)
                    path=DATA/record['image_path'];path.parent.mkdir(exist_ok=True)
                    path.write_bytes(normalized)
                    record['sha256']=hashlib.sha256(normalized).hexdigest()
                    # Wikimedia 同一条目不会重复追加；跨来源同作品仍需人工合并。
                    new_records=records+[record]
                    new_vectors=np.concatenate([vectors,vector[None,:]],axis=0)
                    commit_index({**doc,'records':new_records},new_vectors)
                    records,vectors=new_records,new_vectors
                    existing.add(ident);item.update(status='imported',title=record['title'])
            except (httpx.HTTPError,ValueError,KeyError,IndexError,OSError) as exc:
                item.update(status='failed',reason=str(exc)[:400])
            report.append(item)
            (DATA/'famous-import-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps(item,ensure_ascii=False),flush=True)
            time.sleep(.5)
    imported=sum(x['status']=='imported' for x in report)
    print(f'本次新增 {imported} 幅；当前共 {len(records)} 幅。详见 data/famous-import-report.json。请重启服务。')
    if any(x['status']=='failed' for x in report):raise SystemExit(1)

if __name__=='__main__':main()
