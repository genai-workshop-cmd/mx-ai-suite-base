# IBM Maximo Knowledge Centre — Reference Documentation
*Last synced: 2026-09-30T12:14:01+00:00*
*Source: IBM public documentation (ibm.com/docs) and IBM-verified embedded content.*


## Automation scripting overview
Source: IBM Maximo documentation (embedded IBM-verified content)

IBM Maximo automation scripts are Jython (Python 2.7) scripts that run inside the Maximo JVM.
They execute at defined launch points without requiring a server restart or redeployment.
Scripts can access Maximo Business Objects (MBOs) and the full MBO API through implicit variables.
Key uses: field validation, field population/copy, business rule enforcement, status change triggers,
custom action execution, and integration pre/post-processing.
Automation scripts replace Java customisations for most use cases and are preferred in MAS 8/9.
Scripts are managed in the Automation Scripts application (AUTOSCRIPT).


## Launch points for automation scripts
Source: IBM Maximo documentation (embedded IBM-verified content)

Launch point types in IBM Maximo:
1. Object launch point — fires on MBO lifecycle events (init, add, save, delete, beforeSave, afterSave, beforeDelete, afterDelete, beforeValidate).
   Variables: mbo (the MBO), mboname, launchpoint.
2. Attribute launch point — fires when a specific attribute value changes (validate or retrieve event).
   Variables: mbo, mboname, attribute, launchpoint.
   Use for field-level validation and derived field calculation.
3. Action launch point — called by a workflow action node or toolbar button (Signature Option).
   Variable: mbo (the record the action is invoked on).
4. Custom condition launch point — evaluates a Boolean condition for workflow/escalation routing.
   Must set implicit variable 'result' to True or False.
5. Cron Task launch point — fires on a scheduled cron task execution cycle.
   No mbo variable; use MboSet queries to process records in bulk.
Active launch point = script is bound and will execute. Inactive = ignored at runtime.
Multiple scripts can share the same launch point; execution order is undefined — avoid dependencies.


## Automation script variables
Source: IBM Maximo documentation (embedded IBM-verified content)

Implicit variables available in all Maximo automation scripts (Jython 2.7):
- mbo: the primary MBO (MboRemote) for the current record. Use mbo.getString("ATTR"), mbo.setValue("ATTR", value), mbo.getInt("ATTR"), mbo.getDouble("ATTR"), mbo.getBoolean("ATTR").
- mboname: String name of the MBO object (e.g. "WORKORDER").
- launchpoint: String name of the active launch point.
- app: String name of the application context (may be null for background scripts).
- service: MXServer service reference — use service.getMboSet("OBJECT", userInfo) to open independent MboSet queries.
- user: String user name of the logged-in user.
- errorgroup / errorkey: Set these to throw a Maximo application exception with a message from the message catalogue.
- For Custom Condition scripts: set implicit variable 'result' (Boolean) — True = condition met.
Common patterns:
  val = mbo.getString("DESCRIPTION")          # read a string attribute
  mbo.setValue("SITEID", "BEDFORD", 11L)      # set with no-access flag (11L = MboConstants.NOACCESSCHECK)
  mbo.setValueNull("ATTRIBUTE")               # clear a field
  ms = mbo.getMboSet("WOACTIVITY")            # child MBO set — always close in finally block


## Work order statuses
Source: IBM Maximo documentation (embedded IBM-verified content)

IBM Maximo Work Order status lifecycle (WORKORDER.STATUS synonym domain WOSTATUS):
WAPPR  — Waiting for Approval. Initial status when WO is created manually or from PM.
APPR   — Approved. Work may begin; labour, materials, tools can be reported.
INPRG  — In Progress. Work has started; first labour transaction moves to this status automatically if configured.
COMP   — Completed. Work is done; completion date/time stamped. Can still report actuals.
CLOSE  — Closed. Costs finalised; WO is read-only for most fields.
CAN    — Cancelled. WO will not be executed; removed from scheduling.
HISTEDIT — Historical Edit. Allows editing closed WO records where permitted by security.
Status transitions: WAPPR→APPR→INPRG→COMP→CLOSE. CAN can be reached from WAPPR or APPR only.
PM-generated WOs are created in WAPPR status by default (configurable).
Child work orders (WOACTIVITY) follow the same status domain.
ORIGRECORDCLASS and ORIGRECORDID fields on WORKORDER identify the PM or Master WO that originated the WO.


## Preventive maintenance overview
Source: IBM Maximo documentation (embedded IBM-verified content)

IBM Maximo Preventive Maintenance (PM) records drive time-based and meter-based WO generation.
Key PM fields: PMNUM, DESCRIPTION, SITEID, ORGID, ASSETNUM, LOCATION, JPNUM (Job Plan), WOPRIORITY,
SCHEDFREQ (schedule frequency), FREQUNIT (frequency unit: DAYS/MONTHS/YEARS), LEADTIME,
INSPECTOR (inspector name for inspection WOs), INSPECTIONFORMID (Inspection Form to attach to generated WOs).
PM → WO generation: The PMWOEGENCRON cron task runs on a schedule and creates WORKORDER records from active PM records
that are due. The generated WO inherits ASSETNUM, LOCATION, SITEID, JPNUM, DESCRIPTION, WOPRIORITY from the PM.
WORKORDER.ORIGRECORDCLASS is set to "PM"; WORKORDER.ORIGRECORDID is set to the PMNUM.
Multi-asset PMs: If the PM has child records in MULTIASSETLOCCI, one WO is generated per asset/location row.
The generated WOs are linked back to the PM via ORIGRECORDCLASS/ORIGRECORDID.


## Generating work orders from PM records
Source: IBM Maximo documentation (embedded IBM-verified content)

PMWOEGENCRON cron task generates WOs from PM records in IBM Maximo.
Parameters: SITEID (filter by site), ORGID (filter by org), GENLEADTIME (generate WOs due within N days).
Generation logic: For each active PM where next due date <= today + GENLEADTIME, one WO is created (or one per MULTIASSETLOCCI row).
WORKORDER fields populated from PM:
  DESCRIPTION ← PM.DESCRIPTION
  ASSETNUM    ← PM.ASSETNUM (or MULTIASSETLOCCI.ASSETNUM for multi-asset)
  LOCATION    ← PM.LOCATION (or MULTIASSETLOCCI.LOCATION)
  SITEID      ← PM.SITEID
  JPNUM       ← PM.JPNUM
  WOPRIORITY  ← PM.WOPRIORITY
  ORIGRECORDCLASS ← "PM"
  ORIGRECORDID    ← PM.PMNUM
  INSPECTIONFORMID ← PM.INSPECTIONFORMID (MAS 8.7+)
After generation, PM.LASTGENDATE is updated and the next due date is recalculated.
To copy PM custom attributes to the generated WO, use a Save-event Object launch point on WORKORDER
that checks mbo.getString("ORIGRECORDCLASS") == "PM" and retrieves the PM via mbo.getMboSet("PM").


## Job Plans
Source: IBM Maximo documentation (embedded IBM-verified content)

IBM Maximo Job Plan (JOBPLAN object) is a reusable template for work tasks, labour, materials, services and tools.
Key fields: JPNUM, DESCRIPTION, JPDURATION (estimated hours), SITEID, ORGID.
Child objects: JOBTASK (tasks), JOBLABOR (labour requirements), JOBMATERIAL (material requirements),
JOBSERVICE (service requirements), JOBTOOL (tool requirements).
When a WO is created from a Job Plan (via PM or directly), the job plan tasks become WOACTIVITY records,
and labour/material/tool requirements become WPLABOR/WPMATERIAL/WPTOOL planning records.
Job Plans are assigned to PM records via PM.JPNUM or directly on a WO via WORKORDER.JPNUM.
Revision: Job Plans support version control — new revision does not affect existing WOs.


## Assets overview
Source: IBM Maximo documentation (embedded IBM-verified content)

IBM Maximo Asset Management: ASSET object represents a physical asset (equipment, infrastructure).
Key fields: ASSETNUM, DESCRIPTION, SITEID, ORGID, LOCATION, STATUS (OPERATING/DECOMMISSIONED/NOT READY/etc.),
ASSETTYPE, CLASSSTRUCTUREID (Classification), SERIALNUM, MANUFACTURER, MODELNUM, VENDOR,
PURCHASEPRICE, REPLACECOST, WARRANTYEXPDATE, ISRUNNING (YORN), MOVED (YORN).
Asset hierarchy: Assets can be parent/child via PARENT field (ASSET.PARENT = parent ASSETNUM).
Asset ↔ Location: ASSET.LOCATION links the asset to its current installed location (LOCATIONS object).
Asset ↔ PM: PM records reference ASSET.ASSETNUM to drive scheduled maintenance.
Asset ↔ WO: WORKORDER.ASSETNUM links the WO to the asset being maintained.
Meter readings: ASSETMETER child object tracks meter values; drives meter-based PM scheduling.


## Inspection Forms overview
Source: IBM Maximo documentation (embedded IBM-verified content)

IBM Maximo Inspection Forms (MAS 8.7+) are digital checklists attached to Work Orders.
Inspection Forms replace paper-based inspection sheets; field technicians complete them on mobile devices.
Architecture in MAS 8/9: Inspection Forms are managed in the Inspections application (separate from App Designer).
The form definition is stored in the INSPECTIONFORM object; answers in INSPECTIONRESULT.
Key objects: INSPECTIONFORM (form template), INSPECTIONFORMFIELD (questions/fields on the form),
INSPECTIONRESULT (completed responses per WO), INSPECTIONRESULTFIELD (individual answer values).
Attaching to a WO: Set WORKORDER.INSPECTIONFORMID to link an inspection form to a work order.
PM integration: PM.INSPECTIONFORMID auto-populates WORKORDER.INSPECTIONFORMID when a WO is generated.
To copy INSPECTIONFORMID from PM to WO via automation script, use a Save-event Object launch point on WORKORDER,
check ORIGRECORDCLASS == "PM", open the PM MBO, read PM.INSPECTIONFORMID, and set it on the WO if the WO field is empty.


## Creating inspection forms
Source: IBM Maximo documentation (embedded IBM-verified content)

Creating an Inspection Form in IBM MAS 8/9:
1. Navigate to Inspections application → Inspection Forms tab.
2. Click New Inspection Form. Enter a Name, Description, and set Status to Active.
3. Add fields: each field has a type (Text, Number, Date/Time, Single Choice, Multiple Choice, Attachment, Meter Reading, Signature).
4. For Single/Multiple Choice fields, define the answer options in the Choices section.
5. Add conditional logic: show/hide a field based on another field's answer using Conditions.
6. Save and set form to Active status to make it available for use.
7. Assign to a PM: open the PM record, set Inspection Form field to the form INSPECTIONFORMID.
8. Generated WOs will inherit the inspection form; technicians complete it via the Maximo Mobile app.
Note: Inspection Forms are React-based and are NOT editable via App Designer. The form UI is rendered by the Inspections module.


## Application Designer overview
Source: IBM Maximo documentation (embedded IBM-verified content)

IBM Maximo Application Designer (App Designer) allows customisation of the Maximo web UI without code.
Access: Go To → System Configuration → Platform Configuration → Application Designer (APPDSGN object).
Key operations:
- Clone an existing application to create a custom version (preserves all original controls).
- Add/move/remove controls: Text box, Lookup, Table, Section, Tab, Button (Signature Option button).
- Set field properties: Read-only, Required (Mandatory), Hidden, Length, Label.
- Conditional expressions: Control visibility/required state based on field values (no-code conditions using the expression builder).
- Add a new Tab: drag a Tab control from the palette, assign a Tab Label.
- Add a new Section: drag a Section control inside a Tab.
- Export/Import: XML export of app definition for migration between environments.
App Designer changes are stored in MAXPRESENTATIONSX and take effect immediately (no restart needed).
Do NOT use App Designer for Inspection Form fields — those are managed in the Inspections application.


## Database Configuration
Source: IBM Maximo documentation (embedded IBM-verified content)

IBM Maximo Database Configuration (DB Config) allows adding custom attributes and objects without SQL.
Access: Go To → System Configuration → Platform Configuration → Database Configuration (MAXATTRIBUTE, MAXOBJECT).
Steps to add a custom attribute to an existing object:
1. Open Database Configuration. Find the object (e.g. WORKORDER).
2. Select the Attributes tab. Click New Row.
3. Enter Attribute name (e.g. PLUSDCUSTOMFIELD), Type (ALN/INTEGER/DECIMAL/YORN/DATE/DATETIME/UPPER/LOWER),
   Length (for ALN/UPPER/LOWER), Persistent (Yes = stored in DB), Required, Search Type (WILDCARD/EXACT/NONE).
4. Save. Click "Manage Admin Mode" → "Turn Admin Mode On".
5. Click "Apply Configuration Changes" to run the DDL and add the column to the database table.
6. Turn Admin Mode Off.
Attribute naming: Custom attributes must start with the client prefix (e.g. PLUSD, ZZ) to avoid conflicts with IBM upgrades.
Domain: Assign an ALNDOMAIN/NUMERICDOMAIN/DATEONLY to restrict valid values via a lookup.
After adding an attribute, add it to the application UI via App Designer.


## Domains
Source: IBM Maximo documentation (embedded IBM-verified content)

IBM Maximo Domains provide lists of valid values for attribute lookups.
Access: Go To → System Configuration → Platform Configuration → Domains (ALNDOMAIN, NUMERICDOMAIN etc.).
Domain types:
- ALN domain: list of alphanumeric values with descriptions and defaults. Used for text lookup fields.
- Numeric domain: list of numeric ranges or exact values.
- Date Only domain: restricts to specific dates.
- Synonym domain (internal): used for Maximo status synonyms (e.g. WOSTATUS). Add customer synonyms here.
  Important: Synonym domain values must map to an existing internal value (e.g. APPR maps to APPR).
- Table domain: dynamic lookup from any Maximo table with a filter condition.
- Crossover domain: copies field values from the lookup result record back to the source record.
Attaching a domain to an attribute: In Database Configuration, set the Domain field on the attribute row.
After adding domain values, they are immediately available in the UI dropdown — no restart needed.


## Cron Tasks
Source: IBM Maximo documentation (embedded IBM-verified content)

IBM Maximo Cron Tasks are scheduled background jobs that run at configurable intervals.
Access: Go To → System Configuration → Platform Configuration → Cron Task Setup (CRONTASKDEF, CRONTASKINST).
Key built-in cron tasks:
- PMWOEGENCRON: generates Work Orders from due PM records. Configure: SITEID, ORGID, GENLEADTIME.
- ESCALATION: processes escalation definitions and sends notifications.
- KPICRON: recalculates KPI values.
- SYNCSERVERTIME: syncs server time across cluster nodes.
Custom cron task: create a Java class implementing MXCronTaskBean, register via DB Config, then set up in Cron Task Setup.
Cron task instance settings: Schedule (cron expression or interval in minutes), Active (Yes/No), Run As User.
Cron expression format: minute hour day-of-month month day-of-week (standard Unix cron).
In MAS 9: Cron tasks are managed as Kubernetes CronJobs — the schedule runs outside the JVM.


## Escalations
Source: IBM Maximo documentation (embedded IBM-verified content)

IBM Maximo Escalations trigger notifications and/or actions when records meet a condition after a time threshold.
Access: Go To → System Configuration → Platform Configuration → Escalations (ESCALATION object).
An Escalation has:
- Escalation Condition: SQL WHERE clause on an object (e.g. WORKORDER) that identifies records to escalate.
- Time Limit: how long after the condition is met before escalation fires (e.g. 2 HOURS, 1 DAY).
- Notification: send an email to a person, person group, or role.
- Action: run a Maximo Action (which can trigger an automation script).
Escalations are processed by the ESCALATION cron task.
An escalation can check multiple elapsed-time thresholds (e.g. warn after 4 hours, escalate after 8 hours).
Common use: Notify supervisor when WO stays in WAPPR status for more than 24 hours.
Escalation SQL example: STATUS = 'WAPPR' AND REPORTDATE < :now - 1


## Classifications
Source: IBM Maximo documentation (embedded IBM-verified content)

IBM Maximo Classifications provide a hierarchical taxonomy for categorising Assets, Locations, Items, and Work Orders.
Access: Go To → Administration → Classifications (CLASSSTRUCTURE object).
A Classification tree node (CLASSSTRUCTURE) can have:
- Attributes (CLASSSPEC): custom attributes specific to this classification. Each CLASSSPEC entry adds a field
  to the classified record's Specifications tab (stored in ASSETSPEC, LOCSPEC, ITEMSPEC, WORKORDERSPEC).
- Child nodes: sub-classifications forming a tree.
Assigning a classification: Set CLASSSTRUCTUREID on the target record (Asset, WO, etc.).
The Specifications tab on the record then shows all CLASSSPEC attributes for that classification node and its ancestors.
Classification attributes are NOT stored in MAXATTRIBUTE — they are dynamic via CLASSSPEC/ASSETSPEC.
Use classifications when the set of attributes varies by asset type rather than being universal.


## Security Groups
Source: IBM Maximo documentation (embedded IBM-verified content)

IBM Maximo Security Groups control what users can see and do.
Access: Go To → Security → Security Groups (MAXGROUP object).
A Security Group has:
- Applications tab: grants access to applications. For each app, set:
  - Read, Insert, Save, Delete permissions.
  - Signature Options: grant/deny specific toolbar/menu actions for that app.
- Sites tab: restrict which sites the group can access.
- Storerooms tab: limit storeroom access for inventory users.
- Data Restrictions tab: row-level security — filter visible records by a SQL condition.
- GL Components tab: restrict which GL accounts can be used.
Users can belong to multiple groups; permissions are the union of all groups.
IMPORTANT: Never add custom Signature Options to existing IBM base groups — clone the group first.
After changing security, the user must log out and back in (or MAXSESSION cleared) for changes to take effect.
In MAS 9: Security is managed in IBM Identity and Access Management (IAM) for user accounts,
but application-level permissions (Signature Options, Data Restrictions) remain in Maximo Security Groups.


## Signature Options
Source: IBM Maximo documentation (embedded IBM-verified content)

IBM Maximo Signature Options are toolbar buttons / menu items in application toolbars.
They are the mechanism for adding custom actions to application toolbars (Common Actions menu).
Access: Go To → System Configuration → Platform Configuration → Application Designer → select app → Signature Options tab.
OR: Go To → Security → Security Groups → select group → Applications tab → select app → Signature Options sub-tab.
Creating a custom Signature Option:
1. In Application Designer, open the target application.
2. Go to the Signature Options tab. Click Add Signature Option.
3. Enter: Option name (internal key, e.g. SELECTDESIGNER), Description (displayed in menu), Visible (Yes).
4. Set a Conditional Expression to control when the button is visible/enabled (optional).
   Example condition: STATUS = 'APPR' AND CLASS = 'CHANGE'
5. Save the application definition.
6. Grant the option to a Security Group: Security Groups → Applications tab → Signature Options sub-tab → check the option.
7. Optionally link the option to an Action launch-point automation script for the logic.
Signature Options appear in the "Common Actions" toolbar in the application.


## Integration Framework overview
Source: IBM Maximo documentation (embedded IBM-verified content)

IBM Maximo Integration Framework (MIF) enables data exchange between Maximo and external systems.
Core components:
- Object Structures: define which Maximo objects and attributes are exposed for integration.
- Enterprise Services (inbound): receive data from external systems into Maximo.
- Publish Channels (outbound): send data from Maximo to external systems when records change.
- External Systems: represent the external system; defines the connection endpoint (JMS queue, HTTP endpoint).
- End Points: the technical connection definition (URL, credentials, protocol: JMS, HTTP, FILE, etc.).
- Processing Rules: transform or filter messages.
Message formats supported: XML, JSON (MAS 8+).
Integration flow (outbound): Maximo record saved → Publish Channel fires → message formatted as XML/JSON → sent to End Point.
Integration flow (inbound): Message received at Enterprise Service → transformed → Maximo records created/updated.
In MAS 9: Integration uses Kafka topics or HTTPS endpoints; JMS is being deprecated.


## Object Structures
Source: IBM Maximo documentation (embedded IBM-verified content)

IBM Maximo Object Structures define the data structure exposed for integration.
Access: Go To → Integration → Object Structures (MAXOSDEF object).
An Object Structure has:
- A root (primary) object (e.g. WORKORDER).
- Child objects related to the root (e.g. WOACTIVITY, WPLABOR, WPMATERIAL) — included by relationship name.
- Excluded fields: attributes excluded from the integration message.
- Auto-linking: automatically link child records to parent by key fields.
Object Structures are referenced by Enterprise Services (inbound) and Publish Channels (outbound).
Creating a custom OS: In production avoid modifying IBM base OSes — create a custom OS based on the base OS.
Key base OSes: MXWO (Work Orders), MXASSET (Assets), MXITEM (Items), MXPO (Purchase Orders).
Persistent queries can be added to an OS to filter which records are published.


## Publish Channels
Source: IBM Maximo documentation (embedded IBM-verified content)

IBM Maximo Publish Channels define outbound integration — sending data from Maximo to an external system.
Access: Go To → Integration → Publish Channels (MAXIFACECHAN object).
A Publish Channel:
- References an Object Structure (the data shape to export).
- Is assigned to an External System (the destination).
- Fires on: object events (add/update/delete on the root MBO), or a scheduled query (CRON mode).
- Can have a Processing Class (Java) for custom transformation.
Event-based firing: When the root MBO (e.g. WORKORDER) is saved and the channel is active,
  the channel creates a message and delivers it to the External System's End Point.
Enabling: The Publish Channel must be Active and associated with an Active External System and End Point.
In MAS 9: Publish Channels can output to Kafka topics in addition to HTTP/JMS endpoints.


## Enterprise Services
Source: IBM Maximo documentation (embedded IBM-verified content)

IBM Maximo Enterprise Services define inbound integration — receiving data from an external system into Maximo.
Access: Go To → Integration → Enterprise Services (MAXIFACEOUT object).
An Enterprise Service:
- References an Object Structure (the expected inbound data shape).
- Is assigned to an External System (the sender).
- Has an Operation (Create, CreateUpdate, Sync, Delete).
- Can have a Processing Class for custom pre-processing.
Receiving a message: The external system posts XML/JSON to Maximo's integration endpoint.
  Maximo routes the message to the correct Enterprise Service by External System + message type.
  The service creates, updates, or deletes Maximo records accordingly.
End-to-end test: Use Maximo's Message Reprocessing application to replay failed messages.
In MAS 9: Enterprise Services accept JSON payloads via REST (HTTPS POST to /maximo/oslc/...)


## Workflow Designer
Source: IBM Maximo documentation (embedded IBM-verified content)

IBM Maximo Workflow Designer defines approval and routing processes for Maximo records.
Access: Go To → System Configuration → Platform Configuration → Workflow Designer (WFPROCESS object).
A Workflow Process has nodes connected by edges (routes):
- Start node: entry point; defines the object (e.g. WORKORDER).
- Task node: assigns the record to a person/group for action. Sets a due date and instructions.
- Condition node: evaluates a Custom Condition script or expression to choose the next route.
- Action node: runs a Maximo Action (e.g. change status, send notification, run autoscript).
- Wait node: pauses until an event occurs (e.g. status change, timer).
- Stop node: ends the workflow and optionally sets a final status.
Assignment: A Task node assigns to a Person, Person Group, or Role (a script that resolves to a person).
Escalation: If the assignee does not act within a time limit, the task can be escalated.
Activating a workflow: Set the process Active flag to Yes. Workflow must be active to be triggered.
Triggering: Workflow is initiated by a Maximo Action (STARTWF) or automatically on status change (via escalation or action launch point).


## BIRT Reporting overview
Source: IBM Maximo documentation (embedded IBM-verified content)

IBM Maximo uses BIRT (Business Intelligence and Reporting Tools) for embedded report generation.
Reports are designed in the BIRT Report Designer (Eclipse plugin) and deployed to Maximo.
Access reports: Go To → Reports → Run Reports (REPORTLIST).
Report structure: A BIRT report has a data source (JDBC connection to Maximo DB),
data sets (SQL queries), and layout elements (tables, charts, text, images).
Parameter passing: Reports accept parameters from Maximo (e.g. current record's WONUM, SITEID).
  Parameters are declared in the BIRT design file and mapped to the Maximo Report record.
Deploying a report:
1. Design in Eclipse BIRT Designer.
2. Save the .rptdesign file.
3. In Maximo: Administration → Report Administration → Add a new Report record.
   Set Report File = .rptdesign filename, Application, Description, parameters.
4. Upload the .rptdesign via the Report Administration upload function.
5. Assign the report to a Security Group via the report's Security tab.
BIRT reports query the live Maximo database — data is always current.


## Report Administration
Source: IBM Maximo documentation (embedded IBM-verified content)

IBM Maximo Report Administration manages deployed BIRT reports.
Access: Go To → Administration → Report Administration (REPORTLIST object).
Key fields on a Report record:
- Report File: the .rptdesign filename (must match the deployed file exactly).
- Application: which Maximo application owns this report (controls where it appears).
- Description: user-visible report name.
- Display in Application: if Yes, report appears in the application's Reports menu.
- Direct Print: allows one-click printing without parameter dialog.
Report Parameters: each declared parameter in the .rptdesign is listed with a mapping to a Maximo attribute or literal value.
Scheduling: Reports can be scheduled to run automatically (via a cron-based mechanism) and emailed.
Security: Assign groups access via the Security tab — only users in those groups see the report.
Maximo Report Queue: Report jobs run asynchronously in the report queue (REPORTJOB).
  Users see status in Reports → View Reports.
Upgrading reports: Replace the .rptdesign file, then refresh the report definition in Report Administration.


## Locations overview
Source: IBM Maximo documentation (embedded IBM-verified content)

IBM Maximo Locations represent physical places where assets are installed or work is performed.
Key location attributes: LOCATION (unique ID), SITEID, ORGID, DESCRIPTION, TYPE, STATUS, PARENT.
Location types: OPERATING (physical place), COURIER (transit), LABOR (person), REPAIR (shop).
Location hierarchy: parent-child relationships model buildings, floors, rooms, equipment positions.
CHILDREN: a location can have many children; PARENT is a single reference upward.
LINKEDASSET: the asset currently installed at an operating location (ASSET.LOCATION).
STATUS values: ACTIVE (in use), DECOMMISSIONED, OPERATING.
Location system: a named grouping of locations used for route planning.
Asset install/deinstall: moving an asset to a location updates ASSET.LOCATION and creates an asset move history record.
Used in WO: WORKORDER.LOCATION references where the work is performed; WORKORDER.ASSETNUM is the asset at that location.
GL account on location: GLACCOUNT field provides default charge account for WOs raised at the location.


## Asset hierarchy and relationships
Source: IBM Maximo documentation (embedded IBM-verified content)

IBM Maximo asset hierarchy allows assets to be grouped in parent-child relationships.
ASSET.PARENT: the parent asset's ASSETNUM. An asset can have one parent and many children.
ASSET.ASSETNUM: unique identifier within SITEID + ORGID.
Asset attributes: SERIALNUM, MANUFACTURER, MODEL, VENDOR, PURCHASEPRICE, REPLACECOST, INSTALLDATE.
Asset status: NOT READY, OPERATING, DECOMMISSIONED. Status changes create history records.
Locations: ASSET.LOCATION is where the asset is installed (LOCATIONS.LOCATION).
Asset up/down time: tracked via asset meter readings and downtime records (ASSETDOWNTIME).
Asset move: transferring an asset between sites or locations; creates ASSETMOVE history.
Spare parts: SPITEM records link spare parts (items) to assets via ASSETSPARE.
Asset attributes (classification): classified assets have CLASSSTRUCTUREID linking to the classification hierarchy.
MULTIASSETLOCCI: used when a Work Order or PM applies to multiple assets and locations simultaneously.
  - Rows on a WO allow reporting actuals against individual assets within one work order.
  - Copied from PM.MULTIASSETLOCCI to generated WO.MULTIASSETLOCCI when PM generates a WO.


## Meters and measurement points
Source: IBM Maximo documentation (embedded IBM-verified content)

IBM Maximo meters track asset performance via readings (e.g. odometer, runtime hours, temperature).
Meter types: CONTINUOUS (cumulative, e.g. kilometres), GAUGE (point-in-time, e.g. temperature), CHARACTERISTIC (text values).
ASSETMETER: links a meter to an asset (ASSETNUM, METERNAME, SITEID, LASTREADINGDATE, LASTREADING).
METERREADING: each reading record (ASSETNUM, METERNAME, READINGDATE, READING, INSPECTOR).
Measurement points: similar to meters but attached to locations (LOCMETER table).
PM meter-based frequency: a PM can trigger WO generation when a meter reaches a threshold (PMSEQUENCE, FREQUENCY fields).
  PM.METERBASEDFLAG = 1 enables meter-based PM.
  PM.METER references the meter; PM.FREQUENCY is the interval between WOs.
Rollover: CONTINUOUS meters roll over when they reach ROLLOVER value (e.g. odometer resets to 0).
Average calculation: Maximo calculates average daily meter usage for PM forecasting.


## Storerooms and inventory
Source: IBM Maximo documentation (embedded IBM-verified content)

IBM Maximo storerooms are physical storage locations managed as LOCATIONS with TYPE=STOREROOM.
INVENTORY: the central table; one row per item-storeroom combination (ITEMNUM + LOCATION + SITEID).
INVENTORY.CURBALTOTAL: current balance (quantity on hand) in the storeroom.
INVENTORY.ORDERUNIT / ISSUEUNIT: units used when ordering vs. issuing the item.
INVENTORY.MINLEVEL / REORDER: reorder point and reorder quantity for auto-replenishment.
INVRESERVE: reservations against inventory for planned WO materials (WPITEM records).
INVCOST: cost records per inventory transaction (issue, return, receipt, transfer).
Item issue to WO: MATUSETRANS records the actual material usage against a WO (MATUSETRANS.WONUM).
Storeroom transfer: INVTRANS records stock movements between storerooms.
Rotating items: items with ROTATING=1 are serialised — each INVVENDOR row is one physical unit.
Physical count: PHYSCNT application initiates a count; PHYSCOUNT/PHYSCNTLINE record the count sheets.


## Item Master
Source: IBM Maximo documentation (embedded IBM-verified content)

IBM Maximo Item Master (ITEM table) is the central catalogue of stocked and non-stocked items.
ITEM.ITEMNUM: unique identifier (ORGID-scoped).
ITEM.DESCRIPTION: free-text description (also searchable via ITEM.ITEMID classification).
ITEM.ITEMTYPE: ITEM (stocked), TOOL (tracked tools), MATERIAL (consumable), ASSET (rotating).
ITEM.ISSUEUNIT / ORDERUNIT: how the item is issued vs. ordered (can differ — e.g. order by box, issue by each).
ITEM.COMMODITYGROUP / COMMODITY: purchasing classification.
ITEM.ROTATING: if Yes, each physical unit is tracked as a rotating asset with its own ASSETNUM.
ITEMSPEC: classification-based attributes attached to an item (size, rating, etc.).
ITEMORGINFO: organisation-level defaults (tax codes, GL accounts) per ORGID.
ITEMSTRUCT: bill-of-materials hierarchy for kitted items.
INVVENDOR: vendor catalogue records linking items to suppliers (vendor, manufacturer part numbers, pricing).
Relationship to WO: WPMATERIAL (planned) and MATUSETRANS (actual) reference ITEMNUM.


## Purchase Orders
Source: IBM Maximo documentation (embedded IBM-verified content)

IBM Maximo Purchase Orders (PO) manage procurement from external vendors.
PO.PONUM: unique identifier (SITEID-scoped).
PO status workflow: WAPPR → APPR → CLOSE → CANC.
PO.VENDOR: references the COMPANIES table (vendor master).
POLINE: one line per ordered item or service. Key fields: ITEMNUM, QUANTITY, UNITCOST, LINECOST, RECEIVEDINSITE.
PO receipt: RECEIPTS application; MATRECTRANS records each receipt against a POLINE.
Partial receipt: POLINE.RECEIVEDINSITE tracks running total; line stays open until fully received.
Direct issue: items receipted directly to a WO (MATRECTRANS.WONUM set) bypass the storeroom.
PO revision: creating a new revision increments PO.REVISIONNUM; prior revision is archived.
Tax codes: TAXCODE1–4 on PO and POLINE control tax calculation per jurisdiction.
Currency: PO.CURRENCYCODE; EXCHANGERATE converts to base currency for accounting.
Three-way match: Invoice (INVOICE) is matched to PO and receipt before payment authorisation.


## Purchase Requisitions
Source: IBM Maximo documentation (embedded IBM-verified content)

IBM Maximo Purchase Requisitions (PR) are internal requests to purchase goods or services.
PR.PRNUM: unique identifier.
PR status: WAPPR → APPR → CLOSE → CANC.
PRLINE: one line per requested item. PRLINE.ITEMNUM, QUANTITY, UNITCOST.
PR to PO: approved PR lines are consolidated into a PO (PO.PRNUM reference).
Direct purchase: PR can be raised directly from a WO (WPMATERIAL.DIRECTREQ=1).
Auto-create PR: inventory reorder rules (INVENTORY.REORDER) trigger PR creation automatically.
PR approvals: controlled by workflow and signature options on the PR application.


## Service Requests overview
*Content unavailable: IBM docs SPA requires JavaScript rendering — using embedded fallback*
Source: https://www.ibm.com/docs/en/mas-cd/continuous-delivery?topic=requests-service

## Tickets and service requests
Source: IBM Maximo documentation (embedded IBM-verified content)

IBM Maximo Ticket application is the parent class for Service Requests, Incidents, and Problems.
Common ticket fields: TICKETID, CLASS, DESCRIPTION, REPORTEDBY, REPORTDATE, AFFECTEDPERSON, STATUS.
TICKET.CLASS values: SR (Service Request), INCIDENT, PROBLEM — all stored in the same TICKET table.
Ticket UI: the Service Desk application (SERVICEDESK) or dedicated SR/Incident/Problem applications.
Classifications: CLASSSTRUCTUREID routes tickets to the correct group and applies the right SLA.
Relationships: RELATEDRECORD links tickets to WOs, assets, locations, or other tickets.
Escalation: escalation points fire when tickets exceed SLA thresholds (ESCALATION table).
Global tickets: TICKET.GLOBALTICKETID links a local ticket to a global (cross-site) ticket.


## Migration Manager overview
Source: IBM Maximo documentation (embedded IBM-verified content)

IBM Maximo Migration Manager packages configuration changes as migration packages for controlled deployment.
A migration package contains: Object Structures configuration, Application Designer changes, Automation Scripts,
  Workflow definitions, Cron Tasks, Security settings, and any other exportable configuration.
Key concepts:
  - Source: the environment where the change was built (DEV or TEST).
  - Target: the environment receiving the change (TEST, UAT, or PROD).
  - Package: a named ZIP file containing all selected configuration objects.
Package creation: Migration Manager application → Create Package → select objects → Export.
Deployment: Import the package in the target environment → Validate → Deploy.
Snapshot: a point-in-time export of all configuration; used for baseline comparison.
Delta package: contains only the differences between two snapshots (reduces package size for incremental delivery).
Deployment log: records every object applied, with success/failure status per object.
Best practice: always validate the package in a TEST environment before deploying to PROD.
Migration Manager is the ONLY supported method for moving DB Config and App Designer changes between environments.
Do NOT use direct database scripts to replicate configuration — this bypasses Maximo's metadata layer.


## Admin Mode and database changes
Source: IBM Maximo documentation (embedded IBM-verified content)

IBM Maximo Admin Mode is a required step before applying Database Configuration changes.
What Admin Mode does: prevents all non-admin users from logging in; ensures no active transactions
  conflict with schema changes (attribute additions, type changes, index rebuilds).
How to enable Admin Mode:
  1. Go To → System Configuration → Platform Configuration → System Properties.
  2. Set mxe.adminmode = 1 (or use the Admin Mode button in Database Configuration).
  3. Wait for all active user sessions to end (or kill them from Active Users application).
Apply Configuration Changes:
  - After enabling Admin Mode, open Database Configuration.
  - Select Action → Apply Configuration Changes.
  - Maximo will update the database schema for all pending changes.
  - This may take 2–30 minutes depending on volume of changes.
  - Do NOT interrupt this process.
After applying:
  - Disable Admin Mode (set mxe.adminmode = 0).
  - Users can log back in.
  - Verify new attributes are visible in the target application.
IMPORTANT: Apply Configuration Changes must run before any Application Designer changes
  that reference new attributes, otherwise the App Designer save will fail.


## System Properties
Source: IBM Maximo documentation (embedded IBM-verified content)

IBM Maximo System Properties (MAXPROPVALUE table) store runtime configuration parameters.
Access: Go To → System Configuration → Platform Configuration → System Properties.
Key properties:
  mxe.adminmode: 0=normal, 1=admin mode (locks out non-admin users).
  mxe.db.schemaowner: database schema owner (used in DB Config).
  mxe.system.regtoken: registration token for MAS.
  mxe.email.*: SMTP server settings for email notifications.
  mxe.workflow.*: workflow engine settings.
  mxe.doclink.*: document attachment storage paths.
  mail.smtp.*: outbound email server configuration.
Live refresh: some properties take effect immediately (Live Refresh = Yes); others require server restart.
Property groups: properties are grouped by prefix (mxe, mail, cron, etc.) for easier navigation.
Security: only MAXADMIN role can view and edit system properties.
Encrypted properties: sensitive values (passwords) are stored encrypted; displayed as asterisks.


## Communication Templates
Source: IBM Maximo documentation (embedded IBM-verified content)

IBM Maximo Communication Templates define reusable email/notification message formats.
COMMTEMPLATE table: stores template definitions.
Key fields: TEMPLATEID, DESCRIPTION, SUBJECT, MESSAGE, SENDTO, SENDCC, SENDFRM.
Dynamic content: templates use :attribute_name: substitution tokens to insert record values.
  Example: 'Work Order :wonum: has been approved for site :siteid:' — tokens replaced at send time.
Sending communications: from a WO, SR, or PO record using the Communication Log (Actions → Send Message).
COMMLOG: records every communication sent, with timestamp, recipient, and message body.
Template usage:
  - Escalation points reference a COMMTEMPLATE to send automated notifications.
  - Workflow action nodes can send a template at defined process steps.
  - Users can manually select a template when composing a communication from a record.
Rich text: MESSAGE field supports HTML for formatted email bodies.
Attachments: DOCLINKS records can be attached to a communication at send time.


## Compatible Units overview
Source: IBM Maximo documentation (embedded IBM-verified content)

IBM Maximo Compatible Units (CU) are pre-defined work packages used in utilities (T&D) environments.
A Compatible Unit describes a standard unit of work: the labour, materials, tools, and steps needed
  to install, remove, or maintain a specific type of equipment or structure in the field.
Key objects:
  CUJP (Compatible Unit Job Plan): the master CU record — links a CU code to a Job Plan.
  CUELIBRARY: the CU library; a collection of CUs grouped by work category.
  PLUSDCU: extension table for additional CU attributes specific to the client configuration.
CU code: uniquely identifies a compatible unit (e.g. CU-1234 = "Install 100kVA transformer").
CU components: each CU specifies labour crafts + hours, materials + quantities, and tools.
CU pricing: each CU has a unit price; Work Order cost is calculated from selected CUs × quantity.
CU to WO: a Work Order references one or more CUs via the WO Planning tab (WPCUITEM table).
CU status workflow: DRAFT → PENDING → ACCEPTED → ACTIVE → OBSOLETE.
CU revision: versioning tracks changes over the CU lifecycle.
Used by: capital construction and maintenance in electric utility, telecom, and pipeline industries.


## Compatible Unit Job Plans
Source: IBM Maximo documentation (embedded IBM-verified content)

IBM Maximo Compatible Unit Job Plans (CUJP) link a Compatible Unit to a Maximo Job Plan.
CUJP.JPNUM: the referenced Job Plan (JOBPLAN table).
CUJP.CUID: the CU identifier.
Job Plan tasks (JPTASK): ordered steps within the Job Plan; copied to WO activities when the JP is applied.
Labour on Job Plan: JPLABOR records specify craft, hours, and skill level required.
Materials on Job Plan: JPMATERIAL / JPITEM records specify items, quantities, and estimated costs.
Tools on Job Plan: JPTOOL records specify tool type and duration.
Applying a CU to a WO:
  1. Open the Work Order in WOTRACK.
  2. On the Plans tab, select the CU from the CU library.
  3. Maximo copies the CU's Job Plan tasks, labour, materials, and tools to the WO.
  4. Craft and material estimates are pre-populated; actual values are reported at WO close.
CUJP versioning: each CU revision creates a new CUJP version for audit and cost history.


## Contracts overview
Source: IBM Maximo documentation (embedded IBM-verified content)

IBM Maximo Contracts manage legal agreements with vendors for goods or services.
Contract types: PURCHASE (blanket), LEASE, WARRANTY, MASTER, LABOR, SOFTWARE, SLA.
CONTRACT table: key fields: CONTRACTNUM, VENDOR, STARTDATE, ENDDATE, TOTALCOST, STATUS, TYPE.
Contract status: DRAFT → PENDING → APPROVED → ACTIVE → EXPIRED → TERMINATED.
Contract lines (CONTRACTLINE): individual items or services covered; each line has LINECOST.
Blanket PO: a Purchase contract authorises a vendor to supply goods without a separate PO per order.
Warranty contracts: WARRANTYLINE records link covered assets (ASSETNUM) to warranty terms.
  Warranty lookup: when a WO is raised for an asset, Maximo checks active warranty contracts.
  WORKORDER.WARRANTYCONTRACT is populated if a valid warranty is found.
Lease contracts: LEASEINFO records track scheduled payments and asset details for leased equipment.
SLA contracts: SERVICE LEVEL AGREEMENT contracts define response/resolution targets (linked to tickets).
Amendments: contract revision increments CONTRACT.REVISIONNUM while preserving the original.

