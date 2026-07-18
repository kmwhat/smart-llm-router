# Smart LLM Router

[![CI](https://github.com/kmwhat/smart-llm-router/actions/workflows/ci.yml/badge.svg)](https://github.com/kmwhat/smart-llm-router/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

Version 0.5.0rc1 adds goal-locked workflow planning, quality-band free-first role routing,
ledger-derived route health, golden-set promotion gates, multimodal provider registration, privacy and per-call/workflow budget gates, built-in list-price estimates, and safe
loading from an optional credential catalog selected with
`SMART_LLM_CREDENTIAL_CATALOG`. Secret values remain local and in process
memory; provider/status output never prints them.

The July 7 Hermes Router Hub skillpack is treated as a governance protocol, not
as a replacement for this router's real provider adapters. Its dry-run server
remains a compatibility test surface only.

```bash
smart-llm-router providers
smart-llm-router capabilities --configured-only
smart-llm-router contract-plan task-contract.json --receipt-dir ./route-receipts
smart-llm-router workflow-plan examples/workflow_contract.example.json
```

一个可移植的智能模型路由器：按任务和模态做成本/质量路由，免费池优先但不盲目免费，失败冷却、主动探活、低价付费兜底。适合给多个智能体、脚本、知识库项目复用。

源码可以放在任意工作目录。未显式设置 `SMART_LLM_RUNTIME_DIR` 时，
便携启动器优先使用：

```text
$XDG_STATE_HOME/smart-llm-router
$HOME/.local/state/smart-llm-router
```

## 能力

- 按任务选择模型：除基础任务外，增加 `plan`、`execute`、`audit`、`verify`、`quality_enhance` 五个生产角色。
- 防返工工作流：`workflow-plan` 固化“规划 -> 规划审查 -> 执行 -> 过程检查 -> 最终偏离复验”，`workflow-check` 在本地判定继续、复验、停止或完成。
- 旗舰质量链：规划、执行、跨厂商审计、独立复验、最终质量提升各自选择最合适模型；同模型换 Key 只算容灾，不算独立复验。
- 四档质量：`draft`、`production`、`audit`、`frontier` 分别要求角色质量档至少为 2、3、4、4。达到下限后再按健康、预算资格、免费、重试后预计成本、P95 延迟和质量余量排序。
- 隐私与预算门：敏感手相原图、微信聊天和身份信息默认 `local_only`；`--max-cost-usd` 下未知价格的付费模型失败关闭。
- 多模态路由预演：`route-plan` 会先输出任务描述器、本地步骤、免费池、低价付费和 Codex 审计路线，不调用模型。
- Provider-family 能力注册表：`capabilities` 会区分“供应商 API key 已知可支持的模型态”和“当前已配置、已探活、可执行路由的具体模型”，覆盖文本、视觉/OCR、ASR、图像/视频生成、embedding、rerank、code 等。
- 转写稿分块纠错：`transcript-correct` 会把课程 ASR 文本分块修正并落盘，避免 Codex 吞整节原始转写稿。
- 免费池优先：优先尝试免费模型，失败自动换下一个。
- 视觉模型路由：支持本地图片 `--image`，自动转换为 OpenAI-compatible 多模态消息。
- 视觉图片压缩：发送前自动压缩为适合 API 的 JPEG，避免手机原图上传超时。
- 失败冷却：429、超时、403、空返回会进入冷却，下次跳过。
- 免费池全冷却自救：调用前轻量探活，避免误入付费。
- 角色路线同时考虑任务专长与成本：DeepSeek V4、Qwen 3.7、GLM-5.2、Kimi K3、Gemini Free Tier 和 Doubao Seed 2.1/2.0 分工协作。
- 本地复杂度评分：先判断 `simple`、`medium`、`hard`，简单任务默认禁用付费兜底。
- 成本/调用账本：记录每次模型调用、失败和缓存命中，便于后续调优。
- 历史健康真值面：`route-stats` 按任务/provider/model 汇总成功率、失败类型、P95 延迟和观测成本；明确的本机 DNS/网络故障不计入模型失败率。
- 模型晋级门：`golden-eval` 用任务黄金集对比候选与基线并生成盲审包；`promotion-check` 结合案例、成本、健康样本和独立第三家盲审，只输出可登记资格，不自动修改生产角色表。
- 响应缓存：相同任务和上下文命中本地缓存，避免重复花 token。
- 本地检索前置：可从本地 `txt/md` 资料目录检索相关片段，再注入模型上下文。
- 动态模型发现：OpenRouter、NVIDIA、Groq 候选目录默认每 6 小时按需刷新，单家发现失败会保留上次清单；OpenRouter/NVIDIA 同时发现视觉候选。
- 发现不等于生产晋级：新免费模型可进入通用任务池，规划、执行、审计和复验仍须通过基准测试并登记质量档。
- 按模态健康检查：`refresh-modalities` 会分别用 text/vision/OCR/transcript/code 小探针验证模型，而不只用通用 QA。
- 可迁移：`.env` + 本目录即可复制到其他电脑。

## 安装

从 GitHub Release 安装候选版：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install \
  https://github.com/kmwhat/smart-llm-router/releases/download/v0.5.0rc1/smart_llm_router-0.5.0rc1-py3-none-any.whl
```

从源码安装：

```bash
git clone https://github.com/kmwhat/smart-llm-router.git
cd smart-llm-router
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
cp .env.example .env
```

把 API key 填入 `.env`。不要提交真实 key。详细申请地址和配置说明见 [`PROVIDER_SETUP.md`](https://github.com/kmwhat/smart-llm-router/blob/main/PROVIDER_SETUP.md)。

这个项目不自带任何 API key。谁使用，谁复制 `.env.example` 并填写自己的 key。

## 常用命令

```bash
smart-llm-router recommend "审计架构并设计多步骤优化方案" --task draft
smart-llm-router route-plan "规划、执行并审计系统升级" --task plan --quality-target frontier --paid-allowed --max-cost-usd 0.05
smart-llm-router discover-ark --limit 100
smart-llm-router route-plan "修正奇门课程转写稿" --task transcript_correct --domain qimen --quality-target production --paid-allowed
smart-llm-router transcript-correct /path/to/lesson.chunked.txt --domain qimen --paid-main --cross-check
smart-llm-router capabilities --configured-only
smart-llm-router maintain --limit 8
smart-llm-router refresh-modalities --tasks qa,vision,ocr,transcript_correct,code --limit 2
smart-llm-router refresh-modalities --tasks audit --families zhipu --include-paid --limit 1 --timeout 45
smart-llm-router refresh-modalities --tasks embed,rerank --families zhipu --include-paid --limit 1 --timeout 20
smart-llm-router embed "风水讲究形势与理气" --provider zhipu --model embedding-3 --dimensions 256
smart-llm-router rerank --query "风水气口" "风水重视气口与来龙" "今天适合整理文件" --provider zhipu --model rerank
smart-llm-router embed "风水讲究形势与理气" --provider qwen --model text-embedding-v4 --dimensions 256
smart-llm-router asr-status
smart-llm-router transcribe /path/to/video.mp4 --language zh
smart-llm-router remote-transcribe /path/to/audio.wav --provider zhipu --allow-external
smart-llm-router remote-transcribe /path/to/audio.wav --provider qwen --allow-external
smart-llm-router image-generate "水墨山水" --provider zhipu --allow-paid
smart-llm-router providers
smart-llm-router discover --limit 20
smart-llm-router discover-vision --limit 20
smart-llm-router refresh --timeout 6 --limit 8
smart-llm-router refresh-modalities --timeout 6 --limit 2
smart-llm-router status
smart-llm-router clear
smart-llm-router score "清洗 OCR：生命綫 深長" --task clean
smart-llm-router ledger --limit 20
smart-llm-router route-stats --task audit --limit 1000
smart-llm-router golden-eval examples/golden-sets/audit-public-v1.json --provider groq-free --model qwen/qwen3.6-27b --baseline-provider deepseek-direct-paid --baseline-model deepseek-v4-pro --allow-paid
smart-llm-router promotion-check /path/to/report.json --review /path/to/blind-review.json
```

正常的 `recommend`、`route-plan` 和 `task` 会在免费模型目录过期时按需发现新候选。可用
`SMART_LLM_AUTO_DISCOVER_FREE=false` 关闭，或用 `SMART_LLM_DISCOVERY_TTL_HOURS` 调整刷新周期；
`maintain` 仍用于重要任务前的完整“发现 + 分模态探活”。

执行任务：

```bash
smart-llm-router task "把这段 OCR 文本整理成要点" --task summarize --context "原文..."
smart-llm-router task "判断资料属于手相、八字还是风水" --task classify --context "标题和目录..."
smart-llm-router task "清洗 OCR：生命綫 深長，智惠线 分明" --task clean
smart-llm-router task "只输出 JSON：判断图片是否包含手掌" --task vision --image /path/to/hand.png --free-only
```

从本地资料目录先检索，再调用模型：

```bash
smart-llm-router task "总结手相中生命线的判断要点" \
  --task summarize \
  --retrieve-dir /path/to/vault \
  --retrieve-limit 5 \
  --max-context-chars 6000
```

只允许免费模型：

```bash
smart-llm-router task "只输出 OK" --task qa --free-only
```

允许付费候选，但同等能力仍由免费模型优先：

```bash
smart-llm-router task "生成高质量草稿" --task draft --paid
smart-llm-router task "制定可验收的升级方案" --task plan --quality-target frontier --paid --max-cost-usd 0.05
```

生产质量链的默认职责：

| 阶段 | 优先专长 | 主要候选 |
|---|---|---|
| 规划 | 约束、架构、验收设计 | Qwen 3.7 Max、Kimi K3、Doubao Seed 2.x |
| 执行 | 长链路工程和代码落地 | GLM-5.2、DeepSeek V4 Pro、Doubao Seed 2.0 Code |
| 审计 | 跨厂商找错与风险覆盖 | Gemini 2.5 Pro Free Tier、DeepSeek V4 Pro、Qwen 3.7 Max |
| 复验 | 不继承主结论重新核对 | Gemini 2.5 Pro Free Tier、DeepSeek V4 Pro、Doubao Seed 2.x；公开草稿可用 Groq GPT-OSS 120B（二档、试用额度） |
| 提质 | 保持事实边界的最终收束 | Kimi K3、Qwen 3.7 Max、GLM-5.2 |
| 多模态支线 | 图片理解、OCR、图文联合推理 | Gemini 2.5 Pro Free Tier、Doubao Seed 2.0 Pro、Kimi K3 |

选择顺序固定为：隐私与模态硬门槛 -> `quality_target` 最低角色档（`draft=2`、`production=3`、`audit=4`、`frontier=4`）-> 当前冷却/额度和历史路线健康 -> 预算资格 -> 免费优先 -> 按平滑成功率修正的预计总成本 -> 成功调用 P95 延迟 -> 更高质量余量 -> 角色预设顺序 -> Provider 优先级。至少 3 个非基础设施健康样本且成功率低于 50% 才标记为退化；明确的本机 DNS/网络故障单列，不污染模型成功率。只要达到任务要求的质量下限，健康免费模型可以压过更高但不必要的付费档；低于下限或未登记的模型不会进入角色路线。没有合格角色模型时明确失败关闭，不回退到通用池。每个阶段只执行一个主模型，失败才按候选顺序切换；规划审核和最终复验属于独立治理关卡，不算重复执行。

健康证据只说明 endpoint 最近是否可调用，不等于回答质量。动态发现的新模型仍须通过任务探针、黄金集与独立复核，才能登记进 `plan`、`execute`、`audit`、`verify` 或 `quality_enhance` 的角色质量档。

### 模型晋级门

生产角色晋级分为四道独立证据门：至少 3 个同任务真实健康样本、候选黄金集通过率、相对当前基线不退步、与候选及基线都不同家族的盲审。运行示例：

```bash
smart-llm-router golden-eval \
  examples/golden-sets/audit-public-v1.json \
  --provider groq-free \
  --model qwen/qwen3.6-27b \
  --baseline-provider deepseek-direct-paid \
  --baseline-model deepseek-v4-pro \
  --output-dir ./runtime/golden-evaluations \
  --allow-paid

smart-llm-router promotion-check \
  /path/to/report.json \
  --review /path/to/blind-review.json
```

`golden-eval` 在实测期间关闭响应缓存，逐题写入原有调用账本。执行采用分级止损：候选先过调用完整性、确定性通过率和成本门，才调用付费基线；候选对基线不退步后，才值得调用第三家盲审。完整路线会生成 `report.json`、不暴露 A/B 身份的 `blind-review-packet.json` 和审查模板。`promotion-check` 完全本地运行；`pass` 只表示候选有资格由维护者显式登记到建议质量档，`hold` 表示继续留在普通池。任何结果都不会自动改写 `ROLE_QUALITY_BANDS`。

项目内置四套公开、无密钥黄金集：`audit-public-v1`、`plan-public-v1`、`execute-public-v1`、`verify-public-v1`。2026-07-18 的扩展实测中，OpenRouter Nemotron Ultra 规划候选因空响应 HOLD，OpenRouter Qwen3 Coder 执行候选因 429 HOLD；Groq `openai/gpt-oss-120b` 在复验集与 DeepSeek V4 Pro 基线均为 5/5，并经 Gemini 第三家盲审达到 3 胜 1 平 1 负，已显式登记为 `verify` 二档。它仍是 `trial_quota`，只在同档内免费优先，不越级替代三/四档高风险复验模型。

当前 `GEMINI_API_KEY` 按 `trial_quota` 管理，Gemini 付费 Provider 默认关闭。免费层只用于 `external_allowed` 的公开、非敏感内容，因为额度较低，且免费层提交内容可能用于 Google 产品改进。重新开通付费后，必须显式设置 `SMART_LLM_GEMINI_PAID_ENABLED=true`。

### 防返工工作流

真正的节约先减少错误规划和方向漂移，再考虑模型单价。工作流默认是 dry-run，不调用模型：

```bash
smart-llm-router workflow-plan \
  examples/workflow_contract.example.json \
  --output-dir ./runtime/workflows

smart-llm-router workflow-check \
  examples/workflow_contract.example.json \
  examples/workflow_checkpoint.example.json \
  --output-dir ./runtime/workflows
```

`workflow-plan` 同时检查工作流总预算、单阶段预算、规划与规划审查是否使用独立模型家族、执行与最终复验是否独立，以及 Hermes 无人值守安全门。过程检查点出现范围变化、证据缺失、验收项失败或未知、目标对齐不确定时返回 `verify_required`；目标已偏离、预算超限或最终验收不完整时返回 `stop`。最终提质只在复验明确发现质量缺口时条件调用。真正模型执行继续复用现有 `task` 命令，每次只运行一个已批准阶段。

豆包在线推理、Coding Plan 和自建 Endpoint 是三条独立计费路线，模型名不能混用。当前账号已实测通过 `doubao-seed-2-0-pro-260215` 的文本和图片理解；`doubao-seed-2-1-pro` 公开别名在当前在线推理接口返回 404，处于自动冷却，不进入可执行路线。Seedream、Seedance、语音和多模态 embedding 暂先进入能力注册表，等待专用 adapter 和独立探针。

课程转写稿纠错，建议先规划再执行：

```bash
smart-llm-router route-plan "修正课程转写稿并保留老师判断链" \
  --task transcript_correct \
  --domain qimen \
  --quality-target production \
  --paid-allowed

smart-llm-router transcript-correct /path/to/lesson.chunked.txt \
  --domain qimen \
  --paid-main \
  --cross-check
```

这条路线遵守：

```text
本地 ASR -> 规则预清洗 -> 免费模型粗筛 -> 低价付费主修正 -> 第二模型交验 -> Codex 总控审计
```

`transcript-correct` 会输出：

- `*.local-clean.txt`：本地规则清洗稿。
- `*.corrected.md`：分块修正稿。
- `*.correction-report.json`：每块使用的 provider/model/ledger 和路线计划。

视觉模型快速实测：

```bash
smart-llm-router benchmark-vision /path/to/hand.png --timeout 12 --limit 8
```

`vision` 任务同样有动态换模型能力：会按 `SMART_LLM_TASK_ORDER_VISION` 或默认顺序先试免费视觉模型；某个模型 429、超时、403/404、不支持图片或空返回，会写入冷却状态并立即尝试下一个模型。免费视觉池全部失败后，才按成本策略进入付费兜底。

视觉图片压缩可通过环境变量调整：

```text
SMART_LLM_VISION_MAX_SIDE=1280
SMART_LLM_VISION_JPEG_QUALITY=82
```

## 定期巡检

macOS/Linux cron 示例，每 6 小时探活一次：

```cron
0 */6 * * * cd /path/to/smart-llm-router && .venv/bin/smart-llm-router refresh-modalities --timeout 6 --limit 2 >> ~/.smart-llm-router/refresh-modalities.log 2>&1
```

## 状态文件

默认在：

```text
~/.smart-llm-router/
```

包含：

- `llm_router_state.json`：失败冷却状态。
- `llm_pool_refresh_report.json`：最近一次探活报告。
- `llm_modality_refresh_report.json`：最近一次按任务/模态探活报告。
- `llm_free_model_quick_benchmark.json`：快速基准测试结果。
- `llm_vision_quick_benchmark.json`：视觉模型快速基准测试结果。
- `llm_cost_ledger.jsonl`：模型调用、失败、缓存命中的账本。
- `llm_response_cache.json`：响应缓存。
- `golden-evaluations/`：任务黄金集报告、盲审包和晋级证据；默认只保存在本机运行态。

## 成本控制策略

- `score` 命令完全本地运行，不调用模型。
- `route-stats` 完全本地读取账本，不调用模型、不读取或输出 API key；可用它判断某个任务路线是配额退化、端点失效还是仅遇到本机网络故障。
- `promotion-check` 完全本地运行；黄金集文件禁止携带 API key、令牌、密码或私钥字段，公开套件和私有套件必须按隐私边界分开保存。
- `simple` 任务在默认模式下只走免费池；免费池不可用时会报错，不直接烧付费模型。
- `medium` 和 `hard` 任务仍免费优先，免费池失败后才按低价付费兜底。
- 课程转写稿、知识抽取、生产级笔记这类大吞吐任务，优先用本地工具和低价模型处理，Codex 只做总控、抽检、结构审计和最终收束。
- 一个 provider key 可能覆盖多个模型态；配置应按 provider family + endpoint/model mode 登记。智谱、千问、豆包这类供应商要把文本、视觉/OCR、音频/ASR/TTS、图像/视频生成、embedding、rerank、code 分开登记、分开健康检查。`embed` 和 `rerank` 已有专用 adapter；未实现专用 adapter 的图像/视频/语音生成接口只进入 `capabilities`/`route-plan`，不进入真实 `task` 调用。
- DeepSeek 官方直连目前只登记文本/推理模型，不把同一个 Key 虚构成视觉、ASR、TTS、图像或视频权限。
- `remote-transcribe` 是隐私敏感的显式命令：没有 `--allow-external` 必须失败。课程和用户原始音频默认仍使用本地 Whisper。
- `image-generate` 会产生费用：没有 `--allow-paid` 必须失败。视频生成和 TTS 在异步/WebSocket 专用适配器通过前只保留为候选能力。
- 豆包/火山方舟除 API Key 外还可能需要具体 endpoint/resource id；占位 id 不能进入生产路由。
- `rerank` 分数是 provider-specific 的相对排序信号，不要把原始分数当成跨供应商通用的绝对相关阈值；生产检索要结合 top-k、来源类型、术语命中和二次证据过滤。
- 当前生产热路径：`embed` 默认优先千问 `text-embedding-v4`，再智谱 `embedding-3`；`rerank` 默认智谱 `rerank`。千问 `gte-rerank` adapter 已预留 DashScope 专用路径，但当前账号/服务探活返回 `AccessDenied`，保持软禁用直到权限开通并探活通过。

查看当前能力覆盖：

```bash
smart-llm-router capabilities
smart-llm-router capabilities --configured-only
```

`capabilities` 不输出 API key，只显示 provider family、模型态、任务类型、是否已配置以及 key 是否存在。
- 账本中的 token 和成本是估算值；如果 provider 返回 usage，会优先使用 provider usage。

本轮方法调研、候选评分和升级边界记录在 [`research/runs/20260718-adaptive-routing-method-scan`](research/runs/20260718-adaptive-routing-method-scan)。
- 付费模型价格可用环境变量补充，例如：

```text
SMART_LLM_PRICE_OPENROUTER_DEEPSEEK_FALLBACK_INPUT=0.07
SMART_LLM_PRICE_OPENROUTER_DEEPSEEK_FALLBACK_OUTPUT=0.28
```

价格单位是美元/百万 tokens。没有配置价格时，账本会记录 token 估算，但 `estimated_cost_usd` 为 `null`。

## 迁移到其他电脑

1. 复制 `tools/smart-llm-router` 目录。
2. 在新电脑创建虚拟环境并 `pip install -e .`。
3. 复制 `.env.example` 为 `.env`，填入新电脑可用的 key。
4. 运行 `smart-llm-router refresh --timeout 6 --limit 8`。
5. 运行 `smart-llm-router task "只输出 OK" --task qa --free-only`。

## 接入其他项目

Python 中可以直接调用：

```python
from smart_llm_router.config import load_settings
from smart_llm_router.router import run_llm_task

settings = load_settings("/path/to/.env")
result = run_llm_task(settings, task="summarize", prompt="总结", context="材料")
print(result.provider, result.model, result.content)
```

## 标准化分发

分享给同事时，请分享整个目录或 `smart-llm-router-portable.tar.gz`，但不要分享 `.env`。

标准包应包含：

- `.env.example`
- `PROVIDER_SETUP.md`
- `README.md`
- `smart_llm_router/`
- `codex-skill/smart-llm-router/SKILL.md`
- `examples/refresh.cron`

标准包不应包含：

- `.env`
- 任何真实 API key
- `.venv/`
- `__pycache__/`
- `*.egg-info/`

## License

Licensed under the [Apache License 2.0](LICENSE).
