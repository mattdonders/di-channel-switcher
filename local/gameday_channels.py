import logging
import os
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



class ChannelManagerClient(discord.Client):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # create the background task and run it in the background
        self.bg_task = self.loop.create_task(self.game_state_check())

    async def on_ready(self):
        guild = discord.utils.get(self.guilds, id=GUILD)
        logging.info("%s is connected to the %s server (id: %s).", self.user, guild.name, guild.id)

        await self.change_presence(
            activity=discord.Activity(type=discord.ActivityType.watching, name="the channel permissions.")
        )


    async def get_schedule(self):
        logging.info("Retrieving today's NHL daily schedule now.")
        async with aiohttp.ClientSession() as cs:
            async with cs.get(f"http://statsapi.web.nhl.com/api/v1/schedule?teamId=1&date={script_date}&expand=schedule.linescore") as r:
                return await r.json()  # returns dict

    async def game_state_check(self):
        await self.wait_until_ready()

        channel_notificiations = self.get_channel(CHANNEL_NOTIFICATIONS)

        while not self.is_closed():
            schedule = await self.get_schedule()
            num_games = schedule.get("totalGames")

            if num_games == 0:
                logging.info("No game scheduled today - sleep for 24 hours and come back tomorrow!")
                await channel_notificiations.send("@here There is no game scheduled today - see you tomorrow!")
                # await asyncio.sleep(SLEEP_NO_GAME)
                # continue
                sys.exit()

            # If there are games today, get the start time details and setup our sleep schedule
            game = schedule.get("dates")[0].get("games")[0]
            game_date = game.get("gameDate")

            game_date = dateparser.parse(game_date)
            now = datetime.now(game_date.tzinfo)

            if game_date > now:
                time_until_game = game_date - now
                sleep_time_ss = time_until_game.total_seconds()
                sleep_time_hh = round(sleep_time_ss / 3600)
                await channel_notificiations.send(
                    f"@here I have detected that there is a game today. I will sleep for about {sleep_time_hh} hours, "
                    "switch the channels and then finish sleeping until game time. See you later!"
                )

                pregame_sleep_time = sleep_time_ss - TIME_THRESHOLD
                logging.info(f"Sleeping for %s seconds (game_time - 1 hour) to switch the channels.", pregame_sleep_time)
                await asyncio.sleep(pregame_sleep_time)
                await switch_to_gameday()
                gamestart_sleep_time = TIME_THRESHOLD + SLEEP_IN_GAME
                logging(f"Sleeping for %s seconds (1 hour + 10 minutes) to start checking again.", gamestart_sleep_time)
                await asyncio.sleep(gamestart_sleep_time)
            else:
                game_state = game.get("status").get("abstractGameState")
                if game_state != "Final":
                    logging.info("Game is not Final, current status : %s", game_state)
                    await asyncio.sleep(SLEEP_IN_GAME)
                else:
                    # Calculate if we had to re-run this script and we interrupted the previous sleep
                    game = schedule.get("dates")[0].get("games")[0]
                    game_end = game.get('linescore').get('periods')[-1].get('endTime')
                    game_end = dateparser.parse(game_end)
                    now = datetime.now(game_date.tzinfo)
                    ss_since_end = (now - game_end).total_seconds()

                    if ss_since_end > SLEEP_END_GAME:
                        await channel_notificiations.send(
                            f"@here I have detected that today's game has ended and 2.5 hours has passed. "
                            "I will switch the channels now!"
                        )
                        await switch_to_daily()
                    else:
                        endgame_sleep_time = SLEEP_END_GAME - ss_since_end

                        await channel_notificiations.send(
                            f"@here I have detected that today's game has ended. "
                            f"I will be back in a maximum of 2.5 hours (exactly - {int(endgame_sleep_time)} seconds) "
                            f"to switch the channels back."
                        )
                        logging.info("Game ended - sleeping for 2.5 hours max (actual time - %s seconds).", endgame_sleep_time)
                        await asyncio.sleep(endgame_sleep_time)
                        await switch_to_daily()

                    # logging.info("Channels are swithced - sleeping for ~8 hours for the schedule to refresh.")
                    # await asyncio.sleep(SLEEP_REFRESH)
                    logging.info("Channels are swithced - script will restart tomorrow at 10AM to check again.")
                    sys.exit()


async def switch_to_gameday():
    guild = discord.utils.get(client.guilds, id=GUILD)
    role_everyone = guild.get_role(ROLE_EVERYONE)

    logging.info("Closing down the daily channel.")
    channel_daily = client.get_channel(CHANNEL_DEVILSDAILY)
    channel_gameday = client.get_channel(CHANNEL_GAMEDAY)

    await channel_daily.send(
        f"One hour until game time - this channel is now **closed**. Please use {channel_gameday.mention}!"
    )
    await close_channel(channel_daily, role_everyone)

    logging.info("Opening up the gameday channel.")
    await channel_gameday.send("This channel is now **open** until about 2.5 hours after the end of the game.")
    await open_channel(channel_gameday, role_everyone)


async def switch_to_daily():
    guild = discord.utils.get(client.guilds, id=GUILD)
    role_everyone = guild.get_role(ROLE_EVERYONE)

    logging.info("Closing down the game day channel.")
    channel_gameday = client.get_channel(CHANNEL_GAMEDAY)
    channel_daily = client.get_channel(CHANNEL_DEVILSDAILY)

    await channel_gameday.send(
        f"Game over - this channel is now **closed**. Please head back over to {channel_daily.mention}!"
    )
    await close_channel(channel_gameday, role_everyone)

    logging.info("Re-opening the daily channel.")
    await channel_daily.send("This channel is now **open** until next game.")
    await open_channel(channel_daily, role_everyone)


async def open_channel(channel, role):
    open_overwrite = discord.PermissionOverwrite()
    open_overwrite.send_messages = True

    logging.info("A channel (name - %s) has been requested to be opened (role - %s).", channel.name, role.name)
    await channel.set_permissions(role, overwrite=open_overwrite)


async def close_channel(channel, role):
    closed_overwrite = discord.PermissionOverwrite()
    closed_overwrite.send_messages = False

    logging.info("A channel (name - %s) has been requested to be closed (role - %s).", channel.name, role.name)
    await channel.set_permissions(role, overwrite=closed_overwrite)


client = ChannelManagerClient()
client.run(TOKEN)