# -*- coding: utf-8 -*-
"""
Discord Guild Boss Timer Bot – 完整版
(2025-05-01)
"""
import json, os, re, asyncio, datetime as dt
from typing import Optional, Tuple, Dict, List

import discord
from discord.ext import commands
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
import pytz
from dotenv import load_dotenv

# ─────────────────────────────────── 基本設定
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
TIMEZONE = pytz.timezone("Asia/Taipei")
DATA_FILE = "bosses.json"
DATE_FMT = "%m/%d %H:%M"

# ─────────────────────────────────── 資料存取

def load_bosses() -> Dict[str, dict]:
    if not os.path.exists(DATA_FILE):
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump({}, f, ensure_ascii=False, indent=2)
    with open(DATA_FILE, encoding="utf-8") as f:
        return json.load(f)

def save_bosses(data: Dict[str, dict]):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

bosses = load_bosses()

# ─────────────────────────────────── 工具函式

def parse_time(s: str, now: dt.datetime) -> Optional[dt.datetime]:
    """支援 hhmm 或 MMddhhmm，回傳 tz-aware datetime。"""
    if not s:
        return None
    if re.fullmatch(r"\d{4}", s):
        hh, mm = int(s[:2]), int(s[2:])
        t = TIMEZONE.localize(dt.datetime.combine(now.date(), dt.time(hh, mm)))
        if t < now:
            t += dt.timedelta(days=1)
        return t
    if re.fullmatch(r"\d{8}", s):
        M, d, hh, mm = map(int, (s[:2], s[2:4], s[4:6], s[6:]))
        year = now.year + ((M, d) < (now.month, now.day))
        return TIMEZONE.localize(dt.datetime(year, M, d, hh, mm))
    return None


def resolve_boss(key: str) -> Optional[str]:
    k = key.lower()
    for name, d in bosses.items():
        if k == name.lower() or k in [t.lower() for t in d.get("aliases", [])]:
            return name
    return None


def advance_to_future(name: str, now: dt.datetime) -> Tuple[Optional[dt.datetime], int]:
    data = bosses[name]
    nxt_iso = data.get("next_spawn")
    if not nxt_iso:
        return None, 0
    nxt = dt.datetime.fromisoformat(nxt_iso)
    if nxt > now:
        return nxt, 0
    cycle = dt.timedelta(minutes=data["respawn_min"])
    missed = int((now - nxt) // cycle) + 1
    nxt += cycle * missed
    data["next_spawn"] = nxt.isoformat()
    return nxt, missed

# ─────────────────────────────────── Bot 初始化
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="", intents=intents)

aio_sched = AsyncIOScheduler(timezone=TIMEZONE)
aio_sched.start()

default_channel_id = int(os.getenv("1367444988153171978", 0))  # 建議把公告頻道 ID 放 .env
alert_ch = bot.get_channel(default_channel_id)

now = dt.datetime.now(TIMEZONE)
for name, data in bosses.items():
    nxt_iso = data.get("next_spawn")
    if not nxt_iso:
        continue
    nxt = dt.datetime.fromisoformat(nxt_iso)
    if nxt > now and alert_ch:
        schedule_alert(alert_ch, name, nxt)
# ─────────────────────────────────── 排程提示

def schedule_alert(ch, boss: str, when: dt.datetime):
    alert = when - dt.timedelta(minutes=5)
    if alert < dt.datetime.now(TIMEZONE):
        return
    aio_sched.add_job(
        lambda: asyncio.run_coroutine_threadsafe(ch.send(f"⏰ **{boss}** 5 分鐘後重生！"), bot.loop),
        trigger=DateTrigger(run_date=alert),
        name=f"alert_{boss}_{int(when.timestamp())}"
    )

# ─────────────────────────────────── 事件攔截
@bot.event
async def on_message(msg):
    if msg.author.bot:
        return
    await bot.process_commands(msg)

# ─────────────────────────────────── kb
@bot.command(name="kb")
async def kb(ctx, sub: str = None):
    now = dt.datetime.now(TIMEZONE)
    rows: List[Tuple[str, dt.datetime, int]] = []
    changed = False
    for n in bosses:
        nxt, missed = advance_to_future(n, now)
        if nxt:
            rows.append((n, nxt, missed))
            schedule_alert(ctx.channel, n, nxt)
            if missed:
                changed = True
    if changed:
        save_bosses(bosses)
    if not rows:
        return await ctx.send("尚未有紀錄")
    rows.sort(key=lambda x: x[1])
    if sub != "all":
        rows = rows[:10]
    lines = ["**接下來重生表**"]
    for n, t, m in rows:
        left = int((t - now).total_seconds() // 60)
        miss_txt = f"（已過 {m} 次）" if m else ""
        lines.append(f"• {t:{DATE_FMT}} ➜ **{n}**（剩 {left} 分）{miss_txt}")
    await ctx.send("\n".join(lines))

# ─────────────────────────────────── k
@bot.command(name="k")
async def k(ctx, key: str, when: str = None):
    name = resolve_boss(key)
    if not name:
        return await ctx.send("查無此王/關鍵字")
    now = dt.datetime.now(TIMEZONE)
    death = parse_time(when, now) if when else now
# 若使用者手動輸入的時間被 parse_time 誤判成「明天」
    if when and death > now:
        death -= dt.timedelta(days=1)
    if death is None:
        return await ctx.send("時間格式錯誤 hhmm 或 MMddhhmm")
    nxt = death + dt.timedelta(minutes=bosses[name]["respawn_min"])
    bosses[name]["next_spawn"] = nxt.isoformat()
    save_bosses(bosses)
    schedule_alert(ctx.channel, name, nxt)
    await ctx.send(f"已記錄 **{name}**，下次 {nxt:{DATE_FMT}} 重生")

# ─────────────────────────────────── kr
@bot.command(name="kr")
async def kr(ctx, key: str, ts: str):
    name = resolve_boss(key)
    if not name:
        return await ctx.send("查無此王/關鍵字")
    now = dt.datetime.now(TIMEZONE)
    nxt = parse_time(ts, now)
    if nxt is None:
        return await ctx.send("時間格式錯誤 hhmm 或 MMddhhmm")
    bosses[name]["next_spawn"] = nxt.isoformat()
    save_bosses(bosses)
    schedule_alert(ctx.channel, name, nxt)
    await ctx.send(f"已設定 **{name}** 下一次 {nxt:{DATE_FMT}} 重生")

# ─────────────────────────────────── clear
@bot.command(name="clear")
async def clear(ctx, target: str):
    now = dt.datetime.now(TIMEZONE)
    if target == "all":
        for b in bosses.values():
            b["next_spawn"] = None
        save_bosses(bosses)
        return await ctx.send("已清除所有紀錄")
    if target == "lost":
        for b in bosses.values():
            if b.get("next_spawn") and dt.datetime.fromisoformat(b["next_spawn"]) < now:
                b["next_spawn"] = None
        save_bosses(bosses)
        return await ctx.send("已清除過期紀錄")
    name = resolve_boss(target)
    if not name:
        return await ctx.send("查無此王/關鍵字")
    bosses[name]["next_spawn"] = None
    save_bosses(bosses)
    await ctx.send(f"已清除 **{name}** 紀錄")

# ─────────────────────────────────── restart
@bot.command(name="restart", aliases=["!restart"])
async def restart(ctx, ts: str = None):
    now = dt.datetime.now(TIMEZONE)
    base = parse_time(ts, now) if ts else now
    if ts and base is None:
        return await ctx.send("時間格式錯誤 hhmm")
    for n, d in bosses.items():
        nxt = base + dt.timedelta(minutes=d["respawn_min"])
        d["next_spawn"] = nxt.isoformat()
        schedule_alert(ctx.channel, n, nxt)
    save_bosses(bosses)
    await ctx.send("已重設全部王死亡時間")

# ─────────────────────────────────── 管理指令
@bot.command(name="add")
async def add(ctx, name: str, cycle: int, *tags):
    if name in bosses:
        return await ctx.send("已存在同名王")
    bosses[name] = {"respawn_min": int(cycle), "aliases": list(tags), "next_spawn": None}
    save_bosses(bosses)
    await ctx.send(f"已新增 **{name}**，週期 {cycle} 分，關鍵字 {', '.join(tags) if tags else '無'}")


@bot.command(name="rename")
async def rename(ctx, old: str, new: str):
    if new in bosses:
        return await ctx.send("新名稱已存在")
    name = resolve_boss(old)
    if not name:
        return await ctx.send("查無此王/關鍵字")
    bosses[new] = bosses.pop(name)
    save_bosses(bosses)
    await ctx.send(f"已將 **{name}** 更名為 **{new}**")


@bot.command(name="retime")
async def retime(ctx, key: str, cycle: int):
    name = resolve_boss(key)
    if not name:
        return await ctx.send("查無此王/關鍵字")
    bosses[name]["respawn_min"] = int(cycle)
    save_bosses(bosses)
    await ctx.send(f"已修改 **{name}** 週期為 {cycle} 分")


@bot.command(name="remove")
async def remove(ctx, key: str):
    name = resolve_boss(key)
    if not name:
        return await ctx.send("查無此王/關鍵字")
    bosses.pop(name)
    save_bosses(bosses)
    await ctx.send(f"已刪除 **{name}** 的資料")

# ---------------- 新增指令 ----------------

@bot.command(name="tags")
async def tags(ctx, action: str, boss_name: str, *tag_list: str):
    """管理王的關鍵字：
    - tags add [王名稱] [關鍵字1] [關鍵字2] ...
    - tags remove [王名稱] [關鍵字1] [關鍵字2] ...
    如果未提供任何關鍵字，將提示格式錯誤。"""

    if not tag_list:
        return await ctx.send("格式錯誤：請至少提供一個關鍵字。用法：tags add/remove [王名稱] [關鍵字…]")

    name = resolve_boss(boss_name)
    if not name:
        return await ctx.send("查無此王/關鍵字")

    # 確保 aliases 欄位存在
    aliases = bosses[name].setdefault("aliases", [])

    if action == "add":
        added = []
        existed = []
        for tag in tag_list:
            if tag in aliases:
                existed.append(tag)
            else:
                aliases.append(tag)
                added.append(tag)
        save_bosses(bosses)
        msg = []
        if added:
            msg.append(f"已為 **{name}** 新增關鍵字：{', '.join(added)}")
        if existed:
            msg.append(f"以下關鍵字已存在：{', '.join(existed)}")
        return await ctx.send("\n".join(msg))

    elif action == "remove":
        removed = []
        missing = []
        for tag in tag_list:
            if tag in aliases:
                aliases.remove(tag)
                removed.append(tag)
            else:
                missing.append(tag)
        save_bosses(bosses)
        msg = []
        if removed:
            msg.append(f"已從 **{name}** 移除關鍵字：{', '.join(removed)}")
        if missing:
            msg.append(f"以下關鍵字不存在：{', '.join(missing)}")
        return await ctx.send("\n".join(msg))

    else:
        return await ctx.send("格式錯誤：動作必須是 add 或 remove")


@bot.command(name="info")
async def info(ctx, *args):
    """列出王的設定資料：
    - info                 列出全部王的週期與關鍵字
    - info [王名稱]        列出指定王的週期與關鍵字
    """
    if len(args) == 0:
        if not bosses:
            return await ctx.send("目前無任何王的資料")
        lines = []
        for name, data in bosses.items():
            cycle = data.get("respawn_min", "未知")
            aliases = ", ".join(data.get("aliases", [])) or "無"
            lines.append(f"**{name}** - 週期: {cycle} 分, 關鍵字: {aliases}")
        return await ctx.send("\n".join(lines))

    else:
        name = resolve_boss(args[0])
        if not name:
            return await ctx.send("查無此王/關鍵字")
        data = bosses[name]
        cycle = data.get("respawn_min", "未知")
        aliases = ", ".join(data.get("aliases", [])) or "無"
        return await ctx.send(f"**{name}** - 週期: {cycle} 分\n關鍵字: {aliases}")


# ---------------- 主程式入口 ----------------
if __name__ == "__main__":
    if not TOKEN:
        raise RuntimeError("環境變數 DISCORD_TOKEN 未設定")
    bot.run(TOKEN, reconnect=True)
