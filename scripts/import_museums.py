"""多馆藏增量导入，先停止 ArtLens 服务。仅导入开放绘画图片。"""
import argparse
import json
import re
import time
from collections import Counter
from html import unescape
from urllib.parse import urlparse, urljoin
import httpx
import numpy as np
from artlens.core import DATA, Retriever
from scripts.import_famous import prepare_reference, commit_index, MAX_REFERENCE_BYTES

NAMES={'met':'The Metropolitan Museum of Art','aic':'Art Institute of Chicago','cma':'Cleveland Museum of Art'}
HOSTS={'met':{'images.metmuseum.org'},'aic':{'www.artic.edu'},'cma':{'openaccess-cdn.clevelandart.org'}}


def clean(value):return unescape(re.sub('<[^>]+>',' ',value or '')).strip()


def image_url(source,url):
    p=urlparse(url)
    if p.scheme!='https' or p.hostname not in HOSTS[source] or p.username or p.password or p.port not in (None,443):
        raise ValueError('图片地址不支持，host='+str(p.hostname))
    if source=='aic' and not p.path.startswith('/iiif/'):
        raise ValueError('不是芝加哥 IIIF 图片地址')
    return url


def normalize(source,d):
    if source=='met':
        if not d.get('isPublicDomain') or 'paint' not in (d.get('classification','')+' '+d.get('objectName','')).lower():return None
        ident='met_'+str(int(d['objectID']))
        url=d.get('primaryImageSmall') or d.get('primaryImage')
        author=' '.join(x for x in (d.get('artistPrefix'),d.get('artistDisplayName'),d.get('artistSuffix')) if x) or 'Unknown'
        title=d.get('title');date=d.get('objectDate');desc='; '.join(str(d.get(k) or '') for k in ('medium','culture','period','creditLine'))
        page=d.get('objectURL') or 'https://www.metmuseum.org/art/collection/search/'+str(d['objectID'])
        license='CC0 / public-domain image (museum flag)'
    elif source=='aic':
        if d.get('is_public_domain') is not True or d.get('artwork_type_title')!='Painting' or not d.get('image_id'):return None
        if not re.fullmatch('[A-Za-z0-9-]+',d['image_id']):return None
        ident=str(int(d['id']))  # 兼容既有芝加哥数字 ID，避免重复入库。
        url='https://www.artic.edu/iiif/2/'+d['image_id']+'/full/843,/0/default.jpg'
        title=d.get('title');date=d.get('date_display');author=d.get('artist_display') or 'Unknown'
        desc=clean(d.get('description'))[:5000];page='https://www.artic.edu/artworks/'+ident
        license='Image: public domain; metadata CC0; description CC BY 4.0 Art Institute of Chicago (HTML removed)'
    else:
        if d.get('share_license_status')!='CC0' or d.get('type')!='Painting':return None
        ident='cma_'+str(int(d['id']));url=((d.get('images') or {}).get('web') or {}).get('url')
        title=d.get('title');date=d.get('creation_date');author=' / '.join(x.get('description') or x.get('name','') for x in d.get('creators',[])) or 'Unknown'
        desc=clean(d.get('description') or d.get('wall_description'))[:5000];page=d.get('url');license='CC0'
    if not url or not page or not title:return None
    image_url(source,url)
    return dict(id=ident,title=title,artist=author,date=date,description=desc,url=page,
                image_url=url,image_path='images/'+ident+'.jpg',source=NAMES[source],museum_code=source,license=license)


class API:
    def __init__(self,client):self.client=client
    def get(self,url,**kwargs):
        for attempt in range(3):
            r=self.client.get(url,**kwargs)
            if r.status_code not in (429,500,502,503,504):break
            if attempt<2:time.sleep(2**attempt)
        r.raise_for_status();return r.json()
    def page(self,source,offset):
        if source=='aic':
            fields='id,title,artist_display,date_display,image_id,is_public_domain,description,artwork_type_title'
            result=self.get('https://api.artic.edu/api/v1/artworks/search',params={'params':json.dumps({
                'query':{'bool':{'filter':[{'term':{'is_public_domain':True}},{'match':{'artwork_type_title':'Painting'}}]}},
                'fields':fields.split(','),'limit':100,'page':offset//100+1})})
            return result.get('data',[])
        if source=='cma':
            result=self.get('https://openaccess-api.clevelandart.org/api/artworks/',params={'cc0':'','type':'Painting','has_image':1,'skip':offset,'limit':100})
            return result.get('data',[])
        result=self.get('https://collectionapi.metmuseum.org/public/collection/v1.1/search',params={
            'q':'painting','hasImages':'true','medium':'Paintings','offset':offset,'limit':100})
        return result.get('objectIDs') or []
    def detail(self,source,value):
        return self.get('https://collectionapi.metmuseum.org/public/collection/v1/objects/'+str(int(value))) if source=='met' else value
    def download(self,source,url):
        # 只跟随同一来源允许域名内的跳转。
        for _ in range(4):
            url=image_url(source,url)
            with self.client.stream('GET',url) as r:
                if r.status_code in (301,302,303,307,308):
                    url=urljoin(url,r.headers['location']);continue
                r.raise_for_status();raw=bytearray()
                for chunk in r.iter_bytes():
                    raw.extend(chunk)
                    if len(raw)>MAX_REFERENCE_BYTES:raise ValueError('馆藏原图超过80MB')
                return prepare_reference(bytes(raw))
        raise ValueError('图片重定向过多')


def report_row(path,row):
    with path.open('a',encoding='utf-8') as f:f.write(json.dumps(row,ensure_ascii=False)+'\n')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--sources',nargs='+',choices=list(NAMES),default=list(NAMES))
    p.add_argument('--limit',type=int,default=100,help='本次每馆最多新增数量，不是最终图库总量')
    p.add_argument('--max-scan',type=int,default=10000,help='每馆最多检查的条目数')
    p.add_argument('--check',action='store_true',help='只检查每馆接口及一张图片，不加载CLIP、不修改索引')
    a=p.parse_args()
    if not 1<=a.limit<=10000 or not 1<=a.max_scan<=100000:p.error('limit须1~10000，max-scan须1~100000')
    with httpx.Client(timeout=45,follow_redirects=False,headers={'User-Agent':'ArtLens/0.1.5 (https://github.com/ddding121/artlens-agent)'}) as c:
        api=API(c)
        if a.check:
            for source in a.sources:
                try:
                    found=False
                    for entry in api.page(source,0)[:30]:
                        record=normalize(source,api.detail(source,entry))
                        if record:
                            image,_=api.download(source,record['image_url'])
                            print(json.dumps({'source':source,'status':'check_ok','title':record['title'],'size':image.size},ensure_ascii=False),flush=True);found=True;break
                    if not found:print(source+': 前30条无合格图片，尚未验证下载')
                except Exception as ex:print(json.dumps({'source':source,'status':'check_failed','reason':str(ex)[:400]},ensure_ascii=False),flush=True)
            return
        if not (DATA/'index.json').exists():raise SystemExit('请先建立基础索引。')
        lock=DATA/'import.lock'
        try:lock.touch(exist_ok=False)
        except FileExistsError:raise SystemExit('已有导入进程或残留 import.lock，请先确认进程状态。')
        try:run(api,a)
        finally:lock.unlink(missing_ok=True)


def run(api,args):
    engine=Retriever();engine.load()
    doc=json.loads((DATA/'index.json').read_text(encoding='utf-8'))
    stamp=time.strftime('%Y%m%d-%H%M%S')+'-'+str(time.time_ns());(DATA/('index.backup-museums-'+stamp+'.json')).write_text(json.dumps(doc,ensure_ascii=False),encoding='utf-8')
    report=DATA/('museum-import-'+stamp+'.jsonl')
    records=list(doc['records']);vectors=engine.vectors;ids={str(x['id']) for x in records};previous_generated=None
    failures=0
    for source in args.sources:
        added=0;scanned=0;offset=0;counts=Counter();consecutive_errors=0;paused=False
        while added<args.limit and scanned<args.max_scan and not paused:
            try:page=api.page(source,offset)
            except Exception as exc:
                report_row(report,{'source':source,'status':'source_failed','reason':str(exc)[:400]});print(source+': 接口失败，详见报告',flush=True);failures+=1;break
            if not page:break
            for entry in page:
                if added>=args.limit or scanned>=args.max_scan:break
                scanned+=1
                row={'source':source}
                try:
                    # 大都会先判断ID，重复项无需请求详情。
                    if source=='met' and 'met_'+str(entry) in ids:
                        row.update(id='met_'+str(entry),status='already_present')
                    else:
                        record=normalize(source,api.detail(source,entry))
                        if record is None:row['status']='ineligible'
                        elif record['id'] in ids:row.update(id=record['id'],status='already_present')
                        else:
                            image,raw=api.download(source,record['image_url']);vector=engine.encode(image)
                            (DATA/record['image_path']).write_bytes(raw)
                            next_records=records+[record];next_vectors=np.concatenate([vectors,vector[None,:]])
                            commit_index({**doc,'records':next_records},next_vectors)
                            current=json.loads((DATA/'index.json').read_text(encoding='utf-8'))['vectors_file']
                            # 只删除本次运行生成且已被替代的向量文件，不删初始备份引用的文件。
                            if previous_generated:
                                try:(DATA/previous_generated).unlink(missing_ok=True)
                                except OSError:pass
                            previous_generated=current;records,vectors=next_records,next_vectors;ids.add(record['id']);added+=1
                            row.update(id=record['id'],status='imported',title=record['title'])
                except (httpx.HTTPError,ValueError,KeyError,IndexError,TypeError,OSError) as exc:
                    row.update(status='failed',reason=str(exc)[:400]);failures+=1
                    if isinstance(exc,httpx.HTTPStatusError) and exc.response.status_code in (401,403,429):
                        paused=True
                counts[row['status']]+=1;report_row(report,row)
                if row['status'] in ('imported','failed'):print(json.dumps(row,ensure_ascii=False),flush=True)
                consecutive_errors=consecutive_errors+1 if row['status']=='failed' else 0
                if paused or consecutive_errors>=5:
                    paused=True
                    event={'source':source,'status':'source_paused','reason':'访问被拒绝、限流或连续5条失败，本次停止该馆，继续其他来源。'}
                    report_row(report,event);print(json.dumps(event,ensure_ascii=False),flush=True)
                    break
                time.sleep(.2)
            offset+=100
        summary={'source':source,'added':added,'scanned':scanned,'counts':dict(counts)}
        report_row(report,summary);print(json.dumps(summary,ensure_ascii=False),flush=True)
    print(f'图库共 {len(records)} 幅。报告：{report.name}。请重启服务。',flush=True)
    if failures:raise SystemExit(1)

if __name__=='__main__':
    try:main()
    except KeyboardInterrupt:
        print('\n导入已中止；已提交的索引保留。可稍后重新运行。',flush=True)
        raise SystemExit(130)
