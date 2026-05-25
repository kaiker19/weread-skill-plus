#!/usr/bin/env python3
"""
微信读书阅读统计可视化
生成 HTML 图表展示周/月/年/季度阅读时长、偏好分类、读书排行、月度趋势等
含季度趋势对比（Q1 vs Q2）
"""

import json, subprocess, os
from datetime import datetime, timezone, timedelta

CHINA_TZ = timezone(timedelta(hours=8))
SKILL_VERSION = "1.0.3"
OUTPUT_FILE = os.path.expanduser("~/.openclaw/workspace/data/weread_reading_stats.html")

def api(key, name, payload=None):
    payload = payload or {}
    payload["api_name"] = name
    payload["skill_version"] = SKILL_VERSION
    body = json.dumps(payload)
    r = subprocess.run(
        ["curl", "-s", "-X", "POST", "https://i.weread.qq.com/api/agent/gateway",
         "-H", f"Authorization: Bearer {key}",
         "-H", "Content-Type: application/json", "-d", body],
        capture_output=True, text=True
    )
    try:
        return json.loads(r.stdout)
    except:
        return {"errcode": -1, "errmsg": r.stdout[:200]}

def get_key():
    with open(os.path.expanduser("~/.openclaw/openclaw.json")) as f:
        return json.load(f)["skills"]["entries"]["weread-skills"]["env"]["WEREAD_API_KEY"]

def fmtDuration(seconds):
    h = seconds // 3600
    m = (seconds % 3600) // 60
    return f"{h}小时{m}分钟" if h else f"{m}分钟"

def get_mode_data(key, mode):
    return api(key, "/readdata/detail", {"mode": mode})

def compute_quarterly_with_compare(annual_stat):
    """从 annually readTimes 拆出季度分布，含 Q1 vs Q2 同比变化"""
    times = annual_stat.get("readTimes", {})
    quarters = {"Q1": 0, "Q2": 0, "Q3": 0, "Q4": 0}
    for ts_str, seconds in sorted(times.items()):
        try:
            ts = int(ts_str)
            d = datetime.fromtimestamp(ts, tz=CHINA_TZ)
            month = d.month
            q = f"Q{(month - 1) // 3 + 1}"
            quarters[q] += seconds
        except:
            pass
    q1 = quarters.get("Q1", 0)
    q2 = quarters.get("Q2", 0)
    if q1 > 0 and q2 > 0:
        pct_change = (q2 - q1) / q1 * 100
    elif q2 > 0:
        pct_change = None
    else:
        pct_change = None
    return quarters, pct_change

def generate_html(stats, mode_labels, quarterly, annual_months_data, q1_q2_change=None):
    """生成 HTML 可视化页面"""
    now = datetime.now(CHINA_TZ)
    date_str = now.strftime("%Y-%m-%d")

    # 处理 monthly 的日级数据用于趋势图
    monthly_stat = stats.get("monthly", {})
    monthly_days = []
    for ts_str, seconds in sorted(monthly_stat.get("readTimes", {}).items()):
        try:
            ts = int(ts_str)
            d = datetime.fromtimestamp(ts, tz=CHINA_TZ)
            monthly_days.append({"date": d.strftime("%m-%d"), "seconds": seconds})
        except:
            pass

    html = f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<title>微信读书阅读统计</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 900px; margin: 0 auto; padding: 20px; background: #f5f5f5; }}
  h1 {{ color: #333; font-size: 24px; }}
  h2 {{ color: #555; font-size: 18px; margin-top: 30px; border-bottom: 1px solid #ddd; padding-bottom: 8px; }}
  .card {{ background: white; border-radius: 12px; padding: 20px; margin: 16px 0; box-shadow: 0 2px 8px rgba(0,0,0,0.08); }}
  .metric {{ display: flex; gap: 24px; flex-wrap: wrap; }}
  .metric-item {{ flex: 1; min-width: 120px; }}
  .metric-value {{ font-size: 28px; font-weight: bold; color: #1a73e8; }}
  .metric-label {{ font-size: 13px; color: #888; margin-top: 4px; }}
  .trend-up {{ color: #34a853; }}
  .trend-down {{ color: #e85a5a; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 12px; }}
  th {{ text-align: left; color: #888; font-size: 12px; font-weight: normal; border-bottom: 1px solid #eee; padding: 8px 4px; }}
  td {{ padding: 10px 4px; border-bottom: 1px solid #f5f5f5; font-size: 14px; }}
  .bar-cell {{ width: 40%; }}
  .bar-bg {{ background: #f0f0f0; border-radius: 4px; height: 8px; width: 100%; }}
  .bar-fill {{ background: #1a73e8; border-radius: 4px; height: 8px; }}
  .quarter-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-top: 16px; }}
  .quarter-card {{ background: #f9f9f9; border-radius: 10px; padding: 16px; text-align: center; }}
  .quarter-value {{ font-size: 22px; font-weight: bold; color: #1a73e8; }}
  .quarter-label {{ font-size: 13px; color: #888; margin-top: 4px; }}
  .bar-chart-row {{ display: flex; align-items: center; margin: 6px 0; gap: 12px; }}
  .bar-label {{ font-size: 13px; color: #555; width: 40px; }}
  .bar-track {{ flex: 1; background: #f0f0f0; border-radius: 4px; height: 10px; }}
  .bar-val {{ font-size: 12px; color: #888; width: 60px; text-align: right; }}
</style>
</head>
<body>
<h1>📚 微信读书阅读统计</h1>
<div style="color:#888;font-size:13px;">{date_str} (UTC+8)</div>
"""

    # --- 各周期概览 ---
    for mode, label in mode_labels.items():
        if mode == "quarterly":
            continue
        s = stats.get(mode, {})
        total = s.get("totalReadTime", 0)
        days = s.get("readDays", 0)
        avg = s.get("dayAverageReadTime", 0)
        compare = s.get("compare")

        html += f"""
<div class="card">
  <h2>{label}</h2>
  <div class="metric">"""
        html += f"""
    <div class="metric-item">
      <div class="metric-value">{fmtDuration(total)}</div>
      <div class="metric-label">总阅读时长</div>
    </div>
    <div class="metric-item">
      <div class="metric-value">{days}天</div>
      <div class="metric-label">有效阅读天数</div>
    </div>
    <div class="metric-item">
      <div class="metric-value">{fmtDuration(avg)}</div>
      <div class="metric-label">日均阅读</div>
    </div>"""
        if compare is not None:
            tc = "trend-up" if compare > 0 else "trend-down"
            ti = "📈" if compare > 0 else "📉"
            html += f"""
    <div class="metric-item">
      <div class="metric-value {tc}">{ti} {abs(compare)*100:.0f}%</div>
      <div class="metric-label">相比上期</div>
    </div>"""
        html += "\n  </div>\n</div>"

    # --- 季度分布 ---
    if quarterly:
        max_q = max(quarterly.values()) if quarterly else 1
        html += """
<div class="card">
  <h2>📅 今年各季度阅读时长</h2>"""
        if q1_q2_change is not None:
            icon = "📈" if q1_q2_change >= 0 else "📉"
            sign = "+" if q1_q2_change >= 0 else ""
            html += f"""
  <div style="margin-bottom:12px;font-size:14px;color:#555;">{icon} Q1 vs Q2 变化：<strong style="color:{'#34a853' if q1_q2_change >= 0 else '#e85a5a'}">{sign}{q1_q2_change:.0f}%</strong></div>"""
        html += """
  <div class="quarter-grid">"""
        for q_name in ["Q1", "Q2", "Q3", "Q4"]:
            sec = quarterly.get(q_name, 0)
            pct = int((sec / max_q) * 100) if max_q > 0 else 0
            html += f"""
    <div class="quarter-card">
      <div class="quarter-value">{fmtDuration(sec)}</div>
      <div class="quarter-label">{q_name}</div>
      <div style="background:#e8f0fe;height:4px;border-radius:2px;margin-top:8px;width:{pct}%"></div>
    </div>"""
        html += "\n  </div>\n</div>"

    # --- 月度趋势（本月日级） ---
    if monthly_days:
        max_day = max(d.get("seconds", 0) for d in monthly_days) if monthly_days else 1
        html += """
<div class="card">
  <h2>📈 本月每日阅读时长</h2>
  <div style="display:flex;align-items:flex-end;gap:3px;height:80px;margin-top:12px;">"""
        for d in monthly_days:
            bar_h = int((d["seconds"] / max_day) * 80) if max_day > 0 else 0
            html += f'<div style="flex:1;background:#1a73e8;height:{bar_h}px;border-radius:2px 2px 0 0;min-height:2px;" title="{d["date"]} {fmtDuration(d["seconds"])}"></div>'
        html += """
  </div>
  <div style="display:flex;justify-content:space-between;font-size:11px;color:#aaa;margin-top:4px;">
    <span>1日</span><span>10日</span><span>20日</span><span>31日</span>
  </div>
</div>"""

    # --- 月度趋势（全年，年度模式） ---
    if annual_months_data:
        max_mon = max(m.get("seconds", 0) for m in annual_months_data) if annual_months_data else 1
        html += """
<div class="card">
  <h2>📊 今年各月阅读时长</h2>"""
        month_names = ["1月","2月","3月","4月","5月","6月","7月","8月","9月","10月","11月","12月"]
        current_month = now.month
        for m_data in annual_months_data:
            month_label = month_names[int(m_data["month"]) - 1] if m_data["month"].isdigit() else m_data["month"]
            sec = m_data["seconds"]
            bar_w = int((sec / max_mon) * 100) if max_mon > 0 else 0
            is_current = int(m_data["month"]) == current_month if m_data["month"].isdigit() else False
            dot = "●" if is_current else "○"
            html += f"""
  <div class="bar-chart-row">
    <div class="bar-label">{dot} {month_label}</div>
    <div class="bar-track"><div class="bar-fill" style="width:{bar_w}%"></div></div>
    <div class="bar-val">{fmtDuration(sec)}</div>
  </div>"""
        html += "\n</div>"

    # --- 读得最多 ---
    monthly_stat = stats.get("monthly", {})
    longest = monthly_stat.get("readLongest", [])
    if longest:
        max_rt = max(v.get("readTime", 1) for v in longest)
        html += """
<div class="card">
  <h2>🏆 本月读得最多</h2>
  <table>
    <tr><th>书名</th><th>作者</th><th class="bar-cell">阅读时长</th></tr>"""
        for item in longest[:8]:
            book = item.get("book", {})
            title = book.get("title", "?")
            author = book.get("author", "?")
            rt = item.get("readTime", 0)
            bar_w = int((rt / max_rt) * 100)
            html += f"""
    <tr>
      <td>{title}</td>
      <td style="color:#888;font-size:12px;">{author}</td>
      <td class="bar-cell"><div class="bar-bg"><div class="bar-fill" style="width:{bar_w}%"></div></div><span style="font-size:12px;color:#888;">{fmtDuration(rt)}</span></td>
    </tr>"""
        html += "\n  </table>\n</div>"

    # --- 偏好分类 ---
    prefer_cats = monthly_stat.get("preferCategory", [])
    if prefer_cats:
        max_cat_rt = max(c.get("readingTime", 1) for c in prefer_cats)
        html += """
<div class="card">
  <h2>📊 偏好分类</h2>"""
        for c in prefer_cats[:6]:
            title = c.get("categoryTitle", "?")
            rt = c.get("readingTime", 0)
            bar_w = int((rt / max_cat_rt) * 100)
            html += f"""
  <div class="bar-chart-row">
    <div class="bar-label">{title}</div>
    <div class="bar-track"><div class="bar-fill" style="width:{bar_w}%"></div></div>
    <div class="bar-val">{fmtDuration(rt)}</div>
  </div>"""
        html += "\n</div>"

    # --- 阅读统计摘要 ---
    read_stat = monthly_stat.get("readStat", [])
    if read_stat:
        html += """
<div class="card">
  <h2>📈 阅读统计摘要</h2>
  <div style="display:flex;gap:16px;flex-wrap:wrap;">"""
        for s in read_stat:
            cnt = s.get("counts", "")
            nm = s.get("stat", "")
            html += f'<div style="flex:1;min-width:80px;text-align:center;background:#f9f9f9;border-radius:8px;padding:12px;"><div style="font-size:20px;font-weight:bold;">{cnt}</div><div style="font-size:12px;color:#888;margin-top:4px;">{nm}</div></div>'
        html += "\n  </div>\n</div>"

    html += f"""
<div style="text-align:center;color:#aaa;font-size:12px;margin-top:40px;">
  数据来源：微信读书 API | 生成时间：{date_str} (UTC+8)<br>
  由 OpenClaw 自动生成
</div>
</body></html>"""

    return html


def main():
    key = get_key()
    now = datetime.now(CHINA_TZ)
    date_str = now.strftime("%Y-%m-%d")

    print(f"📊 微信读书阅读统计可视化")
    print("=" * 50)

    modes = {
        "weekly": "本周",
        "monthly": "本月",
        "annually": "今年",
        "overall": "历史总计",
    }

    mode_labels = {}
    stats = {}

    for mode, label in modes.items():
        print(f"\n获取 {label} 数据...")
        s = get_mode_data(key, mode)
        if s.get("errcode"):
            print(f"  获取失败: {s}")
            stats[mode] = {}
        else:
            stats[mode] = s
            total = s.get("totalReadTime", 0)
            days = s.get("readDays", 0)
            print(f"  时长: {fmtDuration(total)}, 天数: {days}")
        mode_labels[mode] = label

    # 年度月度分布（用于月度趋势图）
    annual_stat = stats.get("annually", {})
    annual_months_data = []
    for ts_str, seconds in sorted(annual_stat.get("readTimes", {}).items()):
        try:
            ts = int(ts_str)
            d = datetime.fromtimestamp(ts, tz=CHINA_TZ)
            annual_months_data.append({"month": d.strftime("%m"), "seconds": seconds})
        except:
            pass

    # 季度计算（带 Q1 vs Q2 对比）
    quarterly, q1_q2_change = compute_quarterly_with_compare(annual_stat)
    if any(quarterly.values()):
        stats["quarterly"] = {"quarterly": quarterly}
        mode_labels["quarterly"] = "今年季度"
        print(f"\n季度分布:")
        for q, sec in sorted(quarterly.items()):
            print(f"  {q}: {fmtDuration(sec)}")
        if q1_q2_change is not None:
            print(f"  Q1 vs Q2 变化: {'+' if q1_q2_change > 0 else ''}{q1_q2_change:.0f}%")

    # 生成 HTML
    html = generate_html(stats, mode_labels, quarterly, annual_months_data, q1_q2_change)

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"\n✅ HTML 已生成: {OUTPUT_FILE}")
    print("=" * 50)

    # 摘要输出
    for mode, label in mode_labels.items():
        if mode == "quarterly":
            print(f"\n【{label}】")
            for q, sec in sorted(quarterly.items()):
                print(f"  {q}: {fmtDuration(sec)}")
            if q1_q2_change is not None:
                print(f"  Q1 vs Q2: {'+' if q1_q2_change > 0 else ''}{q1_q2_change:.0f}%")
            continue
        s = stats.get(mode, {})
        total = s.get("totalReadTime", 0)
        days = s.get("readDays", 0)
        avg = s.get("dayAverageReadTime", 0)
        compare = s.get("compare")
        longest = s.get("readLongest", [])
        prefer_cats = s.get("preferCategory", [])
        read_stat = s.get("readStat", [])

        print(f"\n【{label}】")
        print(f"  总时长: {fmtDuration(total)}, 有效天数: {days}, 日均: {fmtDuration(avg)}")
        if compare is not None:
            print(f"  相比上期: {'+' if compare > 0 else ''}{compare*100:.0f}%")
        if longest:
            print(f"  读得最多: {longest[0].get('book',{}).get('title','?')} ({fmtDuration(longest[0].get('readTime',0))})")
        if prefer_cats:
            cats = [c.get("categoryTitle","?") for c in prefer_cats[:4]]
            print(f"  偏好分类: {' | '.join(cats)}")
        if read_stat:
            stat_strs = [f"{x.get('stat','?')}:{x.get('counts','?')}" for x in read_stat]
            print(f"  阅读统计: {', '.join(stat_strs)}")

    print(f"\n🌐 HTML 报告: {OUTPUT_FILE}")

if __name__ == "__main__":
    main()