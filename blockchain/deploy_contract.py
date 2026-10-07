"""Compile and deploy FraudAudit.sol to the configured local/private Ethereum RPC."""
import json
from pathlib import Path

from solcx import compile_standard, install_solc
from web3 import Web3

from config import BLOCKCHAIN_RPC_URL

ROOT = Path(__file__).resolve().parent
VERSION = "0.8.20"


def deploy():
    install_solc(VERSION)
    source = (ROOT / "FraudAudit.sol").read_text(encoding="utf-8")
    compiled = compile_standard({
        "language": "Solidity",
        "sources": {"FraudAudit.sol": {"content": source}},
        "settings": {"outputSelection": {"*": {"*": ["abi", "evm.bytecode"]}}},
    }, solc_version=VERSION)
    artifact = compiled["contracts"]["FraudAudit.sol"]["FraudAudit"]
    abi, bytecode = artifact["abi"], artifact["evm"]["bytecode"]["object"]
    web3 = Web3(Web3.HTTPProvider(BLOCKCHAIN_RPC_URL))
    if not web3.is_connected(): raise ConnectionError(f"Cannot connect to {BLOCKCHAIN_RPC_URL}")
    account = web3.eth.accounts[0]
    contract = web3.eth.contract(abi=abi, bytecode=bytecode)
    receipt = web3.eth.wait_for_transaction_receipt(contract.constructor().transact({"from": account}))
    (ROOT / "FraudAudit.abi.json").write_text(json.dumps(abi, indent=2), encoding="utf-8")
    (ROOT / "deployment.json").write_text(json.dumps({
        "address": receipt.contractAddress,
        "transaction_hash": receipt.transactionHash.hex(),
        "rpc_url": BLOCKCHAIN_RPC_URL,
    }, indent=2), encoding="utf-8")
    print(f"BLOCKCHAIN_CONTRACT_ADDRESS={receipt.contractAddress}")


if __name__ == "__main__": deploy()

