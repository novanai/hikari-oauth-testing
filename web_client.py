import quart
import random
import hikari
import dotenv
import os
from quart import Quart, session
import urllib.parse

dotenv.load_dotenv()


CLIENT_ID = os.environ["CLIENT_ID"]
CLIENT_SECRET = os.environ["CLIENT_SECRET"]
REDIRECT_URI = os.environ["REDIRECT_URI"]


app = Quart(__name__)
app.config.update({"SECRET_KEY": CLIENT_SECRET})

rest = hikari.RESTApp()

URL = f"https://discord.com/api/oauth2/authorize?client_id={CLIENT_ID}&redirect_uri={urllib.parse.quote(REDIRECT_URI)}&response_type=code&scope=identify%20guilds"

def random_str(length: int) -> str:
    text = ""
    possible = list("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789")
    for _ in range(length):
        index = random.randint(0, len(possible)-1)
        text += possible[index]

    return text

@app.route("/")
async def index():
    return await quart.render_template("index.html")

@app.route("/login", methods=["GET"])
async def login():
    state = random_str(16)
    session["state"] = state

    return quart.redirect(f"{URL}&state={state}")

@app.route("/guilds", methods=["GET"])
async def guilds():
    if not session.get("token"):
        code = quart.request.args.get("code")
        state = quart.request.args.get("state")

        if not (ses_state := session.get("state")) or not state or ses_state != state or not code:
            return quart.redirect("/login")

        token = await exchange_code(code)
        session["token"] = token

        return quart.redirect("/guilds")

    if not session.get("token"):
        return quart.redirect("/login")

    async with rest.acquire(session["token"]) as client:
        user = await client.fetch_my_user()
        guilds = await client.fetch_my_guilds()

    return await quart.render_template("guilds.html", guilds=guilds, user=user)

@app.route("/logout")
async def logout():
    if session.get("token"):
        session.pop("token")

    return quart.redirect("/")

async def exchange_code(code: str) -> str:
    async with rest.acquire(None) as r:
        auth_token = await r.authorize_access_token(int(CLIENT_ID), CLIENT_SECRET, code, REDIRECT_URI)

    return auth_token.access_token

app.run(use_reloader=False, debug=True)