"""图像校验、可选 CLIP 检索与保守识别策略。"""
import io
import json
from pathlib import Path
import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data'
Image.MAX_IMAGE_PIXELS = 20_000_000


def decode_image(raw: bytes):
    if not raw or len(raw) > 10 * 1024 * 1024:
        raise ValueError('请上传不超过 10 MB 的图片。')
    try:
        with Image.open(io.BytesIO(raw)) as src:
            if src.format not in {'JPEG', 'PNG', 'WEBP'}:
                raise ValueError('仅支持 JPEG、PNG、WebP。')
            if src.width * src.height > 20_000_000:
                raise ValueError('图片不得超过 2000 万像素。')
            im = ImageOps.exif_transpose(src).convert('RGB')
            im.thumbnail((1600, 1600))
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError('文件不是有效图片，或图片尺寸过大。') from exc
    out = io.BytesIO()
    im.save(out, format='JPEG', quality=90)
    return im, out.getvalue()


def choose_identity(candidates, minimum, margin):
    """阈值只筛选候选，不将余弦相似度解释为正确概率。"""
    if not candidates or minimum is None or margin is None or len(candidates) < 2:
        return 'unknown'
    if candidates[0]['score'] >= minimum and candidates[0]['score'] - candidates[1]['score'] >= margin:
        return 'candidate'
    return 'unknown'


class Retriever:
    def __init__(self):
        self.model = self.processor = None
        self.records = []
        self.vectors = None
        self.model_id = None

    def load(self):
        manifest = DATA / 'index.json'
        if not manifest.exists():
            return False
        import torch
        from transformers import CLIPModel, CLIPProcessor
        doc = json.loads(manifest.read_text(encoding='utf-8'))
        self.model_id = doc['model']
        self.records = doc['records']
        vector_file = doc.get('vectors_file', 'vectors.npy')
        if not isinstance(vector_file,str) or Path(vector_file).name != vector_file or not vector_file.endswith('.npy'):
            raise ValueError('无效向量文件名')
        self.vectors = np.load(DATA / vector_file, allow_pickle=False)
        if len(self.records) != len(self.vectors):
            raise ValueError('索引不一致，请重新构建。')
        self.model = CLIPModel.from_pretrained(self.model_id)
        self.model.eval()
        self.processor = CLIPProcessor.from_pretrained(self.model_id)
        return True

    def encode(self, image):
        import torch
        with torch.inference_mode():
            inputs = self.processor(images=image, return_tensors='pt')
            vector = self.model.get_image_features(**inputs)
            # transformers 4.x 返回 Tensor；本项目锁定兼容范围。
            vector = vector / vector.norm(dim=-1, keepdim=True)
        return vector.cpu().numpy()[0]

    def search(self, image, k=5):
        if self.vectors is None and not self.load():
            return []
        scores = self.vectors @ self.encode(image)
        ids = np.argsort(-scores)[:k]
        return [{**self.records[int(i)], 'score': round(float(scores[i]), 5)} for i in ids]
