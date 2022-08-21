import asyncio
import hashlib
import os
import urllib.parse

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
    cookies = quart.request.cookies
    state = hashlib.sha256(
        str.encode(cookies["session"]), usedforsecurity=True
    ).hexdigest()
    # state = os.urandom(16).hex()
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

    if not session.get("token"):
        return quart.redirect("/login")

    async with rest.acquire(session["token"]) as client:
        user = await client.fetch_my_user()
        user_guilds = await client.fetch_my_guilds()

    msg = polaris.Message(
        polaris.MessageType.CREATE,
        "get_guilds",
        {"guilds": [g.id for g in user_guilds], "user": user.id},
    )
    res = await pl_client.send_message(msg, wait_for_response=True)
    assert res is not None

    manageable_guild_ids = res.data["guilds"]
    manageable_guilds = [guild for guild in user_guilds if guild.id in manageable_guild_ids]

    return await quart.render_template("guilds.html", guilds=manageable_guilds, user=user)


@app.route("/logout")
async def logout():
    if session.get("token"):
        session.pop("token")

    return quart.redirect("/")


@app.after_serving
async def close_polaris():
    await pl_client.close()


async def exchange_code(code: str) -> str:
    async with rest.acquire(None) as r:
        auth_token = await r.authorize_access_token(
            int(CLIENT_ID), CLIENT_SECRET, code, REDIRECT_URI
        )

    return auth_token.access_token


if __name__ == "__main__":
    if os.name == "nt":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    app.run(use_reloader=False, debug=True)
