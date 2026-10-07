# Client Knowledge Files

Drop client-specific `.md` skill files here. All files in this directory are
auto-loaded by every agent at runtime.

## How to populate

Run the discovery command against your live Maximo environment:

```bash
python run.py maximo discover
```

This auto-generates files such as:
- `mx_client_objects_SKILL.md` — custom objects and attributes
- `mx_client_sites_SKILL.md` — organisations and sites
- `mx_client_domains_SKILL.md` — domain values
- `mx_client_security_SKILL.md` — security groups

You can also add manual files here for business rules, naming conventions,
or client-specific Maximo configuration that the agents should know about.

> **Note:** This directory is excluded from the repository. Files generated
> here stay local to your machine (or your team's shared drive).
