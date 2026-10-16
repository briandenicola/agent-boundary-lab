"""Owner-run Agent ID lifecycle check; never invokes Foundry or grants permissions."""

from __future__ import annotations

import argparse
import fcntl
import json
import logging
import os
import re
import secrets
import stat
import sys
import tempfile
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, TextIO
from uuid import UUID

import httpx
from azure.core.credentials import TokenCredential
from azure.core.exceptions import ClientAuthenticationError
from azure.identity import CertificateCredential

from containment_demo.identity_probe import ProbeError, http_client

GRAPH = "https://graph.microsoft.com/v1.0"
TYPES = {
    "blueprint": ("applications", "agentIdentityBlueprint"),
    "principal": ("servicePrincipals", "agentIdentityBlueprintPrincipal"),
    "agent": ("servicePrincipals", "agentIdentity"),
}
ORDER = tuple(TYPES)
DESCRIPTION = "Temporary I0 directory lifecycle check; no Foundry invocation."
PERMISSIONS = {
    "blueprint": ["AgentIdentityBlueprint.ReadWrite.All"],
    "principal": ["AgentIdentityBlueprintPrincipal.ReadWrite.All"],
    "agent": [
        "AgentIdentity.Create.All",
        "AgentIdentity.Read.All",
        "AgentIdentity.DeleteRestore.All",
    ],
}


def identity_id(value: Any) -> str:
    if not isinstance(value, str):
        raise ProbeError("directory_identity_id_invalid")
    try:
        parsed = UUID(value)
    except ValueError:
        raise ProbeError("directory_identity_id_invalid") from None
    if str(parsed) != value or parsed.int == 0:
        raise ProbeError("directory_identity_id_invalid")
    return value


@dataclass(frozen=True)
class Settings:
    tenant_id: str
    client_id: str
    sponsor_user_id: str = field(repr=False)
    certificate_path: Path | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        for value in (self.tenant_id, self.client_id, self.sponsor_user_id):
            identity_id(value)
        if self.certificate_path is not None:
            info = self.certificate_path.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise ProbeError("directory_certificate_must_be_owner_only_regular_file")


class DirectoryAPI(Protocol):
    def request(
        self, method: str, path: str, status: int, body: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...


class StdioGraph:
    """Private pipe to the signed-in Graph PowerShell process; no bearer export."""

    def __init__(self, source: TextIO, destination: TextIO) -> None:
        self.source = source
        self.destination = destination
        self.sequence = 0

    def request(
        self, method: str, path: str, status: int, body: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        self.sequence += 1
        print(
            json.dumps(
                {
                    "graph_request": self.sequence,
                    "method": method,
                    "path": path,
                    "body": body,
                }
            ),
            file=self.destination,
            flush=True,
        )
        line = self.source.readline(1_048_577)
        if not line or len(line) > 1_048_576:
            raise ProbeError("directory_graph_pipe_response_missing_or_oversized")
        try:
            response = json.loads(line)
        except ValueError:
            raise ProbeError("directory_graph_pipe_response_invalid") from None
        if not isinstance(response, dict) or response.get("graph_request") != self.sequence:
            raise ProbeError("directory_graph_pipe_sequence_mismatch")
        if response.get("transport_error") is True:
            raise ProbeError("directory_graph_transport_failed")
        if type(response.get("status")) is not int:
            raise ProbeError("directory_graph_pipe_status_invalid")
        if response["status"] != status:
            raise GraphError(response["status"])
        payload = response.get("body")
        if status == 204:
            return {}
        if not isinstance(payload, dict):
            raise ProbeError("directory_graph_pipe_body_invalid")
        return payload


class GraphError(ProbeError):
    def __init__(self, status: int) -> None:
        self.status = status
        super().__init__(f"directory_graph_http_{status}")


class Graph:
    def __init__(self, http: httpx.Client, credential: TokenCredential) -> None:
        self.http = http
        self.credential = credential

    def request(
        self, method: str, path: str, status: int, body: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        token = self.credential.get_token("https://graph.microsoft.com/.default").token
        response = self.http.request(
            method,
            f"{GRAPH}/{path}",
            headers={"Authorization": f"Bearer {token}", "OData-Version": "4.0"},
            json=body,
        )
        if response.status_code != status:
            raise GraphError(response.status_code)
        if status == 204:
            return {}
        try:
            payload = response.json()
        except ValueError:
            raise ProbeError("directory_graph_response_invalid") from None
        if not isinstance(payload, dict):
            raise ProbeError("directory_graph_response_invalid")
        return payload


def collection(key: str) -> str:
    parent, kind = TYPES[key]
    return f"{parent}/microsoft.graph.{kind}"


def instance(key: str, object_id: str) -> str:
    parent, kind = TYPES[key]
    return f"{parent}/{identity_id(object_id)}/microsoft.graph.{kind}"


def private_open(path: Path) -> int:
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    info = os.fstat(descriptor)
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.getuid()
        or info.st_mode & 0o077
        or info.st_nlink != 1
    ):
        os.close(descriptor)
        raise ProbeError("directory_journal_must_be_owner_only_regular_file")
    return descriptor


@contextmanager
def journal_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = private_open(path.with_suffix(".lock"))
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ProbeError("directory_journal_in_use") from None
        yield
    finally:
        os.close(descriptor)


def save(path: Path, journal: dict[str, Any]) -> None:
    descriptor = private_open(path)
    os.close(descriptor)
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as output:
            temporary = output.name
            json.dump(journal, output, indent=2)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        if temporary is not None and os.path.exists(temporary):
            os.unlink(temporary)


def load(path: Path, settings: Settings) -> dict[str, Any]:
    if not path.exists():
        raise ProbeError("directory_journal_missing")
    with os.fdopen(private_open(path)) as source:
        journal = json.load(source)
    if (
        not isinstance(journal, dict)
        or journal.get("version") != 1
        or journal.get("tenant_id") != settings.tenant_id
        or journal.get("client_id") != settings.client_id
        or not isinstance(journal.get("name"), str)
        or not re.fullmatch(r"i0-directory-[0-9a-f]{12}", journal["name"])
        or journal.get("pending") not in (None, *ORDER)
        or not isinstance(journal.get("resources"), dict)
        or list(journal["resources"]) != list(ORDER[: len(journal["resources"])])
    ):
        raise ProbeError("directory_journal_context_or_schema_invalid")
    for resource in journal["resources"].values():
        if not isinstance(resource, dict) or not isinstance(resource.get("deleted"), bool):
            raise ProbeError("directory_journal_resource_invalid")
        identity_id(resource.get("id"))
        if "app_id" in resource:
            identity_id(resource["app_id"])
    if len(journal["resources"]) > 1 and "app_id" not in journal["resources"]["blueprint"]:
        raise ProbeError("directory_journal_blueprint_client_id_missing")
    return journal


def verify(
    graph: DirectoryAPI, journal: dict[str, Any], key: str, *, missing_ok: bool = False
) -> dict[str, Any] | None:
    resource = journal["resources"][key]
    fields = {
        "blueprint": "id,appId,displayName,description",
        "principal": "id,appId",
        "agent": "id,displayName,agentIdentityBlueprintId",
    }
    try:
        payload = graph.request(
            "GET", f"{instance(key, resource['id'])}?$select={fields[key]}", 200
        )
    except GraphError as exc:
        if missing_ok and exc.status == 404:
            return None
        raise
    if payload.get("id") != resource["id"]:
        raise ProbeError("directory_object_id_mismatch")
    expected_type = f"#microsoft.graph.{TYPES[key][1]}"
    if payload.get("@odata.type", expected_type) != expected_type:
        raise ProbeError("directory_object_type_mismatch")
    if key == "blueprint":
        if payload.get("displayName") != journal["name"]:
            raise ProbeError("directory_object_ownership_mismatch")
        app_id = identity_id(payload.get("appId"))
        if "app_id" in resource and resource["app_id"] != app_id:
            raise ProbeError("directory_blueprint_client_id_mismatch")
    elif key == "principal":
        if payload.get("appId") != journal["resources"]["blueprint"]["app_id"]:
            raise ProbeError("directory_principal_blueprint_mismatch")
    elif (
        payload.get("displayName") != f"{journal['name']}-agent"
        or payload.get("agentIdentityBlueprintId") != journal["resources"]["blueprint"]["app_id"]
    ):
        raise ProbeError("directory_agent_blueprint_mismatch")
    return payload


def cleanup(graph: DirectoryAPI, path: Path, journal: dict[str, Any]) -> None:
    if journal["pending"] is not None:
        raise ProbeError("directory_create_outcome_unknown_manual_reconciliation_required")
    # Check every remaining object before deleting any; never cascade past a mismatch.
    for key in reversed(ORDER):
        if key in journal["resources"] and not journal["resources"][key]["deleted"]:
            verify(graph, journal, key, missing_ok=True)
    for key in reversed(ORDER):
        if key not in journal["resources"] or journal["resources"][key]["deleted"]:
            continue
        resource = journal["resources"][key]
        try:
            graph.request("DELETE", instance(key, resource["id"]), 204)
        except GraphError as exc:
            if exc.status != 404:
                raise
        if verify(graph, journal, key, missing_ok=True) is not None:
            raise ProbeError("directory_deletion_not_observed")
        resource["deleted"] = True
        save(path, journal)


def run(graph: DirectoryAPI, path: Path, settings: Settings) -> dict[str, Any]:
    if path.exists():
        raise ProbeError("directory_journal_exists_review_or_cleanup_before_new_run")
    journal: dict[str, Any] = {
        "version": 1,
        "tenant_id": settings.tenant_id,
        "client_id": settings.client_id,
        "sponsor_user_id": settings.sponsor_user_id,
        "name": f"i0-directory-{secrets.token_hex(6)}",
        "pending": None,
        "resources": {},
    }
    save(path, journal)
    sponsors = [f"{GRAPH}/users/{settings.sponsor_user_id}"]
    for key in ORDER:
        if key == "blueprint":
            body = {"displayName": journal["name"], "sponsors@odata.bind": sponsors}
        elif key == "principal":
            body = {"appId": journal["resources"]["blueprint"]["app_id"]}
        else:
            body = {
                "displayName": f"{journal['name']}-agent",
                "agentIdentityBlueprintId": journal["resources"]["blueprint"]["app_id"],
                "sponsors@odata.bind": sponsors,
            }
        # Persist intent before a non-idempotent POST; never retry an uncertain creation.
        journal["pending"] = key
        save(path, journal)
        try:
            payload = graph.request("POST", collection(key), 201, body)
        except GraphError as exc:
            if 400 <= exc.status < 500 and exc.status != 408:
                journal["pending"] = None
                save(path, journal)
            raise
        resource = {"id": identity_id(payload.get("id")), "deleted": False}
        journal["resources"][key] = resource
        journal["pending"] = None
        save(path, journal)
        observed = verify(graph, journal, key)
        if key == "blueprint" and observed is not None:
            resource["app_id"] = identity_id(observed.get("appId"))
            save(path, journal)
    graph.request(
        "PATCH",
        instance("blueprint", journal["resources"]["blueprint"]["id"]),
        204,
        {"description": DESCRIPTION},
    )
    observed = verify(graph, journal, "blueprint")
    if observed is None or observed.get("description") != DESCRIPTION:
        raise ProbeError("directory_update_not_observed")
    cleanup(graph, path, journal)
    return result("pass")


def result(verdict: str, detail: str | None = None) -> dict[str, Any]:
    report: dict[str, Any] = {
        "directory_lifecycle": verdict,
        "foundry_delegation": "not_evaluated",
        "containment": "not_evaluated",
        "i0_complete": False,
    }
    if detail is not None:
        report["detail"] = detail
    return report


def plan() -> dict[str, Any]:
    return {
        "authentication": "Dedicated certificate-authenticated Graph application; no CLI token.",
        "application_permissions": PERMISSIONS,
        "operations": [
            *[{"method": "POST", "path": collection(key)} for key in ORDER],
            *[
                {"method": "GET", "path": f"{TYPES[key][0]}/{{id}}/microsoft.graph.{TYPES[key][1]}"}
                for key in ORDER
            ],
            {"method": "PATCH", "path": "applications/{id}/microsoft.graph.agentIdentityBlueprint"},
            *[
                {
                    "method": "DELETE",
                    "path": f"{TYPES[key][0]}/{{id}}/microsoft.graph.{TYPES[key][1]}",
                }
                for key in reversed(ORDER)
            ],
        ],
        "scope": "Three new temporary objects only; no consent, RBAC, federation or deployment.",
        "failure": "Stops with an owner-only journal; cleanup never guesses unknown creation IDs.",
        **result("not_run"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("plan", "run", "cleanup"))
    parser.add_argument("--state", type=Path, default=Path(".identity-probe/directory.json"))
    parser.add_argument("--approve", action="store_true")
    parser.add_argument("--graph-stdio", action="store_true")
    args = parser.parse_args()
    for logger in ("azure", "msal", "httpx", "httpcore"):
        logging.getLogger(logger).setLevel(logging.ERROR)
    try:
        if args.command == "plan":
            print(json.dumps(plan(), indent=2))
            return 0
        if not args.approve:
            raise ProbeError("directory_mutation_requires_explicit_approval")
        settings = Settings(
            tenant_id=os.environ.get("IDENTITY_TENANT_ID", ""),
            client_id=os.environ.get("IDENTITY_GRAPH_CLIENT_ID", ""),
            sponsor_user_id=os.environ.get("IDENTITY_SPONSOR_USER_ID", ""),
            certificate_path=None
            if args.graph_stdio
            else Path(os.environ.get("IDENTITY_GRAPH_CERTIFICATE_PATH", "")),
        )
        with journal_lock(args.state), ExitStack() as stack:
            journal = load(args.state, settings) if args.command == "cleanup" else None
            graph: DirectoryAPI
            if args.graph_stdio:
                if (
                    journal is not None
                    and journal.get("sponsor_user_id") != settings.sponsor_user_id
                ):
                    raise ProbeError("directory_interactive_operator_mismatch")
                graph = StdioGraph(sys.stdin, sys.stdout)
            else:
                if settings.certificate_path is None:
                    raise ProbeError("directory_certificate_required")
                credential = stack.enter_context(
                    CertificateCredential(
                        tenant_id=settings.tenant_id,
                        client_id=settings.client_id,
                        certificate_path=str(settings.certificate_path),
                        connection_timeout=10,
                        read_timeout=30,
                        retry_total=0,
                    )
                )
                graph = Graph(stack.enter_context(http_client(30)), credential)
            if journal is None:
                report = run(graph, args.state, settings)
            else:
                cleanup(graph, args.state, journal)
                report = result("not_evaluated", "directory_recorded_objects_cleaned_up")
        print(json.dumps(report, indent=None if args.graph_stdio else 2))
        return 0
    except ProbeError as exc:
        report = result("inconclusive", str(exc))
    except ClientAuthenticationError:
        report = result("inconclusive", "directory_certificate_authentication_failed")
    except httpx.HTTPError as exc:
        from containment_demo.invoke import classify_invocation_exception

        report = result("inconclusive", f"directory_{classify_invocation_exception(exc).value}")
    except (OSError, ValueError, TypeError):
        report = result("inconclusive", "directory_private_file_or_configuration_invalid")
    print(json.dumps(report, indent=None if args.graph_stdio else 2))
    return 2


if __name__ == "__main__":
    sys.exit(main())
