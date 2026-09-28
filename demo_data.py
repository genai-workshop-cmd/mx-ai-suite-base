"""The two reference use cases from blueprint section 11.

`python run.py demo` runs both end to end so a fresh install can be proven
working in one command.
"""
from __future__ import annotations

USE_CASES: dict[str, dict[str, str]] = {
    "uc1": {
        "title": "Add CU Comment field and propagate to Work Order",
        "text": """# Use Case 1 - Add CU Comment field

## Background
Designers capture free-text notes against a Compatible Unit during estimating.
Today those notes are lost when a Work Order is generated from the CU record,
so crews receive no context.

## Requirements

- The system shall add a new CUCOMMENT attribute to the CUJP object through
  Database Configuration, type ALN, length 100, not mandatory.
- The CU Comment field must be visible on the CU Header application in
  Application Designer, on the main tab, labelled "CU Comment".
- On Work Order generation from a CU record, an automation script shall copy
  CUJP.CUCOMMENT into WORKORDER.DESCRIPTION.
- Empty CUCOMMENT must not overwrite an existing Work Order description.
- The field shall be granted to the security groups that already have access to
  the CU Header application.

## Acceptance criteria

- The CU Comment field is visible and editable on CU Header.
- The value persists after save and reopen.
- A Work Order generated from a CU carries the CU Comment in its Description.
- Generating a Work Order from a CU with an empty comment leaves any existing
  Work Order description untouched.
""",
    },
    "uc2": {
        "title": "CU outbound interface to AUD external system",
        "text": """# Use Case 2 - CU outbound to AUD

## Background
The AUD asset utilisation system needs to be notified in real time whenever a
CU Estimate is accepted, so that downstream planning can begin.

## Requirements

- The system shall trigger a CU outbound message to the AUD external system
  when the CUE Status changes to ACCEPTED.
- A Publish Channel named CUACCEPTED_PC shall be defined against the CUJP
  object structure for the outbound interface.
- An External System AUD_EXTSYS shall be configured with an HTTP endpoint and
  credentials held in the End Point definition.
- The outbound message shall carry the CU record key fields: CUJPNUM, STATUS,
  CUCOMMENT and SITEID.
- No message shall be generated for any status change other than ACCEPTED.
- If the endpoint is unreachable the message must be retained in the error
  queue for reprocessing, with no data loss.

## Acceptance criteria

- Changing a CU Estimate status to ACCEPTED produces exactly one outbound
  message.
- Every field in the message matches the agreed field mapping.
- No message is produced for any other status transition.
- An unreachable endpoint results in a reprocessable error-queue entry.
""",
    },
}
