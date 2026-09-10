# ArtLens Agent — 艺术鉴赏智能体

上传画作，检索候选馆藏，获得区分“画面观察 / 文献事实 / 可能解读”的中文回答。

**版本：0.1.0，本地研究原型。** 已实现图片上传、OpenAI 兼容视觉接口、可选 CLIP 图片检索、馆藏来源、保守未知判断和会话追问。未接入音乐；未训练自有模型；尚无真实识别准确率。它是有界工具工作流，尚不是模型自主规划任意工具调用的完整 agent。

## 1. Windows 11 启动

推荐 Python 3.11。在解压后的 `artlens-agent` 文件夹地址栏输入 `cmd`，回车，然后依次执行：

```bat
py -3.11 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
copy .env.example .env
.venv\Scripts\python -m uvicorn artlens.main:app --host 127.0.0.1 --port 8000
```

打开 http://127.0.0.1:8000 。终端保持开启。也可在环境安装好后双击 `run.bat`。如 8000 被占用，改成 `--port 8001` 并打开对应地址。

macOS / Linux 使用 `python3 -m venv .venv`，然后将命令中的 `.venv\Scripts\python` 替换为 `.venv/bin/python`。

## 2. 配置视觉模型

用记事本编辑 `.env`：

```dotenv
VISION_API_KEY=你自己的密钥
VISION_BASE_URL=服务商的OpenAI兼容接口根地址
VISION_MODEL=你已开通的支持图片输入的模型名称
MATCH_MIN_SCORE=
MATCH_MIN_MARGIN=
```

`VISION_BASE_URL` 应为文档给出的 API 根地址（通常以 `/v1` 结尾），不要填网页聊天地址，也不要在末尾添加 `/chat/completions`，程序会自动补齐。模型必须支持 `image_url` 和 base64 图片输入的 Chat Completions 接口。模型名、地域地址和密钥必须属于同一服务，具体以服务商控制台为准。配置后重启服务。文字模型的密钥或名称不一定能用于图片输入。

未配置时页面能打开、图片能读取，但会明确提示未配置，不生成虚假的 AI 回答。没有附带免费密钥。上传图片会发给所配置的服务商；API 可能收费。应用不会把密钥发送给前端。

## 3. 建立真正的图片检索

先停止正在运行的服务，再执行：

```bat
.venv\Scripts\python -m pip install -r requirements-retrieval.txt
.venv\Scripts\python -m scripts.build_index --limit 200
```

脚本先下载 CLIP 模型，再从芝加哥艺术博物馆查询有公有领域标记的绘画，下载图片并生成 `data/index.json` 与 `data/vectors.npy`。首次下载需要网络和磁盘空间；默认 CPU 可运行，不要求 CUDA。馆藏或模型下载失败时脚本会报告错误，不能把索引不存在当作识别成功。不要在服务运行时重建索引；构建完成再启动应用。

图像向量通过 CLIP 生成，归一化后使用 NumPy 余弦相似度进行 Top-5 检索。200 幅的原型无需引入独立向量数据库。该图库不是所有名画全集，也不代表所有地区艺术的均衡覆盖。

## 4. 身份判断的边界

- 默认不启用未经校准的匹配阈值；仍展示检索候选，但身份写“无法确认”。
- 在独立验证集选择阈值后填写 `MATCH_MIN_SCORE` 和 `MATCH_MIN_MARGIN`。
- 达到阈值也只标为候选，**不会标为已核验作者**。二次视觉核验是后续研究工作。
- 相似度不是正确概率；不进行真伪鉴定或估价。
- 候选作品的馆藏事实不等于上传图片身份已经确认。
- 模型仍可能违背提示词，来源级事实校验尚未实现，必须人工检查重要陈述。

## 5. 评估与申请材料

见 `docs/RESEARCH_PLAN.md`。提供可执行的检索评估脚本；不要在申请中填写未经实验得到的结果。

JSONL 查询文件，每行一个独立测试图像：

```json
{"image":"queries/photo-01.jpg","expected_id":"馆藏作品数字ID"}
{"image":"queries/original-01.jpg","expected_id":null}
```

`image` 相对于 JSONL 文件所在目录；同一作品的验证/测试变体应分组，未知作品不得存在于索引内。以下数值仅是命令语法示例，不能当推荐阈值：

```bat
.venv\Scripts\python -m scripts.evaluate queries.jsonl --min-score 0.9 --min-margin 0.05 --output evaluation.json
```

## 6. 测试

```bat
.venv\Scripts\python -m pip install pytest
.venv\Scripts\python -m pytest -q
```

测试覆盖图片校验、无密钥降级、未知判断、会话生命周期及用替身模型验证追问上下文。替身测试不代表真实模型调用已通过。此交付未执行真实视觉 API 或完整 CLIP 下载测试。

## 7. 上传 GitHub

在 GitHub 创建空仓库 `artlens-agent`，不要预先勾选 README。项目包含了 README、MIT LICENSE 和 `.gitignore`。在项目目录执行：

```bat
git init
git branch -M main
git add .
git status
```

确认 `.env`、`.venv`、`data` 没有出现在待提交列表，再执行：

```bat
git commit -m "feat: initial ArtLens research prototype"
git remote add origin https://github.com/ddding121/artlens-agent.git
git push -u origin main
```

如果已存在 origin，先 `git remote -v` 检查。不要随意替换其他项目的远程仓库。GitHub 公开源码不会自动运行 Python 服务，GitHub Pages 不能运行这个后端。

仓库 description：`An evidence-aware art interpretation prototype with visual retrieval, museum sources, and uncertainty-aware responses.`

## 8. 项目结构

- `artlens/main.py`：FastAPI 接口、图片处理流程和短期会话。
- `artlens/core.py`：图片校验、CLIP 检索和候选判断。
- `artlens/provider.py`：视觉模型接口适配。
- `artlens/static/`：无前端构建依赖的中文工作台。
- `scripts/build_index.py`：公开馆藏采集及向量索引。
- `scripts/evaluate.py`：Top-1、Top-5 和未知作品误匹配评估。
- `tests/`：核心行为测试。

会话只保存在进程内，最多 20 个，1 小时后过期，最近 10 条对话进入追问上下文；重启即丢失。清除图片将删除对应会话。过期内存项在下一次分析时清理。当前仅绑定本地地址；公网部署前还需要身份认证、请求体限制、频率限制和更严格的资源控制。上传后的 10 MB 检查不能替代网关的请求体上限。

## 数据与许可

源码 MIT 许可，不覆盖模型权重、馆藏数据或用户图片。下载脚本只收录 API 标记为公有领域的图片并保存来源。description 文本由芝加哥艺术博物馆提供，适用 CC BY 4.0（脚本去除了 HTML 标记），其他元数据依 API 说明适用 CC0；记录中保留该许可说明。发布数据集前仍应核对提供方条款。

- 芝加哥艺术博物馆 API：https://api.artic.edu/docs/
- CLIP 技术接口：https://huggingface.co/docs/transformers/model_doc/clip
- 模型卡：https://huggingface.co/openai/clip-vit-base-patch32
