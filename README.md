# Smart LLM Router

[![CI](https://github.com/kmwhat/smart-llm-router/actions/workflows/ci.yml/badge.svg)](https://github.com/kmwhat/smart-llm-router/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

Development candidate 0.6.0rc3 adds a controlled task descriptor v2, cache isolation,
and strict JSON output validation on top of the 0.6.0rc2 evidence-backed task contracts,
adapter lifecycle governance, goal-locked workflow planning, quality-band free-first role routing,
ledger-derived route health, golden-set promotion gates, multimodal provider registration, privacy and per-call/workflow budget gates, built-in list-price estimates, and safe
loading from an optional credential catalog selected with
`SMART_LLM_CREDENTIAL_CATALOG`. Secret values remain local and in process
memory; provider/status output never prints them.

The July 7 Hermes Router Hub skillpack is treated as a governance protocol, not
as a replacement for this router's real provider adapters. Its dry-run server
remains a compatibility test surface only.

## 公共核心边界

本仓库只提供通用路由、治理、模态适配和成本控制能力，不内置任何特定行业的
术语表、纠错规则、用户资料或业务提示词。垂直领域集成应在私有调用层通过
`--domain`、任务上下文或独立技能封装注入，并与公共发行包分开维护。

```bash
smart-llm-router providers
smart-llm-router capabilities --configured-only
smart-llm-router contract-plan examples/task_contract.example.json --receipt-dir ./route-receipts
smart-llm-router adapter-lifecycle examples/adapter_declaration.example.json examples/adapter_transition.example.json
smart-llm-router workflow-plan examples/workflow_contract.example.json
```

任务契约会严格校验任务族和敏感度。`internal_summary` 只有同时声明
`sanitized_for_external=true` 与 `external_processing_approved=true` 才允许云端路线；
`internal_raw` 和 `secret` 继续失败关闭。路由回执使用稳定契约指纹关联任务，
并可记录 route alias、真实 fallback chain、ledger id，以及经过物化门校验的
输出路径、大小和 SHA-256。`production_changed` 必须由执行方依据真实变更显式提供，
不能仅凭执行模式自动推断。

适配器生命周期使用 `discovered -> shadow -> candidate -> qualified -> production -> retired`
六态治理。`shadow -> candidate` 需要 canary 和最小健康证据；
`candidate -> qualified` 需要与适配器匹配且已通过的 `promotion-check` 决策；
`qualified -> production` 还需要 owner 批准、smoke test 和回滚方案。
降级和退役不被晋级证据门阻塞。命令只生成带指纹的迁移回执，
不会自动改写 provider 注册表、角色质量档或生产默认。
显式传入 `--state-dir` 时，工具会在私有运行态中原子保存全部迁移回执，
并且只在 PASS 后更新适配器声明；目录和文件权限分别收紧为 `0700` 与 `0600`。
运行态不进入公共源码仓。
持久化成功的 PASS 回执使用 `next_action=state_change_persisted`，并在落盘回执中
记录对应的私有声明与回执路径。
当声明位于当前运行目录的 `adapter-lifecycle/adapters` 时，已声明路线只有
`qualified` 或 `production` 才进入实际推荐和执行池；未纳入生命周期的旧路线保持兼容。

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
- 隐私与预算门：私人图片、聊天记录、身份信息和原始音视频默认 `local_only`；`--max-cost-usd` 下未知价格的付费模型失败关闭。
- 多模态路由预演：`route-plan` 会先输出任务描述器、本地步骤、免费池、低价付费和 Codex 审计路线，不调用模型。
- Provider-family 能力注册表：`capabilities` 会区分“供应商 API key 已知可支持的模型态”和“当前已配置、已探活、可执行路由的具体模型”，覆盖文本、视觉/OCR、ASR、图像/视频生成、embedding、rerank、code 等。
- 转写稿分块纠错：`transcript-correct` 会把长篇 ASR 文本分块修正并落盘，避免编排层加载整份原始转写稿。
- 免费池优先：优先尝试免费模型，失败自动换下一个。
- 视觉模型路由：支持本地图片 `--image`，自动转换为 OpenAI-compatible 多模态消息。
- 视觉图片压缩：发送前自动压缩为适合 API 的 JPEG，避免手机原图上传超时。
- 失败冷却：429、超时、403、空返回会进入冷却，下次跳过。
- 免费池全冷却自救：调用前轻量探活，避免误入付费。
- 角色路线同时考虑任务专长与成本：DeepSeek V4、Qwen 3.7、GLM-5.2、Kimi K3、Gemini Free Tier 和 Doubao Seed 2.1/2.0 分工协作。
- 本地复杂度评分：先判断 `simple`、`medium`、`hard`，简单任务默认禁用付费兜底。
- 成本/调用账本：记录每次模型调用、失败和缓存命中，便于后续调优。
- 历史健康真值面：`route-stats` 按任务/provider/model 汇总成功率、失败类型、P95 延迟和观测成本；明确的本地基础设施故障不计入模型失败率。
- 模型晋级门：`golden-eval` 用任务黄金集对比候选与基线并生成盲审包；`promotion-check` 结合案例、成本、健康样本和独立第三家盲审，只输出可登记资格，不自动修改生产角色表。
- 通用 QA 候选使用公开、确定性的 `examples/golden-sets/qa-public-v1.json`，五项硬门必须全部通过；该筛选不替代生产角色所需的基线和独立盲审。
- 响应缓存：相同任务和上下文命中本地缓存，避免重复花 token。
- 本地检索前置：可从本地 `txt/md` 资料目录检索相关片段，再注入模型上下文。
- 动态模型发现：OpenRouter、NVIDIA、Groq 候选目录默认每 6 小时按需刷新，单家发现失败会保留上次清单；OpenRouter/NVIDIA 同时发现视觉候选。
- 发现不等于生产晋级：新免费模型可进入通用任务池，规划、执行、审计和复验仍须通过基准测试并登记质量档。
- 按模态健康检查：`refresh-modalities` 会分别用 text/vision/OCR/transcript/code 小探针验证模型，而不只用通用 QA。
- 可迁移：`.env` + 本目录即可复制到其他电脑。

## 安装

从当前 GitHub 预发布包安装：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install "https://github.com/kmwhat/smart-llm-router/releases/download/v0.6.0rc2/smart_llm_router-0.6.0rc2-py3-none-any.whl"
smart-llm-router --help
```

从源码安装并参与开发：

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

公开快速入口只展示路由器本身：配置检查、路线建议、执行、健康状态和审计账本。
供应商专用或外围适配器命令不作为常用命令发布；需要时请从 `--help` 按能力查找。

```bash
smart-llm-router --help
smart-llm-router providers
smart-llm-router capabilities --configured-only
smart-llm-router recommend "Return OK" --task qa --free-only
smart-llm-router route-plan "Return OK" --task qa --quality-target production
smart-llm-router task "Return OK" --task qa --free-only
smart-llm-router maintain --limit 8
smart-llm-router status
smart-llm-router ledger --limit 20
smart-llm-router route-stats --task qa --limit 1000
```

正常的 `recommend`、`route-plan` 和 `task` 会在免费模型目录过期时按需发现新候选。可用
`SMART_LLM_AUTO_DISCOVER_FREE=false` 关闭，或用 `SMART_LLM_DISCOVERY_TTL_HOURS` 调整刷新周期；
`maintain` 仍用于重要任务前的完整“发现 + 分模态探活”。

实验性任务描述器 v2 默认关闭。显式设置
`SMART_LLM_TASK_DESCRIPTOR_V2_ENABLED=true` 后，它只影响非角色任务的复杂度标签；
`plan`、`execute`、`audit`、`verify`、`quality_enhance` 仍保持原角色质量档。
删除该变量或设为 `false` 即回退，隐私、生命周期、健康、预算和 `quality_target` 门不变。
当任务明确要求严格 JSON 时，响应必须可被本地 JSON 解析器直接读取；Markdown 围栏等不合格输出不会缓存或返回，
路由器会尝试下一条合格路线，全部不合格则失败关闭。

最小执行验证：

```bash
smart-llm-router task "Return OK" --task qa --free-only
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

选择顺序固定为：隐私与模态硬门槛 -> `quality_target` 最低角色档（`draft=2`、`production=3`、`audit=4`、`frontier=4`）-> 当前冷却/额度和历史路线健康 -> 预算资格 -> 免费优先 -> 按平滑成功率修正的预计总成本 -> 成功调用 P95 延迟 -> 更高质量余量 -> 角色预设顺序 -> Provider 优先级。至少 3 个非基础设施健康样本且成功率低于 50% 才标记为退化；明确的本地基础设施故障单列，不污染模型成功率。只要达到任务要求的质量下限，健康免费模型可以压过更高但不必要的付费档；低于下限或未登记的模型不会进入角色路线。没有合格角色模型时明确失败关闭，不回退到通用池。每个阶段只执行一个主模型，失败才按候选顺序切换；规划审核和最终复验属于独立治理关卡，不算重复执行。

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

公共模板把免费层与付费层分开配置。免费层只处理公开、非敏感内容；任何付费路线都必须显式启用并受预算门约束。

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

外围适配器和供应商专用操作不属于公开快速入口。它们保留向后兼容，但必须通过
`smart-llm-router --help` 显式发现，并继续受隐私、付费许可、健康和生命周期门约束。

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
- `route-stats` 完全本地读取账本，不调用模型、不读取或输出 API key；可用它判断某个任务路线是配额退化、端点失效还是仅遇到本地基础设施故障。
- `promotion-check` 完全本地运行；黄金集文件禁止携带 API key、令牌、密码或私钥字段，公开套件和私有套件必须按隐私边界分开保存。
- `simple` 任务在默认模式下只走免费池；免费池不可用时会报错，不直接烧付费模型。
- `medium` 和 `hard` 任务仍免费优先，免费池失败后才按低价付费兜底。
- 专用能力必须独立通过配置、健康、隐私和费用许可检查，不能因某个 Provider 已配置就推断其全部模型态可用。
- 未经验证的 endpoint、模型名或占位资源不得进入生产路由。

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

1. 复制整个 `smart-llm-router` 项目目录。
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
