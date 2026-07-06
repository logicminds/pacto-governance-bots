"""Markdown formatter for governance snapshot data."""

from __future__ import annotations

from datetime import datetime, timezone

from .types import (
    CrewDeadline,
    DeadlineKind,
    Mutiny,
    Proposal,
    SnapshotData,
    SquadInfo,
    TreasuryBalance,
)


def format_snapshot(data: SnapshotData) -> str:
    """Format a governance snapshot into Markdown suitable for a Squad channel."""
    out: list[str] = []
    out.append("# Pacto Governance Snapshot\n")
    out.append(f"- Generated at: {fmt_timestamp(data.generated_at)}\n")

    out.append("\n## Squad Info\n")
    out.append(format_squad_info(data.squad))

    out.append("\n## Active Proposals\n")
    if not data.proposals:
        out.append("No active proposals.\n")
    else:
        for proposal in data.proposals:
            out.append(format_proposal(proposal, data.generated_at))

    out.append("\n## Upcoming Deadlines\n")
    if not data.crew_deadlines:
        out.append("No upcoming crew deadlines.\n")
    else:
        for deadline in data.crew_deadlines:
            out.append(format_crew_deadline(deadline))

    out.append("\n## Treasury / Safe Balance\n")
    out.append(format_treasury(data.treasury))

    out.append("\n## Active Mutinies\n")
    if not data.mutinies:
        out.append("No active mutinies.\n")
    else:
        for mutiny in data.mutinies:
            out.append(format_mutiny(mutiny))

    out.append("\n## Captain & Crew\n")
    out.append(format_crew_state(data.crew_state))

    out.append("\n## Suggested Discussion Prompts\n")
    out.append(format_prompts(data))

    return "".join(out)


def format_squad_info(squad: SquadInfo) -> str:
    return (
        f"- Safe: {squad.safe}\n"
        f"- Quartermaster: {squad.quartermaster}\n"
        f"- Mutiny module: {squad.mutiny_module}\n"
        f"- Treasury authority: {squad.treasury_authority}\n"
        f"- Squad admin proxy: {squad.squad_admin_proxy}\n"
        f"- Top hat: {squad.top_hat_id}\n"
        f"- Captain hat: {squad.captain_hat_id}\n"
        f"- Crew hat: {squad.crew_hat_id}\n"
        f"- Squad admin hat: {squad.squad_admin_hat_id}\n"
        f"- Mutiny role hat: {squad.mutiny_role_hat_id}\n"
        f"- Quartermaster role hat: {squad.quartermaster_role_hat_id}\n"
        f"- Treasury authority role hat: {squad.treasury_authority_role_hat_id}\n"
        f"- Deployed at: {fmt_timestamp(squad.deployed_at)}\n"
        f"- Deployer: {squad.deployer}\n"
    )


def format_proposal(proposal: Proposal, generated_at: int) -> str:
    deadline = fmt_timestamp(proposal.deadline)
    remaining = fmt_duration_until(generated_at, proposal.deadline)
    return (
        f"### Proposal #{proposal.id}\n\n"
        f"- Proposer: {proposal.proposer}\n"
        f"- Target: {proposal.to}\n"
        f"- Value: {format_token_amount(proposal.value, 18)} ETH\n"
        f"- Operation: {proposal.op}\n"
        f"- Deadline: {deadline} ({remaining})\n"
        f"- Yeas: {proposal.yeas} / Nays: {proposal.nays}\n"
        f"- Captain approved: {'Yes' if proposal.captain_approved else 'No'}\n"
        f"- Status: {proposal_status(proposal)}\n\n"
    )


def proposal_status(proposal: Proposal) -> str:
    if proposal.executed:
        return "Executed"
    if proposal.captain_defeated:
        return "Defeated"
    return "Open"


def format_crew_deadline(deadline: CrewDeadline) -> str:
    action = deadline.kind.value
    return f"- Crew {action} for {deadline.target} executable at {fmt_timestamp(deadline.executable_at)}\n"


def format_treasury(treasury: TreasuryBalance) -> str:
    out = f"- ETH: {format_token_amount(treasury.eth_balance, 18)}\n"
    if not treasury.tokens:
        out += "- No ERC-20 tokens tracked.\n"
    else:
        out += "- Tokens:\n"
        for token in treasury.tokens:
            out += f"  - {token.token} ({token.symbol}): {format_token_amount(token.balance, token.decimals)}\n"
    return out


def format_mutiny(mutiny: Mutiny) -> str:
    return (
        f"### Mutiny #{mutiny.id}\n\n"
        f"- Proposed captain: {mutiny.proposed_new_captain}\n"
        f"- Started at: {fmt_timestamp(mutiny.started_at)}\n"
        f"- Yeas: {mutiny.yeas}\n"
        f"- Status: {'Executed' if mutiny.executed else 'Active'}\n\n"
    )


def format_crew_state(state) -> str:
    out = f"- Captain: {state.captain.wearer} ({state.captain.hat_id}: {hat_status(state.captain)})\n"
    if not state.crew:
        out += "- Crew: none\n"
    else:
        out += "- Crew:\n"
        for member in state.crew:
            out += f"  - {member.wearer} ({member.hat_id}: {hat_status(member)})\n"
    return out


def hat_status(hat) -> str:
    return "active" if hat.active else "inactive"


def format_prompts(data: SnapshotData) -> str:
    prompts: list[str] = []
    for proposal in data.proposals:
        remaining = (
            "overdue"
            if proposal.deadline <= data.generated_at
            else f"in {format_relative_duration(proposal.deadline - data.generated_at)}"
        )
        prompts.append(f"Proposal #{proposal.id} deadline is {remaining} — discuss.")
    for deadline in data.crew_deadlines:
        action = deadline.kind.value
        prompts.append(
            f"Crew {action} for {deadline.target} is executable at {fmt_timestamp(deadline.executable_at)} — review."
        )
    for mutiny in data.mutinies:
        prompts.append(
            f"Mutiny #{mutiny.id} proposes {mutiny.proposed_new_captain} as captain — review."
        )
    if not data.crew_state.captain.active:
        prompts.append("Captain's hat is currently inactive — address leadership continuity.")
    if not prompts:
        prompts.append("No urgent governance items — check back later.")
    return "".join(f"{i + 1}. {prompt}\n" for i, prompt in enumerate(prompts))


def format_token_amount(value: int, decimals: int) -> str:
    if value == 0:
        return "0"
    if decimals == 0:
        return str(value)
    divisor = 10**decimals
    integer = value // divisor
    remainder = value % divisor
    if remainder == 0:
        return str(integer)
    frac = str(remainder).rjust(decimals, "0").rstrip("0")
    if not frac:
        return str(integer)
    return f"{integer}.{frac}"


def fmt_timestamp(ts: int) -> str:
    try:
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        return dt.isoformat().replace("+00:00", "Z")
    except (OSError, ValueError, OverflowError):
        return str(ts)


def fmt_duration_until(from_ts: int, until_ts: int) -> str:
    if until_ts <= from_ts:
        return "overdue"
    return f"in {format_relative_duration(until_ts - from_ts)}"


def format_relative_duration(seconds: int) -> str:
    if seconds >= 86_400:
        days = seconds // 86_400
        hours = (seconds % 86_400) // 3_600
        if hours > 0:
            return f"{days}d {hours}h"
        return f"{days}d"
    if seconds >= 3_600:
        hours = seconds // 3_600
        minutes = (seconds % 3_600) // 60
        if minutes > 0:
            return f"{hours}h {minutes}m"
        return f"{hours}h"
    if seconds >= 60:
        minutes = seconds // 60
        secs = seconds % 60
        if secs > 0:
            return f"{minutes}m {secs}s"
        return f"{minutes}m"
    return f"{seconds}s"
