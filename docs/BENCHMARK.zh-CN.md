# ArtLens 完整识别评测

## 安装与快速运行

把更新包的 scripts、tests、docs 合并到项目根目录。无需重建图库，无需额外依赖。
保留原来的服务终端运行（http://127.0.0.1:8000），在项目目录另开一个终端。

生成最多5幅作品各自的原图与中心裁剪，共最多10张：

```bat
.venv\Scripts\python -X utf8 -m scripts.benchmark prepare --count 5
.venv\Scripts\python -X utf8 -m scripts.benchmark run evaluation/smoke/queries.jsonl
```

run 会逐图调用现有分析接口，图片发送给当前配置的视觉模型，会使用API额度。prepare 只在本地生成图片。
请勿在评测中途导入图库、更改模型或阈值。首次模型加载也计入请求耗时。
生成目录已存在时不会覆盖；要重新抽样可用 --seed 43 --output evaluation/smoke-2。
工具固定连接本机8000端口，不使用系统代理访问本地服务。

## 输出

终端给出报告路径，默认 evaluation/run-时间/：

- report.md：中文汇总。
- report.json：指标、按 group 分组结果、逐图核验结果和警告。
- results.jsonl：每个完成请求后的增量记录。

接口错误与讲解失败分别记录。只有 likely_match 视为确认匹配，candidate 和 unknown 计为未确认。
已知作品指标以已完成请求的已知样本为分母；库外误认率以已完成请求的库外样本为分母。
无对应样本时显示无样本，不输出虚假的0%或100%。不能仅看正确率而忽略错误数量。
Ctrl+C 后保存已经完成的部分报告，report.json 的 interrupted 为 true。不支持自动续跑；重跑会重新请求所有样本。

## 独立评测集

自动生成的是图库原图及其派生裁剪，仅适合回归检查，不应在申请材料中写成真实世界准确率。
独立评测请自行准备手机拍摄、不同裁剪、不同光照和库外作品，逐行编辑 UTF-8 JSONL 清单：

```json
{"image":"photos/a.jpg","expected_ids":["cma_135428"],"group":"phone","dataset":"independent"}
{"image":"photos/b.jpg","expected_ids":[],"group":"unknown","dataset":"independent"}
```

以上仅为格式示例，必须以实际照片身份和 data/index.json 中的ID为准。路径相对于清单文件所在目录。
同一作品若有多个跨馆或重复条目，把所有可接受ID列入 expected_ids。未知样本必须人工核查，不能因为单次未识别就标成库外。
测试集与调阈值的验证集按作品划分，同一作品的不同裁剪不应跨集合。固定测试集后不要据测试成绩反复改阈值。

运行自定义集：

```bat
.venv\Scripts\python -X utf8 -m scripts.benchmark run evaluation/independent/queries.jsonl
```

报告保存了服务版本、图库数量、清单SHA256和测试类型。复现实验还需自行记录视觉模型名称、CLIP模型、阈值和图库版本（不要发布API Key）。
该工具不评价讲解的事实正确性；事实引用、观察和解释需要另行人工评审。

## 本次验证范围

4项本地自动测试通过：指标分母及ID别名、模拟接口请求与会话释放、标签缺失校验、原图裁剪生成及防覆盖。
未使用用户的实际图库或付费模型测出识别分数；真实评测需在用户机器运行。
