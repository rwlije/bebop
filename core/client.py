from core.config import *
from utils.log import log
from web3 import Web3
import random
import json


class Client:

    def __init__(self, chain):
        self.chain = chain
        self.token_abi = json.load(open("abi/token.json"))

    async def prepare_transaction(self, web3, account, value=0):
        tx_params = {
            "from": web3.to_checksum_address(account.address),
            "nonce": web3.eth.get_transaction_count(account.address),
            "chainId": self.chain["id"],
            "gasPrice": int(web3.eth.gas_price * 1.25),
            "value": value
        }
        return tx_params

    async def approve(self, web3, account, token_to_approve, address_to_approve, retry=1):
        try:
            token_contract = web3.eth.contract(address=token_to_approve, abi=self.token_abi)
            max_amount = Web3.to_wei(2 ** 64, "ether")

            tx = token_contract.functions.approve(
                address_to_approve,
                max_amount
            ).build_transaction(await self.prepare_transaction(web3, account))
            tx["gas"] = int(web3.eth.estimate_gas(tx) * 1.1)
            signed_tx = web3.eth.account.sign_transaction(tx, web3.to_hex(account.key))
            tx_hash = web3.eth.send_raw_transaction(signed_tx.rawTransaction)
            log.info(f'{account.address} | Attempt {retry}/{NUMBER_OF_RETRIES} | Approve '
                     f'{TOKEN_HASH_TO_NAME[token_to_approve]} | Transaction sent')
            tx_receipt = web3.eth.wait_for_transaction_receipt(tx_hash, timeout=360)

            if tx_receipt.status == 1:
                tx_hash = str(tx_hash.hex())
                log.success(f'{account.address} | Attempt {retry}/{NUMBER_OF_RETRIES} | Approve '
                            f'{TOKEN_HASH_TO_NAME[token_to_approve]} | Transaction succeeded | {SCAN_URL}{tx_hash}')
                return True

            else:
                raise Exception("Transaction failed")

        except Exception as error:
            log.error(f'{account.address} | Attempt {retry}/{NUMBER_OF_RETRIES} | Approve '
                      f'{TOKEN_HASH_TO_NAME[token_to_approve]} | Error: {error}')
            retry += 1

            if retry > NUMBER_OF_RETRIES:
                return False

            await asyncio.sleep(random.randint(*SLEEP_RANGE))
            return await self.approve(web3, account, token_to_approve, address_to_approve, retry)
