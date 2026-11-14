"""Single entrypoint: FastAPI website + Telegram bot polling."""

import asyncio
import logging
import os

import uvicorn

from app import config
from app.main import app

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


async def main() -> None:
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="0.0.0.0",
            port=int(os.getenv("PORT", "8000")),
            proxy_headers=True,
            forwarded_allow_ips="*",
            log_level="info",
        )
    )
    tasks = [asyncio.create_task(server.serve())]
    if config.TELEGRAM_BOT_TOKEN:
        from app.bot import run_bot

        tasks.append(asyncio.create_task(run_bot()))
    else:
        logging.info("TELEGRAM_BOT_TOKEN is empty: bot disabled")
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
