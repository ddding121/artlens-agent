"""Google Web Detection 联网兜底。

只返回可核查的网页线索，不把搜索标签当成已经确认的作品身份。
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import threading
from copy import deepcopy
from datetime import date
from pathlib import Path
from urllib.parse import urlparse


OFFICIAL_DOMAINS = (
    'artic.edu', 'metmuseum.org', 'clevelandart.org', 'moma.org', 'nga.gov',
    'nationalgallery.org.uk', 'louvre.fr', 'museodelprado.es', 'rijksmuseum.nl',
    'getty.edu', 'tate.org.uk', 'guggenheim.org', 'whitney.org',
    'wikimedia.org', 'wikipedia.org', 'artsandculture.google.com',
)


def _truthy(value: str | None) -> bool:
    return (value or '').strip().lower() in {'1', 'true', 'yes', 'on'}


def configured() -> bool:
    """联网识别必须显式开启，防止公开部署后意外消耗额度。"""
    if not _truthy(os.getenv('WEB_SEARCH_ENABLED')):
        return False
    inline = os.getenv('GOOGLE_SERVICE_ACCOUNT_JSON', '').strip()
    credential_path = os.getenv('GOOGLE_APPLICATION_CREDENTIALS', '').strip()
    return bool(inline or (credential_path and Path(credential_path).is_file()))


def _host(url: str) -> str:
    try:
        parsed = urlparse(url)
        return parsed.hostname.lower() if parsed.scheme == 'https' and parsed.hostname else ''
    except ValueError:
        return ''


def _official(host: str) -> bool:
    return any(host == domain or host.endswith('.' + domain) for domain in OFFICIAL_DOMAINS)


def _plain_title(value: str) -> str:
    # Google 会在标题中加入 <b>；先去标签，再解码实体并限制长度。
    import re
    text = re.sub(r'<[^>]+>', '', value or '')
    return html.unescape(text).strip()[:240]


class WebDetector:
    def __init__(self):
        self._cache: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._day = date.today()
        self._calls = 0

    def _limit(self) -> int:
        try:
            return max(0, min(int(os.getenv('WEB_SEARCH_DAILY_LIMIT', '50')), 1000))
        except ValueError:
            return 50

    def _client(self):
        from google.cloud import vision

        inline = os.getenv('GOOGLE_SERVICE_ACCOUNT_JSON', '').strip()
        if inline:
            from google.oauth2 import service_account
            info = json.loads(inline)
            credentials = service_account.Credentials.from_service_account_info(info)
            return vision.ImageAnnotatorClient(credentials=credentials, transport='rest')
        return vision.ImageAnnotatorClient(transport='rest')

    def search(self, image: bytes) -> dict:
        digest = hashlib.sha256(image).hexdigest()
        with self._lock:
            cached = self._cache.get(digest)
            if cached:
                result = deepcopy(cached)
                result['cached'] = True
                return result
            today = date.today()
            if today != self._day:
                self._day, self._calls = today, 0
            limit = self._limit()
            if self._calls >= limit:
                return {'status': 'limit', 'reason': f'今日联网识别已达到 {limit} 次上限。',
                        'sources': [], 'entities': [], 'best_guess': [], 'cached': False}
            self._calls += 1

        try:
            from google.cloud import vision
            response = self._client().web_detection(
                image=vision.Image(content=image), timeout=60
            )
            if response.error.message:
                raise RuntimeError(response.error.message)
            web = response.web_detection
            best_guess = [x.label.strip() for x in web.best_guess_labels if x.label.strip()][:3]
            entities = [
                {'name': x.description.strip(), 'score': round(float(x.score), 4)}
                for x in web.web_entities if x.description.strip()
            ][:8]
            pages = []
            for page in web.pages_with_matching_images:
                host = _host(page.url)
                if not host:
                    continue
                if page.full_matching_images:
                    match_type, match_label = 'full', '发现完整匹配图片'
                elif page.partial_matching_images:
                    match_type, match_label = 'partial', '发现局部匹配图片'
                else:
                    match_type, match_label = 'related', '发现相关图片页面'
                pages.append({
                    'title': _plain_title(page.page_title) or host,
                    'url': page.url,
                    'domain': host,
                    'official': _official(host),
                    'match_type': match_type,
                    'match_label': match_label,
                    'source_kind': 'web',
                })
            order = {'full': 0, 'partial': 1, 'related': 2}
            pages.sort(key=lambda x: (not x['official'], order[x['match_type']], x['domain']))
            # 同一网页只保留一次，避免来源卡片重复。
            unique = []
            seen = set()
            for page in pages:
                if page['url'] not in seen:
                    unique.append(page)
                    seen.add(page['url'])
                if len(unique) == 5:
                    break
            result = {
                'status': 'candidate' if unique or best_guess or entities else 'no_match',
                'reason': '发现可供核查的联网线索。' if unique else '未发现可核查的匹配网页。',
                'best_guess': best_guess,
                'entities': entities,
                'sources': unique,
                'cached': False,
            }
        except Exception as exc:
            result = {'status': 'error', 'reason': f'联网识别暂不可用：{type(exc).__name__}。',
                      'best_guess': [], 'entities': [], 'sources': [], 'cached': False}
        with self._lock:
            # 错误不缓存，网络恢复后允许重试；其余结果按图片哈希复用。
            if result['status'] != 'error':
                self._cache[digest] = deepcopy(result)
                while len(self._cache) > 200:
                    self._cache.pop(next(iter(self._cache)))
        return result


detector = WebDetector()
