import io
import os
import json
import copy
import psutil
import random
import aiohttp
import asyncio
import discord
import datetime
from textwrap import indent
from collections import Counter
from traceback import format_exc
from discord.ext import commands
from urllib.parse import urlencode
from contextlib import redirect_stdout

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
        self.add_cog(Administration(self))
        self.uptime = datetime.datetime.utcnow()
        self.commands_used = Counter()
        self.server_commands = Counter()
        self.socket_stats = Counter()

    async def on_ready(self):
        if not self.started:
            self.loop.create_task(self.refresh())
            self.started = True

            self.loop.create_task(self.update_stats())

    async def on_command(self, ctx):
        self.commands_used[ctx.command] += 1

    async def on_socket_response(self, msg):
        self.socket_stats[msg.get('t')] += 1

    async def get_bot_uptime(self):
        """Get time between now and when the bot went up"""
        now = datetime.datetime.utcnow()
        delta = now - self.uptime
        hours, remainder = divmod(int(delta.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        days, hours = divmod(hours, 24)

        if days:
            fmt = '{d} days, {h} hours, {m} minutes, and {s} seconds'
        else:
            fmt = '{h} hours, {m} minutes, and {s} seconds'

        return fmt.format(d=days, h=hours, m=minutes, s=seconds)

    async def update_stats(self):
        url = "https://bots.discord.pw/api/bots/{}/stats".format(self.user.id)
        while not self.is_closed():
            payload = json.dumps(dict(server_count=len(self.guilds))).encode()
            headers = {'authorization': auth[3], "Content-Type": "application/json"}

            async with self.session.post(url, data=payload, headers=headers) as response:
                await response.read()

            url = "https://discordbots.org/api/bots/{}/stats".format(self.user.id)
            payload = json.dumps(dict(server_count=len(self.guilds))).encode()
            headers = {'authorization': auth[4], "Content-Type": "application/json"}

            async with self.session.post(url, data=payload, headers=headers) as response:
                await response.read()

            await asyncio.sleep(14400)

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

    @staticmethod
    def get_ram():
        """Get the bot's RAM usage info."""
        mem = psutil.virtual_memory()
        return f"{mem.used / 0x40_000_000:.2f}/{mem.total / 0x40_000_000:.2f}GB ({mem.percent}%)"


class Commands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    API_BASE = "http://api.tcgplayer.com/v1.20.0"
    manifests: dict
    categories: dict
    POKEMON_ID: int
    MAGIC_ID: int
    YUGIOH_ID: int
    VANGUARD_ID: int

    with open("files.json", 'r') as fd:
        ocarddata = json.load(fd)

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
        self.VANGUARD_ID = self.categories["Cardfight Vanguard"]

        for id in [self.POKEMON_ID, self.MAGIC_ID, self.YUGIOH_ID, self.VANGUARD_ID]:
            response = await self.bot.session.get(
                f"{self.API_BASE}/catalog/categories/{id}/search/manifest",
                headers={
                    "Authorization": f"bearer {self.bot.BEARER_TOKEN}"
                },
            )
            self.manifests[id] = await response.json()

    async def get_group(self, groupid):
        groupdata = await self.bot.session.get(
            f"{self.API_BASE}/catalog/groups/{groupid}",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"bearer {self.bot.BEARER_TOKEN}"
            },
        )
        return (await groupdata.json())['results'][0]

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
    async def pkmn(self, ctx, *, name: str):
        message = f'c!search "{name}" {"Pokemon"}'
        msg = copy.copy(ctx.message)
        msg.content = message
        ctx = await ctx.bot.get_context(msg)
        await ctx.bot.invoke(ctx)

    @commands.command()
    async def yugioh(self, ctx, *, name: str):
        message = f'c!search "{name}" {"YuGiOh"}'
        msg = copy.copy(ctx.message)
        msg.content = message
        ctx = await ctx.bot.get_context(msg)
        await ctx.bot.invoke(ctx)

    @commands.command()
    async def magic(self, ctx, *, name: str):
        message = f'c!search "{name}" {"Magic"}'
        msg = copy.copy(ctx.message)
        msg.content = message
        ctx = await ctx.bot.get_context(msg)
        await ctx.bot.invoke(ctx)

    @commands.command()
    async def search(self, ctx, query: str, game: str,
                     sort_type: str = "Relevance",
                     rarity: str = None, category: str = None):
        """Query the database for a card. Usage `c!search "Ho-Oh GX (Full Art)"`
        `c!search "Extremely Slow Zombie" Magic` """
        async with ctx.channel.typing():
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
                    "filters": filters,
                    "limit": 100,
                })
            )
            try:
                data = await resp.json()
            except:
                await ctx.send("No items found")
                return
            # ids = data['results'][0]

            pricedata = await ctx.bot.session.get(
                f"{self.API_BASE}/pricing/product/" + ",".join(str(x) for x in data['results']),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"bearer {self.bot.BEARER_TOKEN}"
                },
            )

            listdata = await ctx.bot.session.get(
                f"{self.API_BASE}/catalog/products/" + ",".join(
                    str(x) for x in data['results']) + "?getExtendedFields=true",
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
            #print(card)
            adata = "?partner={a}&utm_campaign=affiliate&utm_medium={a}&utm_source={a}".format(a="CardBuddy")
            prices = filter(lambda x: x['productId'] == card['productId'], pricejson['results'])
            # print(pricejson['results'])
            embed = discord.Embed(title=f"{card['name']} [Item {1}/{len(data['results'])}]",
                                  url=card['url'] + adata)
            embed.set_image(url=card['imageUrl'])
            group = await self.get_group(card['groupId'])
            embed.add_field(name="Pack", value=group['name'])
            embed.add_field(name="Type", value=group['abbreviation'])
            for item in card['extendedData']:
                embed.add_field(name=item['displayName'], value=item['value'])

            for price in prices:
                if price['marketPrice'] is not None:
                    embed.add_field(name=f"Market ({price['subTypeName']})",
                                    value=f"${price['marketPrice']}")

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
                    # embed.clear_fields()
                    index -= 1
                    for emote in emotes:
                        await message.add_reaction(emote)

            elif r.emoji == emotes[1]:
                if index == len(data['results']) - 1:
                    continue
                else:
                    # embed.clear_fields()
                    index += 1
                    for emote in emotes:
                        await message.add_reaction(emote)

            elif r.emoji == emotes[2]:
                return

            card = listjson['results'][index]
            prices = filter(lambda x: x['productId'] == card['productId'], pricejson['results'])
            # print(cardprice)
            embed = discord.Embed(title=f"{card['name']} [Item {index + 1}/{len(data['results'])}]",
                                  url=card['url'])
            embed.set_image(url=card['imageUrl'])
            group = await self.get_group(card['groupId'])
            embed.add_field(name="Pack", value=group['name'])
            embed.add_field(name="Type", value=group['abbreviation'])
            for item in card['extendedData']:
                embed.add_field(name=item['displayName'], value=item['value'])

            for price in prices:
                if price['marketPrice'] is not None:
                    embed.add_field(name=f"Market ({price['subTypeName']})",
                                    value=f"${price['marketPrice']}")

            await message.edit(embed=embed)

    @commands.command()
    async def random(self, ctx):
        """View a random listing"""
        async with ctx.channel.typing():
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

            embed = discord.Embed(title=card['name'], url=card['url'])
            embed.set_image(url=card['image'])
            embed.add_field(name="Pack", value=card['group']['name'])
            embed.add_field(name="Type", value=card['group']['abbreviation'])
            for item in card['extendedData']:
                embed.add_field(name=item['displayName'], value=item['value'])

        await ctx.send(embed=embed)

    @commands.command()
    async def ptcgo(self, ctx, *, name: str):
        """Search the value of something in terms of Guardians Rising packs. `c!info Burning Shadows`
        `c!info Golisopod GX` Very early beta, you might just check ou7c4st"""
        emotes = "\u25c0\u25b6\u274c"

        # print(self.ocarddata)
        vname = name + " 0"
        cards = []
        # print(vname)
        # print(vname in self.ocarddata), print(self.ocarddata[vname])
        while vname in self.ocarddata:
            cards.append(vname)
            vname = vname[:-1] + str(int(vname[-1]) + 1)
        cards.reverse()
        embed = discord.Embed(title=name)
        for fname, field in self.ocarddata[cards[0]].items():
            field = field or "N/A"
            embed.add_field(name=fname, value=field)

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
                if index == len(cards) - 1:
                    continue
                else:
                    embed.clear_fields()
                    index += 1
                    for emote in emotes:
                        await message.add_reaction(emote)

            elif r.emoji == emotes[2]:
                return

            for fname, field in self.ocarddata[cards[index]].items():
                field = field or "N/A"
                embed.add_field(name=fname, value=field)

            await message.edit(embed=embed)


class Administration(commands.Cog):
    _last_result = None

    def __init__(self, bot):
        self.bot = bot

    @staticmethod
    def cleanup_code(content):
        """Automatically removes code blocks from the code. Borrowed from RoboDanny"""
        # remove ```py\n```
        if content.startswith('```') and content.endswith('```'):
            return '\n'.join(content.split('\n')[1:-1])

        # remove `foo`
        return content.strip('` \n')

    @staticmethod
    def get_syntax_error(e):
        if e.text is None:
            return '```py\n{0.__class__.__name__}: {0}\n```'.format(e)
        return '```py\n{0.text}{1:>{0.offset}}\n{2}: {0}```'.format(e, '^', type(e).__name__)

    @commands.is_owner()
    @commands.command(hidden=True)
    async def eval(self, ctx, *, body: str):
        """Borrowed from RoboDanny"""
        env = {
            'bot': self.bot,
            'ctx': ctx,
            'channel': ctx.message.channel,
            'author': ctx.message.author,
            'server': ctx.message.guild,
            'guild': ctx.message.guild,
            'message': ctx.message,
            '_': self._last_result,
            'self': self,
        }

        env.update(globals())

        body = self.cleanup_code(body)
        stdout = io.StringIO()

        to_compile = 'async def func():\n%s' % indent(body, '  ')

        try:
            exec(to_compile, env)
        except SyntaxError as e:
            return await ctx.send(self.get_syntax_error(e))

        func = env['func']
        try:
            with redirect_stdout(stdout):
                ret = await func()
        except Exception as e:
            value = stdout.getvalue()
            await ctx.send('```py\n{}{}\n```'.format(value, format_exc()))
        else:
            value = stdout.getvalue()
            try:
                await ctx.message.add_reaction('\u2705')
            except:
                pass

            if ret is None:
                if value:
                    await ctx.send('```py\n%s\n```' % value)
            else:
                self._last_result = ret
                await ctx.send('```py\n%s%s\n```' % (value, ret))

    @commands.command()
    async def botinfo(self, ctx):
        """Bot Info"""
        me = self.bot.user if not ctx.guild else ctx.guild.me
        appinfo = await self.bot.application_info()
        embed = discord.Embed(color=random.randint(0, 0xFFFFFF), )
        embed.set_author(name=me.display_name, icon_url=appinfo.owner.avatar_url,
                         url="https://github.com/henry232323/CardBuddy")
        embed.add_field(name="Author", value='Henry#6174 (Discord ID: 122739797646245899)')
        embed.add_field(name="Library", value='discord.py (Python)')
        embed.add_field(name="Uptime", value=await self.bot.get_bot_uptime())
        embed.add_field(name="Servers", value="{} servers".format(len(self.bot.guilds)))
        embed.add_field(name="Commands Run",
                        value='{} commands'.format(sum(self.bot.commands_used.values())))

        total_members = sum(len(s.members) for s in self.bot.guilds)
        total_online = sum(1 for m in self.bot.get_all_members() if m.status != discord.Status.offline)
        unique_members = set(map(lambda x: x.id, self.bot.get_all_members()))
        channel_types = Counter(isinstance(c, discord.TextChannel) for c in self.bot.get_all_channels())
        voice = channel_types[False]
        text = channel_types[True]
        embed.add_field(name="Total Members",
                        value='{} ({} online)'.format(total_members, total_online))
        embed.add_field(name="Unique Members", value='{}'.format(len(unique_members)))
        embed.add_field(name="Channels",
                        value='{} text channels, {} voice channels'.format(text, voice))
        embed.add_field(name="Shards",
                        value='Currently running {} shards. This server is on shard {}'.format(
                            ctx.bot.shard_count, getattr(ctx.guild, "shard_id", 0)))

        # a = monotonic()
        # await (await ctx.bot.shards[getattr(ctx.guild, "shard_id", 0)].ws.ping())
        # b = monotonic()
        # ping = "{:.3f}ms".format((b - a) * 1000)

        embed.add_field(name="CPU Percentage", value="{}%".format(psutil.cpu_percent()))
        embed.add_field(name="Memory Usage", value=self.bot.get_ram())
        embed.add_field(name="Observed Events", value=sum(self.bot.socket_stats.values()))
        # embed.add_field(name=await _(ctx, "Ping"), value=ping)

        embed.add_field(name="Source", value="[Github](https://github.com/henry232323/CardBuddy)")

        embed.set_footer(text='Made with discord.py', icon_url='http://i.imgur.com/5BFecvA.png')
        embed.set_thumbnail(url=self.bot.user.avatar_url)
        await ctx.send(delete_after=60, embed=embed)

    @commands.command()
    async def totalcmds(self, ctx):
        """Get totals of commands and their number of uses"""
        embed = discord.Embed(color=random.randint(0, 0xFFFFFF), )
        embed.set_author(name=self.bot.user.name, icon_url=self.bot.user.avatar_url)
        for val in self.bot.commands_used.most_common(25):
            embed.add_field(name=val[0], value=val[1])
        embed.set_footer(text=str(ctx.message.created_at))
        await ctx.send(embed=embed)

    @commands.command()
    async def source(self, ctx, command: str = None):
        """Displays my full source code or for a specific command.
        To display the source code of a subcommand you have to separate it by
        periods, e.g. tag.create for the create subcommand of the tag command.
        """
        source_url = 'https://github.com/henry232323/RPGBot'
        if command is None:
            await ctx.send(source_url)
            return

        code_path = command.split('.')
        obj = self.bot
        for cmd in code_path:
            try:
                obj = obj.get_command(cmd)
                if obj is None:
                    await ctx.send('Could not find the command ' + cmd)
                    return
            except AttributeError:
                await ctx.send('{0.name} command has no subcommands'.format(obj))
                return

        # since we found the command we're looking for, presumably anyway, let's
        # try to access the code itself
        src = obj.callback.__code__

        if not obj.callback.__module__.startswith('discord'):
            # not a built-in command
            location = os.path.relpath(src.co_filename).replace('\\', '/')
            final_url = '<{}/tree/master/{}#L{}>'.format(source_url, location, src.co_firstlineno)
        else:
            location = obj.callback.__module__.replace('.', '/') + '.py'
            base = 'https://github.com/Rapptz/discord.py'
            final_url = '<{}/blob/master/{}#L{}>'.format(base, location, src.co_firstlineno)

        await ctx.send(final_url)

    @commands.command()
    async def donate(self, ctx):
        """Donation information"""
        await ctx.send("Keeping the bots running takes money, "
                       "if several people would buy me a coffee each month, "
                       "I wouldn't have to worry about it coming out of my pocket. "
                       "If you'd like, you can donate to me here: https://ko-fi.com/henrys "
                       "Or subscribe to my Patreon here: https://www.patreon.com/henry232323")


bot = Bot()
bot.run(auth[0])
