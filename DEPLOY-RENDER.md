# ArtLens Render 部署说明

公开免费版不上传 `data/`，使用 Google Web Detection 与已配置的视觉模型进行开放识别；本地版仍保留 790 幅馆藏、CLIP 检索和双图核验。

## 禁止上传

- `.env`
- `google-vision-key.json`
- `data/`
- `.venv/`
- 本地压缩包与评测输出

## Render 环境变量

`render.yaml` 已提供非敏感默认配置。创建服务时，还需在 Render 控制台填写以下 Secret：

- `VISION_API_KEY`：与本地 `.env` 完全相同
- `VISION_BASE_URL`：与本地 `.env` 完全相同
- `VISION_MODEL`：与本地 `.env` 完全相同
- `GOOGLE_SERVICE_ACCOUNT_JSON`：打开 `google-vision-key.json`，复制从 `{` 到 `}` 的完整内容

不要把上述值提交到 GitHub，也不要发送给他人。

## 云端行为

- 没有本地索引时不会安装或加载 PyTorch/CLIP，适合免费实例。
- 每张新图片最多触发一次 Web Detection；相同图片在进程存活期间复用缓存。
- 默认每日最多 50 次联网识别；达到上限后仍会进行视觉分析。
- `/api/health` 用作 Render 健康检查。
