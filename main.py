import os
import sys
import asyncio
import traceback
import discord
import json
import aiofiles
from typing import Callable, Tuple
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(".env"))

GUILDS = os.getenv("GUILDS")
GUILDS = GUILDS.split(",") if "," in GUILDS else [GUILDS]
GUILDS = [int(guild) for guild in GUILDS]
OPERATOR_ROLE = os.getenv("OPERATOR_ROLE")
OPERATOR_ID = os.getenv("OPERATOR_ID")


async def string_dict(dictionary: dict, listed: bool = False, bets: bool = False):
    if dictionary == {}:
        return "- **None**"
    if listed:
        string = "\n".join([f"- {k}: **{v}**" for k, v in dictionary.items()])
    elif bets:
        string = "\n".join(
            [
                f"- **{user}** bet on **{info['bet_on']}** for **{info['points']}** fluxbux"
                for user, info in dictionary.items()
            ]
        )
    else:
        string = ", ".join([f"{k}: {v}" for k, v in dictionary.items()])
    return string


async def print_return(statement):
    print(statement)
    return statement


def check_operator_roles() -> Callable:
    async def inner(ctx: discord.ApplicationContext):
        if OPERATOR_ROLE == [None]:
            return True
        if ctx.user.id == OPERATOR_ID:
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

                formatted_date = datetime.now().strftime("%Y-%m-%d")
                Path("backup").mkdir(exist_ok=True)

                try:
                    async with aiofiles.open(
                        "database.json", "w", encoding="utf-8"
                    ) as f:
                        await f.write(
                            json.dumps(await to_json.game.to_json(), indent=4)
                        )
                except Exception:
                    await asyncio.sleep(PROCESS_WAIT_TIME)
                    raise

                # Save a backup, this is not ran if the first save fails
                async with aiofiles.open(
                    f"backup/database_{formatted_date}.json", "w", encoding="utf-8"
                ) as f:
                    await f.write(json.dumps(await to_json.game.to_json(), indent=4))

                await asyncio.sleep(PROCESS_WAIT_TIME)
            except Exception:
                traceback.print_exc()


class Game:
    def __init__(self, users=None, user_map=None, weeks=None):
        self.users = (
            users if users is not None else {}
        )  # Dictionary to store users and their points
        self.user_map = (
            user_map if user_map is not None else {}
        )  # Dictionary to store users and their points
        self.weeks = (
            weeks if weeks is not None else {}
        )  # Dictionary to store weeks and bets
        self.current_week = str(date.today().isocalendar().week)

    @classmethod
    def from_json(cls, json_str):
        data = json.loads(json_str)
        return cls(**data)

    async def to_json(self):
        return {
            "users": self.users,
            "user_map": self.user_map,
            "weeks": self.weeks,
        }

    async def setup_week(self, week):
        if week not in self.weeks:
            self.weeks[week] = {}
        if "options" not in self.weeks[week]:
            self.weeks[week]["options"] = []
        if "result" not in self.weeks[week]:
            self.weeks[week]["result"] = {}
        if "betting_pool" not in self.weeks[week]:
            self.weeks[week]["betting_pool"] = {}
        if "bets" not in self.weeks[week]:
            self.weeks[week]["bets"] = {}
        if "claimed" not in self.weeks[week]:
            self.weeks[week]["claimed"] = {}

    async def add_user(self, name: str):
        if name not in self.users:
            self.users[name] = 0

    async def link(self, user: str, discord_user: discord.User):
        self.user_map[user] = discord_user.id

    async def set_options(self, week: str, options: list, reset: str):
        if reset == "full":
            self.weeks[week]["options"] = []
            self.weeks[week]["betting_pool"] = {}
            self.weeks[week]["bets"] = {}
            self.weeks[week]["result"] = {}
        if reset == "options":
            self.weeks[week]["options"] = []
        self.weeks[week]["options"] += options
        listed_users = "\n".join("- " + user for user in self.weeks[week]["options"])
        return await print_return(f"Set week {week} to:\n{listed_users}")

    async def give_points(self, user, points, week, button=False):
        await self.add_user(user)
        if not button:
            self.users[user] += points
            return await print_return(
                f"Gave {points} fluxbux to {user}, they now have {self.users[user]} fluxbux"
            )
        if button:
            if not self.weeks.get(week).get("claimed").get(user, False):
                self.weeks[week]["claimed"][user] = True
                self.users[user] += points
                return True
            return False

    async def place_bet(self, week: str, user: str, bet_on: str, points: int):
        try:
            await self.add_user(user)
            # Check if this week has already finished
            if self.weeks.get(week).get("result") != {}:
                return f"Week {week} has already been ran, you bet on {self.weeks.get(week).get('bets').get(user).get('bet_on')}"
            if points <= 0:
                return "You can't bet less than 0 points"
            # Check if the user has enough points to bet
            if self.users.get(user) < points:
                return f"Not enough fluxbux to bet, you only have {self.users[user]} fluxbux"
            # Check if bet_on is an option
            if bet_on not in self.weeks.get(week).get("options", ""):
                return f"{bet_on} is not a valid user to bet on"
            # Check if user exists in weeks dictionary, if they do subtract their old points from the relevant points pool
            if user not in self.weeks.get(week).get("bets"):
                self.weeks[week]["bets"][user] = {"bet_on": "", "points": 0}
            else:
                old_bet_on = self.weeks.get(week).get("bets").get(user).get("bet_on")
                old_points = self.weeks.get(week).get("bets").get(user).get("points")
                try:
                    self.weeks[week]["betting_pool"][old_bet_on] -= old_points
                except Exception:
                    traceback.print_exc()
            # Update bet
            self.weeks[week]["bets"][user]["bet_on"] = bet_on
            self.weeks[week]["bets"][user]["points"] = points

            # Update betting pool
            if bet_on not in self.weeks.get(week).get("betting_pool"):
                self.weeks[week]["betting_pool"][bet_on] = points
            else:
                self.weeks[week]["betting_pool"][bet_on] += points

            ratio = await self.get_payout_ratio(points)
            return_string = f"**{user}** bet **{points}** fluxbux on **{bet_on}** for a **{ratio}** payout ratio on week {week}"
            return await print_return(return_string)
        except Exception as e:
            return e

    async def update_points(self, week: str, roll: str):
        try:
            if week not in self.weeks:
                return await print_return("No game set up for this week")
            betting_pool = sum(
                self.weeks.get(week, {}).get("betting_pool", {}).values()
            )
            winner_pool = self.weeks.get(week).get("betting_pool").get(roll)
            if betting_pool == 0:
                return f"No bets have been made for week {week}"
            if roll not in self.weeks.get(week).get("betting_pool"):
                self.weeks[week]["betting_pool"][roll] = 0
            if "house" not in self.users:
                self.users["house"] = 0
            house_ratio = 0.05
            house_comission = 0
            house_loss = 0
            house_gain = 0
            incorrect_bets = 0
            correct_bets = 0
            payout_total = 0
            outcomes = {}
            # Check if week exists in weeks dictionary
            for user, bet in self.weeks.get(week).get("bets").items():
                if bet.get("bet_on") == roll:
                    ratio = await self.get_payout_ratio(points=bet["points"])
                    payout = bet["points"] * ratio
                    (payout, house_cut) = await self.house_payout(
                        points=payout, ratio=house_ratio
                    )
                    house_comission += house_cut
                    house_loss -= payout
                    payout_total += payout
                    self.users[user] += payout
                    correct_bets += 1
                    outcomes[user] = {"user": user, "outcome": "won", "balance": payout}
                elif bet.get("bet_on") != roll:
                    house_gain += bet["points"]
                    self.users[user] -= bet["points"]
                    incorrect_bets += 1
                    outcomes[user] = {
                        "user": user,
                        "outcome": "lost",
                        "balance": bet["points"],
                    }
            self.users["house"] += house_gain + house_loss
            winning_string = ""
            losing_string = ""
            for user, data in outcomes.items():
                if data["outcome"] == "won":
                    winning_string += f"- **{data['user']}** {data['outcome']} **{data['balance']}** fluxbux\n"
                else:
                    losing_string += f"- **{data['user']}** {data['outcome']} **{data['balance']}** fluxbux\n"
            winner_id = self.user_map.get(roll, roll)
            return_string = f"The winner is <@{winner_id}>\n**Winners:**\n{winning_string}**Losers**\n{losing_string}"
            self.weeks[week]["result"] = {
                ":tada: Winner": roll,
                ":white_check_mark: Correct bets": correct_bets,
                "<:redCross:1126317725497692221> Incorrect bets": incorrect_bets,
                ":moneybag: Total betting pool": betting_pool,
                ":moneybag: Winning pool": winner_pool,
                ":moneybag: Total payouts": payout_total,
                ":house: Total house comission on payouts": house_comission,
                ":house: Total fluxbux to house from lost bets": house_gain,
                ":house: Total fluxbux gone to the house": house_gain + house_loss,
            }
            return await print_return(return_string)
        except Exception as e:
            return e

    async def house_payout(self, points: int, ratio: float) -> Tuple[float, float]:
        payout = points - (points * ratio)
        house_gain = points * ratio
        return (payout, house_gain)

    async def get_payout_ratio(self, points: int) -> float:
        if points <= 100:
            return 2
        if 101 <= points <= 300:
            return 1.5
        # points > 300
        return 1

    async def print_status(self, week):
        currency = await string_dict(self.users, listed=True)
        bets = await string_dict(self.weeks.get(week, {}).get("bets", {}), bets=True)
        betting_pool = await string_dict(
            self.weeks.get(week, {}).get("betting_pool", {}), listed=True
        )
        return f":coin: Current fluxbux listing\n{currency}\n:bar_chart: Bets for week {week}\n{bets}\n:moneybag: Betting pool\n{betting_pool}"

    async def print_roll(self, week: str):
        if self.weeks.get(week, {}).get("result", {}) == {}:
            return f"No roll for week {week}"
        return f"The spin for week {week} is:\n{await string_dict(self.weeks.get(week, self.current_week)['result'], listed=True)}"


class Commands(discord.Cog, name="Commands"):
    def __init__(self, bot, json_queue):
        self.game: Game = None
        self.bot: discord.Bot = bot
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

        # setup giveaway views
        view = discord.ui.View(timeout=None)
        for week in self.game.weeks:
            view.add_item(PointButton(self.game, week))
        self.bot.add_view(view)

        print("Starting json and week setup loop")
        while True:
            await asyncio.sleep(15)
            await self.game.setup_week(self.current_week)
            await self.json_queue.put(Jsonfy(self.game))

    async def bet_on_autocompleter(self, ctx: discord.AutocompleteContext):
        if self.game is None:
            await ctx.interaction.response.defer()
            return []
        users = self.game.weeks[self.current_week]["options"]
        return [user for user in users if user.startswith(ctx.value.lower())][:25]

    async def players_autocompleter(self, ctx: discord.AutocompleteContext):
        if self.game is None:
            await ctx.interaction.response.defer()
            return []
        users = self.game.users.keys()
        return [user for user in users if user.startswith(ctx.value.lower())][:25]

    @discord.slash_command(
        name="set",
        description="Start a betting round",
        guild_ids=GUILDS,
        checks=[check_operator_roles()],
    )
    @discord.option(
        name="users",
        description="Set the users to be able to bet on",
        required=True,
    )
    @discord.option(
        name="reset",
        description="Reset bets",
        choices=["full", "options"],
        required=False,
        default=None,
    )
    @discord.guild_only()
    async def set(self, ctx: discord.ApplicationContext, users: str, reset: str):
        await ctx.defer()
        users = [option.strip() for option in users.split(sep=",")]
        response = await self.game.set_options(self.current_week, users, reset)
        await ctx.respond(response)

    @discord.slash_command(
        name="give",
        description="Give fluxbux",
        guild_ids=GUILDS,
        checks=[check_operator_roles()],
    )
    @discord.option(
        name="user",
        description="Which user to give fluxbux to",
        required=True,
        autocomplete=players_autocompleter,
    )
    @discord.option(
        name="fluxbux", description="How many fluxbux to give", required=True
    )
    @discord.guild_only()
    async def give(
        self, ctx: discord.ApplicationContext, user: discord.User, fluxbux: int
    ):
        await ctx.defer()
        response = await self.game.give_points(user.name, fluxbux, self.current_week)
        await ctx.respond(response)

    @discord.slash_command(
        name="status",
        description="Get fluxbux and the bets for the current week",
        guild_ids=GUILDS,
    )
    @discord.option(
        name="week", description="Which week to look up the bets for", required=False
    )
    @discord.guild_only()
    async def status(self, ctx: discord.ApplicationContext, week: str):
        await ctx.defer()
        if week is None:
            week = self.current_week
        response = await self.game.print_status(week)
        await ctx.respond(response)

    @discord.slash_command(
        name="results",
        description="Get results for a week",
        guild_ids=GUILDS,
    )
    @discord.option(name="week", description="Which week to look up", required=False)
    @discord.guild_only()
    async def results(self, ctx: discord.ApplicationContext, week: str):
        await ctx.defer()
        if week is None:
            week = self.current_week
        response = await self.game.print_roll(week)
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
        description="bux <= 100 = ratio 2, 101 <= bux <= 300 = ratio 1.5, bux > 300 = ratio 1",
        required=True,
    )
    @discord.guild_only()
    async def bet(self, ctx: discord.ApplicationContext, user: str, fluxbux: int):
        await ctx.defer()
        response = await self.game.place_bet(
            self.current_week, ctx.user.name, user, fluxbux
        )
        await ctx.respond(response)

    @discord.slash_command(
        name="payout",
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
    async def payout(self, ctx: discord.ApplicationContext, winner: str):
        await ctx.defer()
        response = await self.game.update_points(self.current_week, winner)
        await ctx.respond(response)

    @discord.slash_command(
        name="giveaway",
        description="Make a message which gives away fluxbux for 4 hours",
        guild_ids=GUILDS,
        checks=[check_operator_roles()],
    )
    @discord.option(
        name="week",
        description="Which week to give the fluxbux away as",
        required=False,
    )
    @discord.guild_only()
    async def giveaway(self, ctx: discord.ApplicationContext, week):
        await ctx.defer()
        if week is None:
            week = self.current_week
        if "claimed" not in self.game.weeks.get(week):
            self.game.weeks[week]["claimed"] = {}
        view = discord.ui.View(timeout=None)
        view.add_item(PointButton(self.game, week))
        await ctx.respond(
            f"Click the button to get 100 fluxbux for week {week}", view=view
        )

    @discord.slash_command(
        name="link",
        description="Link a user to a discord user",
        guild_ids=GUILDS,
        checks=[check_operator_roles()],
    )
    @discord.option(
        name="user",
        description="nickname to use",
        required=True,
    )
    @discord.option(
        name="discord_user",
        description="discord user to use",
        required=True,
    )
    async def link(
        self, ctx: discord.ApplicationContext, user: str, discord_user: discord.User
    ):
        await ctx.defer()
        await self.game.link(user, discord_user)
        await ctx.respond(f"Linked {user} and {discord_user.name}")


class PointButton(discord.ui.Button):
    def __init__(self, game, week):
        super().__init__(
            label="Get Fluxbux",
            style=discord.ButtonStyle.primary,
            custom_id=week,
        )
        self.game = game

    async def callback(self, interaction: discord.Interaction):
        user: discord.User = interaction.user
        game: Game = self.game
        week = str(self.custom_id)
        time_diff = datetime.now(timezone.utc) - interaction.message.created_at
        four_hours = timedelta(hours=4)

        if time_diff > four_hours:
            await interaction.response.send_message(
                "It's been more than 4 hours, this is now invalid", ephemeral=True
            )
            return

        gave_points = await game.give_points(
            user=user.name, points=100, week=week, button=True
        )
        if gave_points:
            await interaction.response.send_message(
                f"You got 100 fluxbux for week {week}", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"You've already gotten fluxbux for week {week}", ephemeral=True
            )


activity = discord.Activity(
    type=discord.ActivityType.playing, name="Let the fluxbux rain"
)
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
