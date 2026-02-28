import discord
from discord.ext import commands
from discord import app_commands
import os
from datetime import datetime
import psycopg2
from psycopg2.extras import RealDictCursor

# ─────────────────────────────────────────
# SETTINGS
# ─────────────────────────────────────────
BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
ADMIN_ROLES = ["Admin", "CFI - Dev"]
ANNOUNCEMENT_CHANNEL_ID = 0
# ─────────────────────────────────────────

TIERS = [
    "Cosmic", "Universal", "Galaxy",
    "Global", "International",
    "Elite 1", "Elite 2", "Elite 3",
    "Gold 1", "Gold 2", "Gold 3",
    "Silver 1", "Silver 2", "Silver 3",
    "Bronze"
]

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# ─────────────────────────────────────────
# DATABASE
# ─────────────────────────────────────────
def get_db():
    conn = psycopg2.connect(os.environ.get("DATABASE_URL"), cursor_factory=RealDictCursor)
    return conn

def setup_db():
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS players (
            name TEXT PRIMARY KEY,
            tier TEXT NOT NULL,
            wins INTEGER DEFAULT 0,
            losses INTEGER DEFAULT 0,
            goals INTEGER DEFAULT 0,
            goals_against INTEGER DEFAULT 0,
            rank_in_tier INTEGER DEFAULT 0,
            round_wins INTEGER DEFAULT 0,
            round_losses INTEGER DEFAULT 0,
            round_done INTEGER DEFAULT 0
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS matches (
            id SERIAL PRIMARY KEY,
            player1 TEXT,
            player2 TEXT,
            score1 INTEGER,
            score2 INTEGER,
            date TEXT
        )
    """)
    conn.commit()
    conn.close()

# ─────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────
def is_admin():
    async def predicate(interaction: discord.Interaction):
        user_roles = [role.name for role in interaction.user.roles]
        if not any(r in user_roles for r in ADMIN_ROLES):
            await interaction.response.send_message("❌ You don't have admin permissions!", ephemeral=True)
            return False
        return True
    return app_commands.check(predicate)

def get_player(name: str):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM players WHERE name = %s", (name,))
    p = c.fetchone()
    conn.close()
    return dict(p) if p else None

def tier_index(tier: str):
    try:
        return TIERS.index(tier)
    except ValueError:
        return -1

def get_tier_players(tier: str):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM players WHERE tier = %s ORDER BY rank_in_tier ASC", (tier,))
    players = c.fetchall()
    conn.close()
    return [dict(p) for p in players]

def update_ranks_in_tier(tier: str):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT name, wins, losses FROM players WHERE tier = %s", (tier,))
    players = [dict(p) for p in c.fetchall()]

    def score(p):
        total = p["wins"] + p["losses"]
        return p["wins"] / total if total > 0 else 0

    sorted_players = sorted(players, key=score, reverse=True)
    for i, p in enumerate(sorted_players):
        c.execute("UPDATE players SET rank_in_tier = %s WHERE name = %s", (i + 1, p["name"]))
    conn.commit()
    conn.close()

def get_valid_matchups(tier: str):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM players WHERE tier = %s AND round_done = 0", (tier,))
    players = [dict(p) for p in c.fetchall()]
    conn.close()

    groups = {}
    for p in players:
        key = (p["round_wins"], p["round_losses"])
        if key not in groups:
            groups[key] = []
        groups[key].append(p["name"])

    matchups = []
    for key, names in groups.items():
        if len(names) >= 2:
            matchups.append((names[0], names[1], key))

    return matchups

async def send_announcement(message: str):
    if ANNOUNCEMENT_CHANNEL_ID and ANNOUNCEMENT_CHANNEL_ID != 0:
        channel = bot.get_channel(ANNOUNCEMENT_CHANNEL_ID)
        if channel:
            await channel.send(message)

# ─────────────────────────────────────────
# SLASH COMMANDS
# ─────────────────────────────────────────

async def tier_autocomplete(interaction: discord.Interaction, current: str):
    return [
        app_commands.Choice(name=tier, value=tier)
        for tier in TIERS if current.lower() in tier.lower()
    ]

@tree.command(name="addplayer", description="Add a player to a tier (admin only)")
@is_admin()
@app_commands.describe(player="Select a Discord user", tier="Select a tier", rank="Rank in tier 1-4 (optional)")
@app_commands.autocomplete(tier=tier_autocomplete)
async def addplayer(interaction: discord.Interaction, player: discord.Member, tier: str, rank: int = None):
    tier = tier.title()
    if tier not in TIERS:
        await interaction.response.send_message("❌ Invalid tier!", ephemeral=True)
        return

    players_in_tier = get_tier_players(tier)
    if len(players_in_tier) >= 4:
        await interaction.response.send_message(f"❌ **{tier}** is full! (max 4 players)", ephemeral=True)
        return

    name = str(player.id)
    display = player.display_name

    if get_player(name):
        await interaction.response.send_message(f"❌ **{display}** already exists!", ephemeral=True)
        return

    if rank is None:
        rank = len(players_in_tier) + 1

    if rank < 1 or rank > 4:
        await interaction.response.send_message("❌ Rank must be between 1 and 4!", ephemeral=True)
        return

    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT INTO players (name, tier, rank_in_tier) VALUES (%s, %s, %s)", (name, tier, rank))
    conn.commit()
    conn.close()
    await interaction.response.send_message(f"✅ **{display}** added to **{tier}** as rank {rank}!")

@tree.command(name="removeplayer", description="Remove a player (admin only)")
@is_admin()
@app_commands.describe(player="Select a Discord user")
async def removeplayer(interaction: discord.Interaction, player: discord.Member):
    name = str(player.id)
    display = player.display_name
    if not get_player(name):
        await interaction.response.send_message(f"❌ **{display}** not found!", ephemeral=True)
        return
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM players WHERE name = %s", (name,))
    conn.commit()
    conn.close()
    await interaction.response.send_message(f"🗑️ **{display}** removed.")

@tree.command(name="score", description="Submit a match score (admin only)")
@is_admin()
@app_commands.describe(
    player1="Select player 1",
    goals1="Goals scored by player 1",
    player2="Select player 2",
    goals2="Goals scored by player 2"
)
async def score(interaction: discord.Interaction, player1: discord.Member, goals1: int, player2: discord.Member, goals2: int):
    await interaction.response.defer()

    name1 = str(player1.id)
    name2 = str(player2.id)

    p1 = get_player(name1)
    p2 = get_player(name2)

    if not p1:
        await interaction.followup.send(f"❌ **{name1}** not found!")
        return
    if not p2:
        await interaction.followup.send(f"❌ **{name2}** not found!")
        return
    if goals1 == goals2:
        await interaction.followup.send("❌ Draws are not allowed!")
        return

    if (p1["round_wins"], p1["round_losses"]) != (p2["round_wins"], p2["round_losses"]):
        await interaction.followup.send(
            f"❌ **{name1}** ({p1['round_wins']}W/{p1['round_losses']}L) and **{name2}** ({p2['round_wins']}W/{p2['round_losses']}L) don't have the same round record and can't face each other yet!"
        )
        return

    if p1["round_done"] or p2["round_done"]:
        await interaction.followup.send("❌ One of these players is already done with this round!")
        return

    winner_name = name1 if goals1 > goals2 else name2
    loser_name = name2 if goals1 > goals2 else name1
    winner_goals = max(goals1, goals2)
    loser_goals = min(goals1, goals2)

    conn = get_db()
    c = conn.cursor()
    c.execute(
        "INSERT INTO matches (player1, player2, score1, score2, date) VALUES (%s, %s, %s, %s, %s)",
        (name1, name2, goals1, goals2, datetime.now().isoformat())
    )

    c.execute("""
        UPDATE players SET wins = wins + 1, goals = goals + %s, goals_against = goals_against + %s,
        round_wins = round_wins + 1 WHERE name = %s
    """, (winner_goals, loser_goals, winner_name))
    c.execute("""
        UPDATE players SET losses = losses + 1, goals = goals + %s, goals_against = goals_against + %s,
        round_losses = round_losses + 1 WHERE name = %s
    """, (loser_goals, winner_goals, loser_name))

    conn.commit()

    c.execute("SELECT * FROM players WHERE name = %s", (winner_name,))
    winner = dict(c.fetchone())
    c.execute("SELECT * FROM players WHERE name = %s", (loser_name,))
    loser = dict(c.fetchone())

    promo_msg = ""
    demo_msg = ""

    if winner["round_wins"] >= 2:
        c.execute("UPDATE players SET round_done = 1 WHERE name = %s", (winner_name,))
        promo_msg = f"\n🎉 **{winner_name}** has 2 wins — **PROMOTION** incoming! Use `/updatetier {winner['tier']}` to process."

    if loser["round_losses"] >= 2:
        c.execute("UPDATE players SET round_done = 1 WHERE name = %s", (loser_name,))
        demo_msg = f"\n📉 **{loser_name}** has 2 losses — **DEMOTION** incoming! Use `/updatetier {loser['tier']}` to process."

    conn.commit()
    conn.close()

    update_ranks_in_tier(p1["tier"])

    msg = f"⚽ **Match Result**\n"
    msg += f"🏆 **{winner_name}** {winner_goals} - {loser_goals} **{loser_name}**\n"
    msg += f"\n📊 **Round Standings — {p1['tier']}:**\n"

    tier_players = get_tier_players(p1["tier"])
    for p in tier_players:
        status = "✅ Done" if p["round_done"] else "🎮 Active"
        msg += f"• <@{p['name']}>: {p['round_wins']}W / {p['round_losses']}L — {status}\n"

    msg += promo_msg
    msg += demo_msg

    matchups = get_valid_matchups(p1["tier"])
    if matchups:
        msg += f"\n⚔️ **Next valid matchup(s):**\n"
        for m in matchups:
            msg += f"• **{m[0]}** vs **{m[1]}** ({m[2][0]}W/{m[2][1]}L each)\n"

    await interaction.followup.send(msg)

@tree.command(name="updatetier", description="Process promos and demos for a tier (admin only)")
@is_admin()
@app_commands.describe(tier="Select a tier")
@app_commands.autocomplete(tier=tier_autocomplete)
async def updatetier(interaction: discord.Interaction, tier: str):
    await interaction.response.defer()

    tier = tier.title()
    if tier not in TIERS:
        await interaction.followup.send("❌ Invalid tier!")
        return

    players = get_tier_players(tier)
    if not players:
        await interaction.followup.send(f"❌ No players found in **{tier}**!")
        return

    results = []
    conn = get_db()
    c = conn.cursor()

    for p in players:
        name = p["name"]
        rw = p["round_wins"]
        rl = p["round_losses"]

        if rw >= 2:
            current_idx = tier_index(p["tier"])
            if current_idx > 0:
                new_tier = TIERS[current_idx - 1]
                c.execute(
                    "UPDATE players SET tier = %s, round_wins = 0, round_losses = 0, round_done = 0 WHERE name = %s",
                    (new_tier, name)
                )
                results.append(f"🎉 **PROMOTION!** {name} → **{new_tier}**")
            else:
                c.execute("UPDATE players SET round_wins = 0, round_losses = 0, round_done = 0 WHERE name = %s", (name,))
                results.append(f"🏅 {name} is already in the highest tier! Round reset.")
        elif rl >= 2:
            current_idx = tier_index(p["tier"])
            if current_idx < len(TIERS) - 1:
                new_tier = TIERS[current_idx + 1]
                c.execute(
                    "UPDATE players SET tier = %s, round_wins = 0, round_losses = 0, round_done = 0 WHERE name = %s",
                    (new_tier, name)
                )
                results.append(f"📉 **DEMOTION!** {name} → **{new_tier}**")
            else:
                c.execute("UPDATE players SET round_wins = 0, round_losses = 0, round_done = 0 WHERE name = %s", (name,))
                results.append(f"⚠️ {name} is already in the lowest tier! Round reset.")
        else:
            c.execute("UPDATE players SET round_wins = 0, round_losses = 0, round_done = 0 WHERE name = %s", (name,))
            results.append(f"➡️ {name}: {rw}W / {rl}L — no change. Round reset.")

    conn.commit()
    conn.close()

    for t in TIERS:
        update_ranks_in_tier(t)

    embed = discord.Embed(title=f"🔄 Tier Update — {tier}", color=0xff9900)
    embed.description = "\n".join(results)
    embed.set_footer(text="Round stats reset. New round can begin!")

    await interaction.followup.send(embed=embed)
    await send_announcement(embed.description)

@tree.command(name="bracket", description="View the current round bracket for a tier")
@app_commands.describe(tier="Select a tier")
@app_commands.autocomplete(tier=tier_autocomplete)
async def bracket(interaction: discord.Interaction, tier: str):
    tier = tier.title()
    if tier not in TIERS:
        await interaction.response.send_message("❌ Invalid tier!", ephemeral=True)
        return

    players = get_tier_players(tier)
    if not players:
        await interaction.response.send_message(f"**{tier}** is empty.")
        return

    embed = discord.Embed(title=f"⚔️ Round Bracket — {tier}", color=0xff4444)

    lines = []
    for p in players:
        if p["round_done"]:
            if p["round_wins"] >= 2:
                status = "✅ PROMO (2W)"
            else:
                status = "❌ DEMO (2L)"
        else:
            status = f"🎮 {p['round_wins']}W / {p['round_losses']}L"
        lines.append(f"**{p['name']}** — {status}")

    embed.description = "\n".join(lines)

    matchups = get_valid_matchups(tier)
    if matchups:
        next_matches = "\n".join([f"• **{m[0]}** vs **{m[1]}**" for m in matchups])
        embed.add_field(name="⚔️ Next Matchup(s)", value=next_matches, inline=False)
    else:
        active = [p for p in players if not p["round_done"]]
        if not active:
            embed.add_field(name="✅ Round Complete!", value="Use `/updatetier` to process promos and demos.", inline=False)
        else:
            embed.add_field(name="⏳ Waiting...", value="Not enough players with the same record to make a match yet.", inline=False)

    embed.set_footer(text="2 wins = Promo | 2 losses = Demo")
    await interaction.response.send_message(embed=embed)

@tree.command(name="tier", description="View all players in a tier")
@app_commands.describe(tier="Select a tier")
@app_commands.autocomplete(tier=tier_autocomplete)
async def view_tier(interaction: discord.Interaction, tier: str):
    tier = tier.title()
    if tier not in TIERS:
        await interaction.response.send_message("❌ Invalid tier!", ephemeral=True)
        return

    players = get_tier_players(tier)
    if not players:
        await interaction.response.send_message(f"**{tier}** is empty.")
        return

    embed = discord.Embed(title=f"🏅 {tier}", color=0x00aaff)
    lines = []
    for p in players:
        total = p["wins"] + p["losses"]
        winrate = round((p["wins"] / total * 100)) if total > 0 else 0
        lines.append(f"**Rank {p['rank_in_tier']} — {p['name']}**\nW: {p['wins']} | L: {p['losses']} | Goals: {p['goals']} | Winrate: {winrate}%")
    embed.description = "\n\n".join(lines)
    await interaction.response.send_message(embed=embed)

@tree.command(name="profile", description="View a player's profile")
@app_commands.describe(player="Select a player")
async def profile(interaction: discord.Interaction, player: discord.Member):
    uid = str(player.id)
    display_name = player.display_name
    p = get_player(uid)
    if not p:
        await interaction.response.send_message(f"❌ **{display_name}** not found!", ephemeral=True)
        return

    total = p["wins"] + p["losses"]
    winrate = round((p["wins"] / total * 100)) if total > 0 else 0

    embed = discord.Embed(title=f"⚽ {display_name}", color=0xffaa00)
    embed.set_thumbnail(url=player.display_avatar.url)
    embed.description = (
        f"**Tier:** {p['tier']} (Rank {p['rank_in_tier']})\n"
        f"**Wins:** {p['wins']}\n"
        f"**Losses:** {p['losses']}\n"
        f"**Goals Scored:** {p['goals']}\n"
        f"**Goals Against:** {p['goals_against']}\n"
        f"**Winrate:** {winrate}%\n"
        f"**Matches Played:** {total}"
    )
    await interaction.response.send_message(embed=embed)

@tree.command(name="alltiers", description="Overview of all tiers and their players")
async def alltiers(interaction: discord.Interaction):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM players ORDER BY rank_in_tier")
    all_players = [dict(p) for p in c.fetchall()]
    conn.close()

    if not all_players:
        await interaction.response.send_message("There are no players yet!")
        return

    embed = discord.Embed(title="🌍 All Tiers Overview", color=0x00ff88)
    tier_data = {}
    for p in all_players:
        if p["tier"] not in tier_data:
            tier_data[p["tier"]] = []
        tier_data[p["tier"]].append(p)

    for tier in TIERS:
        if tier in tier_data:
            lines = "\n".join([f"{p['rank_in_tier']}. <@{p['name']}>" for p in tier_data[tier]])
            embed.add_field(name=f"**{tier}**", value=lines, inline=False)

    await interaction.response.send_message(embed=embed)

# ─────────────────────────────────────────
# BOT EVENTS
# ─────────────────────────────────────────
@bot.event
async def on_ready():
    setup_db()
    await tree.sync()
    print(f"✅ Bot is online as {bot.user}!")
    print(f"📊 Database ready")
    print(f"🎮 Slash commands synced")

from flask import Flask
from threading import Thread

app = Flask(__name__)

@app.route("/")
def home():
    return "Bot is running!"

def run_web():
    app.run(host="0.0.0.0", port=8080)

Thread(target=run_web).start()
bot.run(BOT_TOKEN)
