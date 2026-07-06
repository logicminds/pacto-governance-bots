"""Unit tests for the bosun on-chain governance reader."""

from __future__ import annotations

from typing import Any

import pytest

from bosun.reader import GovernanceError, GovernanceReader
from bosun.types import DeadlineKind


class _AsyncContract:
    """Minimal async contract mock that supports chained functions().call()."""

    def __init__(self, calls: dict[str, Any]) -> None:
        self._calls = calls

    @property
    def functions(self) -> "_Functions":
        return _Functions(self._calls)


class _Functions:
    def __init__(self, calls: dict[str, Any]) -> None:
        self._calls = calls

    def __getattr__(self, name: str) -> "_Function":
        return _Function(self._calls, name)


class _Function:
    def __init__(self, calls: dict[str, Any], name: str) -> None:
        self._calls = calls
        self._name = name

    def __call__(self, *args: Any) -> "_Function":
        self._args = args
        return self

    async def call(self) -> Any:
        key = self._name
        if hasattr(self, "_args") and self._args:
            key = (self._name, self._args)
        if key not in self._calls:
            raise KeyError(f"unexpected call: {key}")
        return self._calls[key]


def _deployment_tuple(
    safe: str = "0x1111111111111111111111111111111111111111",
    quartermaster: str = "0x2222222222222222222222222222222222222222",
    mutiny_module: str = "0x3333333333333333333333333333333333333333",
    treasury_authority: str = "0x4444444444444444444444444444444444444444",
    squad_admin_proxy: str = "0x5555555555555555555555555555555555555555",
):
    return (
        safe,
        quartermaster,
        mutiny_module,
        treasury_authority,
        squad_admin_proxy,
        1,  # topHatId
        2,  # captainHatId
        3,  # crewHatId
        4,  # squadAdminHatId
        5,  # mutinyRoleHatId
        6,  # quartermasterRoleHatId
        7,  # treasuryAuthorityRoleHatId
        1_700_000_000,  # deployedAt
        "0x6666666666666666666666666666666666666666",  # deployer
    )


def _reader_with(calls: dict[str, Any]):
    from web3 import AsyncWeb3
    from web3.providers import AsyncHTTPProvider

    w3 = AsyncWeb3(AsyncHTTPProvider("http://localhost:8545"))
    # Patch contract creation *before* the reader constructs registry/hats.
    w3.eth.contract = lambda address, abi=None, **kwargs: _AsyncContract(calls)
    reader = GovernanceReader(w3, "0x0000000000000000000000000000000000000000", "0x0000000000000000000000000000000000000000")
    return reader


@pytest.mark.asyncio
async def test_discover_squads_empty():
    reader = _reader_with({"deploymentCount": 0})
    squads = await reader.discover_squads()
    assert squads == []


@pytest.mark.asyncio
async def test_discover_squads_one():
    reader = _reader_with(
        {
            "deploymentCount": 1,
            ("deploymentAt", (0,)): 1,
            ("deployment", (1,)): _deployment_tuple(),
        },
    )
    squads = await reader.discover_squads()
    assert len(squads) == 1
    assert squads[0].safe == "0x1111111111111111111111111111111111111111"


@pytest.mark.asyncio
async def test_snapshot_invalid_index():
    reader = _reader_with({"deploymentCount": 0})
    with pytest.raises(GovernanceError) as exc_info:
        await reader.snapshot(0, [], [], "0x0000000000000000000000000000000000000000")
    assert "no deployments" in str(exc_info.value)


@pytest.mark.asyncio
async def test_snapshot_index_out_of_range():
    reader = _reader_with(
        {
            "deploymentCount": 1,
            ("deploymentAt", (0,)): 1,
            ("deployment", (1,)): _deployment_tuple(),
        },
    )
    with pytest.raises(GovernanceError) as exc_info:
        await reader.snapshot(5, [], [], "0x0000000000000000000000000000000000000000")
    assert "invalid squad index" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_snapshot_full(monkeypatch):
    a1 = "0x0000000000000000000000000000000000000001"
    a2 = "0x0000000000000000000000000000000000000002"
    reader = _reader_with(
        {
            "deploymentCount": 1,
            ("deploymentAt", (0,)): 1,
            ("deployment", (1,)): _deployment_tuple(),
            "activeMutinyId": 9,
            ("mutiny", (9,)): (
                "0xCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC",  # proposedNewCaptain
                1_700_010_000,  # startedAt
                100,  # snapshot
                5,  # yeas
                False,  # executed
            ),
            ("openProposalOf", (a2,)): 1,
            ("proposal", (1,)): (
                a2,  # proposer
                "0xBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB",  # to
                1_000_000_000_000_000_000,  # value
                0,  # op
                b"\x01\x02\x03",  # data
                1_700_086_400,  # deadline
                42,  # snapshot
                3,  # yeas
                1,  # nays
                True,  # captainApproved
                False,  # captainDefeated
                False,  # executed
            ),
            ("pendingCrewAddAt", (a1,)): 1_700_172_800,
            ("pendingCrewRemoveAt", (a1,)): 0,
            ("pendingCrewAddAt", (a2,)): 0,
            ("pendingCrewRemoveAt", (a2,)): 0,
            ("isWearerOfHat", (a1, 2)): True,  # captain hat
            ("isWearerOfHat", (a1, 3)): True,  # crew hat
            ("isWearerOfHat", (a2, 3)): False,
        },
    )

    async def fake_get_balance(_addr):
        return 5_000_000_000_000_000_000

    monkeypatch.setattr(reader.w3.eth, "get_balance", fake_get_balance)

    snapshot = await reader.snapshot(
        squad_index=0,
        crew_candidates=[a1, a2],
        proposer_candidates=[a2],
        captain=a1,
    )

    assert snapshot.squad.safe == "0x1111111111111111111111111111111111111111"
    assert len(snapshot.proposals) == 1
    assert snapshot.proposals[0].id == 1
    assert len(snapshot.mutinies) == 1
    assert snapshot.mutinies[0].id == 9
    assert len(snapshot.crew_deadlines) == 1
    assert snapshot.crew_deadlines[0].kind == DeadlineKind.ADD
    assert snapshot.treasury.eth_balance == 5_000_000_000_000_000_000
    assert snapshot.crew_state.captain.active is True
    assert len(snapshot.crew_state.crew) == 1


@pytest.mark.asyncio
async def test_no_active_proposals(monkeypatch):
    a1 = "0x0000000000000000000000000000000000000001"
    reader = _reader_with(
        {
            "deploymentCount": 1,
            ("deploymentAt", (0,)): 1,
            ("deployment", (1,)): _deployment_tuple(),
            "activeMutinyId": 0,
            ("openProposalOf", (a1,)): 0,
            ("pendingCrewAddAt", (a1,)): 0,
            ("pendingCrewRemoveAt", (a1,)): 0,
            ("isWearerOfHat", (a1, 2)): True,
            ("isWearerOfHat", (a1, 3)): True,
        },
    )
    async def fake_get_balance(_addr):
        return 0

    monkeypatch.setattr(reader.w3.eth, "get_balance", fake_get_balance)
    snapshot = await reader.snapshot(0, [a1], [a1], a1)
    assert snapshot.proposals == []
