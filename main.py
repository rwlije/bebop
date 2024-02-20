from utils.file import read_lines
from core.config import (
    SHUFFLE_ACCOUNTS,
    USE_PROXY,
    SEMAPHORE_LIMIT,
    CHAINS
)
from core.bebop import Bebop
from itertools import cycle
from work import start_work
import asyncio
import random


async def main():
    semaphore = asyncio.Semaphore(SEMAPHORE_LIMIT)
    private_keys = await read_lines("files/private_keys.txt")
    parsed_private_keys = ["0x" + private_key if private_key[:2] != "0x" else private_key
                           for private_key in private_keys]

    if SHUFFLE_ACCOUNTS:
        random.shuffle(parsed_private_keys)

    if USE_PROXY:
        proxies = await read_lines("files/proxies.txt")

    else:
        proxies = [None]

    client = Bebop(CHAINS["Polygon"])
    tasks = [asyncio.create_task(start_work(semaphore, client, private_key, proxy))
             for private_key, proxy in zip(parsed_private_keys, cycle(proxies))]

    await asyncio.gather(*tasks)

asyncio.run(main())
