import aiohttp
import asyncio
from discord.ext import commands
import discord
from urllib.parse import urlencode
import json

with open("auth.json") as wf:
    auth = json.load(wf)


class Bot(commands.Bot):
    BEARER_TOKEN = None
    PUBLIC_KEY = auth[1]
    PRIVATE_KEY = auth[2]

    started = False

    def __init__(self):
        super().__init__("c!")
        self.session = aiohttp.ClientSession(loop=self.loop)
        self.cmdobj = Commands(self)
        self.add_cog(self.cmdobj)

    async def on_ready(self):
        if not self.started:
            self.loop.create_task(self.refresh())
            self.started = True

    async def refresh(self):
        while True:
            response = await self.session.get(
                "https://api.tcgplayer.com/token",
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    # f"X-Tcg-Access-Token": "{self.ACCESS_TOKEN}"
                },
                data=urlencode({
                    "grant_type": "client_credentials",
                    "client_id": self.PUBLIC_KEY,
                    "client_secret": self.PRIVATE_KEY
                })
            )
            data = await response.json()
            self.BEARER_TOKEN = data["access_token"]
            assert data["userName"].lower() == self.PUBLIC_KEY.lower()
            await self.cmdobj.prep()
            await asyncio.sleep(data["expires_in"])


class Commands:
    def __init__(self, bot):
        self.bot = bot

    API_BASE = "http://api.tcgplayer.com/v1.10.0"
    manifests: dict
    categories: dict
    POKEMON_ID: int
    MAGIC_ID: int
    YUGIOH_ID: int

    async def prep(self):
        self.manifests = {}

        response = await self.bot.session.get(
            f"{self.API_BASE}/catalog/categories",
            headers={
                "Authorization": f"bearer {self.bot.BEARER_TOKEN}",
                "Accept": "application/json"
            },
            params={"limit": 60}
        )
        rjson = await response.json()

        self.categories = {v["name"]: v["categoryId"] for v in rjson["results"]}
        self.POKEMON_ID = self.categories["Pokemon"]
        self.MAGIC_ID = self.categories["Magic"]
        self.YUGIOH_ID = self.categories["YuGiOh"]

        for id in [self.POKEMON_ID, self.MAGIC_ID, self.YUGIOH_ID]:
            response = await self.bot.session.get(
                f"{self.API_BASE}/catalog/categories/{id}/search/manifest",
                headers={
                    "Authorization": f"bearer {self.bot.BEARER_TOKEN}"
                },
            )
            self.manifests[id] = await response.json()

    @commands.command()
    async def sorting(self, ctx, game: str):
        """See available sorting options for a game. Usage: c!sorting Pokemon"""
        if game not in self.categories:
            await ctx.send("That is not a valid game!")
            return

        CAT_ID = self.categories[game]
        manifest = self.manifests[CAT_ID]
        sorting = manifest["results"][0]["sorting"]

        embed = discord.Embed(description="When using the search command, use the values to choose the search sorting")
        for item in sorting:
            embed.add_field(name=item["text"], value=item["value"])

        await ctx.send(embed=embed)

    @commands.command()
    async def search(self, ctx, query: str, game: str = "Pokemon",
                     sort_type: str = "Relevance",
                     rarity: str = None, category: str = None):
        """Query the database for a card. Usage `c!search "Ho-Oh GX (Full Art)"`
        `c!search "Extremely Slow Zombie" Magic` """
        filters = [
            {"name": "productName", "values": [query]}
        ]
        if rarity is not None:
            filters.append({"name": "Rarity", "values": [i.replace("_", " ") for i in rarity.split()]})

        if category is not None:
            filters.append({"name": "Category", "values": [i.replace("_", " ") for i in category.split()]})

        resp = await ctx.bot.session.post(
            f"{self.API_BASE}/catalog/categories/{self.categories[game]}/search",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"bearer {self.bot.BEARER_TOKEN}"
            },
            data=json.dumps({
                "sort": sort_type,
                "filters": filters
            })
        )
        data = await resp.json()
        # ids = data['results'][0]

        pricedata = await ctx.bot.session.get(
            f"{self.API_BASE}/pricing/product/" + ",".join(str(x) for x in data['results']),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"bearer {self.bot.BEARER_TOKEN}"
            },
        )

        listdata = await ctx.bot.session.get(
            f"{self.API_BASE}/catalog/products/" + ",".join(str(x) for x in data['results']),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"bearer {self.bot.BEARER_TOKEN}"
            },
        )

        pricejson = await pricedata.json()
        pricejson['results'].sort(key=lambda x: data['results'].index(x['productId']))

        listjson = await listdata.json()
        listjson['results'].sort(key=lambda x: data['results'].index(x['productId']))
        emotes = "\u25c0\u25b6\u274c"

        card = listjson['results'][0]
        cardprice = pricejson['results'][0]
        print(cardprice)
        embed = discord.Embed(title=f"{card['productName']} [Item {1}/{len(data['results'])}]", url=card['url'])
        embed.set_image(url=card['image'])
        embed.add_field(name="Pack", value=card['group']['name'])
        embed.add_field(name="Type", value=card['group']['abbreviation'])
        for item in card['extendedData']:
            embed.add_field(name=item['displayName'], value=item['value'])

        embed.add_field(name="Market Price", value=f"${cardprice['marketPrice']}")

        message = await ctx.send(embed=embed)

        index = 0

        for emote in emotes:
            await message.add_reaction(emote)

        def check(r, u):
            return r.message.id == message.id

        while True:
            try:
                r, u = await ctx.bot.wait_for('reaction_add', check=check, timeout=80)
            except asyncio.TimeoutError:
                await ctx.send("Timed out! Try again")
                return

            # if u not in [ctx.author, ctx.bot.user] or r.emoji not in emotes:
            if u != ctx.bot.user:
                try:
                    await message.remove_reaction(r.emoji, u)
                except:
                    pass
            else:
                continue

            if r.emoji == emotes[0]:
                if index == 0:
                    continue
                else:
                    embed.clear_fields()
                    index -= 1
                    for emote in emotes:
                        await message.add_reaction(emote)

            elif r.emoji == emotes[1]:
                if index == len(data['results']) - 1:
                    continue
                else:
                    embed.clear_fields()
                    index += 1
                    for emote in emotes:
                        await message.add_reaction(emote)

            elif r.emoji == emotes[2]:
                return

            card = listjson['results'][index]
            cardprice = pricejson['results'][index]
            print(cardprice)
            embed = discord.Embed(title=f"{card['productName']} [Item {index + 1}/{len(data['results'])}]",
                                  url=card['url'])
            embed.set_image(url=card['image'])
            embed.add_field(name="Pack", value=card['group']['name'])
            embed.add_field(name="Type", value=card['group']['abbreviation'])
            for item in card['extendedData']:
                embed.add_field(name=item['displayName'], value=item['value'])
            embed.add_field(name="Market Price", value=cardprice["marketPrice"])

            await message.edit(embed=embed)

    @commands.command()
    async def random(self, ctx):
        """View a random listing"""
        import random
        while True:
            listdata = await ctx.bot.session.get(
                f"{self.API_BASE}/catalog/products/" + str(random.randint(1, 100000)),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"bearer {self.bot.BEARER_TOKEN}"
                },
            )

            listjson = await listdata.json()
            if len(list('results')) > 0:
                card = listjson['results'][0]
                break

        embed = discord.Embed(title=card['productName'], url=card['url'])
        embed.set_image(url=card['image'])
        embed.add_field(name="Pack", value=card['group']['name'])
        embed.add_field(name="Type", value=card['group']['abbreviation'])
        for item in card['extendedData']:
            embed.add_field(name=item['displayName'], value=item['value'])

        await ctx.send(embed=embed)


bot = Bot()
bot.run(auth[0])
