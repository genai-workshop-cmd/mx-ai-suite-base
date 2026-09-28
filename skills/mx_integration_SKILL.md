# MX_Integration — Maximo Integration Framework (MIF) & OSLC REST Skill (MAS 8 / MAS 9)
*Version: 2.0 | Platform: MAS 8.x / MAS 9.x / Maximo 7.6 | Last updated: 2026-09-28*

---

## Purpose

Load before any integration design, Build Integration document, or interface mapping task.
Covers MIF architecture, Object Structures, Publish Channels, Enterprise Services, OSLC REST,
and IBM best practices. Supplements mx_core_SKILL.md — load both together.

---

## 1. MIF Architecture Overview

Maximo Integration Framework (MIF) enables bi-directional data exchange between Maximo and
external systems via XML, flat files, interface tables, Web Services, JMS queues, and REST.

### Integration Building Blocks
```
Object Structure
      ↓
Enterprise Service (inbound) ←── External System ──→ Publish Channel (outbound)
      ↓                                                       ↓
  Inbound Queue                                         Outbound Queue
      ↓                                                       ↓
  MBO / Maximo DB                                      End Point (HTTP / JMS / File)
```

| Component | Purpose |
|---|---|
| **Object Structure** | Defines the data shape — one or more MBOs hierarchically. Source for all integration |
| **Enterprise Service** | Inbound pipeline — receives data from external system into Maximo |
| **Publish Channel** | Outbound pipeline — sends data from Maximo to external system asynchronously |
| **External System** | Represents the external application — owns services and channels |
| **End Point** | Where outbound messages are delivered (HTTP, JMS, File, Email, etc.) |
| **Processing Rules** | Conditional logic applied during message processing |
| **Message Tracking** | Stores integration message payloads for audit and reprocessing |

---

## 2. Object Structures

`Integration → Object Structures`

### Key Concepts
- An Object Structure defines the message schema for one integration
- Hierarchical: one root object + child objects (e.g., WORKORDER + WOACTIVITY + WOMATL)
- Source for both inbound (Enterprise Service) and outbound (Publish Channel)
- OOTB Object Structures: MXWO, MXASSET, MXPO, MXPERSON, MXINVENTORY, MXLOCATION, etc.
- Custom Object Structures: prefix with client code (e.g., `PLUSDCU`, `CUSTMO`)

### Creating a Custom Object Structure
1. Integration → Object Structures → New
2. Name (e.g., `CUSTWOEXT`), Object Type: MXOBJECT
3. Source Objects tab: Add root object (e.g., WORKORDER), add child objects with relationship
4. Fields tab: select which attributes to include (default: all — trim for performance)
5. Save and test with a sample export

### Object Structure Best Practices (IBM)
- Only include fields the integration actually needs — fewer fields = faster processing
- Define a dedicated OS per integration — avoid reusing one OS for multiple systems
- Always set a primary key field (usually the OOTB key: WONUM, ASSETNUM, etc.)
- Non-persistent (virtual) attributes can be added but require custom processing
- Test with Message Tracking before connecting to external system

### Key OOTB Object Structures
| Object Structure | Root Object | Common Use |
|---|---|---|
| MXWO | WORKORDER | Work Order integration |
| MXASSET | ASSET | Asset master sync |
| MXPO | PO | PO to/from ERP |
| MXPERSON | PERSON | User/person directory sync |
| MXINVENTORY | INVENTORY | Inventory sync |
| MXLOCATION | LOCATIONS | Location master sync |
| MXSR | SR | Service Request integration |
| MXJOBPLAN | JOBPLAN | Job Plan sync |

---

## 3. Enterprise Services (Inbound)

### Processing Flow
```
External System → HTTP POST / JMS / File → Inbound Queue → Router → Enterprise Service → MBOs → DB
```

### Creating an Enterprise Service
1. Integration → Enterprise Services → New
2. Name, Object Structure, Use With: External System or Direct
3. Set Processing Class (default: `psdi.iface.mic.MaximoObjectStructureService`)
4. Activate the service on the External System

### Inbound Message Format
- Default: XML matching the Object Structure schema
- Maximo parses the XML and applies it to the MBOs
- Action attribute in XML: `<WORKORDER action="Add">` / `"Change"` / `"Delete"` / `"AddChange"` / `"Sync"`

### Inbound Processing Rules
- Filter records before they reach the MBO layer
- Example: only process records where `SITEID = 'BEDFORD'`
- Applied as conditions on the Enterprise Service

### Error Handling
- Failed messages stored in `MAXINTMSGTRK` with error detail
- Reprocess via: Integration → Message Tracking → select failed message → Re-submit
- Dead-letter: messages that fail after retries marked with `TRANSACTIONID` for manual review

---

## 4. Publish Channels (Outbound)

### Processing Flow
```
MBO Save/Status Change → Event Listener → Outbound Queue → Router → Publish Channel → End Point → External System
```

### Creating a Publish Channel
1. Integration → Publish Channels → New
2. Name, Object Structure, Publish JSON or XML
3. Set End Point (HTTP / JMS / File / Email)
4. Add Processing Rules (optional — filter which records to publish)
5. Enable the channel on the External System

### Trigger Types
| Trigger | Description |
|---|---|
| Event-driven (SAVE) | Fires when MBO is saved — most common |
| Event-driven (STATUS CHANGE) | Fires on specific status transition |
| Invocation Channel | Manually invoked (not automatic) |
| Cron-driven export | Scheduled batch export (use MAXEXPORTJOB cron) |

### Processing Rules (Outbound Filter)
```xml
<!-- Only publish APPROVED CU records -->
<condition field="STATUS" operator="=" value="APPROVED" />
```

### End Point Types
| Type | Protocol | Use |
|---|---|---|
| HTTP | REST / SOAP | API-based external systems |
| JMS | JMS Queue / Topic | Middleware (IBM MQ, ActiveMQ) |
| FILE | File system | File-based batch exchange |
| EMAIL | SMTP | Email notifications with data payload |
| WEBSERVICE | SOAP/WSDL | Legacy SOAP services |

### Outbound Best Practices (IBM)
- Use Processing Rules to filter at the MIF layer — don't rely on the external system to ignore records
- Set retry count and interval on the End Point (retry 3 times, 30s / 2min / 10min)
- Monitor outbound queue depth — large backlogs indicate endpoint availability issues
- Use Invocation Channel for synchronous request-reply patterns
- Always test End Point connectivity before go-live

---

## 5. OSLC REST API (MAS 8 / MAS 9 Primary Integration Pattern)

### Base URL
```
https://<host>/maximo/oslc/os/<ObjectStructure>
```

### Authentication
| Method | Header | When to use |
|---|---|---|
| API Key | `apikey: <key>` | MAS 8/9 preferred |
| MAXAUTH | `MAXAUTH: base64(user:pass)` | Maximo 7.6 (NO "Basic " prefix) |
| OAuth 2.0 | `Authorization: Bearer <token>` | MAS SSO environments |

### Key Operations
| Operation | HTTP Method | URL pattern |
|---|---|---|
| Query (list) | GET | `/oslc/os/MXWO?oslc.where=STATUS="WAPPR"` |
| Get by ID | GET | `/oslc/os/MXWO/12345` |
| Create | POST | `/oslc/os/MXWO` with JSON body |
| Update | PATCH | `/oslc/os/MXWO/12345` with JSON body |
| Delete | DELETE | `/oslc/os/MXWO/12345` |

### Query Parameters
| Parameter | Purpose | Example |
|---|---|---|
| `oslc.where` | Filter (SQL-like) | `STATUS="APPR" and SITEID="BEDFORD"` |
| `oslc.select` | Field projection | `WONUM,DESCRIPTION,STATUS` |
| `oslc.pageSize` | Page size (default 50, max ~1000) | `oslc.pageSize=200` |
| `oslc.orderBy` | Sort | `+WONUM` (asc) / `-CHANGEDATE` (desc) |
| `oslc.searchTerms` | Full-text search | `"pump failure"` |

### Pagination Pattern
```python
import requests, json

url = "https://host/maximo/oslc/os/MXWO"
params = {"oslc.where": "STATUS=\"WAPPR\"", "oslc.pageSize": 100}
headers = {"apikey": "YOUR_KEY", "Accept": "application/json"}

all_records = []
while url:
    resp = requests.get(url, params=params, headers=headers, verify=False)
    data = resp.json()
    all_records.extend(data.get("member", []))
    next_page = data.get("responseInfo", {}).get("nextPage", {})
    url = next_page.get("href") if next_page else None
    params = {}  # params are in the next page href
```

### OSLC Best Practices (IBM)
- Always use `oslc.select` to limit returned fields — reduces payload size significantly
- Always paginate — never assume all records fit in one page
- Use `oslc.where` with indexed fields for performance
- `MAXAUTH` header: do NOT add "Basic " prefix — it will fail
- For bulk creates/updates, use Interface Tables or MIF Enterprise Services — OSLC is not designed for bulk
- Rate limiting: MAS applies throttling — implement retry with exponential backoff

---

## 6. Integration Message Tracking

`Integration → Message Tracking`

### Key Fields in MAXINTMSGTRK
| Field | Description |
|---|---|
| TRANSACTIONID | Unique message identifier |
| IFACENAME | Enterprise Service or Publish Channel name |
| EXTSYSNAME | External System |
| DIRECTION | INBOUND / OUTBOUND |
| STATUS | QUEUED / PROCESSING / COMPLETED / ERROR |
| ERRORDESC | Error description on failure |
| IFACETBNAME | Interface table name (if used) |

### Reprocessing Failed Messages
1. Message Tracking → search for failed messages (STATUS = ERROR)
2. Select message → View payload to diagnose
3. If fixable without data change: Re-submit
4. If data needs correction: fix in source system, resubmit corrected payload
5. For systematic failures: check End Point connectivity, MBO validation rules

---

## 7. Integration Design Document (Build Integration) Structure

Every integration design must include these sections:

| Section | Content |
|---|---|
| 1. Overview | Interface name, direction, trigger, frequency, systems involved |
| 2. Object Structure | Fields included, hierarchy, custom fields added |
| 3. Field Mapping Table | Source field → Target field, transformation rule, mandatory flag |
| 4. Processing Rules | Filter conditions applied at MIF layer |
| 5. End Point / Channel Config | Protocol, URL/queue, auth, retry policy |
| 6. Error Handling | Error codes, retry count, dead-letter action, alert recipients |
| 7. Test Scenarios | Happy path, boundary, error scenarios |
| 8. Assumptions | Unresolved items flagged as assumptions |

### Field Mapping Table Standard Columns
| Source System | Source Field | Transformation | Target Object | Target Field | Mandatory | Notes |
|---|---|---|---|---|---|---|
| SAP | BUKRS | Direct | WORKORDER | ORGID | Yes | Company code → Org ID |

---

## 8. Common Integration Patterns

### Pattern 1: Event-Driven Outbound (Status Change)
Use case: Notify external system when Maximo record reaches a specific status.
```
WO STATUS → COMP
  → MXWO Publish Channel (filter: STATUS = "COMP")
  → HTTP End Point → External System
```

### Pattern 2: Scheduled Batch Inbound
Use case: Nightly load of master data from external system.
```
External System → Generate XML/JSON file at 02:00
  → MAILROUTER or FILE End Point picks up
  → Enterprise Service processes
  → Maximo MBOs updated
```

### Pattern 3: Request-Reply (Synchronous)
Use case: Real-time lookup from Maximo UI to external system.
```
User action in Maximo UI
  → Automation Script (Action launch point)
    → Python adapter calls external REST API
      → Response returned to script
        → Script updates Maximo field
```

### Pattern 4: Interface Tables (Bulk Load)
Use case: Large data migration or initial load.
```
External system populates MAXIFACEIN table
  → MXIFACEIN cron task processes rows
  → Enterprise Service applied per row
  → MBOs created/updated in batch
```

---

*MX AI Suite | Integration Skill v2.0 | IBM Maximo MAS 8/9 | Last updated: 2026-09-28*
