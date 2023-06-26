import os
import sys
import asyncio
import traceback
import discord
import pickle
import aiofiles
from datetime import date
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(".env"))
GUILDS=["270768834405728258"]

async def string_dict(dictionary:dict, listed:bool = False):
    if listed:
        string = '\n'.join([f'- {k}: {v}' for k, v in dictionary.items()])
    else:
        string = ', '.join([f'{k}: {v}' for k, v in dictionary.items()])
    return string


async def print_return(statement):
    print(statement)
    return statement


class Pickler:
    def __init__(self, game):
        self.game = game

    @staticmethod
    async def process_pickle_queue(pickle_queue, PROCESS_WAIT_TIME, EMPTY_WAIT_TIME):
        while True:
            try:
                # If the queue is empty, sleep for a short time before checking again
                if pickle_queue.empty():
                    await asyncio.sleep(EMPTY_WAIT_TIME)
                    continue
                to_pickle = await pickle_queue.get()

                async with aiofiles.open("database.pickle","wb",
                ) as f:
                    await f.write(pickle.dumps(to_pickle.game))

                await asyncio.sleep(PROCESS_WAIT_TIME)
            except Exception:
                traceback.print_exc()


class Game:
    def __init__(self):
        self.users = {} # Dictionary to store users and their points
        self.weeks = {} # Dictionary to store weeks and bets
        self.week_options = {}
        self.winners = {} # Dictionary to store each weeks winner
        self.betting_pool = {}# dictionary to store overall betting pool

    async def add_user(self, name:str):
        if name not in self.users:
            self.users[name] = 0


    async def set_options(self, week:int, users:list):
        self.week_options[week] = users
        for user in users:
            self.betting_pool[user] = 0
        return await print_return(f"Set {week} to {', '.join(users)}")
    

    async def give_points(self, user, points):
        self.users[user] += points
        return await print_return(f"Gave {points} fluxbux to {user}, they now have {self.users[user]} fluxbux")
    

    async def place_bet(self, week:int, user:str, bet_on:str, points:int):
        # Check if the user has enough points to bet
        if self.users[user] < points:
            return f"Not enough fluxbux to bet, you only have {self.users[user]} points"
        # Check if week exists in weeks dictionary
        if week not in self.weeks:
            self.weeks[week] = {}
        # Check if user exists in weeks dictionary
        if user not in self.weeks[week]:
            self.weeks[week][user] = {'bet_on': '', 'points': 0}
        # Update bet
        self.weeks[week][user]['bet_on'] = bet_on
        self.weeks[week][user]['points'] = points

        # Update betting pool
        if bet_on not in self.betting_pool:
            self.betting_pool[bet_on] = points
        else:
            self.betting_pool[bet_on] += points

        return_string = f"You bet {points} fluxbux on {bet_on} for week {week}"
        return await print_return(return_string)


    async def update_points(self, week:int, winner:str):
        total_pool = sum(self.betting_pool.values())
        if winner not in self.betting_pool:
            self.betting_pool[winner] = 0
        winner_pool = self.betting_pool[winner]
        outcomes = {}
        self.winners[week] = {'winner': winner, 'winner_pool': winner_pool, 'total_pool': total_pool, 'lost_fluxbux': total_pool-winner_pool}
        # Check if week exists in weeks dictionary
        if week in self.weeks:
            for user, bet in self.weeks[week].items():
                if bet['bet_on'] == winner:
                    odds = total_pool / winner_pool
                    payout = odds * bet['points']
                    self.users[user] += payout  # Add points to user
                    outcomes[user] = {'user': user, 'outcome': "won", 'balance': payout}
                else:
                    self.users[user] -= bet['points']  # Subtract points from user
                    outcomes[user] = {'user': user, 'outcome': "lost", 'balance': bet['points']}
        return_string = "The outcome of the gamble is:\n"
        for user, data in outcomes.items():
            return_string += f"- {data['user']} {data['outcome']} {data['balance']} fluxbux\n"
        return await print_return(return_string)


    async def print_status(self):
        return await print_return(f"Fluxbux listing:\n{await string_dict(self.users, True)}")

    
    async def print_winner(self, week:int):
        if week not in self.winners:
            return await print_return(f"No winner for week {week}")
        return await print_return(f"The winner for week {week} is:\n{await string_dict(self.winners[week], True)}")



class Commands(discord.Cog, name="Commands"):
    def __init__(self, bot, pickle_queue):
        self.game: Game = None
        self.bot: discord.bot = bot
        self.pickle_queue = pickle_queue
        self.current_week = date.today().isocalendar().week

    @discord.Cog.listener()
    async def on_ready(self):
        try:
            with open("database.pickle", "rb") as f:
                self.game: Game = pickle.load(f)
                print("Loaded game")
            assert isinstance(self.game, Game)
        except Exception:
            self.game: Game = Game()
            print("Started a new game")

        print("Starting pickle loop")
        while True:
            await asyncio.sleep(15)
            await self.pickle_queue.put(Pickler(self.game))

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
    )
    @discord.option(
        name="options",
        description="Set the users to be able to bet on",
        required=True,
    )
    @discord.guild_only()
    async def start_bet(self, ctx: discord.ApplicationContext, options:str):
        await ctx.defer()
        if self.game is None:
            await ctx.respond("No game is running")
            return
        options = [option.strip() for option in options.split(sep=",")]
        response = await self.game.set_options(self.current_week,options)
        await ctx.respond(response)


    @discord.slash_command(
        name="give",
        description="Give points",
        guild_ids=GUILDS,
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
        if self.game is None:
            await ctx.respond("No game is running")
            return
        await self.game.add_user(user.name)
        response = await self.game.give_points(user.name, fluxbux)
        await ctx.respond(response)


    @discord.slash_command(
        name="status",
        description="Start a betting round",
        guild_ids=GUILDS,
    )
    @discord.guild_only()
    async def status(self, ctx: discord.ApplicationContext):
        await ctx.defer()
        if self.game is None:
            await ctx.respond("No game is running")
            return
        response = await self.game.print_status()
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
    async def winner(self, ctx: discord.ApplicationContext, week:int):
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
        if self.game is None:
            await ctx.respond("No game is running")
            return
        await self.game.add_user(ctx.user.name)
        response = await self.game.place_bet(self.current_week, ctx.user.name, user, fluxbux)
        await ctx.respond(response)


    @discord.slash_command(
        name="play",
        description="Payout based on who won",
        guild_ids=GUILDS,
    )
    @discord.option(
        name="winner",
        description="Who won the game",
        required=True,
        autocomplete=bet_on_autocompleter,
    )
    @discord.guild_only()
    async def play(self, ctx: discord.ApplicationContext, winner: str):
        await ctx.defer()
        if self.game is None:
            await ctx.respond("No game is running")
            return
        response = await self.game.update_points(self.current_week, winner)
        await ctx.respond(response)


activity = discord.Activity(type=discord.ActivityType.watching, name="Let the fluxbux rain")
bot = discord.Bot(intents=discord.Intents.all(), command_prefix="!", activity=activity)

@bot.event
async def on_ready():
    print(f"We have logged in as {bot.user}")

async def main():
    pickle_queue = asyncio.Queue()
    asyncio.ensure_future(Pickler.process_pickle_queue(pickle_queue, 5, 1))
    bot.add_cog(Commands(bot, pickle_queue))
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