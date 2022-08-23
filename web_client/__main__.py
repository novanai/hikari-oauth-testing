import os
import asyncio
from web_client.web_client import app


if __name__ == "__main__":
    if os.name == "nt":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    app.run(use_reloader=False, debug=True)
