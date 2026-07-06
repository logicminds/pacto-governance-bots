"""Unit tests for the bosun Markdown formatter."""

from __future__ import annotations

from bosun.formatter import format_snapshot
from bosun.types import (
    CrewDeadline,
    CrewState,
    DeadlineKind,
    HatState,
    Mutiny,
    Proposal,
    SnapshotData,
    SquadInfo,
    TreasuryBalance,
)


def _sample_snapshot() -> SnapshotData:
    return SnapshotData(
        squad=SquadInfo(
            safe="0x1111111111111111111111111111111111111111",
            quartermaster="0x2222222222222222222222222222222222222222",
            mutiny_module="0x3333333333333333333333333333333333333333",
            treasury_authority="0x4444444444444444444444444444444444444444",
            squad_admin_proxy="0x5555555555555555555555555555555555555555",
            top_hat_id=1,
            captain_hat_id=2,
            crew_hat_id=3,
            squad_admin_hat_id=4,
            mutiny_role_hat_id=5,
            quartermaster_role_hat_id=6,
            treasury_authority_role_hat_id=7,
            deployed_at=1_700_000_000,
            deployer="0x6666666666666666666666666666666666666666",
        ),
        proposals=[
            Proposal(
                id=1,
                proposer="0xAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
                to="0xBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB",
                value=1_000_000_000_000_000_000,
                op=0,
                data=b"\x01\x02\x03",
                deadline=1_700_086_400,
                snapshot=42,
                yeas=3,
                nays=1,
                captain_approved=True,
                captain_defeated=False,
                executed=False,
            )
        ],
        mutinies=[
            Mutiny(
                id=9,
                proposed_new_captain="0xCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC",
                started_at=1_700_010_000,
                snapshot=100,
                yeas=5,
                executed=False,
            )
        ],
        crew_deadlines=[
            CrewDeadline(
                kind=DeadlineKind.ADD,
                target="0xDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDD",
                executable_at=1_700_172_800,
            )
        ],
        treasury=TreasuryBalance(eth_balance=5_000_000_000_000_000_000, tokens=[]),
        crew_state=CrewState(
            captain=HatState(
                wearer="0xAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
                hat_id=2,
                active=True,
            ),
            crew=[
                HatState(
                    wearer="0x1111111111111111111111111111111111111111",
                    hat_id=3,
                    active=True,
                )
            ],
        ),
        generated_at=1_700_000_000,
    )


def test_formatter_includes_all_sections():
    markdown = format_snapshot(_sample_snapshot())
    assert "# Pacto Governance Snapshot" in markdown
    assert "## Squad Info" in markdown
    assert "## Active Proposals" in markdown
    assert "### Proposal #1" in markdown
    assert "Proposer: 0x" in markdown
    assert "Value: 1 ETH" in markdown
    assert "Yeas: 3 / Nays: 1" in markdown
    assert "Captain approved: Yes" in markdown
    assert "## Upcoming Deadlines" in markdown
    assert "## Treasury / Safe Balance" in markdown
    assert "## Active Mutinies" in markdown
    assert "### Mutiny #9" in markdown
    assert "## Captain & Crew" in markdown
    assert "## Suggested Discussion Prompts" in markdown


def test_formatter_no_proposals():
    data = _sample_snapshot()
    data.proposals = []
    markdown = format_snapshot(data)
    assert "No active proposals" in markdown


def test_formatter_no_mutinies():
    data = _sample_snapshot()
    data.mutinies = []
    markdown = format_snapshot(data)
    assert "No active mutinies" in markdown


def test_formatter_no_deadlines():
    data = _sample_snapshot()
    data.crew_deadlines = []
    markdown = format_snapshot(data)
    assert "No upcoming crew deadlines" in markdown


def test_formatter_inactive_captain_prompt():
    data = _sample_snapshot()
    data.crew_state.captain.active = False
    markdown = format_snapshot(data)
    assert "Captain's hat is currently inactive" in markdown


def test_formatter_no_urgent_prompts():
    data = _sample_snapshot()
    data.proposals = []
    data.mutinies = []
    data.crew_deadlines = []
    data.crew_state.captain.active = True
    markdown = format_snapshot(data)
    assert "No urgent governance items" in markdown


def test_formatter_token_amount_zero():
    from bosun.formatter import format_token_amount

    assert format_token_amount(0, 18) == "0"


def test_formatter_token_amount_with_decimals():
    from bosun.formatter import format_token_amount

    assert format_token_amount(1_500_000, 6) == "1.5"
    assert format_token_amount(1_000_000, 6) == "1"


def test_formatter_duration():
    from bosun.formatter import format_relative_duration

    assert format_relative_duration(86_400) == "1d"
    assert format_relative_duration(90_000) == "1d 1h"
    assert format_relative_duration(3_600) == "1h"
    assert format_relative_duration(90) == "1m 30s"
