import json
from pathlib import Path

from external_trade_prospects_api import EXECUTION_SNAPSHOT, MAILBOX_BUY_LEADS


ROOT = Path(__file__).resolve().parents[1]


def test_every_canonical_deal_has_governed_possible_profit():
    payload = json.loads((ROOT / "public" / "canonical-deals.json").read_text())
    assert payload["version"] >= 2
    assert payload["deals"]
    for deal in payload["deals"]:
        profit = deal["possibleProfit"]
        assert profit["status"] in {
            "EVIDENCED_ESTIMATE",
            "UNCONFIRMED_TARGET",
            "TARGET_ONLY",
            "INPUTS_REQUIRED",
        }
        assert profit["basis"]
        assert profit["status"] not in {"CONTRACTED", "INVOICED", "COLLECTED"}


def test_known_profit_scenarios_match_evidenced_deal_math():
    deals = {
        deal["id"]: deal
        for deal in json.loads(
            (ROOT / "public" / "canonical-deals.json").read_text()
        )["deals"]
    }
    soda = deals["SAHJONY-SODA-KR-500"]["possibleProfit"]
    assert soda["minUsd"] == 10 * 42
    assert soda["maxUsd"] == 15 * 42
    assert soda["recurringUsd"] == 15 * 500

    aluminum = deals["SAHJONY-AL-SCRAP-KE-25-50"]["possibleProfit"]
    assert aluminum["minUsd"] == 150 * 25
    assert aluminum["maxUsd"] == 150 * 50
    assert aluminum["status"] == "UNCONFIRMED_TARGET"


def test_every_external_deal_has_fail_closed_profit_fields():
    for deal in EXECUTION_SNAPSHOT + MAILBOX_BUY_LEADS:
        assert deal["possible_profit_status"] in {
            "EVIDENCED_ESTIMATE",
            "UNCONFIRMED_TARGET",
            "TARGET_ONLY",
            "INPUTS_REQUIRED",
        }
        assert deal["possible_profit_basis"]


def test_owner_deal_command_displays_possible_profit_separately():
    source = (ROOT / "src" / "DealCommandCenter.tsx").read_text()
    assert "Possible profit*" in source
    assert "Projected, not contracted or collected" in source
    assert "possibleProfitLabel(d.possibleProfit)" in source
