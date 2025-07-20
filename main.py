import discord
from discord.ext import commands, tasks
import json
import os
from dotenv import load_dotenv
from datetime import datetime, timedelta
import pytz

# --- 設定 ---
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
GUILD_ID = int(os.getenv('GUILD_ID'))
CHANNEL_ID = int(os.getenv('CHANNEL_ID'))
BOSS_FILE = 'bosses.json'
TIMEZONE = pytz.timezone('Asia/Taipei')

# --- Bot 初始化 ---
intents = discord.Intents.default()
intents.messages = True
intents.message_content = True

# --- CHANGED: 修改指令前綴 ---
# 允許 'k' 或 '' (無前綴) 作為指令開頭
# 這讓您可以使用 'kb' 或 'k kb'
bot = commands.Bot(command_prefix=['k', 'K', ''], intents=intents, case_insensitive=True)

# --- 資料處理 (此部分無變更) ---
def load_bosses():
    try:
        with open(BOSS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def save_bosses(bosses):
    with open(BOSS_FILE, 'w', encoding='utf-8') as f:
        json.dump(bosses, f, indent=4, ensure_ascii=False)

bosses_data = load_bosses()

def find_boss_by_name_or_alias(query):
    for name in bosses_data:
        if query.lower() == name.lower():
            return name
    for name, data in bosses_data.items():
        if query.lower() in [a.lower() for a in data.get('aliases', [])]:
            return name
    for name in bosses_data:
        if query.lower() in name.lower():
            return name
    return None

def parse_time_input(time_str):
    now = datetime.now(TIMEZONE)
    try:
        if len(time_str) == 4:
            hour, minute = int(time_str[:2]), int(time_str[2:])
            target_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if target_time < now:
                target_time += timedelta(days=1)
            return target_time
        elif len(time_str) == 8:
            month, day, hour, minute = int(time_str[:2]), int(time_str[2:4]), int(time_str[4:6]), int(time_str[6:])
            return now.replace(year=now.year, month=month, day=day, hour=hour, minute=minute, second=0, microsecond=0)
    except (ValueError, IndexError):
        return None
    return None

def format_datetime(dt):
    if dt:
        return dt.astimezone(TIMEZONE).strftime('%m-%d %H:%M')
    return "N/A"

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}!')
    check_respawn.start()

@tasks.loop(minutes=1)
async def check_respawn():
    await bot.wait_until_ready()
    now = datetime.now(TIMEZONE)
    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        return

    notifications_sent_this_cycle = []
    for name, data in bosses_data.items():
        if data.get('next_spawn'):
            try:
                respawn_time = datetime.fromisoformat(data['next_spawn']).astimezone(TIMEZONE)
                time_diff = respawn_time - now
                if timedelta(minutes=0) < time_diff <= timedelta(minutes=5):
                    if name not in notifications_sent_this_cycle:
                         embed = discord.Embed(title="👑 Boss 即將重生！", description=f"**{name}** 即將在約 **5分鐘** 後重生！", color=discord.Color.gold())
                         embed.add_field(name="預計重生時間", value=format_datetime(respawn_time), inline=False)
                         embed.set_footer(text="請各位勇者做好準備！")
                         await channel.send(embed=embed)
                         notifications_sent_this_cycle.append(name)
            except (ValueError, TypeError):
                continue

# --- 指令 ---

@bot.command(name='k')
async def set_death_time(ctx, boss_query: str, time_str: str = None):
    boss_name = find_boss_by_name_or_alias(boss_query)
    if not boss_name:
        await ctx.send(f"找不到名為、別名為或關鍵字為 '{boss_query}' 的王。")
        return

    if time_str:
        death_time = parse_time_input(time_str)
        if not death_time:
            await ctx.send("無效的時間格式。請使用 `hhmm` 或 `MMddhhmm`。")
            return
    else:
        death_time = datetime.now(TIMEZONE)

    respawn_minutes = bosses_data[boss_name]['respawn_min']
    next_spawn_time = death_time + timedelta(minutes=respawn_minutes)

    bosses_data[boss_name]['next_spawn'] = next_spawn_time.isoformat()
    save_bosses(bosses_data)
    
    embed = discord.Embed(title="✅ 死亡時間已記錄", color=discord.Color.green())
    embed.add_field(name="王", value=boss_name, inline=True)
    embed.add_field(name="死亡時間", value=format_datetime(death_time), inline=True)
    embed.add_field(name="下次重生時間", value=format_datetime(next_spawn_time), inline=False)
    await ctx.send(embed=embed)

@bot.command()
async def kb(ctx, arg: str = None):
    now = datetime.now(TIMEZONE)
    active_bosses = []
    for name, data in bosses_data.items():
        if data.get('next_spawn'):
            try:
                respawn_time = datetime.fromisoformat(data['next_spawn']).astimezone(TIMEZONE)
                if respawn_time > now:
                     active_bosses.append((name, respawn_time))
            except (ValueError, TypeError):
                continue

    active_bosses.sort(key=lambda x: x[1])

    if not active_bosses:
        await ctx.send("目前沒有已記錄的王重生時間。")
        return
        
    embed = discord.Embed(title="👑 Boss 重生時間表", color=discord.Color.blue())
    boss_list = active_bosses if arg and arg.lower() == 'all' else active_bosses[:10]
    
    if not boss_list:
        await ctx.send("目前沒有即將重生的王。")
        return

    description = []
    for name, respawn_time in boss_list:
        time_diff = respawn_time - now
        days = time_diff.days
        hours, remainder = divmod(int(time_diff.total_seconds()), 3600)
        hours = hours % 24
        minutes, _ = divmod(remainder, 60)
        countdown = ""
        if days > 0: countdown += f"{days}天"
        if hours > 0: countdown += f"{hours}小時"
        countdown += f"{minutes}分鐘"
        description.append(f"**{name}**\n重生於: {format_datetime(respawn_time)} (剩餘: {countdown})")

    embed.description = "\n\n".join(description)
    await ctx.send(embed=embed)

@bot.command()
async def kr(ctx, boss_query: str, time_str: str):
    boss_name = find_boss_by_name_or_alias(boss_query)
    if not boss_name:
        await ctx.send(f"找不到王 '{boss_query}'。")
        return

    next_spawn_time = parse_time_input(time_str)
    if not next_spawn_time:
        await ctx.send("無效的時間格式。請使用 `hhmm` 或 `MMddhhmm`。")
        return

    bosses_data[boss_name]['next_spawn'] = next_spawn_time.isoformat()
    save_bosses(bosses_data)

    embed = discord.Embed(title="✅ 重生時間已手動設定", color=discord.Color.purple())
    embed.add_field(name="王", value=boss_name, inline=True)
    embed.add_field(name="下次重生時間", value=format_datetime(next_spawn_time), inline=True)
    await ctx.send(embed=embed)

@bot.command()
async def clear(ctx, query: str):
    now = datetime.now(TIMEZONE)
    if query.lower() == 'all':
        for name in bosses_data:
            bosses_data[name]['next_spawn'] = None
        save_bosses(bosses_data)
        await ctx.send("已清除所有王的重生時間記錄。")
        return
        
    if query.lower() == 'lost':
        cleared_count = 0
        for name, data in bosses_data.items():
            if data.get('next_spawn'):
                try:
                    respawn_time = datetime.fromisoformat(data['next_spawn']).astimezone(TIMEZONE)
                    if respawn_time < now:
                        bosses_data[name]['next_spawn'] = None
                        cleared_count += 1
                except (ValueError, TypeError):
                    continue
        save_bosses(bosses_data)
        await ctx.send(f"已清除 {cleared_count} 筆已錯過的重生記錄。")
        return

    boss_name = find_boss_by_name_or_alias(query)
    if not boss_name:
        await ctx.send(f"找不到王 '{query}'。")
        return

    bosses_data[boss_name]['next_spawn'] = None
    save_bosses(bosses_data)
    await ctx.send(f"已清除 **{boss_name}** 的重生時間記錄。")

# --- CHANGED: 移除管理員權限 ---
@bot.command(name='restart', aliases=['!restart'])
async def restart_all(ctx, time_str: str = None):
    if time_str:
        death_time = parse_time_input(time_str)
        if not death_time:
            await ctx.send("無效的時間格式。請使用 `hhmm`。")
            return
    else:
        death_time = datetime.now(TIMEZONE)
        
    for name in bosses_data:
        respawn_minutes = bosses_data[name]['respawn_min']
        next_spawn_time = death_time + timedelta(minutes=respawn_minutes)
        bosses_data[name]['next_spawn'] = next_spawn_time.isoformat()
    
    save_bosses(bosses_data)
    await ctx.send(f"**維修/重啟**：所有王的死亡時間已設定為 **{format_datetime(death_time)}**，並已重新計算重生排程。")

@bot.command()
@commands.has_permissions(administrator=True)
async def add(ctx, name: str, respawn_min: int, *aliases):
    if name in bosses_data:
        await ctx.send(f"王 '{name}' 已存在。")
        return
    bosses_data[name] = {"respawn_min": respawn_min, "aliases": list(aliases), "next_spawn": None}
    save_bosses(bosses_data)
    await ctx.send(f"已新增王: **{name}** (重生週期: {respawn_min}分鐘, 別名: {', '.join(aliases) if aliases else '無'})")

# --- CHANGED: 移除管理員權限 ---
@bot.command()
async def remove(ctx, name: str):
    boss_name = find_boss_by_name_or_alias(name)
    if not boss_name:
        await ctx.send(f"找不到王 '{name}'。")
        return
    del bosses_data[boss_name]
    save_bosses(bosses_data)
    await ctx.send(f"已移除王: **{boss_name}**。")
    
# --- CHANGED: 移除管理員權限 ---
@bot.command()
async def rename(ctx, old_name: str, new_name: str):
    boss_name = find_boss_by_name_or_alias(old_name)
    if not boss_name:
        await ctx.send(f"找不到王 '{old_name}'。")
        return
    if new_name in bosses_data:
        await ctx.send(f"名稱 '{new_name}' 已被使用。")
        return
    bosses_data[new_name] = bosses_data.pop(boss_name)
    save_bosses(bosses_data)
    await ctx.send(f"已將 **{boss_name}** 更名為 **{new_name}**。")

@bot.command()
@commands.has_permissions(administrator=True)
async def retime(ctx, name: str, new_time: int):
    boss_name = find_boss_by_name_or_alias(name)
    if not boss_name:
        await ctx.send(f"找不到王 '{name}'。")
        return
    bosses_data[boss_name]['respawn_min'] = new_time
    save_bosses(bosses_data)
    await ctx.send(f"已將 **{boss_name}** 的重生週期修改為 **{new_time}** 分鐘。")

@bot.group(invoke_without_command=True)
@commands.has_permissions(administrator=True)
async def tags(ctx):
    await ctx.send("請使用 `tags add` 或 `tags remove`。")

@tags.command(name='add')
@commands.has_permissions(administrator=True)
async def tags_add(ctx, name: str, *aliases_to_add):
    boss_name = find_boss_by_name_or_alias(name)
    if not boss_name:
        await ctx.send(f"找不到王 '{name}'。")
        return
    current_aliases = bosses_data[boss_name].get('aliases', [])
    for alias in aliases_to_add:
        if alias not in current_aliases:
            current_aliases.append(alias)
    bosses_data[boss_name]['aliases'] = current_aliases
    save_bosses(bosses_data)
    await ctx.send(f"已為 **{boss_name}** 新增別名: {', '.join(aliases_to_add)}。")

@tags.command(name='remove')
@commands.has_permissions(administrator=True)
async def tags_remove(ctx, name: str, *aliases_to_remove):
    boss_name = find_boss_by_name_or_alias(name)
    if not boss_name:
        await ctx.send(f"找不到王 '{name}'。")
        return
    current_aliases = bosses_data[boss_name].get('aliases', [])
    removed_aliases = []
    for alias in aliases_to_remove:
        if alias in current_aliases:
            current_aliases.remove(alias)
            removed_aliases.append(alias)
    bosses_data[boss_name]['aliases'] = current_aliases
    save_bosses(bosses_data)
    await ctx.send(f"已從 **{boss_name}** 移除別名: {', '.join(removed_aliases)}。")

@bot.command()
async def info(ctx, name: str = None):
    embed = discord.Embed(title="👑 王設定資料", color=discord.Color.orange())
    if name:
        boss_name = find_boss_by_name_or_alias(name)
        if not boss_name:
            await ctx.send(f"找不到王 '{name}'。")
            return
        data = bosses_data[boss_name]
        info_str = f"重生週期: {data['respawn_min']} 分鐘\n別名: {', '.join(data.get('aliases', ['無']))}"
        embed.add_field(name=boss_name, value=info_str, inline=False)
    else:
        if not bosses_data:
            await ctx.send("目前沒有任何王的設定資料。")
            return
        description = []
        for boss_name, data in bosses_data.items():
            aliases_str = ', '.join(data.get('aliases', [])) or '無'
            description.append(f"**{boss_name}**\n重生週期: {data['respawn_min']}分 | 別名: {aliases_str}")
        embed.description = "\n".join(description)
    await ctx.send(embed=embed)

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"指令缺少參數。請參考指令說明。")
    elif isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ 您沒有權限使用此指令。")
    elif isinstance(error, commands.CommandInvokeError):
        print(f"指令 '{ctx.command.name}' 發生錯誤: {error}")
    else:
        print(f"發生未處理的錯誤: {error}")

if __name__ == "__main__":
    if TOKEN:
        bot.run(TOKEN)
    else:
        print("錯誤：請在環境變數中設定 DISCORD_TOKEN。")
