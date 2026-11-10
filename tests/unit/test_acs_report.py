"""Operator reports describe real configuration, not successful hosted calls."""

from __future__ import annotations

import copy
import json
import logging
import sys
from types import SimpleNamespace

import pytest
from scripts.acs_report import render

from containment_demo.governance import hosted
from containment_demo.governance.hosted import SCENARIOS


@pytest.fixture
def report():
    return {
        "endpoint": "https://synthetic.services.ai.azure.com/api/projects/demo",
        "agents": [
            {
                "scenario": scenario.name,
                "agent_name": f"demo-gov-{scenario.name}",
                "version": "3",
                "image": "example.azurecr.io/demo@sha256:" + "a" * 64,
                "status": "active",
                "governance_mode": scenario.governance_mode.value,
                "rai_policy_id": f"/synthetic/account/raiPolicies/{scenario.network}",
            }
            for scenario in SCENARIOS
        ],
    }


def test_report_shows_versions_registration_ids_and_honest_sample_prompts(report):
    registration = {
        "context": {"display_name": "demo-copilot-oauth", "tenant_id": "synthetic-tenant"},
        "client_id": "synthetic-client",
        "object_id": "synthetic-object",
        "phase": "ready",
    }
    text, code = render(report, registration)
    assert code == 0
    assert "demo-gov-governance-denial  version=3  status=active" in text
    assert "Client ID: synthetic-client" in text
    assert "local journal, not live readback" in text
    assert "Send the synthetic servicing record to the external processor." in text
    assert "Copilot protected lookup: BLOCKED" in text
    assert "BLOCKED in the original ACS-first publication" in text
    assert "runtime results require dated chat/evidence" in text
    assert "Deferred Copilot prompt" not in text
    assert "Configuration readback only" in text


def test_missing_helper_is_inconclusive_and_still_prints_the_prompt():
    text, code = render({"agents": None}, None)
    assert code == 2
    assert "INCONCLUSIVE" in text
    assert "live Foundry readback unavailable" in text
    assert "Send the synthetic servicing record" in text


def test_uncertain_registration_still_reports_known_identity_and_prompts(report):
    registration = {
        "context": {"display_name": "demo-copilot-oauth", "tenant_id": "synthetic-tenant"},
        "phase": "create_requested",
    }
    text, code = render(report, registration)
    assert code == 2
    assert "Recorded Entra app: demo-copilot-oauth" in text
    assert "Client ID: INCONCLUSIVE" in text
    assert "Send the synthetic servicing record" in text


def test_live_status_keeps_logs_off_the_json_channel(tmp_path, monkeypatch, capsys, report):
    path = tmp_path / "deployment.json"
    path.write_text(json.dumps(report))
    monkeypatch.setattr(logging.getLogger(), "handlers", [logging.StreamHandler(sys.stdout)])
    monkeypatch.setattr(hosted, "configure_logging", lambda: None)
    monkeypatch.setattr(hosted, "STATE_DIRECTORY", tmp_path)
    monkeypatch.setattr(hosted, "HostedSettings", lambda: object())
    monkeypatch.setattr(hosted, "Settings", lambda: object())
    monkeypatch.setattr(
        hosted, "build_client", lambda cfg: (SimpleNamespace(close=lambda: None), None)
    )

    def network(cfg, settings):
        logging.warning("Synthetic status log")
        return {}

    monkeypatch.setattr(hosted, "policy_facts", network)
    monkeypatch.setattr(
        hosted,
        "read_scenario",
        lambda client, models, cfg, settings, scenario, version: next(
            row for row in report["agents"] if row["scenario"] == scenario.name
        ),
    )
    http_logger = logging.getLogger("httpx")
    previous_level = http_logger.level
    try:
        assert hosted.main(["status", "--report", str(path)]) == 0
    finally:
        http_logger.setLevel(previous_level)
    captured = capsys.readouterr()
    assert json.loads(captured.out)["agents"] == report["agents"]
    assert "Synthetic status log" in captured.err


@pytest.mark.parametrize("invalid", ["missing", "duplicate", "unhealthy", "mixed_image"])
def test_incomplete_or_unhealthy_configuration_is_not_presented_as_ready(report, invalid):
    report = copy.deepcopy(report)
    if invalid == "missing":
        report["agents"].pop()
    elif invalid == "duplicate":
        report["agents"][0] = report["agents"][1]
    elif invalid == "unhealthy":
        report["agents"][0]["status"] = "failed"
    else:
        report["agents"][0]["image"] = "other.azurecr.io/demo@sha256:" + "b" * 64
    with pytest.raises(ValueError, match="configuration readback"):
        render(report, None)
