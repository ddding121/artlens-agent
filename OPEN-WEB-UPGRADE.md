# ArtLens 开放识别 v0.2.0

## 本次升级

- 保留本地 CLIP 检索、双图核验、人工核验和连续追问。
- 本地身份为 `unknown` 时，自动调用 Google Cloud Vision Web Detection。
- 新增“联网候选 · 身份未确认”状态。
- 官方博物馆、国家美术馆、Wikimedia 等来源优先排序。
- 搜索标签仅作为线索，不能冒充已确认的作品名或作者。
- 相同图片按 SHA-256 缓存，默认每天最多联网查询 50 次。
- Google 请求失败、达到上限或未配置时，自动退回原有画面分析。

## 安装

将升级包解压到原项目根目录并允许覆盖同名文件，然后执行：

```bat
cd /d D:\artline-agent\artlens-agent
.venv\Scripts\python -m pip install -r requirements.txt
```

确认 `.gitignore` 至少包含：

```text
google-vision-key.json
```

在项目根目录的 `.env` 末尾加入：

```text
WEB_SEARCH_ENABLED=1
WEB_SEARCH_DAILY_LIMIT=50
GOOGLE_APPLICATION_CREDENTIALS=D:/artline-agent/artlens-agent/google-vision-key.json
```

重新启动本地服务后，页面底部的服务状态应显示“联网识别：已启用”。

## 测试建议

先上传图库内作品，确认原有馆藏匹配不受影响；再上传一张图库外画作，确认出现联网候选、最佳猜测、相关实体和网页来源。

## 部署说明

不要将 JSON 密钥提交到 GitHub。公开部署时应使用平台环境变量 `GOOGLE_SERVICE_ACCOUNT_JSON` 保存完整服务账号 JSON，并继续设置 `WEB_SEARCH_ENABLED=1` 与调用上限；部署阶段再单独配置。
