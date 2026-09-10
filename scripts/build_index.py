"""下载芝加哥艺术博物馆公有领域绘画并建立 CLIP 索引。
用法：python -m scripts.build_index --limit 200
"""
import argparse
import json
import re
import time
from html import unescape
import httpx
import numpy as np
from PIL import Image
from artlens.core import DATA, Retriever, decode_image


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int, default=200)
    parser.add_argument('--model', default='openai/clip-vit-base-patch32')
    args = parser.parse_args()
    if not 1 <= args.limit <= 5000:
        parser.error('limit 必须介于 1 和 5000 之间')
    from transformers import CLIPModel, CLIPProcessor
    DATA.mkdir(exist_ok=True)
    (DATA / 'images').mkdir(exist_ok=True)
    engine = Retriever()
    engine.model = CLIPModel.from_pretrained(args.model).eval()
    engine.processor = CLIPProcessor.from_pretrained(args.model)
    records, vectors = [], []
    fields = 'id,title,artist_display,date_display,image_id,is_public_domain,description,medium_display,artwork_type_title'
    with httpx.Client(timeout=45, follow_redirects=False, headers={'User-Agent':'ArtLens-Research/0.1'}) as client:
        page = 1
        while len(records) < args.limit:
            response = client.get('https://api.artic.edu/api/v1/artworks/search', params={
                'params': json.dumps({'query': {'bool': {'filter': [{'term': {'is_public_domain': True}}, {'match': {'artwork_type_title': 'Painting'}}]}},
                'fields': fields.split(','), 'limit': 100, 'page': page})})
            response.raise_for_status()
            body = response.json()
            if not body.get('data'):
                break
            for item in body['data']:
                image_id = item.get('image_id')
                if item.get('artwork_type_title') != 'Painting' or not item.get('is_public_domain') or not image_id or not re.fullmatch(r'[a-zA-Z0-9-]+', image_id):
                    continue
                url = f'https://www.artic.edu/iiif/2/{image_id}/full/843,/0/default.jpg'
                path = DATA / 'images' / f"{int(item['id'])}.jpg"
                try:
                    if path.exists():
                        raw = path.read_bytes()
                    else:
                        img_response = client.get(url)
                        img_response.raise_for_status()
                        raw = img_response.content
                    image, normalized = decode_image(raw)
                    vec = engine.encode(image)
                    path.write_bytes(normalized)
                except (httpx.HTTPError, ValueError, OSError) as exc:
                    print(f"跳过 {item['id']}: {type(exc).__name__}")
                    continue
                description = unescape(re.sub('<[^>]+>', ' ', item.get('description') or ''))[:5000]
                records.append({'id': str(item['id']), 'title': item['title'], 'artist': item.get('artist_display') or 'Unknown',
                    'date': item.get('date_display'), 'medium': item.get('medium_display'), 'description': description,
                    'url': f"https://www.artic.edu/artworks/{item['id']}", 'image_url': url,
                    'license': 'Image: public domain; metadata: CC0; description: CC BY 4.0, Art Institute of Chicago (HTML removed)', 'image_path': str(path.relative_to(DATA))})
                vectors.append(vec)
                print(f'{len(records)}/{args.limit}: {item["title"]}')
                if len(records) >= args.limit:
                    break
                time.sleep(0.15)
            page += 1
            if page > body.get('pagination', {}).get('total_pages', page):
                break
    if not vectors:
        raise SystemExit('没有获得有效图片；未创建索引。请检查网络或查询条件。')
    np.save(DATA / 'vectors.npy', np.stack(vectors))
    (DATA / 'index.json').write_text(json.dumps({'model': args.model, 'records': records}, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'完成，共 {len(records)} 幅作品。请重启 ArtLens。')

if __name__ == '__main__':
    main()
