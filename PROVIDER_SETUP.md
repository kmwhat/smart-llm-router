# Provider 凭据配置说明

Smart LLM Router 不内置任何 API key。每个使用者必须复制 `.env.example` 为 `.env`，并填写自己的 key。

## 最小可用配置

建议至少配置以下两类之一：

- `OPENROUTER_API_KEY`：用于 OpenRouter 免费模型和 DeepSeek 低价兜底。
- `NVIDIA_API_KEY`：用于 NVIDIA NIM 免费/试用额度模型池。

如果只配置一个 key，路由器仍可运行，但免费池覆盖面会变小。

## 推荐配置

| 环境变量 | 用途 | 是否必需 | 申请/创建地址 |
|---|---|---:|---|
| `OPENROUTER_API_KEY` | OpenRouter 免费文本/视觉模型、DeepSeek 免费/付费兜底 | 推荐 | https://openrouter.ai/settings/keys |
| `NVIDIA_API_KEY` | NVIDIA NIM 文本/视觉模型池 | 推荐 | https://build.nvidia.com/ 或具体模型页的 Get API Key |
| `GROQ_API_KEY` | Groq 高速免费/低成本模型候选 | 可选 | https://console.groq.com/keys |
| `DASHSCOPE_API_KEY` | 阿里云百炼/Qwen 模型 | 可选 | https://bailian.console.aliyun.com/?apiKey=1 |
| `ARK_API_KEY` | 火山引擎方舟/Doubao endpoint | 可选 | 火山引擎方舟控制台的 API Key 页面 |
| `GEMINI_API_KEY` | Google Gemini 付费/中级兜底 | 可选 | https://aistudio.google.com/apikey |

## 配置步骤

```bash
cp .env.example .env
```

然后编辑 `.env`：

```text
OPENROUTER_API_KEY=你的 OpenRouter key
NVIDIA_API_KEY=你的 NVIDIA key
GROQ_API_KEY=你的 Groq key
DASHSCOPE_API_KEY=你的阿里云百炼 key
ARK_API_KEY=你的火山方舟 key
GEMINI_API_KEY=你的 Gemini key
```

## 安全要求

- 不要把 `.env` 发给别人。
- 不要把 `.env` 提交到 Git。
- 不要在聊天记录、截图、日志里公开 API key。
- 给同事分享时，只分享 `.env.example`，让对方填写自己的 key。
- 建议给付费 key 设置预算、限额、告警，并定期轮换。

## 验证

```bash
smart-llm-router providers
smart-llm-router refresh --timeout 6 --limit 8
smart-llm-router task "只输出 OK" --task qa --free-only
smart-llm-router discover-vision --limit 20
smart-llm-router task "只输出 JSON：判断图片是否包含手掌" --task vision --image /path/to/image.png --free-only
```

`providers` 只显示 `has_key: true/false`，不会输出 key。

## 视觉模型说明

视觉能力优先使用免费池：

- OpenRouter `:free` 且支持 image/text 的候选模型。
- NVIDIA NIM 当前账号可见的 vision/VL/multimodal 模型。

如果某个免费视觉模型失败，路由器会自动冷却并换下一个；只有免费池全部不可用，且调用时未设置 `--free-only`，才会进入付费兜底。
