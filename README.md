# GLM Summarizer

基于 GLM 5.1 的高缓存命中率代码总结工具。

核心理念：通过**稳定前缀 + 会话亲和性路由**最大化服务端 Prefix Caching 的 KV Cache 命中率，大幅降低 token 成本（输入输出比 10:1 场景效果显著）。

## 快速开始

```bash
# 安装
git clone <repo> && cd glm-summarizer
pip install -e .

# 配置
export MAAS_API_KEY="your-key"

# 单文件
glm-summarize file src/main.py

# 批量（同一缓存会话，自动复用 KV Cache）
glm-summarize batch "src/**/*.py" --output summaries/

# 验证缓存效果
glm-summarize benchmark "src/**/*.py"
```

## 配置

优先级：CLI 参数 > 环境变量 > 配置文件 > 默认值

```bash
# 环境变量
export MAAS_API_KEY="your-key"
export MAAS_MODEL="glm-5.1"
export MAAS_BASE_URL="https://api-ap-southeast-1.modelarts-maas.com/openai/v1"
```

或使用配置文件：

```bash
cp config.example.yaml ~/.glm-summarizer/config.yaml
# 编辑 api_key 即可
```

## CLI 命令

| 命令 | 说明 |
|------|------|
| `file <path>` | 总结单个文件 |
| `batch <glob>` | 批量总结，共享缓存会话 |
| `benchmark <glob>` | A/B 对比缓存效果，输出成本报告 |
| `config` | 查看当前配置 |
| `template list` | 列出可用模板 |
| `template show <name>` | 查看模板内容 |
| `hook install` | 安装 git hook 到当前仓库 |

### 常用选项

```
--template, -t   模板名称（默认 file-summary）
--output, -o     输出目录
--format, -f     json / markdown / text
--concurrency, -c 并发数（默认 5）
--verbose, -v    详细输出
```

## Python API

```python
from glm_summarizer import Summarizer, CacheSession, get_template

# 单文件
with Summarizer() as s:
    result = s.summarize_file("src/auth.py")
    print(result.summary, result.usage)

# 批量（共享缓存会话）
template = get_template("code-review")
session = CacheSession()
with Summarizer() as s:
    stats = s.batch_summarize(
        ["src/a.py", "src/b.py", "src/c.py"],
        template=template,
        session=session,
    )
print(f"Tokens: {stats.total_prompt_tokens} in / {stats.total_completion_tokens} out")
print(f"Session: {stats.cache_session}")
```

## 内置模板

| 模板 | 用途 |
|------|------|
| `file-summary` | 文件用途、结构、关键函数 |
| `pr-diff` | PR diff 总结 |
| `api-docs` | API 文档生成 |
| `code-review` | 代码审查（bug/安全/性能） |

自定义模板：

```yaml
# my-templates.yaml
templates:
  my-review:
    description: "聚焦安全审查"
    system: "You are a security engineer..."
    user: "Audit:\n```{language}\n{code}\n```"
```

```bash
glm-summarize batch "src/**/*.py" --templates my-templates.yaml -t my-review
```

## 缓存策略

```
请求1: [System Prompt] [Code file A] → 服务端缓存 System Prompt 的 KV Cache
请求2: [System Prompt] [Code file B] → 复用缓存的 KV Cache
请求3: [System Prompt] [Code file C] → 同上
```

- 所有请求共享**相同 system prompt 前缀**，每文件独立请求，避免累积历史导致前缀膨胀
- 同一批次使用**相同 `X-Conversation-Id`**，路由到同一推理实例
- 自动检测前缀稳定性，变更时告警

## 自动化

### Git Hook（每次 commit 自动总结变更）

```bash
glm-summarize hook install post-commit
```

环境变量控制：

```bash
export GLM_SUMMARIZE_TEMPLATE=file-summary
export GLM_SUMMARIZE_OUTPUT=summaries/
export GLM_SUMMARIZE_MAX_FILES=20
```

### CI/CD

- `contrib/github-actions-pr-summary.yml` — GitHub Actions，PR 时自动总结变更并评论
- `contrib/gitlab-ci-summarize.yml` — GitLab CI，MR 事件触发

### 文件监视

```bash
# 依赖: brew install fswatch
./contrib/watch.sh "src/**/*.py" --template file-summary --output summaries/
```

## 项目结构

```
glm-summarizer/
├── pyproject.toml
├── config.example.yaml
├── src/glm_summarizer/
│   ├── config.py          # 多源配置
│   ├── client.py          # MaaS 客户端（连接池 + 亲和性路由）
│   ├── cache.py           # 缓存策略（CacheSession + 前缀管理）
│   ├── templates.py       # Prompt 模板
│   ├── summarizer.py      # 核心逻辑（单文件 + 批量并发）
│   ├── benchmark.py       # A/B 缓存对比 + 成本计算
│   └── cli.py             # CLI 入口
├── contrib/               # 自动化集成（git hook / CI / watcher）
└── tests/
```
