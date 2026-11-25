#!/usr/bin/env python
#
# Copyright IBM Corp. 2026
# SPDX-License-Identifier: Apache-2.0
#
"""Provision the live systems in compose.yaml and point AgenticHarvest at them.

Run from the repo root once the containers are up::

    podman compose -f examples/systems/compose.yaml up -d
    uv run python examples/systems/setup.py            # provision + write .env
    uv run python examples/systems/setup.py --check    # only report what is reachable

It is idempotent: anything that already exists is left alone. What it does:

    directus   creates the collections the examples use, and an API user and token
    keycloak   creates the "agenticharvest" realm the examples provision accounts in
    odoo       creates an API key for the admin user (JSON-2 needs one)

and then writes the AGENTICHARVEST_WEB_* settings for each app into ``.env``, keeping
every other line of the file as it was. Secrets are written to ``.env`` only;
nothing is printed but their presence.

The admin credentials it uses are the ones compose.yaml sets for a local,
throwaway stack. Override them with the variables in ``DEFAULTS`` below.
"""

from __future__ import annotations

import argparse
import os
import secrets
import sys
import time
from pathlib import Path
from typing import Any

import httpx

ENV_FILE = Path(".env")

DEFAULTS = {
    "DIRECTUS_URL": "http://127.0.0.1:8055",
    "DIRECTUS_ADMIN_EMAIL": "admin@example.com",
    "DIRECTUS_ADMIN_PASSWORD": "agenticharvest-admin",
    # The user whose token AgenticHarvest calls Directus with; one per environment.
    "DIRECTUS_API_USER": "agenticharvest-host@example.com",
    "KEYCLOAK_URL": "http://127.0.0.1:8080",
    "KEYCLOAK_ADMIN": "admin",
    "KEYCLOAK_ADMIN_PASSWORD": "agenticharvest-admin",
    "ODOO_URL": "http://127.0.0.1:8069",
    "ODOO_DB": "agenticharvest",
    "ODOO_LOGIN": "admin",
    "ODOO_PASSWORD": "admin",
}

#: The Keycloak realm the examples create accounts in.
REALM = "agenticharvest"

#: Directus collections the examples use: name -> [(field, type)].
COLLECTIONS: dict[str, list[tuple[str, str]]] = {
    # The shipping portal in examples/order_fulfillment.
    "shipments": [("order_id", "string"), ("customer", "string"), ("net", "decimal"),
                  ("status", "string")],
    # The onboarding tracker in examples/hire_to_onboard.
    "onboarding_tasks": [("employee_ref", "string"), ("task", "string"),
                         ("owner", "string"), ("status", "string")],
}


def setting(name: str) -> str:
    return os.environ.get(name) or DEFAULTS[name]


def wait_for(url: str, label: str, attempts: int = 60) -> None:
    for _ in range(attempts):
        try:
            if httpx.get(url, timeout=5).status_code < 500:
                return
        except httpx.HTTPError:
            pass
        time.sleep(2)
    raise SystemExit(f"{label} is not answering at {url}. Is the stack up?")


# ----------------------------------------------------------------------
# Directus
# ----------------------------------------------------------------------


def setup_directus(existing_token: str) -> dict[str, str]:
    base = setting("DIRECTUS_URL")
    wait_for(f"{base}/server/health", "Directus")
    login = httpx.post(
        f"{base}/auth/login",
        json={"email": setting("DIRECTUS_ADMIN_EMAIL"),
              "password": setting("DIRECTUS_ADMIN_PASSWORD")},
        timeout=30,
    )
    login.raise_for_status()
    headers = {"Authorization": f"Bearer {login.json()['data']['access_token']}"}
    with httpx.Client(base_url=base, headers=headers, timeout=30) as api:
        existing = {c["collection"] for c in api.get("/collections?limit=-1").json()["data"]}
        for name, fields in COLLECTIONS.items():
            if name in existing:
                continue
            api.post("/collections", json={
                "collection": name,
                "schema": {},
                "meta": {"icon": "box"},
                "fields": [
                    {"field": "id", "type": "integer", "meta": {"hidden": True},
                     "schema": {"is_primary_key": True, "has_auto_increment": True}},
                    {"field": "date_created", "type": "timestamp",
                     "meta": {"special": ["date-created"]}},
                    *({"field": f, "type": t} for f, t in fields),
                ],
            }).raise_for_status()
            print(f"  directus: created collection '{name}'")

        # A Directus user holds one static token, and it never reads back (it
        # comes back masked). So each place that runs this script gets its own
        # user, and keeps its token while it works: running setup from the
        # host and from the runner container never revokes the other's token.
        token = existing_token
        works = bool(token) and httpx.get(
            f"{base}/users/me", headers={"Authorization": f"Bearer {token}"}, timeout=30
        ).status_code == 200
        if not works:
            user_id = _directus_api_user(api, setting("DIRECTUS_API_USER"))
            token = secrets.token_urlsafe(32)
            api.patch(f"/users/{user_id}", json={"token": token}).raise_for_status()
            print(f"  directus: issued an API token for {setting('DIRECTUS_API_USER')}")
    return {
        "URL": base,
        "SPEC": "/server/specs/oas",
        "SPEC_KIND": "openapi",
        "AUTH": "bearer",
        "TOKEN": token,
        "PREFIX": "/items/",
    }


def _directus_api_user(api: httpx.Client, email: str) -> str:
    """The id of the Directus user ``email``, created with the admin role if absent."""
    found = api.get("/users", params={"filter[email][_eq]": email, "fields": "id"}).json()
    if found["data"]:
        return str(found["data"][0]["id"])
    admin = api.get("/users/me", params={"fields": "role"}).json()["data"]["role"]
    created = api.post("/users", json={
        "email": email, "role": admin, "status": "active",
        # Never logs in with a password; it authenticates with its token only.
        "password": secrets.token_urlsafe(32),
    })
    created.raise_for_status()
    return str(created.json()["data"]["id"])


# ----------------------------------------------------------------------
# Keycloak
# ----------------------------------------------------------------------

#: The official Admin REST API description for the pinned Keycloak version.
KEYCLOAK_SPEC = "https://www.keycloak.org/docs-api/26.4.7/rest-api/openapi.json"


def setup_keycloak() -> dict[str, str]:
    base = setting("KEYCLOAK_URL")
    wait_for(f"{base}/realms/master", "Keycloak")
    token = httpx.post(
        f"{base}/realms/master/protocol/openid-connect/token",
        data={"grant_type": "password", "client_id": "admin-cli",
              "username": setting("KEYCLOAK_ADMIN"),
              "password": setting("KEYCLOAK_ADMIN_PASSWORD")},
        timeout=30,
    )
    token.raise_for_status()
    headers = {"Authorization": f"Bearer {token.json()['access_token']}"}
    with httpx.Client(base_url=base, headers=headers, timeout=30) as api:
        realms = {r["realm"] for r in api.get("/admin/realms").json()}
        if REALM not in realms:
            api.post("/admin/realms", json={
                "realm": REALM,
                "enabled": True,
                # Record admin events, so account changes are an audit trail.
                "adminEventsEnabled": True,
                "adminEventsDetailsEnabled": True,
            }).raise_for_status()
            print(f"  keycloak: created realm '{REALM}'")
        for role in ("employee", "engineering", "finance"):
            if api.get(f"/admin/realms/{REALM}/roles/{role}").status_code == 404:
                api.post(f"/admin/realms/{REALM}/roles", json={"name": role}).raise_for_status()
                print(f"  keycloak: created role '{role}'")

    spec = Path("examples/systems/specs/keycloak-26.4.7.json")
    if not spec.is_file():
        spec.parent.mkdir(parents=True, exist_ok=True)
        reply = httpx.get(KEYCLOAK_SPEC, timeout=60, follow_redirects=True)
        reply.raise_for_status()
        spec.write_text(reply.text, encoding="utf-8")
        print(f"  keycloak: saved the Admin REST API description to {spec}")
    return {
        "URL": base,
        "SPEC": str(spec),
        "SPEC_KIND": "openapi",
        "AUTH": "oauth2-password",
        "TOKEN_URL": "/realms/master/protocol/openid-connect/token",
        "CLIENT_ID": "admin-cli",
        "USERNAME": setting("KEYCLOAK_ADMIN"),
        "PASSWORD": setting("KEYCLOAK_ADMIN_PASSWORD"),
        # The user-and-role administration of one realm.
        "PREFIX": "/admin/realms/{realm}/",
    }


# ----------------------------------------------------------------------
# Odoo
# ----------------------------------------------------------------------

#: The Odoo models the examples use.
ODOO_MODELS = "hr.job,hr.applicant,hr.employee,hr.department,hr.recruitment.stage"


def setup_odoo(existing_key: str) -> dict[str, str]:
    base = setting("ODOO_URL")
    db = setting("ODOO_DB")
    wait_for(f"{base}/web/login", "Odoo")
    key = existing_key
    if not key or not _odoo_key_works(base, db, key):
        key = _odoo_new_key(base, db)
        print("  odoo: created an API key for the admin user")
    return {
        "URL": base,
        "SPEC": "/doc",
        "SPEC_KIND": "odoo",
        "AUTH": "odoo",
        "TOKEN": key,
        "DATABASE": db,
        "USERNAME": setting("ODOO_LOGIN"),
        "PASSWORD": setting("ODOO_PASSWORD"),
        "MODELS": ODOO_MODELS,
        # Hiring an applicant is a business verb Odoo does not prefix action_.
        "METHODS": "hr.applicant.create_employee_from_applicant",
    }


def _odoo_key_works(base: str, db: str, key: str) -> bool:
    reply = httpx.post(
        f"{base}/json/2/res.users/search_read",
        headers={"Authorization": f"bearer {key}", "X-Odoo-Database": db},
        json={"domain": [], "fields": ["id"], "limit": 1},
        timeout=30,
    )
    return reply.status_code == 200


def _odoo_new_key(base: str, db: str) -> str:
    """Create an API key the way Odoo's Preferences > Security screen does."""
    with httpx.Client(base_url=base, timeout=30) as session:
        login = session.post("/web/session/authenticate", json={
            "jsonrpc": "2.0",
            "params": {"db": db, "login": setting("ODOO_LOGIN"),
                       "password": setting("ODOO_PASSWORD")},
        }).json()
        if not (login.get("result") or {}).get("uid"):
            raise SystemExit("Odoo rejected the admin login; check ODOO_LOGIN / ODOO_PASSWORD.")

        def call(model: str, method: str, args: list[Any], kwargs: dict | None = None) -> Any:
            reply = session.post("/web/dataset/call_kw", json={
                "jsonrpc": "2.0",
                "params": {"model": model, "method": method, "args": args,
                           "kwargs": kwargs or {}},
            }).json()
            if "error" in reply:
                raise SystemExit(f"Odoo {model}.{method}: {reply['error']['data']['message']}")
            return reply["result"]

        wizard = call("res.users.apikeys.description", "create",
                      [{"name": "agenticharvest", "expiration_date": False}])
        # make_key asks for the password again (an identity check) before it
        # issues the key.
        check = call("res.users.apikeys.description", "make_key", [[wizard]])["res_id"]
        shown = call("res.users.identitycheck", "run_check", [[check]],
                     {"context": {"password": setting("ODOO_PASSWORD")}})
        return str(shown["context"]["default_key"])


# ----------------------------------------------------------------------
# .env
# ----------------------------------------------------------------------


def read_env(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines() if path.is_file() else []


def env_value(lines: list[str], key: str) -> str:
    for line in lines:
        name, sep, value = line.partition("=")
        if sep and name.strip() == key:
            return value.strip().strip('"').strip("'")
    return ""


def write_env(path: Path, updates: dict[str, str]) -> None:
    """Set ``updates`` in ``path``, replacing existing keys and keeping the rest."""
    lines = read_env(path)
    remaining = dict(updates)
    out: list[str] = []
    for line in lines:
        name, sep, _ = line.partition("=")
        key = name.strip()
        if sep and key in remaining:
            out.append(f"{key}={remaining.pop(key)}")
        else:
            out.append(line)
    if remaining:
        if out and out[-1].strip():
            out.append("")
        out.append("# Live systems (written by examples/systems/setup.py)")
        out.extend(f"{key}={value}" for key, value in remaining.items())
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


# ----------------------------------------------------------------------
# Check
# ----------------------------------------------------------------------


def check() -> int:
    """List each configured app's resources through AgenticHarvest itself."""
    from agenticharvest.domains.web.config import WebConfigError, configured_apps
    from agenticharvest.domains.web.tools import client_for

    apps = configured_apps()
    if not apps:
        print("No web apps configured; run this script without --check first.")
        return 1
    failed = 0
    for app in apps:
        try:
            ir = client_for(app).ir()
        except (WebConfigError, Exception) as exc:  # noqa: BLE001 - report every failure
            failed += 1
            print(f"  {app:10} FAILED  {exc}")
            continue
        writes = sum(op.writes for op in ir.operations)
        print(f"  {app:10} ok      {ir.title} {ir.version}: {len(ir.resources)} resources, "
              f"{len(ir.operations)} operations ({writes} write)")
    return 1 if failed else 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="only check what is reachable")
    args = parser.parse_args(argv)
    if args.check:
        return check()

    lines = read_env(ENV_FILE)
    apps = {
        "directus": setup_directus(env_value(lines, "AGENTICHARVEST_WEB_DIRECTUS_TOKEN")),
        "keycloak": setup_keycloak(),
        "odoo": setup_odoo(env_value(lines, "AGENTICHARVEST_WEB_ODOO_TOKEN")),
    }
    updates = {"AGENTICHARVEST_WEB_APPS": ",".join(apps)}
    for app, values in apps.items():
        updates.update({f"AGENTICHARVEST_WEB_{app.upper()}_{k}": v for k, v in values.items()})
    write_env(ENV_FILE, updates)
    print(f"\nWrote {len(updates)} settings for {', '.join(apps)} to {ENV_FILE}.")
    print("Checking each app through AgenticHarvest:")
    return check()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
