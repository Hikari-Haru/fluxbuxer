import os
import sys
import asyncio
import traceback
import discord
import json
import aiofiles
from typing import Callable
from datetime import date
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(".env"))

GUILDS=os.getenv("GUILDS")
GUILDS=GUILDS.split(",") if "," in GUILDS else [GUILDS]
GUILDS=[int(guild) for guild in GUILDS]
OPERATOR_ROLE=os.getenv("OPERATOR_ROLE")

async def string_dict(dictionary:dict, listed:bool = False, bets:bool = False):
    if dictionary == {}:
        return "- None"
    if listed:
        string = '\n'.join([f'- {k}: {v}' for k, v in dictionary.items()])
    elif bets:
        string = '\n'.join([f"- {user}: {info['bet_on']} for {info['points']} fluxbux" for user, info in dictionary.items()])
    else:
        string = ', '.join([f'{k}: {v}' for k, v in dictionary.items()])
    return string


async def print_return(statement):
    print(statement)
    return statement


def check_operator_roles() -> Callable:
    async def inner(ctx: discord.ApplicationContext):
        if OPERATOR_ROLE == [None]:
            return True

        if not any(role.name.lower() in OPERATOR_ROLE for role in ctx.user.roles):
            await ctx.defer(ephemeral=True)
            await ctx.respond(
                f"You don't have permission, list of roles is {OPERATOR_ROLE}",
                ephemeral=True,
                delete_after=10,
            )
            return False
        return True

    return inner

class Jsonfy:
    def __init__(self, game):
        self.game = game

    @staticmethod
    async def process_json_queue(json_queue, PROCESS_WAIT_TIME, EMPTY_WAIT_TIME):
        while True:
            try:
                # If the queue is empty, sleep for a short time before checking again
                if json_queue.empty():
                    await asyncio.sleep(EMPTY_WAIT_TIME)
                    continue
                to_json = await json_queue.get()

                async with aiofiles.open("database.json", "w", encoding="utf-8") as f:
                    await f.write(json.dumps(await to_json.game.to_json(), indent=4))

                await asyncio.sleep(PROCESS_WAIT_TIME)
            except Exception:
                traceback.print_exc()


class Game:
    def __init__(self, users=None, weeks=None, week_options=None, winners=None, betting_pool=None):
        self.users = users if users is not None else {} # Dictionary to store users and their points
        self.weeks = weeks if weeks is not None else {} # Dictionary to store weeks and bets
        self.week_options = week_options if week_options is not None else {} # Dictionary of who you can bet on each week
        self.winners = winners if winners is not None else {} # Dictionary to store each weeks winner
        self.betting_pool = betting_pool if betting_pool is not None else {} # dictionary to store overall betting pool
        self.current_week = str(date.today().isocalendar().week)


    @classmethod
    def from_json(cls, json_str):
        data = json.loads(json_str)
        return cls(**data)
    

    async def to_json(self):
        return {
            'users': self.users,
            'weeks': self.weeks,
            'week_options': self.week_options,
            'winners': self.winners,
            'betting_pool': self.betting_pool
        }
    
    
    async def add_user(self, name:str):
        if name not in self.users:
            self.users[name] = 0


    async def set_options(self, week:str, option:list):
        self.week_options[week] = option
        # Check if a week is set up yet
        if week not in self.betting_pool:
            self.betting_pool[week] = {}
        # Add each user to the week as 0
        for user in option:
            self.betting_pool[week][user] = 0
        listed_users = '\n'.join("- " + user for user in option)
        return await print_return(f"Set week {week} to:\n{listed_users}")
    

    async def give_points(self, user, points):
        self.users[user] += points
        return await print_return(f"Gave {points} fluxbux to {user}, they now have {self.users[user]} fluxbux")
    

    async def place_bet(self, week:str, user:str, bet_on:str, points:int):
        # Check if this week has already finished
        if week in self.winners:
            return f"Week {week} has already been ran, you bet on {self.weeks.get(week).get(user).get('bet_on')}"
        # Check if the user has enough points to bet
        if self.users.get(user) < points:
            return f"Not enough fluxbux to bet, you only have {self.users[user]} points"
        # Check if week exists in weeks dictionary
        if week not in self.weeks:
            self.weeks[week] = {}
        # Check if user exists in weeks dictionary, if they do subtract their old points from the relevant points pool
        if user not in self.weeks.get(week):
            self.weeks[week][user] = {'bet_on': '', 'points': 0}
        else: 
            old_bet_on = self.weeks.get(week).get(user).get('bet_on')
            old_points = self.weeks.get(week).get(user).get('points')
            try:
                self.betting_pool[week][old_bet_on] -= old_points
            except Exception:
                traceback.print_exc()
        # Update bet
        self.weeks[week][user]['bet_on'] = bet_on
        self.weeks[week][user]['points'] = points

        # Update betting pool
        if bet_on not in self.betting_pool.get(week):
            self.betting_pool[week][bet_on] = points
        else:
            self.betting_pool[week][bet_on] += points

        return_string = f"{user} bet {points} fluxbux on {bet_on} for week {week}"
        return await print_return(return_string)


    async def update_points(self, week:str, winner:str):
        total_pool = sum(self.betting_pool.get(week).values())
        if total_pool == 0: # Check if there's any points put into this week
            return f"No bets have been made for week {week}"
        if winner not in self.betting_pool.get(week): # Set winner to have a pool of 0 on them if they don't exist as a precaution
            self.betting_pool[week][winner] = 0
        winner_pool = self.betting_pool.get(week).get(winner)
        outcomes = {}
        # Check if week exists in weeks dictionary
        if week in self.weeks:
            for user, bet in self.weeks.get(week).items():
                if bet.get('bet_on') == winner:
                    odds = total_pool / winner_pool
                    payout = odds * bet['points']
                    net = payout - bet['points'] # Remove gambled points from the total
                    self.users[user] += net  # Add points to user
                    outcomes[user] = {'user': user, 'outcome': "won", 'balance': payout}
                else:
                    self.users[user] -= bet['points']  # Subtract points from user
                    outcomes[user] = {'user': user, 'outcome': "lost", 'balance': bet['points']}
        return_string = "The outcome of the gamble is:\n"
        for user, data in outcomes.items():
            return_string += f"- {data['user']} {data['outcome']} {data['balance']} fluxbux\n"
        self.winners[week] = {'roll': winner, 'winner_pool': winner_pool, 'total_pool': total_pool, 'lost_fluxbux': total_pool-winner_pool}
        return await print_return(return_string)


    async def print_status(self, week):
        currency = await string_dict(self.users, listed=True)
        bets = await string_dict(self.weeks.get(week, {}), bets=True)
        return await print_return(f"Current fluxbux listing:\n{currency}\nBets for week {week}:\n{bets}")

    
    async def print_winner(self, week:str):
        if week not in self.winners:
            return await print_return(f"No roll for week {week}")
        return await print_return(f"The roll for week {week} is:\n{await string_dict(self.winners.get(week, self.current_week), listed=True)}")



class Commands(discord.Cog, name="Commands"):
    def __init__(self, bot, json_queue):
        self.game: Game = None
        self.bot: discord.bot = bot
        self.json_queue = json_queue
        self.current_week = str(date.today().isocalendar().week)

    @discord.Cog.listener()
    async def on_ready(self):
        try:
            with open("database.json", "r", encoding="utf-8") as f:
                json_data = json.dumps(json.load(f))
                self.game: Game = Game.from_json(json_data)
                print("Loaded game")
            assert isinstance(self.game, Game)
        except Exception:
            self.game: Game = Game()
            print("Started a new game")

        print("Starting json loop")
        while True:
            await asyncio.sleep(15)
            await self.json_queue.put(Jsonfy(self.game))

    async def bet_on_autocompleter(self, ctx: discord.AutocompleteContext):
        if self.game is None:
            await ctx.interaction.response.defer()
            return []
        users = self.game.week_options[self.current_week]
        return [user for user in users if user.startswith(ctx.value.lower())][:25]
    

    async def players_autocompleter(self, ctx: discord.AutocompleteContext):
        if self.game is None:
            await ctx.interaction.response.defer()
            return []
        users = self.game.users.keys()
        return [user for user in users if user.startswith(ctx.value.lower())][:25]


    @discord.slash_command(
        name="start_bet",
        description="Start a betting round",
        guild_ids=GUILDS,
        checks=[check_operator_roles()],
    )
    @discord.option(
        name="options",
        description="Set the users to be able to bet on",
        required=True,
    )
    @discord.guild_only()
    async def start_bet(self, ctx: discord.ApplicationContext, options:str):
        await ctx.defer()
        options = [option.strip() for option in options.split(sep=",")]
        response = await self.game.set_options(self.current_week,options)
        await ctx.respond(response)


    @discord.slash_command(
        name="give",
        description="Give points",
        guild_ids=GUILDS,
        checks=[check_operator_roles()],
    )
    @discord.option(
        name="user",
        description="Which user to give points to",
        required=True,
        autocomplete=players_autocompleter,
    )
    @discord.option(
        name="fluxbux",
        description="How many fluxbux to give",
        required=True
    )
    @discord.guild_only()
    async def give(self, ctx: discord.ApplicationContext, user:discord.User, fluxbux:int):
        await ctx.defer()
        await self.game.add_user(user.name)
        response = await self.game.give_points(user.name, fluxbux)
        await ctx.respond(response)


    @discord.slash_command(
        name="status",
        description="Start a betting round",
        guild_ids=GUILDS,
    )
    @discord.option(
        name="week",
        description="Which week to look up",
        required=False
    )
    @discord.guild_only()
    async def status(self, ctx: discord.ApplicationContext, week:str):
        await ctx.defer()
        if week is None:
            week = self.current_week
        response = await self.game.print_status(week)
        await ctx.respond(response)


    @discord.slash_command(
        name="winner",
        description="Start a betting round",
        guild_ids=GUILDS,
    )
    @discord.option(
        name="week",
        description="Which week to look up",
        required=False
    )
    @discord.guild_only()
    async def winner(self, ctx: discord.ApplicationContext, week:str):
        await ctx.defer()
        if week is None:
            week = self.current_week
        response = await self.game.print_winner(week)
        await ctx.respond(response)


    @discord.slash_command(
        name="bet",
        description="Bet on a person",
        guild_ids=GUILDS,
    )
    @discord.option(
        name="user",
        description="Which user to bet on",
        required=True,
        autocomplete=bet_on_autocompleter,
    )
    @discord.option(
        name="fluxbux",
        description="How much to bet",
        required=True,
    )
    @discord.guild_only()
    async def bet(
        self, ctx: discord.ApplicationContext, user:str, fluxbux:int
    ):
        await ctx.defer()
        await self.game.add_user(ctx.user.name)
        response = await self.game.place_bet(self.current_week, ctx.user.name, user, fluxbux)
        await ctx.respond(response)


    @discord.slash_command(
        name="gamble",
        description="Payout based on who won",
        guild_ids=GUILDS,
        checks=[check_operator_roles()],
    )
    @discord.option(
        name="winner",
        description="Who won the game",
        required=True,
        autocomplete=bet_on_autocompleter,
    )
    @discord.guild_only()
    async def gamble(self, ctx: discord.ApplicationContext, winner: str):
        await ctx.defer()
        response = await self.game.update_points(self.current_week, winner)
        await ctx.respond(response)


activity = discord.Activity(type=discord.ActivityType.playing, name="Let the fluxbux rain")
bot = discord.Bot(intents=discord.Intents.all(), command_prefix="!", activity=activity)

@bot.event
async def on_ready():
    print(f"We have logged in as {bot.user}")

@bot.event
async def on_application_command_error(
    ctx: discord.ApplicationContext, error: discord.DiscordException
):
    if isinstance(error, discord.CheckFailure):
        pass
    else:
        raise error

async def main():
    json_queue = asyncio.Queue()
    asyncio.ensure_future(Jsonfy.process_json_queue(json_queue, 5, 1))
    bot.add_cog(Commands(bot, json_queue))
    await bot.start(os.getenv("DISCORD_TOKEN"))


def init():
    try:
        asyncio.get_event_loop().run_until_complete(main())
    except KeyboardInterrupt:
        print("Caught keyboard interrupt")
    except Exception as e:
        traceback.print_exc()
        print(str(e))
    sys.exit(0)


if __name__ == "__main__":
    sys.exit(init())