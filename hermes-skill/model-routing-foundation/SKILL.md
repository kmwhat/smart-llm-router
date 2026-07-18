---
name: model-routing-foundation
description: Mandatory Hermes routing policy for choosing or delegating any model by task role, modality, privacy, quality, health, and budget.
---

# Model Routing Foundation

Hermes 必须把全局 Smart LLM Router 视为模型能力入口。任何 agent、skill、子任务或工具流程需要选择模型时，先生成路线，再调用模型。

## 唯一真源

- Launcher: `smart-llm-router`
- Project: `/path/to/smart-llm-router`
- Runtime: `SMART_LLM_RUNTIME_DIR` or the standard user state directory
- Credential catalog: optional `SMART_LLM_CREDENTIAL_CATALOG`

## 强制规则

1. 先判断任务角色、输入模态、隐私、风险、质量档位和预算。
2. 低风险批量任务先本地预处理、缓存和健康免费池；五个角色任务把 `draft=2`、`production=3`、`audit=4`、`frontier=4` 作为最低质量档。达标后按退化状态、预算资格、免费、重试后预计成本、成功调用 P95、质量余量、角色顺序和 Provider 优先级排序；无达标路线时失败关闭，不回退未登记通用模型。
3. `plan`、`execute`、`audit`、`verify`、`quality_enhance` 必须分开，不用一个模型包办所有阶段。
4. 每阶段只选择一个主模型；同模型换 API Key 只是容灾。规划审核必须独立于规划，最终复验必须独立于执行，不强制五阶段使用五家厂商。
5. 手相原图、微信聊天、身份信息和私有音视频默认 `local_only`，不得绕过隐私门。
6. 有预算时使用 `--max-cost-usd`；未知价格的付费模型失败关闭。
7. 子 agent 任务说明必须包含 `selected_route`、`fallback_route`、`quality_target`、`privacy` 和 `max_cost_usd`。
8. 非平凡生产任务必须先生成 `workflow-plan`：冻结目标和验收标准，规划审查通过后才能执行；范围变化必须进入 `workflow-check`。
9. `workflow-check` 返回 `verify_required` 或 `stop` 时不得自行忽略。最终交付只有在原始目标对齐且全部验收项为 `pass` 时才能完成。
10. 五角色是治理阶段，不是每个任务都调用五个模型；过程检查默认本地执行，只有漂移信号才花费独立复验模型。
11. 公共模板默认按 Gemini Free Tier 使用；未显式设置 `SMART_LLM_GEMINI_PAID_ENABLED=true` 时不得进入付费池。免费层仅处理公开、非敏感资料。
12. `quality_enhance` 是条件阶段，只有最终复验明确发现表达、清晰度或覆盖缺口时才调用。
13. OpenRouter/Groq 免费候选目录默认每 6 小时按需刷新；发现失败保留上次清单，429/超时/端点错误进入持久冷却并自动换候选。
14. “发现”不等于“生产晋级”：新模型只可进入低风险通用池；通过任务探针并登记角色质量档后，才可承担规划、执行、审计或最终复验。Groq 按限额试用池管理，不宣称永久免费。
15. 使用 `route-stats` 读取本地历史健康证据。至少 3 个非基础设施样本才可标记路线退化；明确的本机 DNS/网络故障单列，不降低模型健康。
16. API 调用成功只证明 endpoint 可用，不证明输出质量；未经任务黄金集、独立复核和显式质量档登记，不得把动态发现模型晋级为生产角色。
17. 动态发现模型要进入五个生产角色，必须先执行 `golden-eval`。候选硬门失败立即停止；候选通过后才调用付费基线，基线不退步后才由不同于候选和基线的第三模型家族盲审；最后执行 `promotion-check`。
18. `promotion-check` 的 `pass` 只表示有资格人工显式登记，Hermes 不得自动修改角色质量档。黄金集禁止保存 API key、令牌、密码、私钥或未经授权的原始私密资料。
19. 2026-07-18 已完成证据链的 `groq-free/openai/gpt-oss-120b` 可用于公开、低风险、草稿级 `verify` 二档；它属于 `trial_quota`，不得越级替代三/四档高风险复验模型。规划 Nemotron Ultra 与执行 Qwen3 Coder 本轮均为 HOLD，不得登记角色档。
20. `recommend`、`route-plan`、`workflow-plan` 和 `task` 必须共享同一质量下限与角色排序规则；规划结果和真实调用不得一套标准两种选择。

## 角色路线

- 规划：Qwen 3.7 Max；Kimi K3、已验证的 Doubao Seed 2.x 备选。
- 执行：GLM-5.2；DeepSeek V4 Pro、通过专用探针后的 Doubao Seed 2.0 Code 备选。
- 审计：公开任务优先 Gemini 2.5 Pro Free Tier；DeepSeek V4 Pro、Qwen 3.7 Max 备选。
- 复验：公开草稿可选已登记二档的 Groq GPT-OSS 120B；高风险任务优先选择未参与主执行的三/四档模型，不足时使用 DeepSeek V4 Pro 等独立家族。
- 提质：Kimi K3；Qwen 3.7 Max、GLM-5.2 备选。
- 多模态支线：公开、非敏感输入可优先 Gemini 2.5 Pro Free Tier；Doubao Seed 2.0 Pro、Kimi 作为付费或独立复核候选。

## 调用

```bash
smart-llm-router route-plan \
  "任务描述" --task plan --quality-target frontier --paid-allowed --max-cost-usd 0.05

smart-llm-router task \
  "任务描述" --task execute --quality-target production --paid --max-cost-usd 0.05

smart-llm-router workflow-plan \
  /path/to/workflow-contract.json \
  --output-dir ./runtime/workflows

smart-llm-router workflow-check \
  /path/to/workflow-contract.json /path/to/checkpoint.json \
  --output-dir ./runtime/workflows

smart-llm-router maintain --limit 8

smart-llm-router route-stats --limit 1000

smart-llm-router golden-eval \
  /path/to/smart-llm-router/examples/golden-sets/audit-public-v1.json \
  --provider groq-free --model qwen/qwen3.6-27b \
  --baseline-provider deepseek-direct-paid --baseline-model deepseek-v4-pro \
  --allow-paid
```

火山方舟在线推理、Coding Plan 和 Endpoint 的 Base URL、模型名和计费独立，不得混用。所有模型名都必须按具体账号执行发现和任务探针，不能因为官网存在产品名就强行调用。Seedream、Seedance、语音和多模态 embedding 只有专用 adapter 通过后才能执行。
