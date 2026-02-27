import discord
from discord.ext import commands
from discord import app_commands
import sqlite3
import os
from datetime import datetime

# ─────────────────────────────────────────
# SETTINGS - CHANGE THESE
# ─────────────────────────────────────────
BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
ADMIN_ROLE_NAME = "Admin"          # Name of your admin role in Discord
ANNOUNCEMENT_CHANNEL_ID = 0        # Channel ID for promo/demo announcements (0 = disabled)
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
# DATABASE SETUP
# ─────────────────────────────────────────
def get_db():
    conn = sqlite3.connect("inazuma.db")
    conn.row_factory = sqlite3.Row
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
            round_losses INTEGER DEFAULT 0
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS matches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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
# HELPER FUNCTIONS
# ─────────────────────────────────────────
def is_admin():
    async def predicate(interaction: discord.Interaction):
        role = discord.utils.get(interaction.user.roles, name=ADMIN_ROLE_NAME)
        if role is None:
            await interaction.response.send_message("❌ You don't have admin permissions!", ephemeral=True)
            return False
        return True
    return app_commands.check(predicate)

def get_player(name: str):
    conn = get_db()
    player = conn.execute("SELECT * FROM players WHERE name = ?", (name,)).fetchone()
    conn.close()
    return player

def tier_index(tier: str):
    try:
        return TIERS.index(tier)
    except ValueError:
        return -1

def get_tier_players(tier: str):
    conn = get_db()
    players = conn.execute(
        "SELECT * FROM players WHERE tier = ? ORDER BY rank_in_tier ASC",
        (tier,)
    ).fetchall()
    conn.close()
    return players

def update_ranks_in_tier(tier: str):
    conn = get_db()
    players = conn.execute(
        "SELECT name, wins, losses FROM players WHERE tier = ?", (tier,)
    ).fetchall()

    def score(p):
        total = p["wins"] + p["losses"]
        if total == 0:
            return 0
        return p["wins"] / total

    sorted_players = sorted(players, key=score, reverse=True)
    for i, p in enumerate(sorted_players):
        conn.execute("UPDATE players SET rank_in_tier = ? WHERE name = ?", (i + 1, p["name"]))
    conn.commit()
    conn.close()

async def send_announcement(message: str):
    if ANNOUNCEMENT_CHANNEL_ID and ANNOUNCEMENT_CHANNEL_ID != 0:
        channel = bot.get_channel(ANNOUNCEMENT_CHANNEL_ID)
        if channel:
            await channel.send(message)

# ─────────────────────────────────────────
# SLASH COMMANDS
# ─────────────────────────────────────────

@tree.command(name="addplayer", description="Add a player to a tier (admin only)")
@is_admin()
@app_commands.describe(name="Player name", tier="Tier name e.g. Gold 1")
async def addplayer(interaction: discord.Interaction, name: str, tier: str):
    tier = tier.title()
    if tier not in TIERS:
        await interaction.response.send_message(
            f"❌ Invalid tier! Choose from:\n{', '.join(TIERS)}", ephemeral=True
        )
        return

    players_in_tier = get_tier_players(tier)
    if len(players_in_tier) >= 4:
        await interaction.response.send_message(
            f"❌ **{tier}** is full! (max 4 players)", ephemeral=True
        )
        return

    existing = get_player(name)
    if existing:
        await interaction.response.send_message(f"❌ **{name}** already exists!", ephemeral=True)
        return

    rank = len(players_in_tier) + 1
    conn = get_db()
    conn.execute(
        "INSERT INTO players (name, tier, rank_in_tier) VALUES (?, ?, ?)",
        (name, tier, rank)
    )
    conn.commit()
    conn.close()

    await interaction.response.send_message(f"✅ **{name}** added to **{tier}** as rank {rank}!")

@tree.command(name="removeplayer", description="Remove a player (admin only)")
@is_admin()
@app_commands.describe(name="Player name")
async def removeplayer(interaction: discord.Interaction, name: str):
    player = get_player(name)
    if not player:
        await interaction.response.send_message(f"❌ **{name}** not found!", ephemeral=True)
        return

    conn = get_db()
    conn.execute("DELETE FROM players WHERE name = ?", (name,))
    conn.commit()
    conn.close()
    await interaction.response.send_message(f"🗑️ **{name}** removed.")

@tree.command(name="score", description="Submit a match score (admin only)")
@is_admin()
@app_commands.describe(
    player1="Name of player 1",
    goals1="Goals scored by player 1",
    player2="Name of player 2",
    goals2="Goals scored by player 2"
)
async def score(interaction: discord.Interaction, player1: str, goals1: int, player2: str, goals2: int):
    await interaction.response.defer()

    p1 = get_player(player1)
    p2 = get_player(player2)

    if not p1:
        await interaction.followup.send(f"❌ **{player1}** not found!")
        return
    if not p2:
        await interaction.followup.send(f"❌ **{player2}** not found!")
        return

    if goals1 == goals2:
        await interaction.followup.send("❌ Draws are not allowed in this system!")
        return

    winner = player1 if goals1 > goals2 else player2
    loser = player2 if goals1 > goals2 else player1
    winner_goals = max(goals1, goals2)
    loser_goals = min(goals1, goals2)

    conn = get_db()
    conn.execute(
        "INSERT INTO matches (player1, player2, score1, score2, date) VALUES (?, ?, ?, ?, ?)",
        (player1, player2, goals1, goals2, datetime.now().isoformat())
    )

    # Update overall stats and round stats
    conn.execute("""
        UPDATE players SET wins = wins + 1, goals = goals + ?, goals_against = goals_against + ?,
        round_wins = round_wins + 1
        WHERE name = ?
    """, (winner_goals, loser_goals, winner))
    conn.execute("""
        UPDATE players SET losses = losses + 1, goals = goals + ?, goals_against = goals_against + ?,
        round_losses = round_losses + 1
        WHERE name = ?
    """, (loser_goals, winner_goals, loser))

    conn.commit()
    conn.close()

    update_ranks_in_tier(dict(p1)["tier"])
    if dict(p1)["tier"] != dict(p2)["tier"]:
        update_ranks_in_tier(dict(p2)["tier"])

    # Show updated round progress for both players
    w = dict(get_player(winner))
    l = dict(get_player(loser))

    message = f"⚽ **Match Result**\n"
    message += f"🏆 **{winner}** {winner_goals} - {loser_goals} **{loser}**\n\n"
    message += f"📊 **Round Progress:**\n"
    message += f"📈 {winner}: {w['round_wins']}W / {w['round_losses']}L this round\n"
    message += f"📉 {loser}: {l['round_wins']}W / {l['round_losses']}L this round\n"
    message += f"\n💡 Use `/updatetier [tier]` when the round is done to process promos and demos."

    await interaction.followup.send(message)

@tree.command(name="updatetier", description="Process promos and demos for a tier based on round results (admin only)")
@is_admin()
@app_commands.describe(tier="Tier name e.g. Gold 1")
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

    for p in players:
        p = dict(p)
        name = p["name"]
        rw = p["round_wins"]
        rl = p["round_losses"]

        if rw >= 2:
            # Promo
            current_idx = tier_index(p["tier"])
            if current_idx > 0:
                new_tier = TIERS[current_idx - 1]
                conn.execute(
                    "UPDATE players SET tier = ?, round_wins = 0, round_losses = 0 WHERE name = ?",
                    (new_tier, name)
                )
                results.append(f"🎉 **PROMOTION!** {name} moved from **{p['tier']}** to **{new_tier}**!")
            else:
                conn.execute("UPDATE players SET round_wins = 0, round_losses = 0 WHERE name = ?", (name,))
                results.append(f"🏅 {name} already in the highest tier! Round reset.")
        elif rl >= 2:
            # Demo
            current_idx = tier_index(p["tier"])
            if current_idx < len(TIERS) - 1:
                new_tier = TIERS[current_idx + 1]
                conn.execute(
                    "UPDATE players SET tier = ?, round_wins = 0, round_losses = 0 WHERE name = ?",
                    (new_tier, name)
                )
                results.append(f"📉 **DEMOTION!** {name} moved from **{p['tier']}** to **{new_tier}**!")
            else:
                conn.execute("UPDATE players SET round_wins = 0, round_losses = 0 WHERE name = ?", (name,))
                results.append(f"⚠️ {name} already in the lowest tier! Round reset.")
        else:
            conn.execute("UPDATE players SET round_wins = 0, round_losses = 0 WHERE name = ?", (name,))
            results.append(f"➡️ {name}: {rw}W / {rl}L — no promo or demo. Round reset.")

    conn.commit()
    conn.close()

    # Recalculate ranks after moves
    update_ranks_in_tier(tier)
    for t in TIERS:
        update_ranks_in_tier(t)

    embed = discord.Embed(title=f"🔄 Tier Update — {tier}", color=0xff9900)
    embed.description = "\n".join(results)
    embed.set_footer(text="Round stats have been reset for all players in this tier.")

    await interaction.followup.send(embed=embed)
    await send_announcement(embed.description)

@tree.command(name="tier", description="View all players in a tier")
@app_commands.describe(tier="Tier name e.g. Gold 1")
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
    for p in players:
        p = dict(p)
        total = p["wins"] + p["losses"]
        winrate = round((p["wins"] / total * 100)) if total > 0 else 0

        embed.add_field(
            name=f"Rank {p['rank_in_tier']} — {p['name']}",
            value=f"W: {p['wins']} | L: {p['losses']} | Goals: {p['goals']} | Winrate: {winrate}% | This round: {p['round_wins']}W {p['round_losses']}L",
            inline=False
        )

    await interaction.response.send_message(embed=embed)

@tree.command(name="profile", description="View a player's profile")
@app_commands.describe(name="Player name")
async def profile(interaction: discord.Interaction, name: str):
    player = get_player(name)
    if not player:
        await interaction.response.send_message(f"❌ **{name}** not found!")
        return

    p = dict(player)
    total = p["wins"] + p["losses"]
    winrate = round((p["wins"] / total * 100)) if total > 0 else 0

    embed = discord.Embed(title=f"⚽ {name}", color=0xffaa00)
    embed.add_field(name="Tier", value=f"**{p['tier']}** (Rank {p['rank_in_tier']})", inline=True)
    embed.add_field(name="Wins", value=p["wins"], inline=True)
    embed.add_field(name="Losses", value=p["losses"], inline=True)
    embed.add_field(name="Goals Scored", value=p["goals"], inline=True)
    embed.add_field(name="Goals Against", value=p["goals_against"], inline=True)
    embed.add_field(name="Winrate", value=f"{winrate}%", inline=True)
    embed.add_field(name="Matches Played", value=total, inline=True)
    embed.add_field(name="This Round", value=f"{p['round_wins']}W / {p['round_losses']}L", inline=True)

    await interaction.response.send_message(embed=embed)

@tree.command(name="matchups", description="View matchups for a tier")
@app_commands.describe(tier="Tier name e.g. Gold 1")
async def matchups(interaction: discord.Interaction, tier: str):
    tier = tier.title()
    if tier not in TIERS:
        await interaction.response.send_message("❌ Invalid tier!", ephemeral=True)
        return

    players = get_tier_players(tier)
    if len(players) < 4:
        await interaction.response.send_message(
            f"❌ **{tier}** only has {len(players)}/4 players. Can't generate matchups yet."
        )
        return

    p = [dict(x) for x in players]
    embed = discord.Embed(title=f"⚔️ Matchups — {tier}", color=0xff4444)
    embed.add_field(
        name="Match 1",
        value=f"🥇 **{p[0]['name']}** (Rank 1) vs 🥉 **{p[2]['name']}** (Rank 3)",
        inline=False
    )
    embed.add_field(
        name="Match 2",
        value=f"🥈 **{p[1]['name']}** (Rank 2) vs 4️⃣ **{p[3]['name']}** (Rank 4)",
        inline=False
    )
    embed.add_field(
        name="🏆 Winners Round",
        value="Winner of Match 1 vs Winner of Match 2",
        inline=False
    )
    embed.add_field(
        name="💀 Losers Round",
        value="Loser of Match 1 vs Loser of Match 2",
        inline=False
    )
    embed.set_footer(text="Use /updatetier after all matches are done!")

    await interaction.response.send_message(embed=embed)

@tree.command(name="alltiers", description="Overview of all tiers and their players")
async def alltiers(interaction: discord.Interaction):
    conn = get_db()
    all_players = conn.execute("SELECT * FROM players ORDER BY rank_in_tier").fetchall()
    conn.close()

    if not all_players:
        await interaction.response.send_message("There are no players yet!")
        return

    embed = discord.Embed(title="🌍 All Tiers Overview", color=0x00ff88)

    tier_data = {}
    for p in all_players:
        p = dict(p)
        if p["tier"] not in tier_data:
            tier_data[p["tier"]] = []
        tier_data[p["tier"]].append(p)

    for tier in TIERS:
        if tier in tier_data:
            names = " | ".join([f"R{p['rank_in_tier']} {p['name']}" for p in tier_data[tier]])
            embed.add_field(name=f"**{tier}** ({len(tier_data[tier])}/4)", value=names, inline=False)

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

bot.run(BOT_TOKEN)
