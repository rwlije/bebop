from eth_account.messages import encode_typed_data
from core.client import Client
from core.config import *
from utils.log import log
import asyncio
import random


class Bebop(Client):
    def __init__(self, chain):
        super().__init__(chain)
        self.PARAM_TYPES = {
            "Aggregate": [
                {"name": "expiry", "type": "uint256"},
                {"name": "taker_address", "type": "address"},
                {"name": "maker_addresses", "type": "address[]"},
                {"name": "maker_nonces", "type": "uint256[]"},
                {"name": "taker_tokens", "type": "address[][]"},
                {"name": "maker_tokens", "type": "address[][]"},
                {"name": "taker_amounts", "type": "uint256[][]"},
                {"name": "maker_amounts", "type": "uint256[][]"},
                {"name": "receiver", "type": "address"},
                {"name": "commands", "type": "bytes"}
            ]
        }
        self.PARAM_DOMAIN = {
            "name": "BebopSettlement",
            "version": "1",
            "chainId": chain["id"],
            "verifyingContract": BEBOP_ADDRESS
        }

    @staticmethod
    async def get_tokens_to_buy_ratio(number_of_tokens_to_buy):
        first_ratio = round(random.uniform(0.01, round(1 / number_of_tokens_to_buy, 2) * 2 -
                                           (0.01 * (number_of_tokens_to_buy - 1))), 2)
        ratio = [first_ratio]

        for i in range(1, number_of_tokens_to_buy - 1):
            ratio.append(
                round(random.uniform(0.01, min(1 - sum(ratio[0:i]) - (0.01 * (number_of_tokens_to_buy - i - 1)),
                                               round(1 / number_of_tokens_to_buy, 2) * 2)), 2))

        ratio.append(round(1 - sum(ratio), 2))

        return ratio

    @staticmethod
    async def get_random_token_addresses_to_buy(token_addresses_to_exclude=None, exclude_wmatic=False):
        if token_addresses_to_exclude is None:
            token_addresses_to_exclude = []
        return random.sample([token_hash for token_hash in TOKEN_NAME_TO_HASH.values()
                              if not (token_hash in token_addresses_to_exclude) and
                              not ((token_hash == TOKEN_NAME_TO_HASH["WMATIC"]) * exclude_wmatic)],
                             random.randint(2, 5) if len(token_addresses_to_exclude) == 1 else 1)

    async def get_token_addresses_to_collect(self, web3, account):
        token_contracts = [web3.eth.contract(address=Web3.to_checksum_address(token_address),
                                             abi=self.token_abi) for token_address in TOKEN_NAME_TO_HASH.values()
                           if token_address != TOKEN_NAME_TO_HASH["WMATIC"]]
        token_addresses_to_collect = [token_contract.address for token_contract in token_contracts
                                      if token_contract.functions.balanceOf(account.address).call() > 0]
        return token_addresses_to_collect

    async def wrap_matic(self, web3, account, retry=1):
        try:
            token_contract = web3.eth.contract(address=Web3.to_checksum_address(TOKEN_NAME_TO_HASH["WMATIC"]),
                                               abi=self.token_abi)
            wmatic_balance = token_contract.functions.balanceOf(account.address).call()
            value = int((web3.eth.get_balance(account.address) + wmatic_balance) *
                        (min(BALANCE_PERCENT) / 100)) - wmatic_balance
            if value > 0:
                tx = token_contract.functions.deposit().build_transaction(await self.prepare_transaction(web3, account,
                                                                                                         value))
                tx["gas"] = int(web3.eth.estimate_gas(tx) * 1.25)
                signed_tx = web3.eth.account.sign_transaction(tx, private_key=web3.to_hex(account.key))
                tx_hash = web3.eth.send_raw_transaction(signed_tx.rawTransaction)
                log.info(f'{account.address} | Attempt {retry}/{NUMBER_OF_RETRIES} | Wrap MATIC | Transaction sent')
                tx_receipt = web3.eth.wait_for_transaction_receipt(tx_hash, timeout=360)

                if tx_receipt.status == 1:
                    tx_hash = str(tx_hash.hex())
                    log.success(f'{account.address} | Attempt {retry}/{NUMBER_OF_RETRIES} | Wrap MATIC | '
                                f'Wrapped {web3.from_wei(value, "ether")} MATIC | {SCAN_URL + tx_hash}')
                    return True

                else:
                    raise Exception("Transaction failed")

            else:
                log.success(f'{account.address} | Attempt {retry}/{NUMBER_OF_RETRIES} | Wrap MATIC | '
                            f'Already enough WMATIC')
                return True

        except Exception as error:
            log.error(f'{account.address} | Attempt {retry}/{NUMBER_OF_RETRIES} | Wrap MATIC | Error: {error}')
            retry += 1

            if retry > NUMBER_OF_RETRIES:
                return False

            await asyncio.sleep(random.randint(*SLEEP_RANGE))
            return await self.wrap_matic(web3, account, retry)

    async def unwrap_wmatic(self, web3, account, retry=1):
        try:
            token_contract = web3.eth.contract(address=Web3.to_checksum_address(TOKEN_NAME_TO_HASH["WMATIC"]),
                                               abi=self.token_abi)
            value = token_contract.functions.balanceOf(account.address).call()
            tx = token_contract.functions.withdraw(value).build_transaction(await self.prepare_transaction(web3,
                                                                                                           account))
            tx["gas"] = int(web3.eth.estimate_gas(tx) * 1.25)
            signed_tx = web3.eth.account.sign_transaction(tx, private_key=web3.to_hex(account.key))
            tx_hash = web3.eth.send_raw_transaction(signed_tx.rawTransaction)
            log.info(f'{account.address} | Attempt {retry}/{NUMBER_OF_RETRIES} | Unwrap WMATIC | Transaction sent')
            tx_receipt = web3.eth.wait_for_transaction_receipt(tx_hash, timeout=360)

            if tx_receipt.status == 1:
                tx_hash = str(tx_hash.hex())
                log.success(f'{account.address} | Attempt {retry}/{NUMBER_OF_RETRIES} | Unwrap WMATIC | '
                            f'Unwrapped {web3.from_wei(value, "ether")} WMATIC | {SCAN_URL}{tx_hash}')
                return True

            else:
                raise Exception("Transaction failed")

        except Exception as error:
            log.error(f'{account.address} | Attempt {retry}/{NUMBER_OF_RETRIES} | Unwrap WMATIC | Error: {error}')
            retry += 1

            if retry > NUMBER_OF_RETRIES:
                return False

            await asyncio.sleep(random.randint(*SLEEP_RANGE))
            return await self.unwrap_wmatic(web3, account, retry)

    async def swap(self, web3, session, account, token_addresses_to_sell, token_addresses_to_buy, retry=1):
        token_names_for_log = (
            f'{", ".join([TOKEN_HASH_TO_NAME[token_hash] for token_hash in token_addresses_to_sell])} to '
            f'{", ".join([TOKEN_HASH_TO_NAME[token_hash] for token_hash in token_addresses_to_buy])}')

        try:
            token_contracts = [web3.eth.contract(address=Web3.to_checksum_address(token_address),
                                                 abi=self.token_abi) for token_address in token_addresses_to_sell]
            token_amounts_to_sell = [contract.functions.balanceOf(account.address).call() for contract in
                                     token_contracts]
            params = {
                "buy_tokens": str(token_addresses_to_buy)[2:-2].replace(" ", "").replace("'", ""),
                "sell_tokens": str(token_addresses_to_sell)[2:-2].replace(" ", "").replace("'", ""),
                "sell_amounts": str(token_amounts_to_sell)[1:-1].replace(" ", "").replace("'", ""),
                "taker_address": account.address
            }
            number_of_tokens_to_buy = len(token_addresses_to_buy)

            if number_of_tokens_to_buy > 1:
                buy_tokens_ratio = await self.get_tokens_to_buy_ratio(number_of_tokens_to_buy)
                params.update({"buy_tokens_ratios": str(buy_tokens_ratio)[1:-1].replace(" ", "").replace("'", "")})

            approved = True

            for token_hash in token_addresses_to_sell:
                token_contract = web3.eth.contract(address=token_hash, abi=self.token_abi)

                for address_to_allow in (PERMIT2_ADDRESS, BEBOP_ADDRESS):
                    allowance = token_contract.functions.allowance(account.address, address_to_allow).call()
                    decimal = token_contract.functions.decimals().call()

                    if allowance < 1000000 * 10 ** decimal:

                        if not await self.approve(web3, account, token_hash, address_to_allow):
                            approved = False
                            break

                if not approved:
                    break

            if approved:

                quote = session.get(f'https://api.bebop.xyz/{self.chain["name"].lower()}/v2/quote',
                                    params=params).json()

                if "status" in quote and quote["status"] == "QUOTE_SUCCESS":
                    to_sign = quote["toSign"]
                    quote_id = quote["quoteId"]
                    message = encode_typed_data(self.PARAM_DOMAIN, self.PARAM_TYPES, to_sign)
                    signed_message = account.sign_message(message)
                    signature = web3.to_hex(signed_message["signature"])
                    params = {
                        "signature": signature,
                        "quote_id": quote_id
                    }
                    order = session.post(f'https://api.bebop.xyz/{self.chain["name"]}/v2/order',
                                         json=params).json()
                    log.info(f'{account.address} | Attempt {retry}/{NUMBER_OF_RETRIES} | Swap '
                             f'{token_names_for_log} | Transaction sent')

                    if "status" in order and order["status"] == "Success":
                        tx_hash = order["txHash"]
                        tx_receipt = web3.eth.wait_for_transaction_receipt(tx_hash, timeout=360)

                        if tx_receipt.status == 1:
                            log.success(f'{account.address} | Attempt {retry}/{NUMBER_OF_RETRIES} | '
                                        f'Swap {token_names_for_log} | Transaction succeeded | '
                                        f'{SCAN_URL}{tx_hash}')
                            return True

                        else:
                            raise Exception("Transaction failed")

                    else:
                        raise Exception("Order failed")

                else:
                    raise Exception("Quote failed")

            else:
                raise Exception("Approve of the tokens failed")

        except Exception as error:
            log.error(f'{account.address} | Attempt {retry}/{NUMBER_OF_RETRIES} | Swap {token_names_for_log} | '
                      f'Error: {error}')
            retry += 1

            if retry > NUMBER_OF_RETRIES:
                return False

            await asyncio.sleep(random.randint(*SLEEP_RANGE))
            return await self.swap(web3, session, account, token_addresses_to_sell, token_addresses_to_buy, retry)
