# 指数动量信号推送

每周五自动推送6个A股指数的20日动量排名到手机。

## 使用方法

### 1. Fork 或 Clone 本仓库

### 2. 设置 Secret

进入仓库 → Settings → Secrets and variables → Actions → New repository secret

- **Name**: `BARK_KEY`
- **Value**: 你的 Bark Device Key（如 `GmKNMfVWUzs8xiYMxsL7Um`）

### 3. 手动测试

Actions → 指数动量推送 → Run workflow → Run workflow

### 4. 自动执行

每周五 15:30（北京时间）自动执行，Bark 推送到手机。

## 指数列表

- 沪深300 (sh.000300)
- 创业板指 (sz.399006)
- 上证50 (sh.000016)
- 科创50 (sh.000688)
- 深证100 (sz.399330)
- 中证500 (sh.000905)

## 策略说明

- 计算各指数过去20个交易日的涨跌幅
- 动量最高者为本周持仓标的
- 每周五收盘后推送信号
