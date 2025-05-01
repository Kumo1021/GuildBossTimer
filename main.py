# -*- coding: utf-8 -*-
"""
Discord Guild Boss Timer Bot  
功能列表 (2025-05-01 更新)
--------------------------------------------------
吃王 (基礎指令)
  kb                – 顯示最近 10 筆重生
  kb all            – 顯示所有已排程重生
  k <王|關鍵字> [hhmm]           – 紀錄死亡 (預設此刻)
  kr <王|關鍵字> <hhmm|MMddhhmm> – 直接指定下一次重生
  clear <王|關鍵字|all|lost>    – 清除紀錄
  restart [hhmm]    – 維修用，全部重設為剛死亡 (或指定時間)

王清單維護 (管理員)
  add    <王> <週期分> [關鍵字]
  rename <舊王> <新王>
  retime <王> <週期分>
  remove <王>
  tags   add    <王> <關鍵字>
  tags   remove <王> <關鍵字>

查詢設定
  info            – 列出全部王設定
  info <王>       – 列出單一王設定
--------------------------------------------------
"""

import json
import os
import re
import asyncio
import datetime as dt
from typing import Optional, Tuple, Dict, List

import discord
from discord.ext import commands
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
import pytz
from dotenv import load_dotenv

# ------------ 基本設定 -----------------------------
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
TIMEZONE = pytz.timezone("Asia/Taipei")
DATA_FILE = "bosses.json"
DATE_FMT = "%m/%d %H:%M"

# ---------------------------------------------------

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

# ---------------------------------------------------
# 時間與王查詢工具
# ---------------------------------------------------

def parse_time(s: str, now: dt.datetime) -> Optional[dt.datetime]:
    """解析 hhmm 或 MMddhhmm，回傳時區化 datetime。"""
    if re.fullmatch(r"\d{4}", s):
        hh, mm = int(s[:2]), int(s[2:])
        t = TIMEZONE.localize(dt.datetime.combine(now.date(), dt.time(hh, mm)))
        if t < now:
            t += dt.timedelta(days=1)
        return t
    if re.fullmatch(r"\d{8}", s):
        month, day, hh, mm = map(int, (s[:2], s[2:4], s[4:6], s[6:]))
        year = now.year + ((month, day) < (now.month, now.day))
        return TIMEZONE.localize(dt.datetime(year, month, day, hh, mm))
    return None


def resolve_boss(key: str) -> Optional[str]:
    k_low = key.lower()
    for name, data in bosses.items():
        if k_low == name.lower() or k_low in [t.lower() for t in data.get("aliases", [])]:
            return name
    return None


def advance_to_future(name: str, now: dt.datetime) -> Tuple[Optional[dt.datetime], int]:
    data = bosses[name]
    if not data.get("next_spawn"):
        return None, 0
    nxt = dt.datetime.fromisoformat(data["next_spawn"])
    if nxt > now:
        return nxt, 0
    cycle = dt.timedelta(minutes=data["respawn_min"])
    missed = ((now - nxt) // cycle) + 1
    nxt += cycle * missed
    data["next_spawn"] = nxt.isoformat()
    return nxt, missed

# ---------------------------------------------------
# Bot 初始化
# ---------------------------------------------------
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="", intents=intents)

scheduler = AsyncIOScheduler(timezone=TIMEZONE)
scheduler.start()

# ---------------------------------------------------
# 排程助手
# ---------------------------------------------------

def schedule_alert(ch, boss, spawn_time):
    alert_time = spawn_time - dt.timedelta(minutes=5)
    if alert_time < dt.datetime.now(TIMEZONE):
        return
    scheduler.add_job(
        lambda: asyncio.run_coroutine_threadsafe(
            ch.send(f"⏰ **{boss}** 5 分鐘後重生！"), bot.loop),
        trigger=DateTrigger(run_date=alert_time)
    )

# ---------------------------------------------------
# on_message：避免自我觸發
# ---------------------------------------------------
@bot.event
async def on_message(msg):
    if msg.author.bot:
        return
    await bot.process_commands(msg)

# ---------------------------------------------------
# kb / kb all
# ---------------------------------------------------
@bot.command(name="kb")
async def kb_cmd(ctx, sub: str = None):
    now = dt.datetime.now(TIMEZONE)
    items = []
    changed = False
    for n in bosses:
        nxt, missed = advance_to_future(n, now)
        if nxt:
            items.append((n, nxt, missed))
            if missed:
                changed = True
    if changed:
        save_bosses(bosses)
    if not items:
        return await ctx.send("尚未有任何重生紀錄。")
    items.sort(key=lambda x: x[1])
    if sub != "all":
        items = items[:10]
    lines = ["**接下來重生表**"]
    for n, t, m in items:
        minutes = int((t - now).total_seconds() // 60)
        extra = f"（已過 {m} 次）" if m else ""
        lines.append(f"• {t:{DATE_FMT}} ➜ **{n}**（剩 {minutes} 分）{extra}")
    await ctx.send("\n".join(lines))

# ---------------------------------------------------
# k
# ---------------------------------------------------
@bot.command(name="k")
async def killed(ctx, key: str, when: str = None):
    name = resolve_boss(key)
    if not name:
        return await ctx.send("查無此王或關鍵字。")
    now = dt.datetime.now(TIMEZONE)
    death = parse_time(when, now) if when else now
    if death is None:
        return await ctx.send("時間格式錯誤，請用 hhmm 或 MMddhhmm。")
    respawn = death + dt.timedelta(minutes=bosses[name]["respawn_min"])
    bosses[name]["next_spawn"] = respawn.isoformat()
    save_bosses(bosses)
    schedule_alert(ctx.channel, name, respawn)
    await ctx.send(f"已記錄 **{name}**！預計 {respawn:{DATE_FMT}} 重生。")

# ---------------------------------------------------
# kr
# ---------------------------------------------------
@bot.command(name="kr")
async def kr(ctx, key: str, ts: str):
    name = resolve_boss(key)
    if not name:
        return await ctx.send("查無此王或關鍵字。")
    now = dt.datetime.now(TIMEZONE)
    respawn = parse_time(ts, now)
    if respawn is None:
        return await ctx.send("時間格式錯誤，請用 hhmm 或 MMddhhmm。")
    bosses[name]["next_spawn"] = respawn.isoformat()
    save_bosses(bosses)
    schedule_alert(ctx.channel, name, respawn)
    await ctx.send(f"已設定 **{name}** 下次重生：{respawn:{DATE_FMT}}")

# ---------------------------------------------------
# clear
# ---------------------------------------------------
@bot.command(name="clear")
async def clear(ctx, target: str):
    now = dt.datetime.now(TIMEZONE)
    if target == "all":
        for b in bosses.values():
            b["next_spawn"] = None
        save_bosses(bosses)
        return await ctx.send("已清除所有重生紀錄。")
    if target == "lost":
        for b in bosses.values():
            if b.get("next_spawn") and dt.datetime.fromisoformat(b["next_spawn"]) < now:
                b["next_spawn"] = None
        save_bosses(bosses)
        return await ctx.send("已清除過期紀錄。")
    name = resolve_boss(target)
    if not name:
        return await ctx.send("查無此王或關鍵字。")
    bosses[name]["next_spawn"] = None
    save_bosses(bosses)
    await ctx.send(f"已清除 **{name}** 重生紀錄。")

# ---------------------------------------------------
# restart
# ---------------------------------------------------
@bot.command(name="restart", aliases=["!restart"])
async def restart(ctx, ts: str = None):
    now = dt.datetime.now(TIMEZONE)
    base = parse_time(ts, now) if ts else now
    if ts and base is None:
        return await ctx.send("時間格式錯誤，請用 hhmm。")
    for n, d in bosses.items():
        respawn = base + dt.timedelta(minutes=d["respawn_min"])
        d["next_spawn"] = respawn.isoformat()
        schedule_alert(ctx.channel, n, respawn)
    save_bosses(bosses)
    await ctx.send("已重設所有王死亡時間！")

# ---------------------------------------------------
# add / rename / retime / remove / tags
# ---------------------------------------------------
@bot.command(name="add")
async def add(ctx, name: str, cycle: int, *tags):
    if name in bosses:
        return await ctx.send("已存在同名王")
    bosses[name] = {"respawn_min": int(cycle), "aliases": list
