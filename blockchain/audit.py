"""Optional Web3 audit writer. The app stays available if the chain is offline."""
import hashlib
import json
from pathlib import Path

from config import BLOCKCHAIN_CONTRACT_ADDRESS, BLOCKCHAIN_RPC_URL, ROOT

ABI_PATH = ROOT / "blockchain" / "FraudAudit.abi.json"


def record_hash(event):
    canonical = json.dumps({
        "event_id": event["event_id"], "transaction_id": event["source_transaction_id"],
        "risk": event["fraud_probability"], "decision": event["decision"],
        "timestamp": event["timestamp"].isoformat(),
    }, sort_keys=True).encode()
    return hashlib.sha256(canonical).hexdigest()


def write_audit(event):
    digest = record_hash(event)
    if not BLOCKCHAIN_CONTRACT_ADDRESS or not ABI_PATH.exists():
        return {"status": "not configured", "record_hash": digest, "tx_hash": ""}
    try:
        from web3 import Web3
        web3 = Web3(Web3.HTTPProvider(BLOCKCHAIN_RPC_URL, request_kwargs={"timeout": 2}))
        if not web3.is_connected(): raise ConnectionError("blockchain RPC unavailable")
        account = web3.eth.accounts[0]
        contract = web3.eth.contract(
            address=Web3.to_checksum_address(BLOCKCHAIN_CONTRACT_ADDRESS),
            abi=json.loads(ABI_PATH.read_text(encoding="utf-8")),
        )
        tx_hash = contract.functions.recordAlert(
            event["event_id"], bytes.fromhex(digest), int(event["fraud_probability"] * 10000), event["decision"]
        ).transact({"from": account})
        receipt = web3.eth.wait_for_transaction_receipt(tx_hash, timeout=15)
        return {"status": "verified", "record_hash": digest, "tx_hash": receipt.transactionHash.hex()}
    except Exception as exc:
        return {"status": f"offline: {type(exc).__name__}", "record_hash": digest, "tx_hash": ""}

