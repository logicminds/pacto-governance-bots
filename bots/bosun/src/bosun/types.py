"""Typed snapshot data shared between the EVM reader and Markdown formatter."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class DeadlineKind(Enum):
    """Kind of pending crew roster change."""

    ADD = "add"
    REMOVE = "remove"


@dataclass
class SquadInfo:
    """On-chain squad metadata from the registry."""

    safe: str
    quartermaster: str
    mutiny_module: str
    treasury_authority: str
    squad_admin_proxy: str
    top_hat_id: int
    captain_hat_id: int
    crew_hat_id: int
    squad_admin_hat_id: int
    mutiny_role_hat_id: int
    quartermaster_role_hat_id: int
    treasury_authority_role_hat_id: int
    deployed_at: int
    deployer: str


@dataclass
class Proposal:
    """A governance proposal tracked by TreasuryAuthority."""

    id: int
    proposer: str
    to: str
    value: int
    op: int
    data: bytes
    deadline: int
    snapshot: int
    yeas: int
    nays: int
    captain_approved: bool
    captain_defeated: bool
    executed: bool


@dataclass
class Mutiny:
    """An active mutiny against the current captain."""

    id: int
    proposed_new_captain: str
    started_at: int
    snapshot: int
    yeas: int
    executed: bool


@dataclass
class CrewDeadline:
    """A pending crew roster change with its executable timestamp."""

    kind: DeadlineKind
    target: str
    executable_at: int


@dataclass
class TokenBalance:
    """Balance of a single ERC-20 token held by the Safe."""

    token: str
    symbol: str
    decimals: int
    balance: int


@dataclass
class TreasuryBalance:
    """Treasury holdings for the squad Safe."""

    eth_balance: int = 0
    tokens: list[TokenBalance] = field(default_factory=list)


@dataclass
class HatState:
    """Status of a single hat wearer."""

    wearer: str
    hat_id: int
    active: bool


@dataclass
class CrewState:
    """Captain and crew state derived from Hats."""

    captain: HatState = field(default_factory=lambda: HatState("", 0, False))
    crew: list[HatState] = field(default_factory=list)


@dataclass
class SnapshotData:
    """Aggregated governance snapshot for a single squad."""

    squad: SquadInfo
    proposals: list[Proposal] = field(default_factory=list)
    mutinies: list[Mutiny] = field(default_factory=list)
    crew_deadlines: list[CrewDeadline] = field(default_factory=list)
    treasury: TreasuryBalance = field(default_factory=TreasuryBalance)
    crew_state: CrewState = field(default_factory=CrewState)
    generated_at: int = 0
