# A股研究员 Agent

一个零框架、从零手写的 A 股个股研究智能体。**LLM 在循环里，自主决定下一步调哪个工具**：
给它一个任务或问题，它自己完成"取数 → 分析 → 成稿"，全程只引用工具返回的真实数据。

主循环约 200 行（`agent/loop.py`），刻意保持能一口气读完——这个项目同时也是
"Agent 到底是什么"的最小实现样本：Agent = LLM + 工具 + 循环 + 熔断，其余都是工程。

## 能做什么

```bash
# 四段式研究草稿（基本面画像/近期走势/资金动向/风险提示）
python3 main.py "研究 600519 贵州茅台"

# 直接回答具体问题：结论 + 倾向 + 每条依据的硬度标注 + 数据缺口
python3 main.py "分析下 002017 后续最有可能的走势"
```

两种模式由任务措辞驱动，同一套循环与工具。回答中的观点会逐条标注硬度
（[高]=数据直接支持 / [中]=数据暗示 / [低]=推断），数据缺口如实说明，绝不编造数字。

内置工具（全部只读）：腾讯实时行情快照（现价/估值/市值/换手）、腾讯日K线
（前复权，10~250日）、东财主力资金流（日频，主站+延迟站自动回退）。

## 快速开始

```bash
pip3 install -r requirements.txt        # 唯一依赖：requests
cp .env.example .env                    # 填入任意 OpenAI 兼容 API key
python3 main.py "研究 600519" --verbose
```

`.env` 默认指向 DeepSeek（便宜、JSON 输出稳），换通义千问只需改三行——
任何 OpenAI 兼容端点都可以。不填 key 也能先验证全部管道（mock LLM 驱动
真实循环 + 真实数据接口，零成本）：

```bash
python3 tests/test_tools.py             # 三个数据工具直连真实接口
python3 tests/test_plumbing.py          # 8条断言：决策/熔断/截断/解析/日志
```

注：数据源为腾讯/东财国内端点，运行环境需能访问国内网络；Python 3.9+（在 3.11/3.12 验证）。

## 架构

```
main.py               CLI 入口
agent/
  loop.py             ★ 主循环：决策->执行->回灌->再决策（核心，先读这个）
  llm.py              OpenAI兼容客户端：JSON模式降级/重试/token记账/宽容JSON解析
  llm_hermes.py       可选通道：本地hermes gateway复用（见"部署形态"）
  trunc.py            工具输出截断 adapter（防上下文裸灌）
  config.py           .env 加载
tools/
  __init__.py         ★ 工具注册表：描述即提示词、错误结构化返回
  quote.py            腾讯实时行情（GBK编码）
  kline.py            腾讯日K线（前复权）
  fflow.py            东财主力资金流（push2→push2delay 回退链）
prompts/
  researcher.txt      system prompt（落文件；{{TOOLS}} 由注册表自动注入）
tests/                工具实测 + mock 全链路（不需要 API key）
runs/                 每次运行的 jsonl 日志（自动生成，gitignore）
deploy/               可选部署样例（ECS + 飞书投递）
```

## 设计决策（为什么这样写）

- **主循环手写**：loop 是 agent 的全部本质，200 行读完之前不碰框架。
- **能力=提示词**：支持问答模式没有改一行循环代码，只改了 prompt——工具层与
  循环层稳定后，能力迭代收敛到提示词工程。
- **工具描述 = system prompt 的一部分**：注册表 `TOOL_SPECS` 是工具清单的
  唯一事实源，改 `desc` 等于改提示词，会影响模型路由决策。
- **错误写给 LLM 看**：`tools/execute()` 永不裸抛异常——失败返回
  「错误原因 + 下一步建议」，否则 LLM 看不到错误就会开始编造。
- **截断闸**：所有工具结果进 messages 前过 `truncate()`（每工具有独立限额）。
  宁可让 agent 缩小 days 重查，也不裸灌 200 行原始数据。
- **四重熔断**：步数硬顶 max_steps（默认15）→ 耗尽后一次 forced_final
  无工具收尾 → 连续3次 JSON 解析失败中止 → LLM通道故障预算内重试、
  连续3次熔断。agent 最贵的行为是「再试一次」。
- **宽容 JSON 解析**：LLM 输出脏是常态（字符串内真实换行、JSON 后跟回声
  上下文、markdown 围栏），解析器负责兜住——剥围栏 → 首个配平 JSON 对象 →
  `json.loads(strict=False)`，三种脏形态有回归断言。
- **prompt_hash**：每次运行把 system prompt 的 md5 指纹写进日志头部——
  行为突变时先对 hash，再查是谁改了提示词或工具描述。
- **jsonl 运行日志**：每步 decision/tool_result/parse_error/final 落盘
  `runs/`，排障先看日志再猜原因。

## 如何加一个新工具

1. `tools/` 下写纯函数：入参用简单标量，返回给 LLM 看的字符串（格式化好、
   带表头）；失败直接抛异常（注册表会包装成带建议的错误信息返回给 LLM）。
2. 在 `tools/__init__.py` 的 `TOOL_SPECS` 注册：`func` / `desc`（什么情况
   该用它，这决定模型路由）/ `args` 必填 / `optional_args` 可选 / `limit`
   结果进入上下文的截断上限。
3. `python3 tests/test_tools.py` 回归，再跑一次真实任务看路由是否正确。

## 运行日志与排障

```bash
python3 main.py "研究 000001 平安银行" --verbose   # 看每步决策
cat runs/run_*.jsonl | tail -5                     # 最近一次运行
```

`stopped` 取值含义：`done` 正常完成 / `forced_final` 步数耗尽被强制收尾 /
`max_steps` 收尾机会也没听话（查日志看卡在哪）/ `parse_failures` 连续输出
垃圾 / `llm_error` LLM 通道连续故障。

## 部署形态（可选，非必需）

本仓库默认单机单次运行。仓库另附一套零 API 成本部署样例：LLM 走本地
hermes gateway（`--llm hermes`），cron 定时运行并把结果投递到飞书群
（`deploy/agent-research.sh`）。开源使用者不需要这些，`.env` 配任意
OpenAI 兼容 key 即为完整功能。

```bash
# 定时运行 + 飞书投递（须先部署 hermes gateway）
cp deploy/agent-research.sh ~/.hermes/scripts/
hermes cron create '30 16 * * 1-5' --name agent-research \
  --script agent-research.sh --no-agent --deliver feishu:<chat_id>
```

## 红线

1. 本 agent 只产出研究草稿与观点分析，**永不接入交易执行**——LLM 幻觉率
   不为零，涉钱环节永久人工确认。
2. 工具只读公开行情数据，无任何写操作。
3. 工具描述与 prompts 改动前先跑 `tests/`（改提示词等于改代码）。

## 非目标（现阶段）

- 不做多轮对话与跨会话记忆（单任务一次性运行；任务记忆是下一步方向）
- 不接交易执行（永久红线）
- 财务三表/同业对比/公告事件等工具未内置（扩展方法见"如何加一个新工具"）

## License

MIT
