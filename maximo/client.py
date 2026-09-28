"""Maximo Manage REST client.

Read-only by construction: `MaximoClient` exposes GET only. Writes live in
`deploy.py` and are reachable solely from Agent 5 after the final user gate
(blueprint section 6).

Two routes are supported:

  route="api"  -> GET {base}/api/{path}   with an `apikey` header
  route="oslc" -> GET {base}/oslc/{path}  with a `MAXAUTH` header

`api` is the default. On the MAS trial and ACN IAX environments the `/oslc/`
route is SAML-intercepted and redirects to OIDC, silently ignoring the API key;
`/api/` (lowercase) is the one that works. See skills/mx_rest_api_SKILL.md.
"""
from __future__ import annotations

import base64
import json
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from core.config import MaximoConfig
from core.errors import MaximoError
from core.logging import get

log = get("suite.maximo.client")


@dataclass
class ConnectionStatus:
    reachable: bool
    route: str
    base_url: str
    detail: str = ""
    object_structures: int = 0
    version: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "reachable": self.reachable,
            "route": self.route,
            "base_url": self.base_url,
            "detail": self.detail,
            "object_structures": self.object_structures,
            "version": self.version,
        }


class MaximoClient:
    """Read-only HTTP access to a Maximo Manage environment."""

    def __init__(self, cfg: MaximoConfig) -> None:
        self.cfg = cfg
        self._session: Any = None
        self._lock = threading.Lock()
        self._probe: ConnectionStatus | None = None
        self._os_names: set[str] | None = None

    # -- wiring ------------------------------------------------------------
    @property
    def configured(self) -> bool:
        return self.cfg.configured

    def _http(self):
        if self._session is None:
            with self._lock:
                if self._session is None:
                    import httpx

                    self._session = httpx.Client(
                        verify=self.cfg.verify_tls,
                        timeout=self.cfg.timeout_seconds,
                        follow_redirects=False,  # a redirect means auth was not honoured
                    )
        return self._session

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.cfg.route == "oslc":
            if not self.cfg.maxauth:
                raise MaximoError(
                    "route=oslc requires MAXAUTH.",
                    remedy="Set MAXAUTH=base64(user:password) in .env, or switch maximo.route to 'api'.",
                )
            token = self.cfg.maxauth
            # Accept a raw user:password and encode it, per blueprint section 6.
            if ":" in token and not token.endswith("="):
                token = base64.b64encode(token.encode()).decode()
            headers["MAXAUTH"] = token
        else:
            if not self.cfg.api_key:
                raise MaximoError(
                    "route=api requires MAXIMO_MANAGE_APIKEY.",
                    remedy="Set MAXIMO_MANAGE_APIKEY in .env.",
                )
            headers["apikey"] = self.cfg.api_key
        return headers

    def _url(self, path: str) -> str:
        prefix = "/oslc/" if self.cfg.route == "oslc" else "/api/"
        return urljoin(self.cfg.base_url.rstrip("/") + prefix, path.lstrip("/"))

    # -- reads -------------------------------------------------------------
    def get(self, path: str, params: dict | None = None) -> Any:
        """GET against the configured route. Raises MaximoError on failure."""
        if not self.configured:
            raise MaximoError(
                "Maximo is not configured.",
                remedy="Set MAXIMO_MANAGE_URL and MAXIMO_MANAGE_APIKEY in .env, or work offline.",
            )
        url = self._url(path)
        try:
            resp = self._http().get(url, headers=self._headers(), params=params)
        except Exception as exc:
            raise MaximoError(f"Could not reach Maximo at {url}: {exc}") from exc

        if resp.status_code in (301, 302, 303, 307, 308):
            location = resp.headers.get("location", "")
            raise MaximoError(
                f"Maximo redirected the request (HTTP {resp.status_code}) - authentication was not honoured.",
                remedy=(
                    "This is the SAML/OIDC interception seen on /oslc/. "
                    "Set maximo.route: api in config/suite.yaml."
                    + (f" Redirect target: {location[:120]}" if location else "")
                ),
            )
        if resp.status_code in (401, 403):
            raise MaximoError(
                f"Maximo rejected the credentials (HTTP {resp.status_code}).",
                remedy="Regenerate the API key in Maximo and update MAXIMO_MANAGE_APIKEY.",
            )
        if resp.status_code == 404:
            raise MaximoError(f"Not found in Maximo: {path}")
        if resp.status_code >= 400:
            raise MaximoError(f"Maximo returned HTTP {resp.status_code} for {path}: {resp.text[:300]}")

        try:
            return resp.json()
        except ValueError as exc:
            raise MaximoError(f"Maximo returned non-JSON for {path}: {resp.text[:200]}") from exc

    def ping(self, *, force: bool = False) -> ConnectionStatus:
        """Cheap reachability probe used by `doctor` and the UI status bar."""
        if self._probe is not None and not force:
            return self._probe

        if not self.configured:
            self._probe = ConnectionStatus(
                reachable=False,
                route=self.cfg.route,
                base_url=self.cfg.base_url or "(not set)",
                detail="Not configured - MAXIMO_MANAGE_URL / MAXIMO_MANAGE_APIKEY missing.",
            )
            return self._probe

        try:
            meta = self.get("apimeta")
            entries = meta if isinstance(meta, list) else meta.get("member", [])
            self._probe = ConnectionStatus(
                reachable=True,
                route=self.cfg.route,
                base_url=self.cfg.base_url,
                detail="Connected.",
                object_structures=len(entries),
            )
        except MaximoError as exc:
            self._probe = ConnectionStatus(
                reachable=False,
                route=self.cfg.route,
                base_url=self.cfg.base_url,
                detail=exc.message,
            )
        return self._probe

    # -- typed reads used by the validator ---------------------------------
    def object_structure_schema(self, os_name: str) -> dict | None:
        """JSON schema for one object structure, or None if absent."""
        try:
            return self.get(f"jsonschemas/{os_name.lower()}")
        except MaximoError as exc:
            log.debug("schema fetch failed for %s: %s", os_name, exc)
            return None

    def object_structure_names(self) -> set[str]:
        """Every object-structure name in the live environment, lower-cased.

        One `/apimeta` call, cached. Without this the validator can only guess
        at OS names, and guessing misses the structures that matter most - the
        add-on ones the bundled catalogue does not have.
        """
        if self._os_names is not None:
            return self._os_names
        try:
            meta = self.get("apimeta")
        except MaximoError as exc:
            log.debug("apimeta fetch failed: %s", exc)
            self._os_names = set()
            return self._os_names

        entries = meta if isinstance(meta, list) else meta.get("member", []) or []
        self._os_names = {
            (e.get("osName") or "").lower() for e in entries if isinstance(e, dict) and e.get("osName")
        }
        log.info("live environment exposes %d object structures", len(self._os_names))
        return self._os_names

    def script_exists(self, name: str) -> bool | None:
        """True/False if we could check, None if Maximo was unreachable.

        Blueprint section 6: verify an autoscript name is free before generating.
        """
        try:
            data = self.get(
                "os/mxapiautoscript",
                params={"oslc.where": f'autoscript="{name.upper()}"', "oslc.select": "autoscript", "lean": 1},
            )
        except MaximoError as exc:
            log.debug("script check failed for %s: %s", name, exc)
            return None
        members = data.get("member", data.get("rdfs:member", [])) if isinstance(data, dict) else data
        return bool(members)

    def sync_schemas(
        self,
        target: Path,
        *,
        workers: int = 8,
        progress=None,
    ) -> dict[str, Any]:
        """Mirror every live object-structure schema into `target`.

        Read-only. This is what makes live validation exact: with the real
        schemas on disk the validator resolves any object by its MBO name,
        instead of guessing which structure exposes it.
        """
        from concurrent.futures import ThreadPoolExecutor

        names = sorted(self.object_structure_names())
        if not names:
            raise MaximoError(
                "The live environment returned no object structures.",
                remedy="Check the connection with `python run.py maximo ping`.",
            )

        target.mkdir(parents=True, exist_ok=True)
        written = failed = 0
        done = 0

        def fetch(os_name: str) -> tuple[str, dict | None]:
            return os_name, self.object_structure_schema(os_name)

        with ThreadPoolExecutor(max_workers=workers) as pool:
            for os_name, schema in pool.map(fetch, names):
                done += 1
                if schema:
                    (target / f"{os_name}.json").write_text(
                        json.dumps(schema, indent=1), encoding="utf-8"
                    )
                    written += 1
                else:
                    # Usually a security-group restriction, not an error.
                    failed += 1
                if progress and done % 25 == 0:
                    progress(done, len(names))

        meta = [{"osName": n.upper()} for n in names]
        (target.parent / "apimeta-live.json").write_text(
            json.dumps(meta, indent=1), encoding="utf-8"
        )
        if progress:
            progress(done, len(names))
        log.info("synced %d/%d live object-structure schemas to %s", written, len(names), target)
        return {"total": len(names), "written": written, "unreadable": failed, "path": str(target)}

    def count(self, os_name: str, where: str | None = None) -> int | None:
        params: dict[str, Any] = {"oslc.pageSize": 1, "lean": 1, "count": 1}
        if where:
            params["oslc.where"] = where
        try:
            data = self.get(f"os/{os_name.lower()}", params=params)
        except MaximoError:
            return None
        if isinstance(data, dict):
            for key in ("totalCount", "count", "oslc:totalCount"):
                if key in data:
                    try:
                        return int(data[key])
                    except (TypeError, ValueError):
                        pass
        return None

    def close(self) -> None:
        if self._session is not None:
            self._session.close()
            self._session = None
