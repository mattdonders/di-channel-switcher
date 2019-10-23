import os

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


class ChannelManagerClient(discord.Client):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # create the background task and run it in the background
        self.bg_task = self.loop.create_task(self.game_state_check())

    async def on_ready(self):
        guild = discord.utils.get(self.guilds, id=GUILD)
        print(f"{self.user} is connected to the following guild:\n" f"{guild.name} (id: {guild.id})")

        await self.change_presence(
            activity=discord.Activity(type=discord.ActivityType.watching, name="the channel permissions.")
        )


    async def get_schedule(self):
        print("Retrieving today's NHL daily schedule now.")
        async with aiohttp.ClientSession() as cs:
            async with cs.get("http://statsapi.web.nhl.com/api/v1/schedule?teamId=1") as r:
                return await r.json()  # returns dict

    async def game_state_check(self):
        await self.wait_until_ready()

        channel_notificiations = self.get_channel(CHANNEL_NOTIFICATIONS)

        while not self.is_closed():
            schedule = await self.get_schedule()
            num_games = schedule.get("totalGames")

            if num_games == 0:
                print("No game scheduled today - sleep for 24 hours and come back tomorrow!")
                await channel_notificiations.send("@here There is no game scheduled today - see you tomorrow!")
                await asyncio.sleep(SLEEP_NO_GAME)
                continue

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

                print(f"Sleeping for {sleep_time_ss - TIME_THRESHOLD} seconds (game_time - 1 hour) to switch the channels.")
                await asyncio.sleep(sleep_time_ss - TIME_THRESHOLD)
                await switch_to_gameday()
                print(f"Sleeping for {TIME_THRESHOLD + SLEEP_IN_GAME} seconds (1 hour + 10 minutes) to start checking again.")
                await asyncio.sleep(TIME_THRESHOLD + SLEEP_IN_GAME)
            else:
                game_state = game.get("status").get("abstractGameState")
                if game_state != "Final":
                    await asyncio.sleep(SLEEP_IN_GAME)
                else:
                    await channel_notificiations.send(
                        f"@here I have detected that today's game has ended. "
                        "I will be back in about 2.5 hours to switch the channels back."
                    )

                    print("Game ended - sleeping for 2.5 hours.")
                    await asyncio.sleep(SLEEP_END_GAME)
                    await switch_to_daily()
                    print("Channels are swithced - sleeping for ~8 hours for the schedule to refresh.")
                    await asyncio.sleep(SLEEP_REFRESH)


async def switch_to_gameday():
    print("Switching permissions to the Gameday channel.")
    channel_testing = client.get_channel(CHANNEL_TESTING)
    channel_daily = client.get_channel(CHANNEL_DEVILSDAILY)
    channel_gameday = client.get_channel(CHANNEL_GAMEDAY)

    guild = discord.utils.get(client.guilds, id=GUILD)
    role_everyone = guild.get_role(ROLE_EVERYONE)
    await channel_daily.send(
        f"One hour until game time - this channel is now **closed**. Please use {channel_gameday.mention}!"
    )
    await channel_daily.set_permissions(role_everyone, send_messages=False)

    await channel_gameday.send("This channel is now **open** until about 2.5 hours after the end of the game.")
    await channel_gameday.set_permissions(role_everyone, send_messages=True)


async def switch_to_daily():
    print("Switching permissions to the Devils Daily channel.")
    channel_testing = client.get_channel(CHANNEL_TESTING)
    channel_daily = client.get_channel(CHANNEL_DEVILSDAILY)
    channel_gameday = client.get_channel(CHANNEL_GAMEDAY)

    guild = discord.utils.get(client.guilds, id=GUILD)
    role_everyone = guild.get_role(ROLE_EVERYONE)
    await channel_gameday.send(
        f"Game over - this channel is now **closed**. Please head back over to {channel_daily.mention}!"
    )
    await channel_gameday.set_permissions(role_everyone, send_messages=False)

    await channel_daily.send("This channel is now **open** until next game.")
    await channel_daily.set_permissions(role_everyone, send_messages=True)


client = ChannelManagerClient()
client.run(TOKEN)

