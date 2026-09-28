# maximo-api skill

Use this skill whenever you need to call Maximo REST APIs.

---

## Configured environments

Two Maximo Manage endpoints are known-good. Only one at a time lives in `.env` under `MAXIMO_MANAGE_URL` / `MAXIMO_MANAGE_APIKEY`; the other is kept commented out.

| Environment | URL | Notes |
|---|---|---|
| **MAS trial (IBM public)** | `https://main.manage.sandbox-trial.suite.maximo.com/maximo` | Public TLS cert (`verify=True`). User `50368WY0EQ` (Amherst Campus / EAGLENA). Maximo Manage 9.1.395. 401 object structures. Has PLUSC (Calibration) but no PLUSDCU / no cuelibrary. |
| **ACN IAX (Accenture sandbox)** | `https://acnsbx.manage.sbx.apps.ocp.acn-ix.iam.accenture.com/maximo` | Self-signed cert (`verify=False`). User `KUSHAL.F.SHARMA`. Manage on Liberty 26.0.0.4 / DB2. 503 object structures. Has `cuelibrary`. Requires 74.179.199.93 hosts file entries. |

Both use identical auth: `apikey: <MAXIMO_MANAGE_APIKEY>` header on the **lowercase `/api/`** route.

MVI (Visual Inspection) endpoints, if present:

| Variable | Value |
|---|---|
| `MAXIMO_API_ENDPOINT1` | `https://main.visualinspection.sandbox-trial.suite.maximo.com/api` — MVI trial |
| `MAXIMO_APIKEY1` | MVI API key |

---

## Both environments — confirmed working (2026-09-22, trial re-confirmed 2026-09-23)

**Auth:** `apikey: <MAXIMO_MANAGE_APIKEY>` header on the **`/api/`** (lowercase) route (works on both environments).
Also accepted as `?apikey=...` query param.

**Per-env quirks:**
- **MAS trial** — public TLS cert (`verify=True` ok). No hosts-file entries needed. WebSphere Liberty 26.0.0.3.
- **ACN IAX** — self-signed cert (`verify=False` required). Requires 74.179.199.93 entries in hosts file. WebSphere Liberty 26.0.0.4.

### Critical routing rule

| Route | Behaviour |
|---|---|
| `/maximo/oslc/...` | **SAML-intercepted** — redirects to OIDC, ignores apikey |
| `/maximo/API/...` (uppercase) | 404 — not configured on this server |
| **`/maximo/api/...` (lowercase)** | **Works** — apikey header processed by Maximo |

Always use `/api/` (lowercase). Never use `/oslc/` for programmatic calls.

---

## Python helper

```python
import warnings, json, requests
from pathlib import Path

warnings.filterwarnings("ignore", message="Unverified HTTPS request")

def _load_env():
    env = {}
    with open(Path(r"c:\Users\kushal.f.sharma\repos\maximo\.env")) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip()
    return env

_env = _load_env()
MX_BASE  = _env["MAXIMO_MANAGE_URL"].rstrip("/")
MX_KEY   = _env["MAXIMO_MANAGE_APIKEY"]

_s = requests.Session()
# ACN IAX has a self-signed cert; MAS trial has a valid public cert.
# Set verify=False only when MX_BASE points at the ACN IAX host.
_s.verify = "acn-ix.iam.accenture.com" not in MX_BASE

def mx_get(path: str, params: dict = None) -> dict:
    """Read-only GET against Maximo Manage /api/ route."""
    r = _s.get(
        MX_BASE + "/api" + path,
        headers={"apikey": MX_KEY, "Accept": "application/json"},
        params=params,
        timeout=30,
    )
    r.raise_for_status()
    return r.json()
```

---

## Confirmed working object structures

Common to both environments:

| Object Structure | Data | Notes |
|---|---|---|
| `mxapiwo` | Work Orders | Full WO data including status, worktype, siteid |
| `mxapiasset` | Assets | assetnum, description, status, siteid |
| `mxapijobplan` | Job Plans | jpnum, description, tasks |
| `mxapiadmin` | System admin | Metadata |

Environment-specific:

| Object Structure | MAS trial | ACN IAX |
|---|---|---|
| `cuelibrary` (CU Library) | ❌ not present | ✓ live records |
| `plusdutylog` | ❌ | ✓ (0 records) |
| `mxpluscdsconfig` (Calibration) | ✓ | not tested |
| `mxapipluscassetstat` | BMXAA9301E | not tested |

Object-structure counts: **trial = 401**, **ACN IAX = 503** (via `/api/apimeta`).

### Not accessible in either env (BMXAA9301E — security group restriction)
`mxwo`, `mxasset`, `mxjobplan` — use `mxapi*` versions above instead.
`plusdcuestimate`, `plusgwo`, `plusgasset` — PLUSG/PLUSD security groups not granted on ACN IAX.

### Not installed (BMXAA4216E)
`mxplusdu` — PLUSDCU (CU catalogue) module isn't installed on either the trial or the ACN IAX demo. For CU work, `cuelibrary` on ACN IAX is the only live CU-like source available today.

---

## Common queries

```python
# Identity check
me = mx_get("/whoami")
print(me.get("spi:userName"))   # KUSHAL.F.SHARMA

# Work Orders (3 records)
data = mx_get("/os/mxapiwo", {
    "lean": "1", "oslc.pageSize": "3",
    "oslc.select": "wonum,description,status,worktype,siteid,woclass"
})
for wo in data.get("member", []):
    print(wo["wonum"], wo["status"])

# Assets
data = mx_get("/os/mxapiasset", {
    "lean": "1", "oslc.pageSize": "5",
    "oslc.select": "assetnum,description,siteid,status,assettype"
})

# Job Plans
data = mx_get("/os/mxapijobplan", {
    "lean": "1", "oslc.pageSize": "5",
    "oslc.select": "jpnum,description,siteid,jpduration"
})

# CU Library (cuelibrary object structure)
data = mx_get("/os/cuelibrary", {
    "lean": "1", "oslc.pageSize": "5"
})

# Filter WOs by status
data = mx_get("/os/mxapiwo", {
    "lean": "1",
    "oslc.where": "status=\"INPRG\"",
    "oslc.select": "wonum,description,status,worktype",
    "oslc.pageSize": "10"
})

# System info
info = mx_get("/systeminfo")

# apimeta — full list of 503 accessible object structures
meta = mx_get("/apimeta")
names = [str(m).rstrip("/").split("/")[-1] for m in meta]
```

---

## API key generation (one-time, if key is lost)

Works on **both** the MAS trial and ACN IAX — neither exposes the "Manage API keys" screen in the UI (trial restriction / no Integration menu in the demo).

1. Log into the Maximo UI in a browser and complete SSO:
   - Trial: `https://main.manage.sandbox-trial.suite.maximo.com/maximo/`
   - ACN IAX: accept SSL warning on `https://api.sbx.apps.ocp.acn-ix.iam.accenture.com` first, then log into `https://acnsbx.manage.sbx.apps.ocp.acn-ix.iam.accenture.com/maximo/`
2. F12 → Console → paste:
```javascript
fetch('/maximo/oslc/apitoken/create', {
  method: 'POST',
  headers: {'Content-Type': 'application/json', 'Accept': 'application/json'},
  body: JSON.stringify({"expiration": -1})
}).then(r => r.json()).then(d => console.log('API KEY:', JSON.stringify(d)))
```
3. Copy the returned key → paste into `.env` as `MAXIMO_MANAGE_APIKEY`.

---

## MVI API (Visual Inspection)

Auth: `X-Auth-Token: <MAXIMO_APIKEY1>` header (different from Manage).

```python
MVI_BASE = _env["MAXIMO_API_ENDPOINT1"].rstrip("/")
MVI_KEY  = _env["MAXIMO_APIKEY1"]

def mvi_get(path):
    r = _s.get(MVI_BASE + path,
               headers={"X-Auth-Token": MVI_KEY, "Accept": "application/json"},
               timeout=30)
    r.raise_for_status()
    return r.json()

mvi_get("/ping")      # {"healthy": true, "status": "Ready"}
mvi_get("/profiles")  # workspace=main, version 9.14.82
mvi_get("/datasets")  # []
mvi_get("/projects")  # []
```

---

## Error codes

| Code | Meaning | Fix |
|---|---|---|
| `BMXAA9301E` | User's security group lacks object-structure permission | Ask ACN admin to grant access |
| `BMXAA4216E` | Object structure not registered (module not installed) | Use alternative OS or different environment |
| `BMXAA7901E` | No valid API key | Check `MAXIMO_MANAGE_APIKEY` in `.env` |
| 302 to OIDC | Using `/oslc/` route — SAML intercepts before apikey is read | Switch to `/api/` route |

---

## MX AI Suite integration notes

- Use `mxapiwo` not `mxwo` for work order queries from runtime agents
- Use `mxapiasset` not `mxasset` for asset queries
- Never log or print API key values
- All agent calls must be GET (read-only) unless explicitly authorised to write
- Before any write: `dryRun=true` per CLAUDE.md rule
- The ACN IAX sandbox has a low concurrent-user limit — do not follow `/oslc/` redirects (they create session slots)
