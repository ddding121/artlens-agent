"""OpenAI 兼容的视觉接口。图片只发往用户配置的服务端地址。"""
import base64
import os
import httpx


class ModelUnavailable(Exception):
    pass


def configured():
    return all(os.getenv(k, '').strip() for k in ('VISION_API_KEY', 'VISION_BASE_URL', 'VISION_MODEL'))


async def complete(system, text, image=None, history=None):
    if not configured():
        raise ModelUnavailable('尚未配置视觉模型。请在 .env 中填写 VISION_API_KEY、VISION_BASE_URL 和 VISION_MODEL，然后重启。')
    content = [{'type': 'text', 'text': text}]
    images = image if isinstance(image, (list, tuple)) else ([image] if image else [])
    for image in images:
        content.append({'type': 'image_url', 'image_url': {'url': 'data:image/jpeg;base64,' + base64.b64encode(image).decode()}})
    messages = [{'role': 'system', 'content': system}]
    messages.extend(history or [])
    messages.append({'role': 'user', 'content': content})
    async with httpx.AsyncClient(timeout=90) as client:
        try:
            response = await client.post(os.environ['VISION_BASE_URL'].rstrip('/') + '/chat/completions',
                headers={'Authorization': 'Bearer ' + os.environ['VISION_API_KEY']},
                json={'model': os.environ['VISION_MODEL'], 'messages': messages, 'temperature': 0.2, 'max_tokens': 1800})
            response.raise_for_status()
            answer = response.json()['choices'][0]['message']['content']
            if not isinstance(answer, str) or not answer.strip():
                raise ValueError('empty response')
            return answer
        except httpx.HTTPStatusError as exc:
            raise ModelUnavailable(f'模型服务返回 HTTP {exc.response.status_code}，请检查模型名称、密钥、地域和余额。') from exc
        except (httpx.HTTPError, KeyError, ValueError, IndexError) as exc:
            raise ModelUnavailable('模型请求失败或返回格式不兼容，请检查网络及接口配置。') from exc
