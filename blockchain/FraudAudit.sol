// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

contract FraudAudit {
    struct Alert { bytes32 recordHash; uint256 riskBps; string decision; uint256 timestamp; }
    mapping(string => Alert) public alerts;
    event AlertRecorded(string indexed eventId, bytes32 recordHash, uint256 riskBps, string decision);

    function recordAlert(string calldata eventId, bytes32 recordHash, uint256 riskBps, string calldata decision) external {
        require(alerts[eventId].timestamp == 0, "alert already recorded");
        alerts[eventId] = Alert(recordHash, riskBps, decision, block.timestamp);
        emit AlertRecorded(eventId, recordHash, riskBps, decision);
    }
}

