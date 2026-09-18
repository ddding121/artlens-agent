# ArtLens 0.1.5 多馆藏增量导入

本补丁基于已安装的 0.1.4 和前续导入修复。包含最新 import_famous 大图处理函数，保留 .env、.venv、data，无需安装新依赖。先停止服务和所有导入进程，备份项目，再合并补丁并替换同名文件。

## 已实现的来源适配器

| 代码 | 来源 | 当前筛选范围 |
|---|---|---|
| met | The Metropolitan Museum of Art | API 绘画搜索候选，且公开领域标记为真、有主图 |
| aic | Art Institute of Chicago | Painting、公有领域、有图片 |
| cma | Cleveland Museum of Art | Painting、CC0、有 web 图片 |

这是开放数据可接入范围，不是世界排名前三，也不代表全馆已下载。卢浮宫、大英博物馆、故宫、冬宫等尚未直接接入。跨馆作品与不同版本需要来源核对；跨来源同一作品没有自动语义去重，同馆ID会去重。

## 先检查，再下载

```bat
.venv\Scripts\python -m scripts.import_museums --check
```

只请求每馆第一页候选，检查前30条并尝试一张合格图片；不加载 CLIP，不写索引，不保证全馆批次后续都能成功。check_ok 表示单样本接口和图片通过；check_failed 或前30条无合格图片都不能当作已验证。

先小批量：

```bat
.venv\Scripts\python -m scripts.import_museums --sources met aic cma --limit 20
```

稳定后继续每馆最多新增500幅：

```bat
.venv\Scripts\python -m scripts.import_museums --sources met aic cma --limit 500
```

limit 是本次每馆新增上限，不是全库总量或馆藏保有量。已存在条目不占新增配额，重复执行会继续找未入库作品。每馆默认最多扫描10000条，来源耗尽或扫描上限可能使新增不足目标。数据分页变化不保证同一顺序，但ID去重避免同馆重复。

如果某一馆被403拒绝或超时，可以单独运行其他来源，例如：

```bat
.venv\Scripts\python -m scripts.import_museums --sources aic cma --limit 500
```

运行结束再重启原 uvicorn 命令，浏览器 Ctrl+F5。health 版本为0.1.5。现有名画和馆藏保留，不重新计算旧向量。不要同时运行名画导入、博物馆导入或旧 build_index。

## 结果与恢复

报告为 data/museum-import-时间.jsonl，每条记录明确 imported、already_present、ineligible、failed 或 source_failed。每馆结束显示新增和扫描数量，最终显示全库总量。部分失败时退出码1，成功作品仍然保留。

每新增一幅以独立向量文件和原子清单替换方式提交；备份 index.backup-museums-时间.json 及其引用的向量保留。本次运行产生的过渡向量在成功替换后删除。不要删除任何备份引用的 vectors*.npy。可把指定备份复制为 index.json 后重启恢复。

图片先选较小版本：Met primaryImageSmall、AIC IIIF 843、CMA web；下载仍设80MB及1.2亿像素上限，并缩至最长边1600。下载仅允许指定馆藏图片域名，最多3次受限域内重定向。403不会绕过；动态CDN域名变化须核对后更新适配器。

## 许可和限制

Met 仅收录 isPublicDomain；CMA 仅 CC0；AIC 图片依公有领域标记，description CC BY 4.0（保留署名，去除HTML），其他元数据CC0。作者前后限定词尽量保留，如 Possibly by，不能将候选归属改成确定作者。

不包含已下载馆藏图片。脚本和官方API文档不等于完成真实导入；不宣称500幅/馆一定成功、不宣称识别准确率提高。多馆藏只扩大候选范围，仍需模型验证和独立评估。

## 验证状态

39项Python测试通过，JS语法检查通过，包括来源字段映射、许可过滤、数字ID兼容、新ID路由、域名限制、增量追加和重复执行不覆盖旧作品。模型和多馆藏导入行为测试使用替身，未下载真实大规模馆藏。当前环境Met联网返回403，CMA超时；需在用户网络执行 --check。没有浏览器视觉测试。

官方文档：
- https://metmuseum.github.io/
- https://api.artic.edu/docs/
- https://openaccess-api.clevelandart.org/
