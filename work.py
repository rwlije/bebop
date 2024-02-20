from web3.middleware import geth_poa_middleware
from utils.file import append_line
from utils.useragent import ua
from core.config import *
from utils.log import log
from web3 import Web3
import random
import httpx


async def start_work(semaphore, client, private_key, proxy):
    async with semaphore:
        random_useragent = ua.random
        web3 = Web3(Web3.HTTPProvider(RPC_URL, request_kwargs={"timeout": 360,
                                                               "proxies": {
                                                                   "all://": proxy
                                                               },
                                                               "headers": {
                                                                   "User-Agent": random_useragent}
                                                               }))
        session = httpx.Client(headers={"User-Agent": random_useragent}, proxies={"all://": proxy})
        web3.middleware_onion.inject(geth_poa_middleware, layer=0)

        try:
            account = web3.eth.account.from_key(private_key)

        except Exception:
            log.critical(f'Invalid private key -> {private_key}')
            return False

        result = await worker(client, web3, session, account)

        if result:
            await append_line(private_key, "files/succeeded_wallets.txt")

        else:
            await append_line(private_key, "files/failed_wallets.txt")


async def worker(client, web3, session, account):
    try:
        token_addresses_to_collect = await client.get_token_addresses_to_collect(web3, account)
        token_addresses_to_buy = [TOKEN_NAME_TO_HASH["WMATIC"]]

        while token_addresses_to_collect:
            token_addresses_to_sell = random.sample(
                token_addresses_to_collect, random.randint(2, 5)
                if len(token_addresses_to_collect) > 5 else len(token_addresses_to_collect))

            if await client.swap(web3, session, account, token_addresses_to_sell, token_addresses_to_buy):
                token_addresses_to_collect = [token_address for token_address in token_addresses_to_collect
                                              if not (token_address in token_addresses_to_sell)]
                await asyncio.sleep(*SLEEP_RANGE)

            else:
                log.critical(f'{account.address} | Some swap failed after {NUMBER_OF_RETRIES} retries | '
                             f'Account will be skipped')
                return False

        if await client.wrap_matic(web3, account):
            await asyncio.sleep(random.randint(*SLEEP_RANGE))

            tx_amount = random.randint(*NUMBER_OF_TRANSACTIONS)
            tx_amount += tx_amount % 2
            tx_counter = tx_amount

            while tx_counter:
                if tx_counter == 2:
                    if "tokens_addresses_to_buy" in locals():
                        tokens_addresses_to_sell = tokens_addresses_to_buy
                        tokens_addresses_to_buy = await client.get_random_token_addresses_to_buy(
                            tokens_addresses_to_sell, True)
                    else:
                        tokens_addresses_to_sell = [TOKEN_NAME_TO_HASH["WMATIC"]]
                        tokens_addresses_to_buy = await client.get_random_token_addresses_to_buy(
                            tokens_addresses_to_sell, True)

                elif tx_counter == 1:
                    tokens_addresses_to_sell = tokens_addresses_to_buy
                    tokens_addresses_to_buy = [TOKEN_NAME_TO_HASH["WMATIC"]]

                elif tx_counter == tx_amount:
                    tokens_addresses_to_sell = [TOKEN_NAME_TO_HASH["WMATIC"]]
                    tokens_addresses_to_buy = await client.get_random_token_addresses_to_buy(tokens_addresses_to_sell)

                else:
                    tokens_addresses_to_sell = tokens_addresses_to_buy
                    tokens_addresses_to_buy = await client.get_random_token_addresses_to_buy(tokens_addresses_to_sell)

                if await client.swap(web3, session, account, tokens_addresses_to_sell, tokens_addresses_to_buy):
                    tx_counter -= 1
                    await asyncio.sleep(random.randint(*SLEEP_RANGE))

                else:
                    log.critical(f'{account.address} | Some swap failed after {NUMBER_OF_RETRIES} retries | '
                                 f'Account will be skipped')
                    return False

            if await client.unwrap_wmatic(web3, account):
                await asyncio.sleep(random.randint(*SLEEP_RANGE))
                return True

            else:
                log.critical(f'{account.address} | Unwrap failed after {NUMBER_OF_RETRIES} retries | '
                             f'Account will be skipped')
                return False

        else:
            log.critical(f'{account.address} | Wrap failed after {NUMBER_OF_RETRIES} retries | '
                         f'Account will be skipped')
            return False

    except Exception as error:
        log.critical(f'{account.address} | Error: {error} | Account will be skipped')
        return False
