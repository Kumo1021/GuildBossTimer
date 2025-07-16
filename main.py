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
GUILD_ID = int(os.getenv('GUILD_ID')) # 你的伺服器 ID
CHANNEL_ID = int(os.getenv('CHANNEL_ID')) # 要推播通知的頻道 ID
BOSS_FILE = 'bosses.json'
TIMEZONE = pytz.timezone('Asia/Taipei') # 設定時區為台灣

# --- Bot 初始化 ---
intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
# 注意：指令前綴已從 '!' 改為 'k'，以符合 'kb', 'kr' 等指令格式
# 您也可以繼續使用 '!'，只需將下一行的 'k' 改回 '!' 即可
bot = commands.Bot(command_prefix='k', intents=intents) 

# --- 資料處理 ---
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
    # 完全匹配優先
    for name in bosses_data:
        if query.lower() == name.lower():
            return name
    # 別名匹配
    for name, data in bosses_data.items():
        if query.lower() in [a.lower() for a in data.get('aliases', [])]:
            return name
    # 關鍵字部分匹配
    for name in bosses_data:
        if query.lower() in name.lower():
            return name
    return None

# --- 時間處理 ---
def parse_time_input(time_str):
    now = datetime.now(TIMEZONE)
    try:
        if len(time_str) == 4: # hhmm
            hour, minute = int(time_str[:2]), int(time_str[2:])
            target_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            # 如果設定的時間比現在早，則視為隔天
            if target_time < now:
                target_time += timedelta(days=1)
            return target_time
        elif len(time_str) == 8: # MMddhhmm
            month, day, hour, minute = int(time_str[:2]), int(time_str[2:4]), int(time_str[4:6]), int(time_str[6:])
            return now.replace(year=now.year, month=month, day=day, hour=hour, minute=minute, second=0, microsecond=0)
    except (ValueError, IndexError):
        return None
    return None

def format_datetime(dt):
    if dt:
        return dt.astimezone(TIMEZONE).strftime('%m-%d %H:%M')
    return "N/A"

# --- Bot 事件 ---
@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}!')
    check_respawn.start()

# --- 定時任務：檢查重生並推播 ---
@tasks.loop(minutes=1)
async def check_respawn():
    await bot.wait_until_ready()
    now = datetime.now(TIMEZONE)
    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        print(f"錯誤：找不到頻道 ID {CHANNEL_ID}")
        return

    notifications_sent_this_cycle = []
    for name, data in bosses_data.items():
        if data.get('next_spawn'):
            try:
                respawn_time = datetime.fromisoformat(data['next_spawn']).astimezone(TIMEZONE)
                time_diff = respawn_time - now
                
                # 推播條件：重生時間在未來 5 分鐘內
                if timedelta(minutes=0) < time_diff <= timedelta(minutes=5):
                    if name not in notifications_sent_this_cycle:
                         embed = discord.Embed(title="👑 Boss 即將重生！", description=f"**{name}** 即將在約 **5分鐘** 後重生！", color=discord.Color.gold())
                         embed.add_field(name="預計重生時間", value=format_datetime(respawn_time), inline=False)
                         embed.set_footer(text="請各位勇者做好準備！")
                         await channel.send(embed=embed)
                         notifications_sent_this_cycle.append(name) # 避免重複推播
            except (ValueError, TypeError):
                # 如果時間格式錯誤，跳過這個王
                continue


# --- 指令 ---

# 為了讓 `k [王]` 指令能運作，我們把主指令群組移除，直接建立 'k' 指令
@bot.command(name='k')
async def set_death_time(ctx, boss_query: str, time_str: str = None):
    """設定王的死亡時間。 `k [王名稱]` 或 `k [王名稱] [hhmm]`"""
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
    """列出王的重生時間表。 `kb all` 可列出全部。"""
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
        if days > 0:
            countdown += f"{days}天"
        if hours > 0:
            countdown += f"{hours}小時"
        countdown += f"{minutes}分鐘"

        description.append(f"**{name}**\n重生於: {format_datetime(respawn_time)} (剩餘: {countdown})")

    embed.description = "\n\n".join(description)
    await ctx.send(embed=embed)

@bot.command()
async def kr(ctx, boss_query: str, time_str: str):
    """直接指定下一次重生時間。 `kr [王] [hhmm]` 或 `kr [王] [MMddhhmm]`"""
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
    """清除王的死亡時間。 `all` 清除全部, `lost` 清除已錯過的。"""
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

@bot.command(name='restart', aliases=['!restart']) # 允許 !restart
@commands.has_permissions(administrator=True)
async def restart_all(ctx, time_str: str = None):
    """重置所有王的死亡時間為當前或指定時間。 `k!restart [hhmm]`"""
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

# --- 修改指令 (需要管理員權限) ---
@bot.command()
@commands.has_permissions(administrator=True)
async def add(ctx, name: str, respawn_min: int, *aliases):
    """新增王到名單。 `kadd [王名稱] [重生週期(分)] [別名1] [別名2]...`"""
    if name in bosses_data:
        await ctx.send(f"王 '{name}' 已存在。")
        return
    
    bosses_data[name] = {
        "respawn_min": respawn_min,
        "aliases": list(aliases),
        "next_spawn": None
    }
    save_bosses(bosses_data)
    await ctx.send(f"已新增王: **{name}** (重生週期: {respawn_min}分鐘, 別名: {', '.join(aliases) if aliases else '無'})")

@bot.command()
@commands.has_permissions(administrator=True)
async def remove(ctx, name: str):
    """從名單中移除王。 `kremove [王名稱]`"""
    boss_name = find_boss_by_name_or_alias(name)
    if not boss_name:
        await ctx.send(f"找不到王 '{name}'。")
        return
        
    del bosses_data[boss_name]
    save_bosses(bosses_data)
    await ctx.send(f"已移除王: **{boss_name}**。")
    
@bot.command()
@commands.has_permissions(administrator=True)
async def rename(ctx, old_name: str, new_name: str):
    """修改王的名稱。 `krename [舊王名] [新王名]`"""
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
    """修改王的重生週期。 `kretime [王名稱] [新重生週期(分)]`"""
    boss_name = find_boss_by_name_or_alias(name)
    if not boss_name:
        await ctx.send(f"找不到王 '{name}'。")
        return
        
    bosses_data[boss_name]['respawn_min'] = new_time
    save_bosses(bosses_data)
    await ctx.send(f"已將 **{boss_name}** 的重生週期修改為 **{new_time}** 分鐘。")

# --- 別名管理 (tags) ---
@bot.group(invoke_without_command=True)
@commands.has_permissions(administrator=True)
async def tags(ctx):
    await ctx.send("請使用 `ktags add` 或 `ktags remove`。")

@tags.command(name='add')
@commands.has_permissions(administrator=True)
async def tags_add(ctx, name: str, *aliases_to_add):
    """為王新增別名。 `ktags add [王名稱] [別名1] [別名2]...`"""
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
    """為王移除別名。 `ktags remove [王名稱] [別名1] [別名2]...`"""
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


# --- 王設定訊息 ---
@bot.command()
async def info(ctx, name: str = None):
    """列出王的設定資料。 `kinfo [王名稱]`"""
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


# --- 錯誤處理 ---
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        # 忽略找不到指令的錯誤，因為 'k' 本身就是一個指令
        return
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"指令缺少參數。請參考指令說明。 `k{ctx.command.name} {ctx.command.signature}`")
    elif isinstance(error, commands.MissingPermissions):
        await ctx.send("你沒有權限使用此指令。")
    elif isinstance(error, commands.CommandInvokeError):
        await ctx.send(f"執行指令時發生內部錯誤。")
        print(f"指令 '{ctx.command.name}' 發生錯誤: {error}")
    else:
        print(f"發生未處理的錯誤: {error}")

# --- 執行 Bot ---
if __name__ == "__main__":
    if TOKEN:
        bot.run(TOKEN)
    else:
        print("錯誤：請在環境變數中設定 DISCORD_TOKEN。")
