import asyncio
import hashlib
import os
import traceback
import urllib.parse

import asyncpg
import dotenv
import hikari
import polaris
import quart
from quart import Quart, session

dotenv.load_dotenv()


CLIENT_ID = os.environ["CLIENT_ID"]
CLIENT_SECRET = os.environ["CLIENT_SECRET"]
REDIRECT_URI = os.environ["REDIRECT_URI"]

app = Quart(__name__)
app.config.update({"SECRET_KEY": CLIENT_SECRET})

rest = hikari.RESTApp()
pl_client = polaris.Producer(os.environ["REDIS_ADDRESS"])

URL = f"https://discord.com/api/oauth2/authorize?client_id={CLIENT_ID}&redirect_uri={urllib.parse.quote(REDIRECT_URI)}&response_type=code&scope=identify%20guilds"


@app.route("/")
async def index():
    return await quart.render_template("index.html")


@app.route("/login", methods=["GET"])
async def login():
    # cookies = quart.request.cookies
    # state = hashlib.sha256(
    #     str.encode(cookies["session"]), usedforsecurity=True
    # ).hexdigest()
    state = os.urandom(16).hex()
    session["state"] = state

    return quart.redirect(f"{URL}&state={state}")


@app.route("/guilds", methods=["GET"])
async def guilds():
    if not session.get("token"):
        code = quart.request.args.get("code")
        state = quart.request.args.get("state")

        if (
            not (ses_state := session.get("state"))
            or not state
            or ses_state != state
            or not code
        ):
            return quart.redirect("/login")

        token = await exchange_code(code)
        session["token"] = token

        return quart.redirect("/guilds")

    # if not session.get("token"):
    #     return quart.redirect("/login")

    async with rest.acquire(session["token"]) as client:
        user = await client.fetch_my_user()
        user_guilds = await client.fetch_my_guilds()

    session["avatar"] = user.display_avatar_url.url
    session["username"] = user.username
    session["discriminator"] = user.discriminator

    msg = polaris.Message(
        polaris.MessageType.CREATE,
        "get_guilds",
        {"guilds": [g.id for g in user_guilds], "user": user.id},
    )
    res = await pl_client.send_message(msg, wait_for_response=True)
    assert res is not None

    manageable_guild_ids = res.data["guilds"]
    manageable_guilds = [
        guild for guild in user_guilds if guild.id in manageable_guild_ids
    ]

    return await quart.render_template(
        "guilds.html",
        guilds=manageable_guilds,
        username=session["username"],
        discriminator=session["discriminator"],
        avatar=session["avatar"],
    )


@app.route("/guild/<guild_id>", ["GET", "POST"])
async def guild(guild_id: str):
    if not session.get("token"):
        return quart.redirect("/login")

    if quart.request.method != "POST":
        settings = await db.fetchrow(
            "SELECT * FROM welcome_messages WHERE guild_id = $1", int(guild_id)
        )
        colour = hikari.Colour.from_tuple_string(str(settings["colour"])).hex_code

        msg = polaris.Message(
            polaris.MessageType.CREATE, "get_channels", {"guild_id": guild_id}
        )
        res = await pl_client.send_message(msg, wait_for_response=True)
        assert res is not None
        channels = res.data["channels"]

        return await quart.render_template(
            "guild.html",
            settings=settings,
            colour=colour,
            channels=channels,
            username=session["username"],
            discriminator=session["discriminator"],
            avatar=session["avatar"],
            guild=res.data["guild_name"],
        )

    else:
        form = await quart.request.form

        await db.execute(
            """UPDATE welcome_messages SET
                channel_id = $2,
                message_enabled = $3,
                message = $4,
                embed_enabled = $5,
                title = $6,
                description = $7,
                colour = $8,
                thumbnail = $9,
                image = $10
            WHERE guild_id = $1""",
            int(guild_id),
            int(form["channel"]),
            form.get("message_enabled") == "on",
            form["message"],
            form.get("embed_enabled") == "on",
            form["title"],
            form["description"],
            hikari.Color.from_hex_code(form["colour"]).rgb,
            form["thumbnail"],
            form["image"],
        )

        return quart.redirect(f"/guild/{guild_id}")


@app.route("/logout")
async def logout():
    if session.get("token"):
        async with rest.acquire(None) as r:
            await r.revoke_access_token(int(CLIENT_ID), CLIENT_SECRET, session["token"])
        session.pop("token")

    return quart.redirect("/")


@app.before_serving
async def start_db():
    global db
    db = await asyncpg.connect(
        "postgresql://postgres@localhost/bot_testing", password=os.environ["DB_PASS"]
    )


@app.after_serving
async def close_polaris():
    await pl_client.close()


async def exchange_code(code: str) -> str:
    async with rest.acquire(None) as r:
        auth_token = await r.authorize_access_token(
            int(CLIENT_ID), CLIENT_SECRET, code, REDIRECT_URI
        )

    return auth_token.access_token
