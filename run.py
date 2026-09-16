# run.py — launch API + Bot concurrently
import asyncio
import multiprocessing
import subprocess
import sys
import os


def run_api():
    import uvicorn
    from api.main import app
    from config import API_HOST, API_PORT
    uvicorn.run(app, host=API_HOST, port=API_PORT, log_level="info")


def run_bot():
    from bot.main import main
    main()


if __name__ == "__main__":
    api_proc = multiprocessing.Process(target=run_api, daemon=True)
    api_proc.start()
    print("[run] API started")

    # Bot runs in main process
    run_bot()