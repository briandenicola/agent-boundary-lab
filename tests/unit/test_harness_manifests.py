"""Guards on the harness chat service's deployment artifacts (no cluster, no network)."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEPLOYMENT = ROOT / "deploy/kustomize/harness/deployment.yaml"
DOCKERFILE = ROOT / "Dockerfile.harness"
TASKFILE = ROOT / "tasks/Taskfile.harness.yml"
DOCKERIGNORE = ROOT / ".dockerignore"


def test_deployment_wires_the_model_and_both_facades_by_dns() -> None:
    dep = DEPLOYMENT.read_text()
    for name in (
        "LOCAL_MODEL_BASE_URL",
        "DEMO_A2A_FACADE_URL_AUDIT",
        "DEMO_A2A_FACADE_URL_ENFORCED",
    ):
        assert name in dep
    assert "local-model.REPLACE_WITH_NAMESPACE.svc.cluster.local/v1" in dep
    assert not re.search(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", dep)


def test_tokens_come_from_secrets_never_from_the_manifest() -> None:
    dep = DEPLOYMENT.read_text()
    assert "name: a2a-facade-config" in dep and "name: harness-config" in dep
    assert not re.search(r"(?m)^\s*-?\s*name: (DEMO_A2A_TOKEN|HARNESS_UI_TOKEN)\s*\n\s*value:", dep)
    assert not list((ROOT / "deploy/kustomize/harness").glob("secret*"))


def test_harness_has_no_azure_identity_and_is_not_the_agent_image() -> None:
    dep = DEPLOYMENT.read_text()
    assert "REPLACE_WITH_HARNESS_IMAGE" in dep
    assert "REPLACE_WITH_AGENT_IMAGE" not in dep
    assert "azure.workload.identity" not in dep
    assert "serviceAccountName" not in dep
    assert "automountServiceAccountToken: false" in dep


def test_harness_image_has_no_azure_sdk_and_caps_protobuf() -> None:
    docker = DOCKERFILE.read_text()
    code = "\n".join(ln for ln in docker.splitlines() if not ln.lstrip().startswith("#"))
    assert "azure" not in code.lower()
    assert '"protobuf>=5.29.5,<7"' in docker and '"a2a-sdk==1.0.2"' in docker
    assert "containment_demo.harness.chat" in docker


def test_task_pins_by_digest_and_dockerignore_has_no_trailing_slash() -> None:
    task = TASKFILE.read_text()
    assert "harness-digest" in task and "Dockerfile.harness" in task
    for line in DOCKERIGNORE.read_text().splitlines():
        rule = line.strip()
        if rule and not rule.startswith("#"):
            assert not rule.rstrip().endswith("/"), rule
