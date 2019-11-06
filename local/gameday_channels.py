import logging
import os
import time
import sys

import aiohttp
import asyncio
import dateparser
import discord
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Keep all server-specific variables in a .env file (easier configuration)
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

logging.basicConfig(
    level=logging.INFO,
    datefmt="%Y-%m-%d %H:%M:%S",
    format="%(asctime)s - %(module)s.%(funcName)s - %(levelname)s - %(message)s",
)

# Non-Secret Items
GUILD = int(os.getenv("DISCORD_GUILD"))

CHANNEL_NOTIFICATIONS = int(os.getenv("DISCORD_CHANNEL_NOTIFICATIONS"))
# CHANNEL_NOTIFICATIONS = 513415230026547202
CHANNEL_TESTING = int(os.getenv("DISCORD_CHANNEL_TESTING"))
CHANNEL_DEVILSDAILY = int(os.getenv("DISCORD_CHANNEL_DEVILSDAILY"))
CHANNEL_GAMEDAY = int(os.getenv("DISCORD_CHANNEL_GAMEDAY"))

ROLE_EVERYONE = int(os.getenv("DISCORD_ROLE_EVERYONE"))

# Sleep Timers
SLEEP_NO_GAME = 86400  # 24 Hours
SLEEP_IN_GAME = 600  # 10 Minutes
SLEEP_END_GAME = 9000  # 2.5 Hours
SLEEP_REFRESH = 36000  # 10 Hours
TIME_THRESHOLD = 3600  # 1 Hour - Switch to Gameday Channel

# Get Global script date
script_date = datetime.now().strftime("%Y-%m-%d")

# Set global permission overwrites
open_overwrite = discord.PermissionOverwrite()
open_overwrite.send_messages = True

closed_overwrite = discord.PermissionOverwrite()
closed_overwrite.send_messages = False


class ChannelManager(discord.Client):
    def __init__(self, action=None, msg=None, channel_id=None, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.action = action
        self.msg =  msg
        self.channel_id = channel_id

    # This runs when the bot is ready -
    # Prints the connection info & changes activity.
    async def on_ready(self):
        guild = discord.utils.get(self.guilds, id=GUILD)
        logging.info("%s is connected to the %s server (id: %s).", self.user, guild.name, guild.id)

        await self.change_presence(
            activity=discord.Activity(type=discord.ActivityType.watching, name="the channel permissions.")
        )

        logging.info("Action: %s", self.action)
        logging.info("Message: %s", self.msg)
        logging.info("Channel ID: %s", self.channel_id)


        if self.action == "SENDMSG":
            await self.send_message(self.msg, self.channel_id)
            await self.logout()

        if self.action == "SWITCHTOGAMEDAY":
            await self.switch_to_gameday()
        elif self.action == "SWITCHTODAILY":
            await self.switch_to_daily()

        await self.logout()

    async def switch_to_gameday(self):
        guild = discord.utils.get(self.guilds, id=GUILD)
        role_everyone = guild.get_role(ROLE_EVERYONE)

        logging.info("Closing down the daily channel.")
        channel_daily = self.get_channel(CHANNEL_DEVILSDAILY)
        channel_gameday = self.get_channel(CHANNEL_GAMEDAY)

        await channel_daily.send(
            f"One hour until game time - this channel is now **closed**. Please use {channel_gameday.mention}!"
        )
        await channel_daily.set_permissions(role_everyone, overwrite=closed_overwrite)

        logging.info("Opening up the gameday channel.")
        await channel_gameday.set_permissions(role_everyone, overwrite=open_overwrite)
        await channel_gameday.send(
            "This channel is now **open** until about 2.5 hours after the end of the game."
        )


    async def switch_to_daily(self):
        guild = discord.utils.get(self.guilds, id=GUILD)
        role_everyone = guild.get_role(ROLE_EVERYONE)

        logging.info("Closing down the game day channel.")
        channel_gameday = self.get_channel(CHANNEL_GAMEDAY)
        channel_daily = self.get_channel(CHANNEL_DEVILSDAILY)

        await channel_gameday.send(
            f"Game over - this channel is now **closed**. Please head back over to {channel_daily.mention}!"
        )
        await channel_gameday.set_permissions(role_everyone, overwrite=closed_overwrite)

        logging.info("Re-opening the daily channel.")
        await channel_daily.set_permissions(role_everyone, overwrite=open_overwrite)
        await channel_daily.send("This channel is now **open** until next game.")


    async def send_message(self, msg, channel_id):
        channel = self.get_channel(channel_id)
        await channel.send(msg)


def get_nhl_schedule():
    schedule_url = f"http://statsapi.web.nhl.com/api/v1/schedule?teamId=1&date={script_date}&expand=schedule.linescore"
    r = requests.get(schedule_url).json()
    return r


if __name__ == "__main__":
    # Get the asyncio loop for running async/await functions
    loop = asyncio.get_event_loop()

    schedule = get_nhl_schedule()
    num_games = schedule.get("totalGames")

    if num_games == 0:
        logging.info("No game scheduled today - come back tomorrow!")
        client = ChannelManager(action='SENDMSG', msg="@here There is no game scheduled today - see you tomorrow!", channel_id=CHANNEL_NOTIFICATIONS)
        loop.run_until_complete(client.start(TOKEN))
        sys.exit()

    # If there are games today, get the start time details and setup our sleep schedule
    game = schedule.get("dates")[0].get("games")[0]
    game_date = game.get("gameDate")
    game_state = game.get("status").get("abstractGameState")

    game_date = dateparser.parse(game_date)
    now = datetime.now(game_date.tzinfo)

    if game_date > now:
        time_until_game = game_date - now
        sleep_time_ss = time_until_game.total_seconds()
        sleep_time_hh = round(sleep_time_ss / 3600)

        pregame_sleep_time = sleep_time_ss - TIME_THRESHOLD
        logging.info(
            f"Sleeping for %s seconds (game_time - 1 hour) to switch the channels.",
            pregame_sleep_time,
        )
        game_today_msg = (
            f"@here I have detected that there is a game today. I will sleep for about {sleep_time_hh} hours, "
            "switch the channels and then finish sleeping until game time. See you later!"
        )
        client = ChannelManager(action='SENDMSG', msg=game_today_msg, channel_id=CHANNEL_NOTIFICATIONS)
        loop.run_until_complete(client.start(TOKEN))
        time.sleep(pregame_sleep_time)

        # Temporarily open a Discord client to switch to the gameday channel
        logging.info("It is approximately 1 hour until game time, switch to the game day channel.")
        gameday_client = ChannelManager(action='SWITCHTOGAMEDAY')
        loop.run_until_complete(gameday_client.start(TOKEN))

        gamestart_sleep_time = TIME_THRESHOLD + SLEEP_IN_GAME
        logging.info(
            "Sleeping for %s seconds (1 hour + 10 minutes) to start checking again.",
            gamestart_sleep_time,
        )
        time.sleep(gamestart_sleep_time)

    while game_state != "Final":
        schedule = get_nhl_schedule()
        game = schedule.get("dates")[0].get("games")[0]
        game_date = game.get("gameDate")
        game_state = game.get("status").get("abstractGameState")

        logging.info("Game is not yet final (PERIOD/TIMELEFT), sleep 10 minutes and check again.")
        time.sleep(SLEEP_IN_GAME)

    # Now that we are out of Live game loop (& the game has gone Final), sleep for ~2.5 hours
    # Calculate if we had to re-run this script and we interrupted the previous sleep
    schedule = get_nhl_schedule()
    game = schedule.get("dates")[0].get("games")[0]
    game_end = game.get("linescore").get("periods")[-1].get("endTime")
    game_end = dateparser.parse(game_end)
    now = datetime.now(game_date.tzinfo)
    ss_since_end = (now - game_end).total_seconds()

    if ss_since_end > SLEEP_END_GAME:
        logging.info("2.5 hours has passed since game end (due to a script restart) - switch back to Daily.")
        daily_client = ChannelManager(action='SWITCHTODAILY')
        loop.run_until_complete(daily_client.start(TOKEN))
    else:
        endgame_sleep_time = SLEEP_END_GAME - ss_since_end
        logging.info(
            "Game ended - sleeping for 2.5 hours max (actual time - %s seconds).",
            endgame_sleep_time,
            )
        time.sleep(endgame_sleep_time)
        daily_client = ChannelManager(action='SWITCHTODAILY')
        loop.run_until_complete(daily_client.start(TOKEN))

    logging.info("Channels are swithced - script will restart tomorrow at 10AM to check again.")
    sys.exit()
