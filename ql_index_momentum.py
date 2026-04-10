#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
指数动量信号推送 - GitHub Actions 版
===============================================================
策略：每周五推送6个A股指数过去20个交易日涨幅排名，
     并标注当前应持仓的最强指数。

数据源：东方财富/新浪实时行情（无需登录，HTTP 可达即用）
推送方式：Bark

环境变量配置（在 GitHub Secrets 中设置）：
    BARK_KEY = 你的 Bark Device Key
"""

import sys, os, json, re
from datetime import datetime, timedelta
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

# ============================================================
#  ⚙️ 配置 — 从环境变量读取
# ============================================================
BARK_SERVER = os.environ.get("BARK_SERVER", "https://api.day.app")
BARK_KEY    = os.environ.get("BARK_KEY", "")
# ============================================================

# 六大指数
INDICES = [
    ("s_sh000300", "sh.000300", "沪深300"),
    ("s_sz399006", "sz.399006", "创业板指"),
    ("s_sh000016", "sh.000016", "上证50"),
    ("s_sh000688", "sh.000688", "科创50"),
    ("s_sz399330", "sz.399330", "深证100"),
    ("s_sh000905", "sh.000905", "中证500"),
]

LOOKBACK = 20   # 计算N日动量


def is_last_trading_day() -> bool:
    """
    检查今天是否为本周最后一个交易日。
    原理：检查今天是否为交易日 + 未来几天是否还有交易日。
    """
    # GitHub Actions 使用 UTC，需要转换为北京时间
    import os
    tz_env = os.environ.get("TZ", "")
    if "Asia/Shanghai" not in tz_env and "PRC" not in tz_env:
        # 如果没有设置时区，假设需要 +8 小时
        today = datetime.now() + timedelta(hours=8)
    else:
        today = datetime.now()
    weekday = today.weekday()  # 0=周一, 6=周日
    print(f"[DEBUG] 当前北京时间: {today.strftime('%Y-%m-%d %H:%M')} 周{['一','二','三','四','五','六','日'][weekday]}")
    
    # 尝试获取-market数据判断是否为交易日
    # 简单方法：检查今天是否有实时行情（市场开盘）
    try:
        url = "https://push2.eastmoney.com/api/qt/ulist.np/get?fltt=2&invt=2&fields=f2,f12&secids=1.000001"
        req = Request(url, headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://quote.eastmoney.com/",
        })
        with urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        
        items = data.get("data", {}).get("diff", [])
        if not items:
            print("[INFO] 今天非交易日（无行情数据）")
            return False
        
        # 检查今天数据是否有效（价格不为0或-）
        price = float(items[0].get("f2", 0))
        if price <= 0:
            print("[INFO] 今天非交易日（行情无效）")
            return False
    except Exception as e:
        print(f"[WARN] 检查交易日失败: {e}，默认假设为交易日")
        # 如果API失败，工作日假设为交易日
        if weekday >= 5:  # 周末
            return False

    # 检查今天之后的几天内是否还有交易日（到周日为止）
    # 简化：周五必然是最后交易日（除非节假日）
    # 如果API返回了有效价格，说明市场开市
    # 对于周中，需要判断后续是否有交易日
    
    # 简化逻辑：
    # - 周五 → 最后交易日（节假日本身会通过行情验证排除）
    # - 周一到周四 → 检查后续是否还有交易日
    if weekday == 4:  # 周五
        return True
    
    # 对于周一到周四，默认不是最后交易日
    # 如果遇到节假日导致今天变成最后交易日，需要更复杂的日历判断
    # 这里简化处理：仅周五推送
    print(f"[INFO] 今天是周{['一','二','三','四','五','六','日'][weekday]}，不是周五，跳过")
    return False


def fetch_realtime() -> dict:
    """通过东方财富实时接口获取6个指数当前价格"""
    em_codes = {
        "sh.000300": "1.000300",
        "sz.399006": "0.399006",
        "sh.000016": "1.000016",
        "sh.000688": "1.000688",
        "sz.399330": "0.399330",
        "sh.000905": "1.000905",
    }
    codes_str = ",".join(em_codes.values())
    url = f"https://push2.eastmoney.com/api/qt/ulist.np/get?fltt=2&invt=2&fields=f2,f3,f4,f12,f13,f18&secids={codes_str}"
    result = {}
    try:
        req = Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://quote.eastmoney.com/",
        })
        with urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        
        for item in data.get("data", {}).get("diff", []):
            code_short = item.get("f12", "")
            close = float(item.get("f2", 0))
            prev_close = float(item.get("f18", 0))
            today_chg = float(item.get("f3", 0))
            
            bs_code_map = {v.split(".")[1]: k for k, v in em_codes.items()}
            bs_code = bs_code_map.get(code_short, "")
            if bs_code:
                result[bs_code] = {
                    "close": close,
                    "prev_close": prev_close,
                    "today_chg": today_chg,
                    "date": datetime.now().strftime("%Y-%m-%d"),
                    "time": datetime.now().strftime("%H:%M"),
                }
        print(f"[INFO] 东方财富实时数据: {len(result)} 只成功")
    except Exception as e:
        print(f"[WARN] 东方财富接口失败: {e}，尝试备用接口...")
        return fetch_realtime_v2()
    return result


def fetch_realtime_v2() -> dict:
    """备用：腾讯实时接口"""
    codes = ["sh000300", "sz399006", "sh000016", "sh000688", "sz399330", "sh000905"]
    qurl  = ",".join(codes)
    url   = f"https://qt.gtimg.cn/q={qurl}"
    req   = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    result = {}
    try:
        with urlopen(req, timeout=10) as resp:
            text = resp.read().decode("gbk", "ignore")
        for line in text.strip().split("\n"):
            parts = line.split("~")
            if len(parts) < 10:
                continue
            raw_code = parts[2]
            name_map = {"000300": "sh.000300", "399006": "sz.399006",
                        "000016": "sh.000016", "000688": "sh.000688",
                        "399330": "sz.399330", "000905": "sh.000905"}
            bs_code  = name_map.get(raw_code, "")
            close    = float(parts[3])
            prev_cls = float(parts[4])
            if bs_code:
                result[bs_code] = {
                    "close":     close,
                    "prev_close": prev_cls,
                    "today_chg": (close / prev_cls - 1) * 100,
                    "date":      parts[30] if len(parts) > 30 else "",
                    "time":      parts[33] if len(parts) > 33 else "",
                }
    except Exception as e:
        print(f"[WARN] 腾讯接口也失败: {e}")
    return result


def fetch_history_sina(bs_code: str, days: int = 60) -> list:
    """通过新浪历史K线接口获取日线收盘价"""
    symbol_map = {
        "sh.000300": "sh000300", "sz.399006": "sz399006",
        "sh.000016": "sh000016", "sh.000688": "sh000688",
        "sz.399330": "sz399330", "sh.000905": "sh000905",
    }
    symbol = symbol_map.get(bs_code, bs_code.replace(".", ""))
    url    = (
        f"https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
        f"CN_MarketData.getKLineData?symbol={symbol}&scale=240&ma=5&datalen={days + 10}"
    )
    req = Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn"})
    try:
        with urlopen(req, timeout=10) as resp:
            text = resp.read().decode("utf-8", "ignore")
        data = json.loads(text)
        return [(d["day"], float(d["close"])) for d in data if "close" in d]
    except Exception as e:
        print(f"[WARN] 新浪历史K线失败 ({bs_code}): {e}")
        return []


def get_historical_prices(bs_code: str) -> list:
    """获取历史收盘价"""
    rows = fetch_history_sina(bs_code)
    if len(rows) >= LOOKBACK + 5:
        return rows
    print(f"[WARN] {bs_code} 历史数据不足")
    return []


def calc_momentum(hist: list, n: int = 20, realtime_close: float = None) -> float:
    """计算N日动量（优先用实时价格）- 通达信算法"""
    if len(hist) < n:
        return None
    # 通达信用 hist[-n+1]，即从今天往前数 n-1 个交易日
    earlier = hist[-(n - 1)][1]
    if earlier == 0:
        return None
    today_price = realtime_close if realtime_close is not None else hist[-1][1]
    return round((today_price / earlier - 1) * 100, 2)


def emoji_for(ret: float) -> str:
    if ret >=  5: return "🔥🔥🔥"
    if ret >=  3: return "🔥🔥"
    if ret >=  1: return "📈"
    if ret >=  0: return "📊"
    if ret >= -1: return "📉"
    if ret >= -3: return "🔴"
    return "⚠️⚠️"


def send_bark(title: str, body: str):
    from urllib.parse import urlencode, quote
    server = BARK_SERVER.rstrip("/")
    key    = BARK_KEY
    if not key:
        print("⚠️ BARK_KEY 未设置，跳过推送")
        return
    encoded_title = quote(title, safe="")
    params = urlencode({
        "body":  body[:2000],
        "level": "timeSensitive",
        "icon":  "https://img.icons8.com/ios-filled/100/26e07f/stocks.png",
        "copy":  body[:200],
    })
    url = f"{server}/{key}/{encoded_title}?{params}"
    try:
        req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=10) as r:
            resp = r.read().decode()
        print(f"  Bark 响应: {resp[:100]}")
    except Exception as e:
        print(f"  ⚠️ Bark 推送失败: {e}")


def main():
    print(f"📊 指数动量信号推送  [{datetime.now().strftime('%Y-%m-%d %H:%M')}]")
    print("=" * 52)
    
    # 调试：打印环境变量
    print(f"[DEBUG] BARK_KEY 设置: {'是' if BARK_KEY else '否'}")
    print(f"[DEBUG] TZ: {os.environ.get('TZ', '未设置')}")

    # 检查是否为本周最后一个交易日
    print("[0/3] 检查今日是否为本周最后交易日...")
    try:
        is_last = is_last_trading_day()
    except Exception as e:
        print(f"[ERROR] is_last_trading_day() 异常: {e}")
        # 如果检查失败，假设是周五继续执行
        is_last = True
    if not is_last:
        print("⏭️ 今天不是本周最后交易日，跳过推送")
        sys.exit(0)
    print("✅ 确认为本周最后交易日，继续执行...")

    # Step 1: 获取实时价格
    try:
        realtime = fetch_realtime()
    except Exception as e:
        print(f"[ERROR] fetch_realtime() 异常: {e}")
        realtime = {}
    print(f"[1/3] 实时行情: {len(realtime)} 只成功")

    # Step 2: 获取历史数据 + 实时价格计算动量
    print(f"[2/3] 获取历史数据 + 实时价格计算{LOOKBACK}日动量...")
    results = []
    for sina_code, bs_code, name in INDICES:
        try:
            hist = get_historical_prices(bs_code)
        except Exception as e:
            print(f"[ERROR] get_historical_prices({bs_code}) 异常: {e}")
            hist = []
        
        rt = realtime.get(bs_code, {})
        realtime_close = rt.get("close", None)
        today_chg = rt.get("today_chg", None)
        
        try:
            mom = calc_momentum(hist, LOOKBACK, realtime_close)
        except Exception as e:
            print(f"[ERROR] calc_momentum 异常: {e}")
            mom = None

        if mom is not None:
            emoji = emoji_for(mom)
            today_str = f"(今{today_chg:+.1f}%)" if today_chg is not None else ""
            print(f"  {emoji} {name:<5} {mom:+.2f}% {today_str}")
            results.append({
                "name":       name,
                "bs_code":    bs_code,
                "momentum":   mom,
                "today_chg":  today_chg,
            })
        else:
            print(f"  ⚠️ {name} 数据不足，跳过")

    if len(results) < 2:
        print("❌ 有效数据不足，退出")
        sys.exit(1)

    # 按20日动量降序
    results.sort(key=lambda x: x["momentum"], reverse=True)

    # iOS 通知标题显示全部内容（20日动量已含今日盘中涨跌）
    title = "  ".join(
        f"{'⭐' if i==0 else ''}{r['name']}{r['momentum']:+.1f}%"
        for i, r in enumerate(results)
    )
    body = ""

    print()
    print(body)
    print()

    send_bark(title, body)
    print("✅ 完成")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"[FATAL] 脚本异常退出: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(2)
