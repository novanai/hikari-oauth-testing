import asyncio
import itertools
import os

import asyncpg
import dotenv
import hikari
import lightbulb
import polaris
import toolbox

dotenv.load_dotenv()

bot = lightbulb.BotApp(
    os.environ["BOT_TOKEN"],
    banner=None,
    intents=hikari.Intents.ALL,
)
bot.d.polaris = polaris.Consumer(os.environ["REDIS_ADDRESS"])


@bot.d.polaris.handler_for("get_guilds", polaris.MessageType.CREATE)
async def get_guilds(message: polaris.Message):
    guilds: list[int] = message.data["guilds"]
    user = message.data["user"]
    mutual_guilds = [guild for guild in guilds if bot.cache.get_guild(guild)]
    manageable_guilds = []

    for guild in mutual_guilds:
        member = bot.cache.get_member(guild, user)
        if not member:
            continue
        perms = toolbox.calculate_permissions(member)
        if perms & hikari.Permissions.MANAGE_GUILD:
            manageable_guilds.append(guild)

    await message.respond({"guilds": manageable_guilds})


@bot.d.polaris.handler_for("get_channels", polaris.MessageType.CREATE)
async def get_channels(message: polaris.Message):
    guild_id = message.data["guild_id"]
    guild = bot.cache.get_guild(guild_id)

    channels = bot.cache.get_guild_channels_view_for_guild(guild_id)
    chan_to_cat = itertools.groupby(
        filter(lambda c: isinstance(c, hikari.GuildTextChannel), channels.values()),
        key=lambda c: (
            chn.name if (chn := bot.cache.get_guild_channel(c.parent_id)) else None
        )
        if c.parent_id
        else None,
    )
    chan_to_cat_2 = {}
    for cat, group in chan_to_cat:
        channels_: dict[str, int] = {}
        for chn in group:
            assert chn.name is not None
            channels_[chn.name] = chn.id
        chan_to_cat_2[cat or "no category"] = channels_

    await message.respond(
        {
            "channels": chan_to_cat_2,
            "guild_name": guild.name if guild else "Unknown Guild",
        }
    )


@bot.listen(hikari.ShardReadyEvent)
async def on_started(_: hikari.ShardReadyEvent) -> None:
    await start_db()
    await bot.d.polaris.run()


async def start_db() -> None:
    bot.d.conn = await asyncpg.connect(
        "postgresql://postgres@localhost/bot_testing", password=os.environ["DB_PASS"]
    )

    conn = bot.d.conn

    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS welcome_messages(
            guild_id bigint PRIMARY KEY,
            channel_id bigint,
            message_enabled bool,
            message text,
            embed_enabled bool,
            title text,
            description text,
            colour int[][][],
            thumbnail text,
            image text
        )
    """
    )


@bot.command
@lightbulb.command("ping", "The bot's ping")
@lightbulb.implements(lightbulb.SlashCommand)
async def ping(ctx: lightbulb.SlashContext) -> None:
    await ctx.respond(f"Pong! Latency: {bot.heartbeat_latency*1000:.2f}ms")




@bot.listen(hikari.MemberCreateEvent)
async def on_member_create(event: hikari.MemberCreateEvent) -> None:
    guild = event.get_guild()
    if not guild:
        return

    settings = await bot.d.conn.fetchrow(
        "SELECT * FROM welcome_messages WHERE guild_id = $1", event.guild_id
    )

    if not settings["message_enabled"]:
        return

    embed = hikari.UNDEFINED
    if settings["embed_enabled"]:
        embed = hikari.Embed(
            title=sub_strings(settings["title"], guild.name, event.member.mention, len(guild.get_members())),
            description=sub_strings(settings["description"], guild.name, event.member.mention, len(guild.get_members())),
            colour=hikari.Colour.from_tuple_string(str(settings["colour"]))
        )
        embed.set_thumbnail(settings["thumbnail"])
        embed.set_image(settings["image"])

    await bot.rest.create_message(
        settings["channel_id"],
        sub_strings(settings["message"], guild.name, event.member.mention, len(guild.get_members())),
        embed=embed,
        user_mentions=True
    )




def sub_strings(text: str, guild: str, mention: str, count: int) -> str:
    return text.format(server=guild, user_mention=mention, member_count=count)

