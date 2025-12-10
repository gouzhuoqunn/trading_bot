# 自动 OCR 监听与 Binance Web3 全仓买入机器人

本项目在 Windows + Python 环境下实现以下流程：

1. 通过 `pywinauto` 锁定微信桌面窗口右侧聊天区域，并使用 `pyautogui` 定时截屏。
2. OCR 前对截图做灰度、可配置的高斯平滑与自适应阈值增强，再调用本地 `Tesseract OCR`（`pytesseract`）将 `O/o` 统一替换为 `0`，并提取符合 `0x` 开头、长度 42 的 BSC 地址。
3. 将最新地址附带 UTC 时间戳写入 `data/addresses.txt`，供交易管道读取。
4. 调度队列会合并短时间内的 OCR 事件，仅在时间窗（默认 20 秒）内对最新一条地址触发自动化，在 Binance Web3 页面完成全仓买入；同一地址只会触发一次，后续重复识别会被秒级去重跳过。

> ⚠️ 请务必确保整个自动化流程符合交易所条款与当地法规，并在真实资金环境启用前充分测试。

## 目录结构

```
风凌渡/
├── config.py                # 全局配置（窗口识别、时间阈值、交易选择器等）
├── main.py                  # 启动入口
├── wechat_ocr_listener.py   # 截屏 + OCR + 地址写入
├── scheduler/
│   └── pipeline.py          # 调度队列、时间窗校验与重试逻辑
├── storage/
│   └── address_repo.py      # 地址文件持久化与备份
├── trading/
│   ├── executor.py          # Playwright 自动化完成买入
│   └── time_guard.py        # 时间窗口验证
├── utils/
│   └── ocr_engine.py        # pytesseract 简易封装
├── logging_utils/
│   └── logger.py            # 统一日志配置
├── data/
│   └── addresses.txt        # OCR 结果存放（运行时生成）
└── requirements.txt         # 依赖清单
```

## 环境准备

1. 安装 Python 3.9 及以上版本。
2. 建议创建虚拟环境并激活：
   ```powershell
   python -m venv .venv
   .venv\Scripts\activate
   ```
3. 安装依赖：
   ```powershell
   pip install -r requirements.txt
   ```
4. 安装 Playwright 浏览器驱动：
   ```powershell
   playwright install
   ```
5. 安装 Tesseract OCR（例如默认安装在 `C:\Program Files\Tesseract-OCR\tesseract.exe`）。程序会自动检测常见安装路径；如未命中，可在运行前设置环境变量 `TESSERACT_CMD` 指向可执行文件。

## 关键配置项（`config.py` / 环境变量）

| 配置键 | 说明 | 默认值 |
| ------ | ---- | ------ |
| `WECHAT_WINDOW_TITLE_PATTERN` | `pywinauto` 连接微信窗口的正则模式 | `r"(锁子密码【禁言群】🚫)|微信"` |
| `WECHAT_WINDOW_CLASS_NAME` | 无法通过标题匹配时使用的窗口类名 | `WeChatMainWndForPC` |
| `WECHAT_CHAT_LEFT_RATIO` | 聊天区域相对窗口宽度的起始比例 | `0.4` |
| `WECHAT_CHAT_TOP_OFFSET` | 聊天区域距离窗口顶部的像素偏移 | `100` |
| `WECHAT_CHAT_RIGHT_OFFSET` | 聊天区域距离窗口右侧的像素偏移 | `10` |
| `WECHAT_CHAT_BOTTOM_OFFSET` | 聊天区域距离窗口底部的像素偏移 | `80` |
| `WECHAT_FORCE_FOCUS` | 截图前是否强制激活微信窗口 | `True` |
| `TESSERACT_CMD` | Tesseract 可执行文件路径 | `None`（若已在 PATH 中则可缺省） |
| `OCR_USE_ADAPTIVE_THRESHOLD` | 是否启用 OCR 自适应阈值增强 | `True` |
| `OCR_THRESHOLD_BLOCK_SIZE` | 自适应阈值窗口大小（需奇数） | `31` |
| `OCR_THRESHOLD_CONSTANT` | 自适应阈值常数偏移 | `6` |
| `OCR_GAUSSIAN_KERNEL_SIZE` | 高斯模糊核尺寸（需奇数） | `3` |
| `TRADE_TIME_WINDOW_SECONDS` | 地址有效时间窗（秒） | `20` |
| `BINANCE_ADDRESS_INPUT_SELECTORS` | 地址输入框候选选择器（逗号分隔） | `input[data-testid='wallet-address-input'],input[placeholder*='合约地址'],input[placeholder*='地址'],input[aria-label*='地址']` |
| `BINANCE_MAX_BUY_SELECTORS` | 全仓按钮候选选择器 | `button[data-testid='max-balance-button'],button:has-text('最大'),button:has-text('Max')` |
| `BINANCE_CONFIRM_BUY_SELECTORS` | 确认按钮候选选择器 | `button[data-testid='confirm-purchase-button'],button:has-text('确认'),button:has-text('Confirm')` |
| `BINANCE_TRENDING_SEARCH_INPUT_SELECTORS` | 热门页面搜索框选择器 | `input[placeholder*='搜索'],input[placeholder*='Search'],input[aria-label*='搜索'],input[data-testid*='search'],input[type='search']` |
| `BINANCE_TRENDING_RESULT_SELECTORS` | 搜索结果项候选选择器 | `a[data-testid*='market'],div[data-testid*='search'][role='button'],div[role='option'],a[href*='/token/'],a[href*='/swap']` |
| `BINANCE_TRENDING_TRADE_BUTTON_SELECTORS` | 热门页面交易按钮候选选择器 | `button:has-text('交易'),a:has-text('交易'),button:has-text('Swap'),a:has-text('Swap')` |
| `BINANCE_SWAP_URL_TEMPLATE` | 跳转失败时的备用 Swap URL 模板 | `''` |
| `PLAYWRIGHT_BROWSER_CHANNEL` | Playwright 浏览器通道 | `'chrome'` |
| `PLAYWRIGHT_BROWSER_EXECUTABLE` | 指定 Chrome 可执行文件路径 | `None` |
| `TRADE_AUTOMATION_MODE` | 交易执行模式（`playwright` / `gui`） | `gui` |
| `CHROME_WINDOW_TITLE_PATTERN` | 已打开 Chrome 窗口标题匹配正则 | `(BSC 市场上的热门代币和 Meme 币\|\币安钱包)\|Binance\|Google Chrome` |
| `CHROME_ADDRESS_BAR_RATIO` | 地址栏点击位置（相对窗口宽高） | `0.32,0.05` |
| `CHROME_SEARCH_ICON_RATIO` | 顶部搜索图标点击位置 | `0.82,0.12` |
| `CHROME_SEARCH_INPUT_RATIO` | 搜索框点击位置（相对窗口宽高） | `0.63,0.18` |
| `CHROME_RESULT_CLICK_RATIO` | 搜索结果点击位置 | `0.48,0.38` |
| `CHROME_PRICE_VALUE_RATIO` | “市价/BNB”左侧价格的点击位置 | `0.78,0.45` |
| `CHROME_QUANTITY_INPUT_RATIO` | “数量/BNB”输入框点击位置 | `0.78,0.58` |
| `CHROME_BUY_BUTTON_RATIO` | “买入”黄色按钮位置 | `0.9,0.82` |
| `CHROME_CONFIRM_BUTTON_RATIO` | 确认按钮点击位置 | `0.85,0.88` |
| `CHROME_USE_ABSOLUTE_POINTS` | 是否使用绝对坐标执行 GUI 点击 | `True` |
| `CHROME_ADDRESS_FIELD_POINT` | 地址输入框绝对坐标（像素） | `598,440` |
| `CHROME_RESULT_ROW_POINT` | 搜索结果绝对坐标 | `612,784` |
| `CHROME_PRICE_FIELD_POINT` | “市价/BNB”价格绝对坐标 | `1087,631` |
| `CHROME_QUANTITY_FIELD_POINT` | “数量/BNB”输入框绝对坐标 | `911,720` |
| `CHROME_BUY_BUTTON_POINT` | “买入”按钮绝对坐标 | `945,1154` |
| `CHROME_PRICE_OFFSET` | 复制价格后自动减掉的值 | `0.006` |
| `CHROME_PAGE_LOAD_SECONDS` | Chrome 导航后等待秒数 | `4.0` |
| `CHROME_RESULT_WAIT_SECONDS` | 搜索后等待秒数 | `1.5` |
| `CHROME_TRADE_WAIT_SECONDS` | 进入代币页后等待秒数 | `2.5` |

如需微调聊天区域，可通过环境变量或直接修改 `config.py`。

### GUI 模式（复用已有 Chrome）

- 将 `TRADE_AUTOMATION_MODE` 设为 `gui`，程序将不再启动 Playwright，而是直接操控已经登录好的 Chrome 窗口。
- 请提前打开并登录 `https://web3.binance.com/zh-CN/markets/trending?chain=bsc`，默认会匹配截图中的标题 **“BSC 市场上的热门代币和 Meme 币 | 币安钱包”**；若本地标题不同，可通过 `CHROME_WINDOW_TITLE_PATTERN` 提供自定义正则。
- GUI 步骤包括：点击顶部“搜索”图标→粘贴最新地址并点选搜索结果→双击“市价/BNB”左侧数字复制→粘贴到“数量/BNB”输入框→点击“买入”及确认按钮。若任何点击偏移，可通过 `CHROME_*_RATIO` 调整对应位置（坐标以窗口左上角为 0~1 比例表示）。
- 若页面结构变化或加载较慢，可分别调整 `CHROME_*_SECONDS` 等待时间，必要时结合系统分辨率手动校准。

## 运行步骤

1. 确保微信客户端处于桌面前台，并将目标群（如“锁子密码【禁言群】🚫”）显示在右侧聊天区域。
2. 登录 Binance 并保持 Web3 页面可用；如需复用登录态，可设置 `PLAYWRIGHT_USER_DATA_DIR` 指向浏览器用户数据目录。
3. 在项目根目录执行：
   ```powershell
   python main.py
   ```
4. 观察终端输出及 `data/bot.log` 日志，确认是否成功截屏、识别地址并触发交易。

## 常见问题

- **找不到微信窗口**：如果日志提示 “Target WeChat window not found”，请确认微信未以管理员权限运行；必要时以管理员权限启动 PowerShell 再运行脚本。
- **OCR 无法识别或为空**：检查聊天区域是否显示完整地址，可适当调整区域偏移或提升截屏分辨率。
- **交易页面元素变化**：当 Binance 页面改版时，需重新获取 CSS 选择器并更新 `config.py`。

## 后续优化建议

- 利用样板图片对 OCR 模块做离线测试，确保识别准确率。
- 针对交易环节加入更多风控策略，例如白名单地址或余额阈值。
- 实现健康检查与通知机制（如桌面弹窗或企业微信提醒），以及自动重启守护脚本。

> 默认 `BINANCE_TRADING_URL` 为 https://web3.binance.com/zh-CN/markets/trending?chain=bsc，可通过环境变量覆盖；Playwright 默认以 channel='chrome' 启动本机 Google Chrome，若需指定其他内核，可设置 `PLAYWRIGHT_BROWSER_CHANNEL` 或 `PLAYWRIGHT_BROWSER_EXECUTABLE`。
