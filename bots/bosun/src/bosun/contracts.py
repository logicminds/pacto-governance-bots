"""ABI fragments for on-chain Pacto governance reads.

Mirrors the inline alloy::sol! bindings used by the Rust governance crate.
"""

from __future__ import annotations

INAVE_PIRATA_REGISTRY_ABI: list[dict] = [
    {
        "inputs": [],
        "name": "deploymentCount",
        "outputs": [{"internalType": "uint256", "name": "_count", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "uint256", "name": "_i", "type": "uint256"}],
        "name": "deploymentAt",
        "outputs": [{"internalType": "uint256", "name": "_topHatId", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "uint256", "name": "_topHatId", "type": "uint256"}],
        "name": "deployment",
        "outputs": [
            {
                "components": [
                    {"internalType": "address", "name": "safe", "type": "address"},
                    {"internalType": "address", "name": "quartermaster", "type": "address"},
                    {"internalType": "address", "name": "mutinyModule", "type": "address"},
                    {"internalType": "address", "name": "treasuryAuthority", "type": "address"},
                    {"internalType": "address", "name": "squadAdminProxy", "type": "address"},
                    {"internalType": "uint256", "name": "topHatId", "type": "uint256"},
                    {"internalType": "uint256", "name": "captainHatId", "type": "uint256"},
                    {"internalType": "uint256", "name": "crewHatId", "type": "uint256"},
                    {"internalType": "uint256", "name": "squadAdminHatId", "type": "uint256"},
                    {"internalType": "uint256", "name": "mutinyRoleHatId", "type": "uint256"},
                    {"internalType": "uint256", "name": "quartermasterRoleHatId", "type": "uint256"},
                    {"internalType": "uint256", "name": "treasuryAuthorityRoleHatId", "type": "uint256"},
                    {"internalType": "uint64", "name": "deployedAt", "type": "uint64"},
                    {"internalType": "address", "name": "deployer", "type": "address"},
                ],
                "internalType": "struct INavePirataRegistry.Deployment",
                "name": "_deployment",
                "type": "tuple",
            }
        ],
        "stateMutability": "view",
        "type": "function",
    },
]

ITREASURY_AUTHORITY_ABI: list[dict] = [
    {
        "inputs": [{"internalType": "address", "name": "_proposer", "type": "address"}],
        "name": "openProposalOf",
        "outputs": [{"internalType": "uint256", "name": "_openProposalId", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "uint256", "name": "_id", "type": "uint256"}],
        "name": "proposal",
        "outputs": [
            {"internalType": "address", "name": "_proposer", "type": "address"},
            {"internalType": "address", "name": "_to", "type": "address"},
            {"internalType": "uint256", "name": "_value", "type": "uint256"},
            {"internalType": "enum ITreasuryAuthority.Operation", "name": "_op", "type": "uint8"},
            {"internalType": "bytes", "name": "_data", "type": "bytes"},
            {"internalType": "uint64", "name": "_deadline", "type": "uint64"},
            {"internalType": "uint64", "name": "_snapshot", "type": "uint64"},
            {"internalType": "uint64", "name": "_yeas", "type": "uint64"},
            {"internalType": "uint64", "name": "_nays", "type": "uint64"},
            {"internalType": "bool", "name": "_captainApproved", "type": "bool"},
            {"internalType": "bool", "name": "_captainDefeated", "type": "bool"},
            {"internalType": "bool", "name": "_executed", "type": "bool"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
]

IMUTINY_MODULE_ABI: list[dict] = [
    {
        "inputs": [],
        "name": "activeMutinyId",
        "outputs": [{"internalType": "uint256", "name": "_id", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "uint256", "name": "_id", "type": "uint256"}],
        "name": "mutiny",
        "outputs": [
            {"internalType": "address", "name": "_proposedNewCaptain", "type": "address"},
            {"internalType": "uint64", "name": "_startedAt", "type": "uint64"},
            {"internalType": "uint64", "name": "_snapshot", "type": "uint64"},
            {"internalType": "uint64", "name": "_yeas", "type": "uint64"},
            {"internalType": "bool", "name": "_executed", "type": "bool"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
]

IQUARTERMASTER_ABI: list[dict] = [
    {
        "inputs": [{"internalType": "address", "name": "_candidate", "type": "address"}],
        "name": "pendingCrewAddAt",
        "outputs": [{"internalType": "uint256", "name": "_executableAt", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "address", "name": "_crew", "type": "address"}],
        "name": "pendingCrewRemoveAt",
        "outputs": [{"internalType": "uint256", "name": "_executableAt", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "crewChangeDelay",
        "outputs": [{"internalType": "uint256", "name": "_delay", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "mutinyActive",
        "outputs": [{"internalType": "bool", "name": "_active", "type": "bool"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "captainHatId",
        "outputs": [{"internalType": "uint256", "name": "_captainHatId", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "crewHatId",
        "outputs": [{"internalType": "uint256", "name": "_crewHatId", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
]

IERC20_ABI: list[dict] = [
    {
        "inputs": [{"internalType": "address", "name": "_account", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"internalType": "uint256", "name": "_balance", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
]

IHATS_ABI: list[dict] = [
    {
        "inputs": [
            {"internalType": "address", "name": "_user", "type": "address"},
            {"internalType": "uint256", "name": "_hatId", "type": "uint256"},
        ],
        "name": "isWearerOfHat",
        "outputs": [{"internalType": "bool", "name": "_isWearer", "type": "bool"}],
        "stateMutability": "view",
        "type": "function",
    },
]
