"""On-chain governance reader for a single NavePirata squad.

Uses web3.py v7 AsyncWeb3/AsyncHTTPProvider so all reads can run against any
JSON-RPC endpoint (Sepolia, anvil, or a mocked transport).
"""

from __future__ import annotations

import time
from typing import Any

from web3 import AsyncWeb3
from web3.providers import AsyncHTTPProvider

from . import contracts
from .types import (
    CrewDeadline,
    CrewState,
    DeadlineKind,
    HatState,
    Mutiny,
    Proposal,
    SnapshotData,
    SquadInfo,
    TokenBalance,
    TreasuryBalance,
)

MAX_DEPLOYMENT_COUNT = 10_000


class GovernanceError(Exception):
    """Errors that can occur while reading governance state."""


class GovernanceReader:
    """Reads public governance state for a Pacto squad."""

    def __init__(self, w3: AsyncWeb3, registry: str, hats: str) -> None:
        self.w3 = w3
        self.registry = self.w3.eth.contract(
            address=registry, abi=contracts.INAVE_PIRATA_REGISTRY_ABI
        )
        self.hats = self.w3.eth.contract(address=hats, abi=contracts.IHATS_ABI)
        self.known_tokens: list[TokenBalance] = []

    @classmethod
    def from_url(cls, rpc_url: str, registry: str, hats: str) -> "GovernanceReader":
        w3 = AsyncWeb3(AsyncHTTPProvider(rpc_url))
        return cls(w3, registry, hats)

    async def discover_squads(self) -> list[SquadInfo]:
        """Discover every squad registered in NavePirataRegistry."""
        try:
            count = await self.registry.functions.deploymentCount().call()
        except Exception as exc:  # noqa: BLE001
            raise GovernanceError(f"failed to read deploymentCount: {exc}") from exc

        if count > MAX_DEPLOYMENT_COUNT:
            raise GovernanceError(
                f"deployment count {count} exceeds maximum allowed {MAX_DEPLOYMENT_COUNT}"
            )

        squads: list[SquadInfo] = []
        for i in range(count):
            try:
                top_hat_id = await self.registry.functions.deploymentAt(i).call()
                deployment = await self.registry.functions.deployment(top_hat_id).call()
            except Exception as exc:  # noqa: BLE001
                raise GovernanceError(f"failed to read deploymentAt({i}): {exc}") from exc
            squads.append(_deployment_to_squad_info(deployment))
        return squads

    async def snapshot(
        self,
        squad_index: int,
        crew_candidates: list[str],
        proposer_candidates: list[str],
        captain: str,
    ) -> SnapshotData:
        """Build a full snapshot for the squad at the given registry index."""
        squads = await self.discover_squads()
        if not squads:
            raise GovernanceError(
                f"invalid squad index {squad_index} (no deployments in registry)"
            )
        if squad_index < 0 or squad_index >= len(squads):
            raise GovernanceError(
                f"invalid squad index {squad_index} (count: {len(squads)})"
            )
        squad = squads[squad_index]

        mutinies = await self._read_mutinies(squad.mutiny_module)
        proposals = await self._read_proposals(
            squad.treasury_authority, proposer_candidates
        )
        crew_deadlines = await self._read_crew_deadlines(
            squad.quartermaster, crew_candidates
        )
        treasury = await self._read_treasury(squad.safe)
        crew_state = await self._read_crew_state(
            squad.captain_hat_id, squad.crew_hat_id, captain, crew_candidates
        )

        return SnapshotData(
            squad=squad,
            proposals=proposals,
            mutinies=mutinies,
            crew_deadlines=crew_deadlines,
            treasury=treasury,
            crew_state=crew_state,
            generated_at=int(time.time()),
        )

    async def _read_mutinies(self, mutiny_module_address: str) -> list[Mutiny]:
        mutiny = self.w3.eth.contract(
            address=mutiny_module_address, abi=contracts.IMUTINY_MODULE_ABI
        )
        try:
            active_id = await mutiny.functions.activeMutinyId().call()
        except Exception as exc:  # noqa: BLE001
            raise GovernanceError(f"failed to read activeMutinyId: {exc}") from exc
        if active_id == 0:
            return []
        try:
            result = await mutiny.functions.mutiny(active_id).call()
        except Exception as exc:  # noqa: BLE001
            raise GovernanceError(f"failed to read mutiny({active_id}): {exc}") from exc
        proposed_new_captain, started_at, snapshot, yeas, executed = result
        return [
            Mutiny(
                id=active_id,
                proposed_new_captain=str(proposed_new_captain),
                started_at=int(started_at),
                snapshot=int(snapshot),
                yeas=int(yeas),
                executed=bool(executed),
            )
        ]

    async def _read_proposals(
        self, treasury_authority_address: str, proposer_candidates: list[str]
    ) -> list[Proposal]:
        treasury = self.w3.eth.contract(
            address=treasury_authority_address, abi=contracts.ITREASURY_AUTHORITY_ABI
        )
        proposals: list[Proposal] = []
        for candidate in proposer_candidates:
            try:
                proposal_id = await treasury.functions.openProposalOf(candidate).call()
            except Exception as exc:  # noqa: BLE001
                raise GovernanceError(
                    f"failed to read openProposalOf({candidate}): {exc}"
                ) from exc
            if proposal_id == 0:
                continue
            try:
                result = await treasury.functions.proposal(proposal_id).call()
            except Exception as exc:  # noqa: BLE001
                raise GovernanceError(
                    f"failed to read proposal({proposal_id}): {exc}"
                ) from exc
            (
                proposer,
                to,
                value,
                op,
                data,
                deadline,
                snapshot,
                yeas,
                nays,
                captain_approved,
                captain_defeated,
                executed,
            ) = result
            proposals.append(
                Proposal(
                    id=int(proposal_id),
                    proposer=str(proposer),
                    to=str(to),
                    value=int(value),
                    op=int(op),
                    data=bytes(data),
                    deadline=int(deadline),
                    snapshot=int(snapshot),
                    yeas=int(yeas),
                    nays=int(nays),
                    captain_approved=bool(captain_approved),
                    captain_defeated=bool(captain_defeated),
                    executed=bool(executed),
                )
            )
        return proposals

    async def _read_crew_deadlines(
        self, quartermaster_address: str, crew_candidates: list[str]
    ) -> list[CrewDeadline]:
        quartermaster = self.w3.eth.contract(
            address=quartermaster_address, abi=contracts.IQUARTERMASTER_ABI
        )
        deadlines: list[CrewDeadline] = []
        for candidate in crew_candidates:
            try:
                add_at = await quartermaster.functions.pendingCrewAddAt(candidate).call()
                remove_at = await quartermaster.functions.pendingCrewRemoveAt(
                    candidate
                ).call()
            except Exception as exc:  # noqa: BLE001
                raise GovernanceError(
                    f"failed to read pending crew deadlines for {candidate}: {exc}"
                ) from exc
            if add_at > 0:
                deadlines.append(
                    CrewDeadline(
                        kind=DeadlineKind.ADD,
                        target=candidate,
                        executable_at=int(add_at),
                    )
                )
            if remove_at > 0:
                deadlines.append(
                    CrewDeadline(
                        kind=DeadlineKind.REMOVE,
                        target=candidate,
                        executable_at=int(remove_at),
                    )
                )
        return deadlines

    async def _read_treasury(self, safe_address: str) -> TreasuryBalance:
        try:
            eth_balance = await self.w3.eth.get_balance(safe_address)
        except Exception as exc:  # noqa: BLE001
            raise GovernanceError(f"failed to read ETH balance: {exc}") from exc
        tokens: list[TokenBalance] = []
        for token in self.known_tokens:
            try:
                erc20 = self.w3.eth.contract(address=token.token, abi=contracts.IERC20_ABI)
                balance = await erc20.functions.balanceOf(safe_address).call()
            except Exception as exc:  # noqa: BLE001
                raise GovernanceError(
                    f"failed to read token balance for {token.token}: {exc}"
                ) from exc
            tokens.append(
                TokenBalance(
                    token=token.token,
                    symbol=token.symbol,
                    decimals=token.decimals,
                    balance=int(balance),
                )
            )
        return TreasuryBalance(eth_balance=int(eth_balance), tokens=tokens)

    async def _read_crew_state(
        self,
        captain_hat_id: int,
        crew_hat_id: int,
        captain: str,
        crew_candidates: list[str],
    ) -> CrewState:
        captain_wearer = ""
        if captain and captain != "0x0000000000000000000000000000000000000000":
            try:
                is_wearer = await self.hats.functions.isWearerOfHat(
                    captain, captain_hat_id
                ).call()
            except Exception as exc:  # noqa: BLE001
                raise GovernanceError(
                    f"failed to read captain hat status: {exc}"
                ) from exc
            if is_wearer:
                captain_wearer = captain
        crew: list[HatState] = []
        for candidate in crew_candidates:
            try:
                is_wearer = await self.hats.functions.isWearerOfHat(
                    candidate, crew_hat_id
                ).call()
            except Exception as exc:  # noqa: BLE001
                raise GovernanceError(
                    f"failed to read crew hat status for {candidate}: {exc}"
                ) from exc
            if is_wearer:
                crew.append(
                    HatState(wearer=candidate, hat_id=crew_hat_id, active=True)
                )
        return CrewState(
            captain=HatState(
                wearer=captain_wearer,
                hat_id=captain_hat_id,
                active=bool(captain_wearer),
            ),
            crew=crew,
        )


def _deployment_to_squad_info(deployment: Any) -> SquadInfo:
    """Convert an INavePirataRegistry.Deployment tuple to SquadInfo."""
    return SquadInfo(
        safe=str(deployment[0]),
        quartermaster=str(deployment[1]),
        mutiny_module=str(deployment[2]),
        treasury_authority=str(deployment[3]),
        squad_admin_proxy=str(deployment[4]),
        top_hat_id=int(deployment[5]),
        captain_hat_id=int(deployment[6]),
        crew_hat_id=int(deployment[7]),
        squad_admin_hat_id=int(deployment[8]),
        mutiny_role_hat_id=int(deployment[9]),
        quartermaster_role_hat_id=int(deployment[10]),
        treasury_authority_role_hat_id=int(deployment[11]),
        deployed_at=int(deployment[12]),
        deployer=str(deployment[13]),
    )
