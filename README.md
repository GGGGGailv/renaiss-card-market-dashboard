# Renaiss Card Market Dashboard

一个使用 Python、Streamlit、Plotly、Pandas 与 SQLite 构建的 Renaiss 卡牌市场曲线仪表盘。项目通过 `subprocess` 调用本地 `renaiss` CLI，不假设存在未提供的 HTTP API；当 CLI 未安装、不可用或真实输出暂时无法取得时，可自动切换到离线模拟数据，保证界面仍能启动和预览。

> 趋势状态和指标仅是历史数据统计结果，不构成投资建议。

## 1. 项目设计

项目采用分层结构：

- **CLI 层**：`RenaissCLIClient` 负责安装检查、版本读取、帮助探测、安全调用、超时与错误处理。
- **解析层**：先尝试 JSON，再进入独立文本解析器；无法识别时保留原始输出与解析错误。
- **服务层**：统一真实 CLI 与模拟数据的数据模型，并负责持久化。
- **数据库层**：SQLite 保存市场快照、单卡价格快照、活动记录、卡牌与卡包信息。
- **分析层**：计算 24h/7d/30d 涨跌、移动平均、波动率、成交频率、活跃度和趋势状态。
- **展示层**：Streamlit 页面与 Plotly 交互图表。

CLI 参数采用“帮助驱动”策略：程序先执行：

```bash
renaiss marketplace --help
renaiss card --help
renaiss packs --help
```

只有在帮助文本中确认存在某个选项时，程序才会附加该选项。若发现 `--json`，或帮助明确说明 `--output json` / `--format json`，则优先请求 JSON 输出。所有用户输入均经过校验，不允许直接拼接任意 CLI 参数。

## 2. 功能列表

- 市场概览：卡牌数量、在售数量、最低价、均价、中位数、24h 成交量与成交额、涨跌榜、最近成交、价格分布。
- 本地筛选：卡包、卡牌名称、稀有度、价格区间、上架状态、排序与成交时间范围。
- 单卡分析：卡牌详情、活动历史、成交历史、价格曲线、7/30 日均线、高低点和缩放。
- 趋势分析：24h/7d/30d 涨跌、波动率、成交频率、市场活跃度、历史均价位置和趋势状态。
- 卡牌对比：2–5 张卡牌的指标对比、原始价格曲线和首值为 100 的归一化曲线。
- 卡包分析：卡包列表、最低价、均价、总市值、热门卡牌、价格趋势和价格排名。
- 本地历史：自动保存查询快照，并通过活动 ID、交易哈希或稳定哈希去重成交活动。
- 数据刷新：手动刷新、30 秒/1 分钟/5 分钟/15 分钟自动刷新、Streamlit 缓存。
- 诊断页面：数据库状态、表计数、市场快照、CLI 帮助、运行日志和原始数据。
- 模拟数据模式：没有安装 CLI 时也可以完整预览。

## 3. 目录结构

```text
renaiss_dashboard/
├── .streamlit/
│   └── config.toml
├── analytics/
│   ├── __init__.py
│   └── indicators.py
├── assets/
│   └── cards/
│       ├── card_1.svg ... card_8.svg
├── components/
│   ├── __init__.py
│   ├── charts.py
│   ├── metrics.py
│   └── tables.py
├── data/
│   └── renaiss.db
├── database/
│   ├── __init__.py
│   ├── connection.py
│   └── repository.py
├── logs/
│   └── app.log
├── parsers/
│   ├── __init__.py
│   ├── common.py
│   ├── marketplace_parser.py
│   ├── card_parser.py
│   └── pack_parser.py
├── services/
│   ├── __init__.py
│   ├── renaiss_cli.py
│   ├── mock_data.py
│   ├── marketplace_service.py
│   ├── card_service.py
│   └── pack_service.py
├── tests/
│   ├── sample_outputs/
│   │   ├── marketplace.json
│   │   ├── marketplace_text.txt
│   │   ├── card.json
│   │   ├── card_text.txt
│   │   └── packs.json
│   ├── test_cli.py
│   ├── test_database.py
│   ├── test_indicators.py
│   └── test_parsers.py
├── app.py
├── config.py
├── models.py
├── requirements.txt
└── README.md
```

## 4. 环境要求

- Python 3.10 或更高版本
- 可选：已安装并位于 PATH 中的 Renaiss CLI
- SQLite 由 Python 标准库提供，无需单独安装

检查 Python：

```bash
python --version
```

检查 Renaiss CLI：

```bash
renaiss --version
renaiss marketplace --help
renaiss card --help
renaiss packs --help
```

本项目不编造 Renaiss CLI 的安装方式。请按照你获得 CLI 的官方发行说明完成安装，并确保终端可以直接执行 `renaiss`。

## 5. 安装依赖

建议创建虚拟环境：

```bash
python -m venv .venv
```

Windows：

```bash
.venv\Scripts\activate
```

macOS / Linux：

```bash
source .venv/bin/activate
```

安装依赖：

```bash
pip install -r requirements.txt
```

## 6. 启动项目

```bash
streamlit run app.py
```

浏览器通常会自动打开；也可以访问终端显示的本地地址。

### 模拟数据模式

CLI 未安装时，“自动”模式会直接使用模拟数据。也可以在侧边栏将“数据模式”切换为“模拟数据”。模拟 Token ID 为：

```text
1001–1030
```

## 7. SQLite 数据位置

默认数据库：

```text
data/renaiss.db
```

数据库包含：

- `cards`
- `market_snapshots`
- `card_price_snapshots`
- `card_activities`
- `packs`

SQLite 启用 WAL 和 `busy_timeout`，以降低并发读取与刷新时的锁冲突。删除 `data/renaiss.db` 后重新启动应用，可创建全新数据库。

## 8. 日志位置

```text
logs/app.log
```

界面不会向普通用户展示完整 Python 堆栈。详细异常会写入日志。CLI 日志只记录命令类别和错误摘要，不记录用户可任意拼接的命令字符串，也不记录敏感凭据。

## 9. 运行测试

```bash
pytest -q
```

测试覆盖：

- JSON 输出解析
- 文本输出解析
- 空数据与未知格式
- CLI 超时与非零退出状态
- 用户输入安全校验
- 涨跌幅、移动平均与波动率
- SQLite 写入和读取
- 重复成交活动去重

## 10. CLI 接入流程

`services/renaiss_cli.py` 中的 `RenaissCLIClient` 提供：

```python
class RenaissCLIClient:
    def check_installation(self) -> bool: ...
    def get_version(self) -> str: ...
    def get_help(self, command: str) -> str: ...
    def get_marketplace(self, **filters) -> dict: ...
    def get_card(self, token_id: str) -> dict: ...
    def get_pack_list(self) -> list[dict]: ...
    def get_pack(self, slug: str) -> dict: ...
```

安全措施：

- `subprocess.run(..., shell=False)`
- 固定可执行文件与子命令
- Token ID / Slug 正则校验
- 可选筛选项采用逻辑字段白名单
- 只有帮助文本中实际存在的 CLI 选项才会传入
- 调用超时
- 捕获命令不存在、超时、非零退出状态与系统启动异常
- 保存 `stderr` 供诊断
- UI 不显示 Python 堆栈

## 11. 根据真实 CLI 输出调整解析器

首次连接真实 CLI 后，建议进入“数据与日志”页面：

1. 点击“读取三个子命令帮助”，确认 CLI 支持的选项和 JSON 输出方式。
2. 执行市场、单卡和卡包查询。
3. 在“原始数据检查”中查看保留的原始结果。
4. 将脱敏后的输出保存到 `tests/sample_outputs/`。
5. 根据数据类型修改对应解析器：
   - `parsers/marketplace_parser.py`
   - `parsers/card_parser.py`
   - `parsers/pack_parser.py`
6. 优先在规范化函数中增加字段别名，而不是在 Streamlit 页面中处理原始字段。
7. 为新格式补充测试，然后运行 `pytest -q`。

### JSON 字段适配

字段别名集中在 `first_value()`、`nested_value()` 和各解析器的 `_normalize_*()` 函数中。例如真实 CLI 使用 `askingPrice` 时，可以把它加入当前价格候选字段：

```python
price = first_value(item, [
    "current_price",
    "price",
    "asking_price",
    "askingPrice",
])
```

公共的 `normalize_key()` 会把 camelCase 转成 snake_case，因此多数情况下只需增加一个语义别名。

### 文本格式适配

文本解析分为两层：

- `parse_key_value_lines()`：解析 `Key: Value`
- `parse_text_tables()`：解析管道表格或由多个空格分隔的表格

若真实 CLI 是固定段落格式，建议在对应解析器中添加专用的“段落解析函数”，不要把专用规则混入数据库或 UI。

### 未识别格式

解析失败时不会丢弃数据：

- `raw_data` 保存原始输出
- `parse_mode` 标记 `json` / `text` / `empty`
- `parse_errors` 保存友好说明
- UI 继续启动，并可在自动模式下降级到模拟数据

## 12. 常见问题排查

### 未找到 Renaiss CLI

确认：

```bash
renaiss --version
```

若终端也无法执行，请检查安装目录是否加入 PATH。界面可先使用模拟数据模式。

Windows 建议在启动 Streamlit 的同一个终端中依次检查：

```bat
where renaiss
renaiss --version
python -c "import shutil; print(shutil.which('renaiss'))"
```

如果 `where renaiss` 能看到 `renaiss.cmd`，旧版项目可能出现“检测到但无法执行”的情况；当前版本已兼容 npm 常见的 `.cmd/.bat` 命令包装器。也可以通过环境变量指定完整路径：

```bat
set RENAISS_CLI_BINARY=C:\Users\你的用户名\AppData\Roaming\npm\renaiss.cmd
streamlit run app.py
```

### CLI 返回错误或超时

- 检查网络、RPC 或区块链数据源状态。
- 在“数据与日志”查看 `stderr` 摘要和 `logs/app.log`。
- 增加 `config.py` 中的 `cli_timeout_seconds`，但不建议设置过大。

### 页面显示“解析器未识别”

真实 CLI 输出格式可能与样例不同。按照“根据真实 CLI 输出调整解析器”章节增加字段别名或文本规则。

### 数据库被占用

- 关闭直接长期占用 `renaiss.db` 的数据库工具。
- 确认 `data/` 可写。
- 稍后刷新；项目已设置 10 秒 `busy_timeout`。

### 图片无法加载

CLI 返回的图片 URL 可能失效、需要鉴权或网络不可达。卡牌数据和价格分析仍可使用，UI 会显示友好占位提示。

### 自动刷新不可用

重新安装依赖：

```bash
pip install -r requirements.txt
```

确认 `streamlit-autorefresh` 已安装。
