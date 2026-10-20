from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_external_kustomization_includes_ingress_resources_only() -> None:
    content = (ROOT / "deploy/kustomize/harness-external/kustomization.yaml").read_text()
    assert "resources:" in content
    assert "- ingress-harness.yaml" in content
    assert "- ingress-oauth2.yaml" in content
    assert "harness-auth-mode.yaml" not in content


def test_oauth2_ingress_increases_proxy_header_buffer() -> None:
    content = (ROOT / "deploy/kustomize/harness-external/ingress-oauth2.yaml").read_text()
    assert "nginx.ingress.kubernetes.io/proxy-buffer-size" in content
    assert '"16k"' in content


def test_harness_ingress_allows_slow_chat_turns() -> None:
    content = (ROOT / "deploy/kustomize/harness-external/ingress-harness.yaml").read_text()
    assert 'nginx.ingress.kubernetes.io/proxy-read-timeout: "300"' in content
    assert 'nginx.ingress.kubernetes.io/proxy-send-timeout: "300"' in content
    assert 'nginx.ingress.kubernetes.io/proxy-connect-timeout: "30"' in content
