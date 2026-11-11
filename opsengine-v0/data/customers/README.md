# Real customers

Each real customer gets a folder here, made from `_template/`:

```bash
python -m opsengine new-customer acme_drylining --name "Acme Drylining Ltd"
```

**Everything in this folder except `_template/` and this README is git-ignored.**
Customer details, workers and documents are personal data (GDPR) and must never be
committed. Back them up somewhere access-controlled instead.

Folder layout (same as `data/sample/liffey_interiors/`):

| File | What goes in it |
| --- | --- |
| `company.json` | Company, owner, broker, sites and which main contractor runs each site |
| `workers.json` | One entry per worker: name, role, language, phone, tasks |
| `documents.json` | Documents already on file at onboarding (cards, insurance, Safety Statement...) |
| `incoming/` | Proof that arrives later (document JSON or photos) |
