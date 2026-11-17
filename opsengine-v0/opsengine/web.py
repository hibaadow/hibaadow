"""Web portal on top of the real engine (stdlib only), with sign-in.

    python -m opsengine web --demo     # SAMPLE companies + demo accounts (shown on the sign-in page)
    python -m opsengine web            # real customers in data/customers/; users from `opsengine user add`

Who sees what:
  - Customer users see only their own company: site status, approvals, what's being done.
  - Ops team: every customer - photo reviews, escalations, bookings.
  - Safety reviewer: drafted safety documents and high-risk closures waiting for a competent person.

Sign-in, sessions, the second step for staff, lockout and the account audit log are in auth.py.
Every form carries a per-session token (CSRF). Every approval is recorded against the signed-in
person's name and email. The demo clock and Reset exist only in --demo mode.
"""
import email.parser
import hashlib
import hmac
import os
import re
import email.policy
import html
import json
import shutil
import urllib.parse
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import approval_links, auth, config, delivery, inbound, limits, llm, scheduler, whatsapp
from .actions import provider_problems
from .engine import DONE, Engine
from .knowledge import ROOT, LANGUAGE_NAMES
from .labels import fee_line, money, nice_date, service
from .report import (ACTION_WORDS, STATE_WORDS, compliance_register, current_step, customer_stats, metrics,
                     risk_overview, title_of, weekly_summary, where_it_stands)

SAMPLES = [ROOT / "data" / "sample" / "bremore_groundworks", ROOT / "data" / "sample" / "liffey_interiors"]
DEFAULT_DAY = date(2026, 11, 11)
ROLE_APPROVES = {"customer": "customer", "ops": "ops", "reviewer": "safety_reviewer"}
e_ = html.escape


VIEW_ROLE = {"customer": "customer", "ops": "ops", "admin": "ops", "reviewer": "reviewer"}
TABS = {"customer": {"home", "issues", "issue", "people", "subcontractors", "equipment", "documents", "actions",
                     "bookings", "messages", "message", "report", "how", "settings"},
        "ops": {"ops", "issues", "issue", "bookings", "providers", "documents", "actions", "messages", "message", "insights",
                "home", "people", "subcontractors", "equipment", "report", "how", "settings", "console"},
        "reviewer": {"reviewer", "actions", "documents", "issue", "issues", "message", "console"}}


class Portal:
    def __init__(self, customers, state_dir, demo=False):
        self.demo = demo
        self.customers = {}
        for folder in customers:
            company = json.loads((Path(folder) / "company.json").read_text(encoding="utf-8"))
            if demo and not company.get("sample"):
                raise ValueError(f"--demo only runs with SAMPLE customers; {company['name']} is not SAMPLE")
            self.customers[company["id"]] = Path(folder)
        self.state = Path(state_dir)
        self.state.mkdir(parents=True, exist_ok=True)
        self.uploads = self.state / "uploads"
        self.clock_file = self.state / "clock.json"
        self.accounts_path = self.state / "accounts.db"
        if demo:
            auth.ensure_demo_users(self.accounts, set(self.customers))
            if not self.clock_file.exists():
                self.reset()

    @property
    def accounts(self):
        """A fresh connection per use: SQLite connections can't be shared between the server's threads."""
        return auth.Accounts(self.accounts_path)

    # ---- demo clock (demo mode only; real mode uses today's date) ----
    @property
    def today(self):
        if not self.demo:
            return date.today()
        try:
            return date.fromisoformat(json.loads(self.clock_file.read_text())["today"])
        except (OSError, ValueError, KeyError):
            return DEFAULT_DAY

    def set_today(self, day):
        self.clock_file.write_text(json.dumps({"today": day.isoformat()}))

    def reset(self):
        if not self.demo:
            raise PermissionError("reset is only available in demo mode")
        for child in self.state.iterdir():  # keep accounts.db: sign-ins and their audit log survive a reset
            if child.name.startswith("accounts.db"):
                continue
            shutil.rmtree(child) if child.is_dir() else child.unlink()
        self.set_today(DEFAULT_DAY)
        for folder in self.customers.values():
            scheduler.run_customer(folder, state_dir=self.state, today=DEFAULT_DAY)

    def next_day(self):
        if not self.demo:
            raise PermissionError("the demo clock is only available in demo mode")
        day = self.today + timedelta(days=1)
        self.set_today(day)
        return [scheduler.run_customer(f, state_dir=self.state, today=day) for f in self.customers.values()]

    def engine(self, cid):
        return Engine(self.customers[cid], state_dir=self.state, today=self.today)

    def safe_file(self, path, user=None):
        """Serve only files from the portal state and the sample data; a customer user only their own."""
        p = Path(path).resolve()
        if user and user["role"] == "customer":
            cid = user["customer_id"]
            roots = [(self.state / cid).resolve(), self.customers[cid].resolve()] if cid in self.customers else []
            if self.demo:
                roots.append((ROOT / "tests" / "fixtures").resolve())
        else:
            roots = [self.state.resolve(), (ROOT / "data" / "sample").resolve(), (ROOT / "tests" / "fixtures").resolve()]
        return p if p.is_file() and not p.name.startswith("accounts.db") and any(r in p.parents for r in roots) else None


# ---------------- plain-language helpers ----------------

def pill(severity):
    label = {"critical": "Can stop work", "high": "High", "medium": "Medium"}.get(severity, severity)
    return f'<span class="pill sev-{e_(severity)}">{e_(label)}</span>'


def status_chip(status):
    words = {"ok": "OK", "missing": "Missing", "expired": "Expired", "expiring": "Expiring", "incomplete": "Incomplete",
             "content_gap": "Needs revising", "out_of_use": "Out of use"}
    cls = "ok" if status == "ok" else ("bad" if status in ("missing", "expired", "out_of_use") else "warn")
    return f'<span class="chip {cls}">{e_(words.get(status, status))}</span>'


def md_to_html(md):
    """Just enough markdown for the weekly summary and outbox messages."""
    out, table, in_list = [], [], False
    def inline(t):
        t = e_(t)
        while "**" in t:
            t = t.replace("**", "<strong>", 1).replace("**", "</strong>", 1)
        return t
    def flush():
        nonlocal table
        if table:
            rows = [r for r in table if not set(r.replace("|", "").strip()) <= {"-", " "}]
            cells = [[c.strip() for c in r.strip().strip("|").split("|")] for r in rows]
            out.append('<div class="tbl"><table><thead><tr>' + "".join(f"<th>{inline(c)}</th>" for c in cells[0]) +
                       "</tr></thead><tbody>" + "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>"
                                                       for r in cells[1:]) + "</tbody></table></div>")
            table = []
    for line in md.splitlines():
        if line.startswith("|"):
            table.append(line); continue
        flush()
        if line.startswith("- "):
            if not in_list:
                out.append("<ul>"); in_list = True
            out.append(f"<li>{inline(line[2:])}</li>"); continue
        if in_list:
            out.append("</ul>"); in_list = False
        if line.startswith("```"):
            continue
        if line.startswith("#"):
            level = min(len(line) - len(line.lstrip("#")) + 1, 4)
            out.append(f"<h{level}>{inline(line.lstrip('#').strip())}</h{level}>")
        elif line.strip():
            out.append(f"<p>{inline(line)}</p>")
    flush()
    if in_list:
        out.append("</ul>")
    return "\n".join(out)


# ---------------- page shell ----------------

CSS = """
:root{--bg:#f4f5f3;--surface:#fff;--ink:#1b2430;--muted:#5a6571;--line:#dce0e2;--accent:#1f4e79;--accent-ink:#fff;
--accent-soft:#e6eef6;--hivis:#f2b705;--ok:#067647;--ok-bg:#e4f5ec;--warn:#9a5b00;--warn-bg:#fdf2dc;--bad:#b42318;--bad-bg:#fde8e6;
--f-d:"Archivo","Arial Narrow",Arial,sans-serif;--f-b:"IBM Plex Sans","Segoe UI",system-ui,sans-serif;--f-m:"IBM Plex Mono",ui-monospace,monospace}
@media (prefers-color-scheme:dark){:root{--bg:#11161c;--surface:#19212a;--ink:#e6eaee;--muted:#9ba7b3;--line:#2b3540;--accent:#8ab8e6;
--accent-ink:#0d1620;--accent-soft:#1c2c3c;--ok:#6fd3a0;--ok-bg:#16322a;--warn:#f5c26b;--warn-bg:#3a2e17;--bad:#ff8a80;--bad-bg:#3a1d1b;color-scheme:dark}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 var(--f-b)}
a{color:var(--accent)}h1,h2,h3{font-family:var(--f-d);line-height:1.2;margin:0;text-wrap:balance}h1{font-size:26px}h2{font-size:19px}h3{font-size:15px}
p{margin:0}.muted{color:var(--muted)}.small{font-size:13px}.mono{font-family:var(--f-m);font-size:12.5px}
.top{background:var(--ink);color:var(--bg);padding:10px max(16px,env(safe-area-inset-right,0px)) 10px max(16px,env(safe-area-inset-left,0px));display:flex;flex-wrap:wrap;gap:10px 18px;align-items:center}
.top .brand{font:800 17px var(--f-d);letter-spacing:.02em;display:flex;gap:8px;align-items:center}
.top .brand i{display:inline-block;width:22px;height:8px;background:repeating-linear-gradient(-45deg,var(--hivis) 0 6px,transparent 6px 12px);border:1px solid var(--hivis)}
.top a{color:inherit}.roles{display:flex;gap:4px;flex-wrap:wrap}.roles a{padding:4px 10px;border-radius:999px;text-decoration:none;font-size:13px;border:1px solid rgba(255,255,255,.25)}
.roles a.on{background:var(--hivis);color:#1b1400;border-color:var(--hivis);font-weight:600}
.demo{margin-left:auto;display:flex;gap:8px;align-items:center;font-size:13px;flex-wrap:wrap}
.demo form{display:inline}.demo button{font-size:12.5px;padding:4px 10px}
.sub{background:var(--surface);border-bottom:1px solid var(--line);padding:0 max(16px,env(safe-area-inset-right,0px)) 0 max(16px,env(safe-area-inset-left,0px));display:flex;gap:4px;overflow-x:auto;align-items:center}
.sub a{padding:11px 10px;text-decoration:none;color:var(--muted);white-space:nowrap;border-bottom:2px solid transparent;font-size:14px}
.sub a.on{color:var(--ink);border-bottom-color:var(--accent);font-weight:600}.sub select{margin-left:auto;font:inherit;font-size:13px;padding:4px}
main{max-width:1060px;margin:0 auto;padding-block:24px 64px;padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px));display:grid;gap:26px}
section{display:grid;gap:12px;min-width:0}.card{background:var(--surface);border:1px solid var(--line);border-radius:8px;padding:14px 16px;display:grid;gap:8px;min-width:0}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px}
.list{display:grid;gap:8px}.row{background:var(--surface);border:1px solid var(--line);border-radius:8px;padding:12px 14px;display:grid;grid-template-columns:minmax(0,1fr) auto;gap:6px 12px;align-items:center}
@media (max-width:640px){.row{grid-template-columns:1fr}.row .actions{justify-content:flex-start}}
.row .meta{font-size:13px;color:var(--muted)}.row a{text-decoration:none;color:inherit}.row a:hover h3{text-decoration:underline}
.pill{display:inline-block;font:600 11px/1.7 var(--f-b);padding:0 8px;border-radius:999px;text-transform:uppercase;letter-spacing:.04em;white-space:nowrap}
.sev-critical{background:var(--bad-bg);color:var(--bad)}.sev-high{background:var(--warn-bg);color:var(--warn)}.sev-medium{background:var(--accent-soft);color:var(--accent)}
.chip{display:inline-block;font-size:12px;padding:1px 8px;border-radius:4px;font-weight:600;white-space:nowrap}.chip.ok{background:var(--ok-bg);color:var(--ok)}
.chip.warn{background:var(--warn-bg);color:var(--warn)}.chip.bad{background:var(--bad-bg);color:var(--bad)}
.site{border-left:5px solid var(--ok)}.site.red{border-left-color:var(--bad)}.site .big{font:800 30px/1 var(--f-d)}
button,.btn{font:600 13.5px var(--f-b);padding:7px 14px;border-radius:6px;border:1px solid var(--accent);background:var(--accent);color:var(--accent-ink);cursor:pointer;text-decoration:none;display:inline-block}
button.ghost,.btn.ghost{background:transparent;color:var(--accent)}button.warn{background:var(--bad);border-color:var(--bad);color:#fff}
button:focus-visible,a:focus-visible,select:focus-visible,input:focus-visible{outline:2px solid var(--hivis);outline-offset:2px}
.actions{display:flex;gap:8px;flex-wrap:wrap;align-items:center}form.inline{display:flex;gap:6px;flex-wrap:wrap;align-items:center}
input,select,textarea{font:inherit;padding:7px 9px;border:1px solid var(--line);border-radius:6px;background:var(--surface);color:var(--ink);max-width:100%}
label{display:grid;gap:4px;font-size:13px;color:var(--muted)}.form{display:grid;gap:10px;grid-template-columns:repeat(auto-fit,minmax(200px,1fr))}
.tbl{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:14px;font-variant-numeric:tabular-nums}th,td{text-align:left;padding:7px 9px;border-bottom:1px solid var(--line);vertical-align:top}
th{font:600 12px var(--f-b);color:var(--muted);text-transform:uppercase;letter-spacing:.04em}
.timeline{list-style:none;margin:0;padding:0;display:grid;gap:0}.timeline li{display:grid;grid-template-columns:18px minmax(0,1fr);gap:10px;padding-bottom:12px;position:relative}
.timeline li::before{content:"";width:10px;height:10px;border-radius:50%;margin-top:6px;background:var(--surface);border:2px solid var(--line)}
.timeline li.done::before{background:var(--ok);border-color:var(--ok)}.timeline li.wait::before{background:var(--hivis);border-color:var(--hivis)}
.flash{background:var(--ok-bg);color:var(--ok);padding:10px 14px;border-radius:8px;font-weight:600}.flash.err{background:var(--bad-bg);color:var(--bad)}
.msg{white-space:normal}.msg h2{font-size:17px}.msg ul{margin:0;padding-left:18px}
.photo{max-width:320px;border-radius:8px;border:1px solid var(--line)}.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px}
.kpi{border-top:3px solid var(--accent);padding-top:8px}.kpi b{display:block;font:800 26px/1.1 var(--f-d)}.kpi span{font-size:13px;color:var(--muted)}
.note{border-left:3px solid var(--hivis);padding-left:10px;font-size:13px;color:var(--muted)}
@media (prefers-reduced-motion:reduce){*{transition:none!important}}
"""

FONTS = ('<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wght@600;800'
         '&family=IBM+Plex+Sans:wght@400;600&family=IBM+Plex+Mono:wght@500&display=swap">')


def page(portal, user, cid, tab, title, body, flash=None, csrf=""):
    role = VIEW_ROLE[user["role"]]
    names = {c: json.loads((f / "company.json").read_text(encoding="utf-8"))["name"] for c, f in portal.customers.items()}
    tabs = {"customer": [("home", "Overview"), ("issues", "Issues"), ("people", "People"), ("subcontractors", "Subcontractors"),
                         ("equipment", "Equipment"), ("documents", "Documents"), ("actions", "Corrective actions"),
                         ("bookings", "Bookings"), ("messages", "Messages"), ("report", "Weekly report"),
                         ("settings", "Approvals"), ("how", "How it works")],
            "ops": [("console", "All customers"), ("ops", "Ops queue"), ("issues", "Issues"), ("bookings", "Bookings"), ("providers", "Providers"),
                    ("documents", "Documents"), ("actions", "Corrective actions"), ("messages", "Messages"), ("insights", "Insights"),
                    ("how", "How it works")],
            "reviewer": [("console", "All customers"), ("reviewer", "To review"), ("actions", "Corrective actions"), ("documents", "Documents")]}[role]
    nav = "".join(f'<a class="{"on" if t == tab else ""}" href="/c/{cid}/{t}">{label}</a>' for t, label in tabs)
    pick = ""
    if role != "customer" and len(names) > 1:  # staff can move between customers; customers never see others
        pick = (f'<form class="inline" method="get" action="/switch" style="margin-left:auto"><input type="hidden" name="tab" value="{e_(tab)}">'
                '<select name="to" aria-label="Customer">' +
                "".join(f'<option value="{c}" {"selected" if c == cid else ""}>{e_(n)}</option>' for c, n in names.items()) +
                '</select><button class="ghost" style="padding:4px 10px">Go</button></form>')
    mode = "mock AI" if config.mock_ai() else ("live Claude" if llm.available() else "AI off")
    demo = ""
    if portal.demo:
        demo = (f'<span>Demo date <b>{portal.today.isoformat()}</b> · {mode}</span>'
                f'<form method="post" action="/demo/next-day"><input type="hidden" name="next" value="/c/{cid}/{tab}"><button class="ghost" style="color:inherit;border-color:rgba(255,255,255,.4)">Run next day ▸</button></form>'
                '<form method="post" action="/demo/reset"><button class="ghost" style="color:inherit;border-color:rgba(255,255,255,.25)">Reset</button></form>')
    admin = ('<a class="small" href="/admin/users" style="color:inherit">Users</a>'
             '<a class="small" href="/admin/plans" style="color:inherit">Plans</a>') if user["role"] == "admin" else ""
    who = (f'<span class="small">{e_(user["name"])} · {e_(ROLE_LABELS[user["role"]])}</span>{admin}'
           '<a class="small" href="/account/password" style="color:inherit">Password</a>'
           '<form method="post" action="/logout"><button class="ghost" style="color:inherit;border-color:rgba(255,255,255,.4)">Sign out</button></form>')
    flash_html = f'<div class="flash{" err" if flash and flash.startswith("!") else ""}">{e_(flash.lstrip("!"))}</div>' if flash else ""
    html_ = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>{e_(title)} · OpsEngine</title>{FONTS}<style>{CSS}</style></head><body>
<div class="top"><span class="brand"><i></i>OpsEngine{' <span class="small" style="color:var(--hivis)">SAMPLE DEMO</span>' if portal.demo else ''}</span>
<span class="roles">{who}</span><span class="demo">{demo}</span></div>
<nav class="sub">{nav}{pick}</nav><main>{flash_html}{body}</main></body></html>"""
    return with_csrf(html_, csrf)


ROLE_LABELS = {"customer": "Customer", "ops": "Ops team", "admin": "Admin", "reviewer": "Safety reviewer"}


def with_csrf(html_, csrf):
    """Every POST form carries the session's CSRF token."""
    return re.sub(r'(<form[^>]*method="post"[^>]*>)', lambda m: m.group(1) + f'<input type="hidden" name="csrf" value="{e_(csrf)}">', html_)


def bare_page(title, body, portal=None):
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>{e_(title)} · OpsEngine</title>{FONTS}<style>{CSS}</style></head><body>
<div class="top"><span class="brand"><i></i>OpsEngine{' <span class="small" style="color:var(--hivis)">SAMPLE DEMO</span>' if portal and portal.demo else ''}</span></div>
<main style="max-width:460px">{body}</main></body></html>"""


def view_link(portal, token, summary=None, approver="", error=None, done=None):
    """Approve-by-link page. Opening it changes nothing; only the buttons do."""
    if error or done:
        msg = f'<div class="flash{" err" if error else ""}">{e_(error or done)}</div>'
        return bare_page("Approval", f"<section><h1>Approval</h1>{msg}</section>", portal)
    return bare_page("Approval", f"""<section><h1>Your approval is needed</h1>
<p class="note">For {e_(approver)}. Nothing has happened yet: choose below. This link works once.</p>
<div class="card"><p>{e_(summary)}</p></div>
<form method="post" action="/a/{e_(token)}" style="display:grid;gap:10px;margin-top:12px">
<button name="decision" value="approved">Approve</button></form>
<form method="post" action="/a/{e_(token)}" style="display:grid;gap:10px;margin-top:18px">
<label for="reason">Or decline, and tell us why<input id="reason" name="reason" maxlength="300" required></label>
<button class="ghost" name="decision" value="declined">Decline</button></form></section>""", portal)


def view_password(portal, csrf, forced=False, error=None, user=None):
    err = f'<div class="flash err">{e_(error)}</div>' if error else ""
    codes = ""
    if user and not forced and not (user["role"] in auth.STAFF) and not user.get("mfa_wanted"):
        codes = ('<h2 style="margin-top:24px">Sign-in codes</h2><p class="note">Add a 6-digit code from an authenticator app '
                 "to your sign-in, so a stolen password isn't enough. You'll set it up the next time you sign in.</p>"
                 '<form method="post" action="/account/codes"><button class="ghost">Turn on sign-in codes</button></form>')
    intro = ('<p class="note">You signed in with a temporary password. Choose your own before you carry on.</p>'
             if forced else "")
    return with_csrf(bare_page("Change password", f"""<section><h1>Change your password</h1>{intro}{err}
<form class="card" method="post" action="/account/password" style="display:grid;gap:10px">
<label for="current">Current password<input id="current" name="current" type="password" autocomplete="current-password" required></label>
<label for="new">New password (12+ characters)<input id="new" name="new" type="password" autocomplete="new-password" minlength="12" required></label>
<label for="again">New password again<input id="again" name="again" type="password" autocomplete="new-password" minlength="12" required></label>
<button>Change password</button></form>{codes}{'' if forced else '<a href="/">Back</a>'}</section>""", portal), csrf)


def view_plans(portal, csrf, flash=None):
    """Administrators: plan limits for everyone, and each customer's custom limits and extra capacity."""
    from . import pricing
    prices = pricing.load()
    over = limits.plan_limit_overrides(portal.state)
    fl = f'<div class="flash{" err" if flash and flash.startswith("!") else ""}">{e_(flash.lstrip("!"))}</div>' if flash else ""
    plan_rows = []
    for x in prices["plans"]:
        lim = {**(x.get("limits") or {}), **over.get(x["id"], {})}
        inputs = "".join(f'<td><input name="{m}" type="number" min="0" max="100000" value="{e_(str(lim.get(m, "")))}" aria-label="{e_(x["name"])} {m}" style="width:7em"></td>'
                         for m in limits.METRICS)
        plan_rows.append(f'<tr><td><form id="p-{x["id"]}" method="post" action="/admin/plans/{x["id"]}"></form>{e_(x["name"])}</td>'
                         + inputs.replace("<input ", f'<input form="p-{x["id"]}" ') +
                         f'<td><button form="p-{x["id"]}" class="ghost">Save</button></td></tr>')
    cust = []
    for cid in portal.customers:
        e = portal.engine(cid)
        o, ex, u = limits.overrides(e), limits.extras(e), limits.usage(e)
        plan = (e.customer.company.get("plan") or {}).get("id", "none")
        used = " · ".join(f'{v["used"]}/{v["allowance"] if v["allowance"] is not None else "custom"} {k.replace("_per_month", "")}' for k, v in u.items())
        field = lambda name, label, val: (f'<label>{label}<input name="{name}" type="number" min="0" step="any" value="{e_(str(val if val is not None else ""))}" '
                                          f'style="width:7em"></label>')
        cust.append(f'<div class="card"><h3>{e_(e.customer.company["name"])} · {e_(plan)}</h3><p class="small">Usage: {e_(used)}</p>'
                    f'<form method="post" action="/admin/plans/customer/{cid}" style="display:flex;flex-wrap:wrap;gap:8px;align-items:end">'
                    f'{field("workers", "Custom workers limit", o.get("workers"))}{field("sites", "Custom sites limit", o.get("sites"))}'
                    f'{field("reviews_per_month", "Custom reviews a month", o.get("reviews_per_month"))}'
                    f'{field("extra_worker_blocks", "Extra 25-worker blocks", ex["extra_worker_blocks"])}{field("extra_sites", "Extra sites", ex["extra_sites"])}'
                    f'{field("extra_site_eur", "Extra site price € (enterprise)", ex["extra_site_eur"])}'
                    f'{field("extra_reviews_this_month", "Extra reviews this month", ex["extra_reviews"])}'
                    '<button class="ghost">Save</button></form>'
                    '<p class="small muted">Only add paid capacity once the customer has agreed to the charge.</p></div>')
    heads = "".join(f"<th>{h}</th>" for h in ("Plan", "Workers", "Sites", "Reviews a month", ""))
    return with_csrf(bare_page("Plans and limits", f"""<section><h1>Plans and limits</h1>{fl}
<p class="note">Changes apply straight away and are recorded in the audit log. Limits never stop monitoring, hide issues,
silence safety alerts or approve anything; a review over the allowance waits in the queue.</p>
<div class="tbl"><table><thead><tr>{heads}</tr></thead><tbody>{''.join(plan_rows)}</tbody></table></div></section>
<section><h2>Customers</h2>{''.join(cust)}<a href="/">Back</a></section>""", portal).replace("max-width:460px", "max-width:960px"), csrf)


def view_users(portal, me, csrf, flash=None, shown=None):
    names = {c: json.loads((f / "company.json").read_text(encoding="utf-8"))["name"] for c, f in portal.customers.items()}
    rows = []
    for u in portal.accounts.users():
        status = "disabled" if u["disabled"] else ("locked" if u["locked_until"] else "active")
        flags = [x for x, on in (("demo", u["demo"]), ("must change password", u["must_change"]),
                                 ("code set", u["mfa_secret"] and u["role"] in auth.STAFF)) if on]
        acts = []
        if u["id"] != me["id"]:
            acts.append(f'<form class="inline" method="post" action="/admin/users/{u["id"]}/{"enable" if u["disabled"] else "disable"}">'
                        f'<button class="ghost">{"Enable" if u["disabled"] else "Disable"}</button></form>')
        acts.append(f'<form class="inline" method="post" action="/admin/users/{u["id"]}/reset-password"><button class="ghost">Reset password</button></form>')
        if u["role"] in auth.STAFF:
            acts.append(f'<form class="inline" method="post" action="/admin/users/{u["id"]}/reset-code"><button class="ghost">Reset sign-in code</button></form>')
        rows.append(f'<tr><td>{e_(u["name"])}<br><span class="small muted">{e_(u["email"])}</span></td><td>{e_(ROLE_LABELS[u["role"]])}</td>'
                    f'<td>{e_(names.get(u["customer_id"], u["customer_id"] or "All customers"))}</td>'
                    f'<td><span class="chip {"ok" if status == "active" else "bad"}">{status}</span> <span class="small muted">{e_(", ".join(flags))}</span></td>'
                    f'<td><div class="actions">{"".join(acts)}</div></td></tr>')
    shown_html = ""
    if shown:
        shown_html = (f'<div class="card" style="border-color:var(--hivis)"><b>Temporary password for {e_(shown[0])}</b>'
                      f'<span class="mono" style="font-size:18px">{e_(shown[1])}</span>'
                      '<span class="small muted">Shown once. Give it to them securely (not by email with their username). '
                      'They must choose their own password when they first sign in.</span></div>')
    flash_html = f'<div class="flash{" err" if flash and flash.startswith("!") else ""}">{e_(flash.lstrip("!"))}</div>' if flash else ""
    opts = "".join(f'<option value="{c}">{e_(n)}</option>' for c, n in names.items())
    body = f"""<section><a href="/">‹ Back</a><h1>Users</h1>{flash_html}{shown_html}
<div class="tbl"><table><thead><tr><th>Person</th><th>Role</th><th>Company</th><th>Status</th><th></th></tr></thead><tbody>{''.join(rows)}</tbody></table></div></section>
<section><h2>Add a user</h2><form class="card form" method="post" action="/admin/users/add">
<label for="u-name">Name<input id="u-name" name="name" required></label>
<label for="u-email">Email<input id="u-email" name="email" type="email" required></label>
<label for="u-role">Role<select id="u-role" name="role"><option value="customer">Customer</option><option value="ops">Ops team</option>
<option value="reviewer">Safety reviewer</option><option value="admin">Admin</option></select></label>
<label for="u-customer">Company (customer users only)<select id="u-customer" name="customer"><option value="">None (staff)</option>{opts}</select></label>
<button>Add user</button></form><p class="note">They get a temporary password to change at first sign-in. Staff also set up an authenticator code.</p></section>"""
    return with_csrf(bare_page("Users", body, portal).replace('<main style="max-width:460px">', "<main>"), csrf)


def view_login(portal, error=None, email="", notice=None):
    demo = ""
    if portal.demo:
        rows = "".join(
            f'<form class="row" method="post" action="/login"><div><h3>{e_(name)}</h3><div class="meta">{e_(ROLE_LABELS[role])}</div></div>'
            f'<input type="hidden" name="email" value="{e_(addr)}"><input type="hidden" name="password" value="{auth.DEMO_PASSWORD}">'
            f'<button class="ghost">Sign in</button></form>'
            for addr, name, role, cid in auth.DEMO_USERS if not cid or cid in portal.customers)
        demo = (f'<section><h2>Demo accounts</h2><p class="note">SAMPLE data only. These accounts exist only in demo mode, '
                f'where staff accounts skip the second sign-in step.</p><div class="list">{rows}</div></section>')
    err = f'<div class="flash err">{e_(error)}</div>' if error else ""
    if notice and not error:
        err = f'<div class="flash">{e_(notice[:200])}</div>'
    return bare_page("Sign in", f"""<section><h1>Sign in</h1>{err}
<form class="card" method="post" action="/login" style="display:grid;gap:10px">
<label for="email">Email<input id="email" name="email" type="email" autocomplete="username" required value="{e_(email)}"></label>
<label for="password">Password<input id="password" name="password" type="password" autocomplete="current-password" required></label>
<button>Sign in</button></form></section>{demo}""", portal)


def view_code(portal, setup_secret=None, email="", error=None):
    err = f'<div class="flash err">{e_(error)}</div>' if error else ""
    setup = ""
    if setup_secret:
        setup = (f'<p>Staff accounts need a second step. Add OpsEngine to an authenticator app (for example Google Authenticator, '
                 f'Microsoft Authenticator or 1Password) using this key, then enter the 6-digit code it shows.</p>'
                 f'<div class="card"><span class="small muted">Setup key</span><b class="mono" style="font-size:16px;word-break:break-all">'
                 f'{e_(" ".join(setup_secret[i:i + 4] for i in range(0, len(setup_secret), 4)))}</b>'
                 f'<span class="small muted" style="word-break:break-all">{e_(auth.totp_uri(setup_secret, email))}</span></div>'
                 f'<input type="hidden" name="secret" value="{e_(setup_secret)}">')
    return bare_page("Enter your code", f"""<section><h1>{"Set up your sign-in code" if setup_secret else "Enter your code"}</h1>{err}
<form class="card" method="post" action="/login/code" style="display:grid;gap:10px">{setup}
<label for="code">6-digit code<input id="code" name="code" inputmode="numeric" autocomplete="one-time-code" pattern="[0-9 ]{{6,7}}" required></label>
<button>Continue</button></form><a href="/login">Start again</a></section>""", portal)


# ---------------- views ----------------

def approve_buttons(cid, step, role, label="Approve"):
    if ROLE_APPROVES[role] != step["approval_role"]:
        who = {"customer": "the customer", "safety_reviewer": "the safety reviewer", "ops": "the ops team"}[step["approval_role"]]
        return f'<span class="muted small">Waiting for {who}</span>'
    return (f'<form class="inline" method="post" action="/c/{cid}/approve"><input type="hidden" name="step" value="{e_(step["id"])}">'
            f'<button>{e_(label)}</button></form>'
            f'<form class="inline" method="post" action="/c/{cid}/reject"><input type="hidden" name="step" value="{e_(step["id"])}">'
            f'<input name="reason" placeholder="Reason to decline" aria-label="Reason to decline" required size="16"><button class="ghost">Decline</button></form>')


def prior_results(eng, step):
    return {p["action"]: p["result"] for p in eng.store.steps(step["issue_id"]) if p["state"] in DONE and p["result"]}


def cost_note(eng, s):
    """For anything that costs money: who gets paid what, and what we charge, kept apart."""
    rec = (prior_results(eng, s).get("find_provider") or {}).get("recommended")
    if s["action"] != "book_service" or not rec:
        return ""
    return (f'<div class="small" style="margin-top:4px">{money(rec["price_eur"])} paid to {e_(rec["name"])} at their price · '
            f'{e_(fee_line())}</div>')


def approval_row(eng, cid, role, s):
    return (f'<div class="row"><div><h3>{e_(eng.approval_summary(s, prior_results(eng, s)))}</h3>{cost_note(eng, s)}'
            f'<div class="meta"><a href="/c/{cid}/issue/{s["issue_id"]}">{s["issue_id"]}</a></div></div>'
            f'<div class="actions">{approve_buttons(cid, s, role)}</div></div>')


def approval_groups(eng, cid, role, steps):
    """Approvals of the same kind (e.g. four Safe Pass bookings) shown as one group, with
    'Approve all' and the individual approve/decline still available."""
    groups = {}
    for s in steps:
        issue = eng.store.issue(s["issue_id"])
        groups.setdefault((s["action"], issue["requirement"], s["spec"].get("template")), []).append((s, issue))
    out = []
    for (action, req_id, _), members in groups.items():
        if len(members) == 1:
            out.append(approval_row(eng, cid, role, members[0][0]))
            continue
        req = eng.kb.requirements[req_id]["name"]
        names = [eng.customer.holder_name(i["holder"]) for _, i in members]
        if action == "book_service":
            total = sum((prior_results(eng, s).get("find_provider") or {}).get("recommended", {}).get("price_eur", 0) for s, _ in members)
            title = f"Book {req} for {len(members)} workers, {money(total)} total, paid to the course providers"
        else:
            first = eng.approval_summary(members[0][0], prior_results(eng, members[0][0]))
            title = f"{len(members)} similar approvals: {first.split(' for ')[0]} ({req})"
        ids = ",".join(s["id"] for s, _ in members)
        allowed = ROLE_APPROVES[role] == members[0][0]["approval_role"]
        buttons = (f'<form class="inline" method="post" action="/c/{cid}/approve-group"><input type="hidden" name="steps" value="{e_(ids)}">'
                   f'<button>Approve all {len(members)}</button></form>') if allowed else ""
        extra = f'<div class="small">{e_(fee_line()[0].upper() + fee_line()[1:])}.</div>' if action == "book_service" else ""
        out.append(f'<div class="card"><div class="actions" style="justify-content:space-between"><h3>{e_(title)}</h3>{buttons}</div>'
                   f'<span class="small muted">{e_(", ".join(names))}</span>{extra}'
                   f'<details><summary>Review one by one</summary><div class="list" style="margin-top:8px">'
                   f'{"".join(approval_row(eng, cid, role, s) for s, _ in members)}</div></details></div>')
    return "".join(out)


def issue_row(eng, cid, i, extra=""):
    who = eng.customer.holder_name(i["holder"])
    return (f'<div class="row"><a href="/c/{cid}/issue/{i["id"]}"><h3>{e_(title_of(eng, i))}</h3>'
            f'<div class="meta">{e_(who)} · {e_(where_it_stands(eng, i))} · <span class="mono">{i["id"]}</span></div></a>'
            f'<div class="actions">{pill(i["severity"])}{extra}</div></div>')


def setup_progress(eng):
    rows = [r for r in compliance_register(eng) if r["requirement"] != "safe_to_use"]
    on_file = sum(1 for r in rows if r["document"])
    return on_file, len(rows)


def view_how(portal, eng, cid, role):
    """The customer's questions answered: who is responsible, what it costs, who does setup, workers' data."""
    from . import gdpr
    svc = service()
    c = eng.customer
    rev = svc["safety_reviewer"]
    on_file, total = setup_progress(eng)
    r = gdpr.retention(customer=c)
    subs = json.loads((ROOT / "docs" / "sub-processors.json").read_text(encoding="utf-8"))
    dp = c.company.get("data_protection") or {}
    if c.company.get("sample"):
        dpa = "This is a SAMPLE company, so no agreement is needed."
    elif dp.get("dpa_signed_on"):
        dpa = f"Your data processing agreement was signed on {nice_date(dp['dpa_signed_on'])}."
    else:
        dpa = "Your data processing agreement isn't signed yet. We don't handle your workers' data until it is."
    costs = view_costs(eng, svc)
    li = lambda items: "<ul>" + "".join(f"<li>{e_(x)}</li>" for x in items) + "</ul>"
    return f"""<section><h1>How OpsEngine works for you</h1>
<p class="note">Plain answers to the questions customers ask us most: who is responsible for what, what it costs, who does the setup, and what happens to your workers' data.</p></section>
<section><h2>Who is responsible for what</h2><div class="grid">
<div class="card"><h3>We do</h3>{li([
    "Track every card, certificate, insurance and inspection, and spot gaps before they stop work.",
    "Chase workers, subcontractors and brokers for documents, in their own language.",
    "Find the cheapest or fastest provider in time, and do the booking admin once you approve.",
    "Check every document we receive. Anything we're not sure about goes to a person on our team.",
    "Keep a complete record of who did what and when, ready for any main contractor or audit."])}</div>
<div class="card"><h3>You decide</h3>{li([
    "Anything that costs money or commits you. Nothing is booked or paid for without your OK, or your own standing approval.",
    "Who works on your sites. We tell you who is clear and who isn't; the call is yours.",
    "How long your workers' data is kept (we suggest periods; you choose)."])}
<p class="small">You stay the employer and the contractor, with the legal duties that come with that. We help you meet them; we don't take them over.</p></div>
<div class="card"><h3>A qualified person signs off</h3>{li([
    (f"Safety Statements, method statements (RAMS) and high-risk corrective actions are released only by {rev['name']}, {rev['qualification']}."
     if rev.get("appointed") else
     "Safety Statements, method statements (RAMS) and high-risk corrective actions are released only by a named, qualified safety reviewer. "
     "That reviewer hasn't been appointed yet, so safety reviews aren't running yet."),
    "Training, inspections and repairs are done by qualified providers. We never mark them done without their proof.",
    "Translated safety content is checked by a native speaker before it's used."])}</div>
<div class="card"><h3>We never</h3>{li([
    "Act as your PSCS or PSDP, or sign anything in a legal capacity. We put you in touch with qualified partners.",
    "Guess a document. If a photo isn't clear, a person checks it.",
    "Approve spending on your behalf beyond the limit you set."])}</div></div>
<p class="small muted">Your agreement with us sets out liability in full. Every action, approval and decision is recorded, so you can always see who did what and when.</p></section>
{costs}
<section><h2>Setup: our team does it</h2>
<p><b>You don't have to upload your certs.</b> Our team sets you up, usually within {svc["onboarding"]["typical_days"]} working days.</p>{li(svc["onboarding"]["how"])}
<div class="kpis"><div class="kpi"><b>{on_file} of {total}</b><span>required records on file so far</span></div></div></section>
<section><h2>Your workers' data</h2>
<p>Card photos and worker details are personal data. You control them; we look after them for you under a data processing agreement. {e_(dpa)}</p>
<div class="grid"><div class="card"><h3>What we hold</h3>{li([
    "Workers' names, roles, phone numbers and preferred language.",
    "Card and certificate details, and photos of the cards they send us.",
    "The messages we send and receive about their documents."])}
<p class="small">We only read the text on a card. We never use the photo to recognise faces.</p></div>
<div class="card"><h3>Who sees it</h3>{li([
    "You, and our team when they need to.",
    "Main contractors you work for: proof that your workers are compliant. For employment terms, only a confirmation, never the contract.",
    "Course providers: only what a booking you approved needs."])}</div>
<div class="card"><h3>How long we keep it</h3>{li([
    f"Card photos: {r['leaver_photos_months']} months after someone leaves.",
    f"Training records: {r['leaver_records_years']} years after someone leaves, in case of an injury claim. Then they're deleted and the person is removed from our records.",
    f"Photos a person rejected: {r['review_uploads_days']} days.",
    "WhatsApp preferences: deleted when someone leaves."])}
<p class="small">These are our suggested periods{' and the ones you chose' if r.get('customer_choices') else ''}. You can change them.</p></div>
<div class="card"><h3>Your workers' rights</h3>{li([
    "We can give any worker a full copy of what we hold about them.",
    "We only message workers on WhatsApp once they've opted in, and STOP ends it.",
    "Everything is hosted in the EU."])}
<p class="small">Outside services we use (version {subs["version"]} of the list): {e_(", ".join(x["name"] for x in subs["sub_processors"]))}. We tell you before adding one, and you can object.</p></div></div></section>"""


def view_costs(eng, svc):
    """Your plan and bill, every plan side by side, and what is charged separately. All excluding VAT."""
    from . import pricing
    prices = pricing.load()
    mine = pricing.customer_plan(eng.customer, prices, limits.extras(eng))
    p = mine["plan"]
    price = lambda v: f"{money(v)} a month" if v is not None else "Custom pricing"
    if p:
        extras = "".join(f'<li>{e_(x["name"])}: {e_(x["price"])}</li>' for x in mine["extras"])
        total = (f'<p>Your monthly total: <b>{money(mine["monthly_total_eur"])}</b> + VAT</p>' if mine["monthly_total_eur"] is not None
                 else '<p>Your monthly total: as agreed with you, + VAT</p>')
        plan_card = (f'<div class="card"><h3>Your plan: {e_(p["name"])}</h3><p><b>{e_(price(p["monthly_eur"]))}</b> + VAT</p>'
                     f'{"<ul>" + extras + "</ul>" if extras else ""}{total}'
                     f'<p class="small">One-off onboarding fee: {money(p["onboarding_eur"]) if p["onboarding_eur"] else "quoted individually"} + VAT. '
                     f'It pays for our team setting you up.</p></div>')
    else:
        plan_card = '<div class="card"><h3>Your plan</h3><p>Not set yet. Our team will agree it with you.</p></div>'
    rows = []
    meters = "".join(
        f'<div class="kpi"><b>{u["used"]} of {u["allowance"] if u["allowance"] is not None else "custom"}</b><span>{e_(u["label"])}'
        f'{" (" + str(u["percent"]) + "%)" if u["percent"] is not None else ""}'
        f'{"<br><b>At your limit: " + e_(limits.offer(eng, m)) + "</b>" if u["level"] in ("at", "over") else ""}</span></div>'
        for m, u in limits.usage(eng).items())
    for x in prices["plans"]:
        size = f'{x["workers_min"]}–{x["workers_max"]} workers' if x["workers_max"] else f'{x["workers_min"] - 1}+ workers'
        prev = "" if x is prices["plans"][0] or not x.get("includes_previous", True) else \
            f'Everything in {prices["plans"][prices["plans"].index(x) - 1]["name"]}, plus: '
        onboarding = money(x["onboarding_eur"]) if x["onboarding_eur"] else "Quoted"
        lim = x.get("limits")
        caps = (f'{lim["workers"]} workers, {lim["sites"]} site{"s" if lim["sites"] != 1 else ""}, '
                f'{lim["reviews_per_month"]} routine reviews a month') if lim else "Custom limits"
        rows.append(f'<tr{" style=\"font-weight:600\"" if p and x["id"] == p["id"] else ""}><td>{e_(x["name"])}</td><td>{e_(size)}</td>'
                    f'<td>{e_(price(x["monthly_eur"]))}</td><td>{e_(onboarding)}</td><td class="small">{e_(caps)}</td>'
                    f'<td class="small">{e_(prev + ", ".join(x["features"].values()))}</td></tr>')
    addons = "".join(f'<tr><td>{e_(a["name"])}{"<div class=small>" + e_(a["note"]) + "</div>" if a.get("note") else ""}</td>'
                     f'<td>{e_(a["price"])}</td></tr>' for a in prices["add_ons"])
    return f"""<section><h2>What it costs</h2><p class="note">All prices are monthly subscriptions in euro, excluding VAT.</p>
<div class="grid">{plan_card}
<div class="card"><h3>Courses, inspections and repairs</h3><p><b>Paid to the provider, at their price</b></p>
<p class="small">They're charged separately from your subscription, and only once you've approved them. Every approval shows the provider's price on its own line. {e_(fee_line(svc)[0].upper() + fee_line(svc)[1:])}.</p></div></div>
<p><b>Included in every plan:</b> {e_("; ".join(prices.get("included_in_every_plan", [])))}. OpsEngine itself never signs off safety documents: a competent person does.</p>
<h3 style="margin-top:16px">Your usage</h3><div class="kpis">{meters}</div>
<p class="small">We tell you at 80% and at 100%. At a limit we offer an upgrade or extra capacity. {e_(prices["limits_notes"]["at_limit"])}</p>
<h3 style="margin-top:16px">Specialist safety work, quoted separately</h3>
<p class="small">Ordinary reviews of RAMS and Safety Statements are never specialist work. Specialist work is quoted before it starts, and only goes ahead with your OK:</p>
<ul>{"".join(f"<li>{e_(x)}</li>" for x in prices["specialist_safety_work"])}</ul>
<h3 style="margin-top:16px">All plans</h3><div style="overflow-x:auto"><table><thead><tr><th>Plan</th><th>For</th><th>Monthly</th><th>Onboarding</th><th>Limits</th><th>Includes</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table></div>
<h3 style="margin-top:16px">Extras</h3><div style="overflow-x:auto"><table><thead><tr><th>Service</th><th>Price</th></tr></thead><tbody>{addons}</tbody></table></div>
<p class="small muted">{e_(prices["separate_charges"])}</p></section>"""


def view_settings(portal, eng, cid, role):
    rule = eng.standing_approval()
    spent = eng.auto_spent_this_month()
    limit = rule["limit_eur"] if rule else 0
    cap = (rule or {}).get("monthly_cap_eur") or ""
    state = (f'<p><b>On:</b> bookings up to {money(limit)} each are approved automatically'
             f'{f", up to {money(cap)} a month" if cap else ""}. Set by {e_(rule["set_by"])}. '
             f'Used so far this month: {money(spent)}.</p>' if rule else
             '<p><b>Off:</b> every booking waits for your OK.</p>')
    form = "" if role != "customer" else f"""<form class="card" method="post" action="/c/{cid}/standing-approval" style="display:grid;gap:10px;max-width:420px">
<label for="limit">Approve bookings automatically up to (€ each, 0 = off)<input id="limit" name="limit" type="number" min="0" max="5000" step="1" value="{e_(str(limit))}"></label>
<label for="cap">But no more than (€ a month, optional)<input id="cap" name="cap" type="number" min="1" max="50000" step="1" value="{e_(str(cap))}"></label>
<button>Save</button></form>"""
    return f"""<section><h1>Approvals</h1>
<p class="note">Fewer taps: let small, routine bookings (training courses, inspections) go ahead without asking you each time.
Each one is still recorded and shown to you, with the provider's price. Insurance changes, signatures and anything over your limit always wait for your OK.
Safety sign-off always needs the safety reviewer. The limit applies to new bookings; anything already waiting stays for you to approve.</p>
{state}{form}{'' if role == 'customer' else '<p class="small muted">Only the customer can change this.</p>'}</section>"""


def view_home(portal, eng, cid, role):
    c = eng.customer
    reg = compliance_register(eng)
    risks = risk_overview(eng)
    sites = []
    for sid, s in c.sites.items():
        n = risks["by_site"].get(sid, {"blocking": 0, "other": 0})
        red = n["blocking"] > 0
        sites.append(f'<div class="card site{" red" if red else ""}"><span class="muted small">{e_(s["name"])}</span>'
                     f'<span class="big">{n["blocking"]}</span><span>{"item(s) could stop people working here" if red else "Clear to work"}</span>'
                     f'<span class="muted small">{n["other"]} other item(s) in progress</span></div>')
    queue = [s for s in eng.store.steps(state="awaiting_approval")]
    yours = [s for s in queue if s["approval_role"] == "customer"]
    others = [s for s in queue if s["approval_role"] != "customer"]
    appr = approval_groups(eng, cid, role, yours) or '<p class="muted">Nothing needs your OK right now.</p>'
    open_issues = sorted(eng.store.issues("open"), key=lambda i: ({"critical": 0, "high": 1}.get(i["severity"], 2), i["id"]))
    working = "".join(issue_row(eng, cid, i) for i in open_issues[:8])
    done = eng.store.issues("resolved")[-5:]
    st = customer_stats(eng)
    rule = eng.standing_approval()
    auto_note = (f", or it's a booking under the {money(rule['limit_eur'])} limit you set (<a href=\"/c/{cid}/settings\">change</a>)" if rule
                 else f' (<a href="/c/{cid}/settings">let small bookings go ahead automatically</a>)')
    auto = [x for x in eng.store.steps() if (x["approved_by"] or "").startswith("Standing approval")][-5:]
    auto_list = ('<h3 style="margin-top:14px">Approved automatically under your limit</h3><div class="list">' +
                 "".join(f'<div class="row"><div><h3>{e_(eng.approval_summary(x, prior_results(eng, x)))}</h3>{cost_note(eng, x)}</div></div>' for x in reversed(auto)) +
                 "</div>") if auto else ""
    on_file, total = setup_progress(eng)
    setup = (f'<section><h2>Setup</h2><p>Our team is setting you up: <b>{on_file} of {total}</b> required records are on file. '
             f'You don\'t need to upload anything; we ask your workers directly. <a href="/c/{cid}/how">How it works ›</a></p></section>'
             if total and on_file < total * 0.8 else "")
    return f"""
<section><div><span class="muted small">{e_(c.company["name"])}</span><h1>Can your team work on site?</h1></div>
<div class="grid">{''.join(sites)}</div></section>
<section><h2>Needs your OK ({len(yours)})</h2><p class="note">Nothing that costs money or commits you happens until you approve it{auto_note}. {len(others)} other item(s) are with the safety reviewer or our team.</p>
<div class="list">{appr}</div>{auto_list}</section>{setup}
<section><h2>We're working on ({len(open_issues)})</h2><div class="list">{working}</div>
<a href="/c/{cid}/issues">See all issues ›</a></section>
<section><h2>Recently sorted</h2><div class="list">{''.join(issue_row(eng, cid, i) for i in reversed(done)) or '<p class="muted">Nothing sorted yet. Try uploading a card photo under Documents.</p>'}</div></section>
<section><h2>This week</h2><div class="kpis">
<div class="kpi"><b>{st['sorted_this_week']}</b><span>issues sorted this week</span></div>
<div class="kpi"><b>{st['average_days_to_sort'] if st['average_days_to_sort'] is not None else '–'}</b><span>average days to sort</span></div>
<div class="kpi"><b>{st['could_stop_work']}</b><span>items that could stop work</span></div></div></section>"""


def view_issues(portal, eng, cid, role, q):
    status = q.get("status", ["open"])[0]
    holder = q.get("holder", [None])[0]
    issues = eng.store.issues(None if status == "all" else status)
    if holder:
        issues = [i for i in issues if i["holder"] == holder]
    issues.sort(key=lambda i: ({"critical": 0, "high": 1}.get(i["severity"], 2), i["id"]))
    tabs = " · ".join(f'<a href="/c/{cid}/issues?status={s}{"&holder=" + holder if holder else ""}">{"<b>" + l + "</b>" if s == status else l}</a>'
                      for s, l in (("open", "Open"), ("escalated", "Escalated"), ("resolved", "Sorted"), ("all", "All")))
    who = f" for {e_(eng.customer.holder_name(holder))}" if holder else ""
    return f'<section><h1>Issues{who}</h1><p>{tabs}</p><div class="list">{"".join(issue_row(eng, cid, i) for i in issues) or "<p class=muted>No issues here.</p>"}</div></section>'


def view_issue(portal, eng, cid, role, issue_id):
    h = eng.issue_history(issue_id)
    i = h["issue"]
    data = json.loads(i["data"] or "{}")
    steps = []
    for s in h["steps"]:
        cls = "done" if s["state"] in DONE else ("wait" if s["state"] in ("waiting", "awaiting_approval") else "")
        r = s["result"] or {}
        bits = [f'<b>{e_(ACTION_WORDS.get(s["action"], s["action"]))}</b> <span class="chip {"ok" if cls == "done" else "warn" if cls == "wait" else ""}">{e_(STATE_WORDS.get(s["state"], s["state"]))}</span>']
        if s["approved_by"]:
            bits.append(f'<span class="small muted">approved by {e_(s["approved_by"])}</span>')
        if r.get("sent_to"):
            bits.append(f'<span class="small muted">to {e_(r["sent_to"])}</span>')
        if r.get("recommended"):
            bits.append(f'<span class="small muted">recommended {e_(r["recommended"]["name"])}, {money(r["recommended"]["price_eur"])}</span>')
        if r.get("reason"):
            bits.append(f'<span class="small muted">{e_(r["reason"])}</span>')
        if r.get("requested_from"):
            bits.append(f'<span class="small muted">quotes asked from {len(r["requested_from"])} providers</span>')
        if r.get("appointment"):
            bits.append(f'<span class="small muted">appointment {e_(r["appointment"])} on or after {e_(r.get("date", ""))}</span>')
        if r.get("retry_reason"):
            bits.append(f'<span class="small" style="color:var(--bad)">sent back: {e_(r["retry_reason"])}</span>')
        if r.get("outbox") and not (role == "customer" and s["action"] == "find_provider"):
            bits.append(f'<a class="small" href="/c/{cid}/message?path={urllib.parse.quote(r["outbox"])}">view message</a>')
        if r.get("draft"):
            bits.append(f'<a class="small" href="/c/{cid}/message?path={urllib.parse.quote(r["draft"])}">view draft</a>')
        if s["state"] == "awaiting_approval":
            bits.append(approve_buttons(cid, s, role, "Approve" if s["approval_role"] != "safety_reviewer" else "Release / sign off"))
        if s["state"] == "rejected" and s["approval_role"] == "safety_reviewer" and s["action"] == limits.ROUTINE_REVIEW_ACTION:
            bits.append(f'<span class="small" style="color:var(--bad)">declined: {e_(r.get("reason", ""))}</span>')
            if role == "ops":
                bits.append(f'<form class="inline" method="post" action="/c/{cid}/resubmit"><input type="hidden" name="issue" value="{e_(i["id"])}">'
                            '<input name="note" required placeholder="What was amended" aria-label="What was amended" size="18">'
                            '<button class="ghost">Resubmit amended draft</button></form>')
        steps.append(f'<li class="{cls}"><div style="display:flex;flex-wrap:wrap;gap:6px 10px;align-items:center">{" ".join(bits)}</div></li>')
    comms = "".join(f'<tr><td class="mono">{e_(c["ts"][:16])}</td><td>{"→" if c["direction"] == "out" else "←"} {e_(c["to_name"] or "")}</td>'
                    f'<td>{e_(c["channel"] or "")}</td><td>{e_(c["subject"])}</td><td class="small">{e_(eng.kb.wording.delivery(c["status"]))}</td></tr>'
                    for c in h["comms"] if not (role == "customer" and c["channel"] == "file"))
    proof = h["proof"]
    proof_html = ""
    if proof:
        img = ""
        ev = proof.get("evidence")
        if ev and ev["stored_as"].endswith((".png", ".jpg", ".jpeg", ".webp")):
            img = f'<img class="photo" alt="Evidence photo" src="/file?path={urllib.parse.quote(str(eng.evidence_dir / ev["stored_as"]))}">'
        fields = " · ".join(f"{k}: {v}" for k, v in eng.kb.wording.visible_fields(proof))
        proof_html = f'<section><h2>Proof on file</h2><div class="card"><b>{e_(eng.kb.requirements.get(proof["type"], {}).get("name", "Document"))}</b><span class="small">{e_(fields)}</span>{img}</div></section>'
    corrective = ""
    if i["requirement"] == "corrective_action":
        corrective = (f'<div class="card"><span>Owner: <b>{e_(eng.customer.holder_name(data.get("owner")))}</b> · Due <b>{e_(nice_date(data["due"]) if data.get("due") else "")}</b></span>'
                      f'<span>Evidence needed: {e_(data.get("evidence_required", ""))}</span>'
                      f'<form class="form" method="post" action="/c/{cid}/evidence"><input type="hidden" name="issue" value="{i["id"]}">'
                      f'<label>Evidence (what was done)<input name="note" required placeholder="e.g. guard rail refitted by site foreman"></label>'
                      f'<label>&nbsp;<button>Send evidence</button></label></form></div>')
    return f"""<section><a href="/c/{cid}/issues">‹ All issues</a><div class="actions">{pill(i['severity'])}<span class="mono">{i['id']}</span>
<span class="chip {'ok' if i['status'] == 'resolved' else 'warn'}">{e_(eng.kb.wording.issue_status(i['status']))}</span></div>
<h1>{e_(title_of(eng, i))}</h1><p class="muted">{e_(eng.customer.holder_name(i['holder']))} · {e_(eng.kb.requirements[i['requirement']]['name'])} · {e_(where_it_stands(eng, i))}</p>{corrective}</section>
<section><h2>What's been done</h2><ol class="timeline">{''.join(steps)}</ol></section>{proof_html}
<section><h2>Messages</h2><div class="tbl"><table><thead><tr><th>When</th><th>Who</th><th>Channel</th><th>Subject</th><th>Delivery</th></tr></thead><tbody>{comms}</tbody></table></div></section>
<p class="small muted">{len(h['audit'])} audit entries recorded for this issue.</p>"""


def view_register(eng, cid, kind, title, intro):
    reg = [r for r in compliance_register(eng) if r["holder_kind"] == kind]
    groups = {}
    for r in reg:
        groups.setdefault(r["holder"], []).append(r)
    cards = []
    for holder, rows in groups.items():
        bad = [r for r in rows if r["status"] != "ok"]
        blocking = any(r["blocks_site_access"] and r["status"] in ("missing", "expired", "out_of_use") for r in rows)
        out = next((r for r in rows if r["status"] == "out_of_use"), None)
        verdict = '<span class="chip ok">All in order</span>' if not bad else (
            '<span class="chip bad">Out of use</span>' if out else
            '<span class="chip bad">Not cleared for site</span>' if blocking else '<span class="chip warn">Attention needed</span>')
        extra = ""
        if kind == "worker":
            w = eng.customer.workers[holder]
            extra = f'{e_(w.get("role", ""))} · {e_(LANGUAGE_NAMES.get(w.get("language", "en"), ""))}'
        elif kind == "subcontractor":
            s = eng.customer.subcontractors[holder]
            extra = f'{e_(", ".join(t.replace("_", " ") for t in s.get("trades", [])))} · {e_(s.get("contact", {}).get("name", ""))}'
        elif kind == "asset":
            a = eng.customer.assets[holder]
            extra = f'{e_(a.get("type", "").replace("_", " "))}{" · serial " + e_(a["serial"]) if a.get("serial") else ""}'
        lines = "".join(f'<tr><td>{e_(r["name"])}</td><td>{status_chip(r["status"])}</td><td class="mono">{e_(nice_date(r["expires"]) if r["expires"] else "")}</td></tr>' for r in rows)
        cards.append(f'<div class="card"><div class="actions" style="justify-content:space-between"><h3>{e_(eng.customer.holder_name(holder))}</h3>{verdict}</div>'
                     f'<span class="small muted">{extra}</span><div class="tbl"><table><tbody>{lines}</tbody></table></div>'
                     f'<a class="small" href="/c/{cid}/issues?status=all&holder={urllib.parse.quote(holder)}">Issues for {e_(eng.customer.holder_name(holder))} ›</a></div>')
    return f'<section><h1>{title}</h1><p class="muted">{intro}</p><div class="grid">{"".join(cards) or "<p class=muted>Nothing on file yet.</p>"}</div></section>'


def holder_options(eng, include_company=True):
    opts = [("company", eng.customer.company["name"])] if include_company else []
    opts += [(k, v["name"]) for k, v in eng.customer.workers.items()]
    opts += [(k, v["name"]) for k, v in eng.customer.subcontractors.items()]
    opts += [(k, v["name"]) for k, v in eng.customer.assets.items()]
    return "".join(f'<option value="{e_(k)}">{e_(n)}</option>' for k, n in opts)


def sample_photos(cid):
    folder = {"bremore_groundworks_sample": ROOT / "data" / "sample" / "bremore_groundworks" / "incoming" / "photos"}.get(cid)
    photos = []
    if folder and folder.exists():
        for p in sorted(folder.glob("*.png")):
            holder = {"safe_pass_andriy_kovalenko.png": "w16", "cscs_slinger_marcin_zielinski.png": "w08"}.get(p.name)
            photos.append((p, holder, p.stem.replace("_", " ").title()))
    if cid == "liffey_interiors":
        photos.append((ROOT / "tests" / "fixtures" / "photos" / "safe_pass_clear.png", "w06", "Safe Pass - Lucas Pereira"))
    photos.append((ROOT / "tests" / "fixtures" / "photos" / "safe_pass_blurry.png",
                   "w16" if cid == "bremore_groundworks_sample" else "w06", "Blurry photo (should go to a person)"))
    return photos


def doc_reference(doc):
    for key in ("number", "policy_number", "tcan", "scheme", "inspector", "provider"):
        if doc.get(key):
            return str(doc[key])
    return "On file"


def view_documents(portal, eng, cid, role):
    samples = "".join(
        f'<form class="card" method="post" action="/c/{cid}/upload"><img class="photo" alt="{e_(label)}" src="/file?path={urllib.parse.quote(str(p))}">'
        f'<input type="hidden" name="sample" value="{e_(str(p))}"><input type="hidden" name="holder" value="{e_(h)}">'
        f'<span class="small">{e_(label)} · from {e_(eng.customer.holder_name(h))}</span><button>Send this photo</button></form>'
        for p, h, label in sample_photos(cid))
    doc_type_options = "".join(f'<option value="{t}">{e_(eng.kb.requirements[t]["name"])}</option>' for t in
                               CARD_TYPES + ("public_liability", "employers_liability", "professional_indemnity"))
    groups = eng.document_history()
    rows = []
    for g in groups[:400]:
        cur = next((d for d in g["versions"] if d["id"] == g["current"]), g["versions"][0])
        rows.append(f'<tr><td>{e_(eng.customer.holder_name(g["holder"]))}</td><td>{e_(eng.kb.requirements.get(g["type"], {}).get("name", g["type"]))}</td>'
                    f'<td class="mono">{e_(doc_reference(cur))}</td><td class="mono">{e_(nice_date(cur.get("expires") or cur.get("issued") or ""))}</td>'
                    f'<td>{len(g["versions"])}</td><td>{"📎" if any(d.get("evidence") for d in g["versions"]) else ""}</td></tr>')
    return f"""<section><h1>Documents</h1><p class="muted">Send a photo of a card or certificate. Claude reads it; anything it isn't sure about goes to a person, never guessed.</p>
<form class="card form" method="post" action="/c/{cid}/upload" enctype="multipart/form-data">
<label>Photo or scan<input type="file" name="file" accept="image/*,.pdf" required></label>
<label>Whose is it?<select name="holder">{holder_options(eng)}</select></label>
<label>What is it? (optional)<select name="type"><option value="">Let OpsEngine work it out</option>
{doc_type_options}</select></label>
<label>&nbsp;<button>Upload</button></label></form>
<h2>Or try a sample photo</h2><div class="grid">{samples}</div></section>
<section><h2>On file</h2><div class="tbl"><table><thead><tr><th>Who</th><th>Document</th><th>Reference</th><th>Expires / issued</th><th>Versions</th><th>File</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table></div></section>"""


def view_actions(portal, eng, cid, role):
    rows = eng.corrective_actions(None)
    rows.sort(key=lambda a: (a["status"] == "resolved", {"critical": 0, "high": 1}.get(a["severity"], 2), a.get("due", "")))
    def due(a):
        late = a["status"] != "resolved" and a.get("due", "9") < portal.today.isoformat()
        return f'<span class="small muted">due {e_(nice_date(a["due"]) if a.get("due") else "")}</span>' + (' <span class="chip bad">Overdue</span>' if late else "")
    items = "".join(issue_row(eng, cid, a, due(a)) for a in rows)
    owners = '<option value="company">' + e_(eng.customer.company["owner"]["name"]) + " (owner)</option>" + \
        "".join(f'<option value="{k}">{e_(v["name"])}</option>' for k, v in eng.customer.workers.items()) + \
        "".join(f'<option value="{k}">{e_(v["name"])}</option>' for k, v in eng.customer.subcontractors.items())
    sites = '<option value="">Company-wide</option>' + "".join(f'<option value="{k}">{e_(v["name"])}</option>' for k, v in eng.customer.sites.items())
    return f"""<section><h1>Corrective actions</h1><p class="muted">Anything that needs fixing, with an owner, a deadline and the evidence needed to close it. Inspection defects appear here automatically.</p>
<form class="card form" method="post" action="/c/{cid}/raise">
<label>What needs fixing<input name="title" required placeholder="e.g. Edge protection missing at stair core"></label>
<label>Owner<select name="owner">{owners}</select></label>
<label>Site<select name="site">{sites}</select></label>
<label>Severity<select name="severity"><option value="medium">Medium</option><option value="high">High</option><option value="critical">Critical (can stop work)</option></select></label>
<label>Due date<input type="date" name="due" value="{(portal.today + timedelta(days=7)).isoformat()}"></label>
<label>Evidence needed<input name="evidence" value="photo of the completed work"></label>
<label>&nbsp;<button>Raise action</button></label></form>
<div class="list">{items or '<p class="muted">No corrective actions.</p>'}</div></section>"""


def view_bookings(portal, eng, cid, role):
    rows = []
    for a in eng.store.appointments():
        btns = ""
        if role == "ops" and a["status"] in ("requested", "confirmed"):
            btns = "".join(f'<form class="inline" method="post" action="/c/{cid}/appointment"><input type="hidden" name="id" value="{a["id"]}">'
                           f'<input type="hidden" name="status" value="{s}"><button class="{"warn" if s == "no_show" else "ghost"}">{l}</button></form>'
                           for s, l in (("confirmed", "Confirmed"), ("attended", "Attended"), ("no_show", "No-show")))
        rows.append(f'<div class="row"><a href="/c/{cid}/issue/{a["issue_id"]}"><h3>{e_(eng.kb.wording.booking_kind(a["kind"]))}: {e_(eng.customer.holder_name(a["holder"]))}</h3>'
                    f'<div class="meta">{e_(a["provider_name"])} · on or after {e_(nice_date(a["date"]))} · {e_(money(a["price_eur"]))} · <span class="mono">{a["id"]}</span></div></a>'
                    f'<div class="actions"><span class="chip {"ok" if a["status"] in ("attended", "completed") else "bad" if a["status"] in ("no_show", "cancelled") else "warn"}">{e_(eng.kb.wording.booking_status(a["status"]))}</span>{btns}</div></div>')
    hint = "" if rows else '<p class="muted">No bookings yet. Approve a training course or inspection on the Overview page and it appears here.</p>'
    return f'<section><h1>Bookings</h1><p class="muted">Training courses, inspections and services booked after approval. Our team records attendance; a no-show goes back to you to rebook.</p><div class="list">{"".join(rows)}</div>{hint}</section>'


def view_messages(portal, eng, cid, role):
    rows = []
    for c in reversed(eng.store.comms()):
        if role == "customer" and c["channel"] == "file":
            continue  # internal notes for our team are not shown to customers
        subject = e_(c["subject"])
        if c["outbox"]:
            subject = f'<a href="/c/{cid}/message?path={urllib.parse.quote(c["outbox"])}">{subject}</a>'
        arrow = "→" if c["direction"] == "out" else "←"
        rows.append(f'<tr><td class="mono">{e_(c["ts"][:16])}</td><td>{arrow}</td><td>{e_(c["to_name"] or "")}</td>'
                    f'<td>{e_(c["channel"] or "")}</td><td>{subject}</td><td class="small">{e_(eng.kb.wording.delivery(c["status"]))}</td></tr>')
    return (f'<section><h1>Messages</h1><p class="muted">Every message OpsEngine wrote or received for {e_(eng.customer.company["name"])}. '
            'Nothing is actually sent in this demo: messages wait in the outbox.</p>'
            f'<div class="tbl"><table><thead><tr><th>When</th><th></th><th>Who</th><th>Channel</th><th>Subject</th><th>Delivery</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div></section>')


def view_message(portal, eng, cid, role, path):
    p = portal.safe_file(path)
    if not p:
        return '<p class="flash err">Message not found.</p>'
    subject, meta, body = parse_outbox(p.read_text(encoding="utf-8"))
    to = meta.get("To", "")
    who, _, how = to.partition(" via ")
    channel = how.split(" (")[0]
    extra = "".join(f'<p class="note">{e_(meta[k])}</p>' for k in ("Translation",) if meta.get(k))
    return (f'<section><a href="/c/{cid}/messages">‹ Messages</a><div class="card msg"><h2>{e_(subject)}</h2>'
            f'<p class="muted small">To {e_(who)}{" by " + e_(channel) if channel and channel != "file" else ""}</p>{extra}'
            f'{md_to_html(body)}</div></section>')


def parse_outbox(text):
    """Outbox file -> (subject, header fields, body). Header lines are internal and never shown as-is."""
    head, _, body = text.partition("\n\n")
    subject = head.lstrip("# ").strip()
    rest = body.split("\n\n", 1)
    meta = {}
    if rest and rest[0].startswith("- "):
        for line in rest[0].splitlines():
            k, _, v = line[2:].partition(": ")
            meta[k] = v
        body = rest[1] if len(rest) > 1 else ""
    return subject, meta, body


def view_report(portal, eng, cid, role):
    return f'<section><div class="card msg">{md_to_html(weekly_summary(eng))}</div></section>'


CARD_TYPES = ("safe_pass", "cscs_excavator", "cscs_dumper", "cscs_slinger_signaller", "cscs_scaffolding")


def type_options(eng, chosen=None):
    return "".join(f'<option value="{t}"{" selected" if t == chosen else ""}>{e_(eng.kb.requirements[t]["name"])}</option>'
                   for t in CARD_TYPES)


def view_console(portal, eng, cid, role, q=None):
    """Every queue across every customer, most urgent first. Links go to the customer's own pages."""
    from . import console
    q = q or {}
    engines = {c: portal.engine(c) for c in portal.customers}
    rows = console.items(engines, role)
    pick_q, pick_c = q.get("queue", [""])[0], q.get("customer", [""])[0]
    counts = console.counts(rows)
    shown = [r for r in rows if (not pick_q or r["queue"] == pick_q) and (not pick_c or r["customer_id"] == pick_c)]
    chips = " · ".join(f'<a href="/c/{cid}/console?queue={k}">{"<b>" if k == pick_q else ""}{e_(label)} ({counts[k]}){"</b>" if k == pick_q else ""}</a>'
                       for k, label in console.QUEUES.items() if counts[k] or k == pick_q)
    cust = " · ".join(f'<a href="/c/{cid}/console?customer={c}{"&queue=" + pick_q if pick_q else ""}">{e_(e.customer.company["name"])}</a>'
                      for c, e in engines.items())
    body = "".join(
        f'<tr><td>{pill(r["severity"])}</td><td>{e_(console.QUEUES[r["queue"]])}</td><td>{e_(r["customer"])}</td>'
        f'<td><a href="{e_(r["link"])}">{e_(r["title"])}</a>{"<div class=small>" + e_(r["detail"]) + "</div>" if r["detail"] else ""}</td>'
        f'<td class="mono">{r["age_days"]}d</td></tr>' for r in shown[:300])
    return f"""<section><h1>All customers</h1>
<p class="note">Every queue across every customer, most urgent first. Act on each item from the customer's own page.</p>
<div class="kpis"><div class="kpi"><b>{len(rows)}</b><span>items in all queues</span></div>
<div class="kpi"><b>{counts["stops_work"]}</b><span>could stop work</span></div>
<div class="kpi"><b>{counts["safety_reviews"]}</b><span>safety reviews waiting</span></div>
<div class="kpi"><b>{counts["photo_checks"]}</b><span>documents to check</span></div></div>
<p>{chips or "Nothing waiting."} {'· <a href="/c/' + cid + '/console">Show all</a>' if pick_q or pick_c else ''}</p><p class="small">Customer: {cust}</p>
<div class="tbl"><table><thead><tr><th>Priority</th><th>Queue</th><th>Customer</th><th>Item</th><th>Waiting</th></tr></thead>
<tbody>{body or '<tr><td colspan="5" class="muted">Nothing here.</td></tr>'}</tbody></table></div>
{'<p class="small muted">Showing the first 300.</p>' if len(shown) > 300 else ''}</section>"""


def view_ops(portal, eng, cid, role):
    parts = []
    for c in portal.customers:
        e = portal.engine(c)
        name = e.customer.company["name"]
        reviews = e.review_queue()
        esc = e.store.issues("escalated")
        blocked = [s for s in e.store.steps(state="blocked")]
        waiting_customer = [s for s in e.store.steps(state="awaiting_approval") if s["approval_role"] == "customer"]
        rv = []
        for r in reviews:
            ex = r["extraction"] or {}
            vals = ex.get("values") or {}
            img = f'<img class="photo" alt="Photo sent in" src="/file?path={urllib.parse.quote(r["file"])}">' if portal.safe_file(r["file"]) else ""
            rv.append(f'<div class="card"><div class="actions"><b class="mono">{r["id"]}</b><span>from {e_(e.customer.holder_name(r["holder"]))}</span>'
                      f'<span class="chip warn">{int(r["confidence"] * 100)}% confidence</span></div>{img}'
                      f'<ul class="small">{"".join(f"<li>{e_(x)}</li>" for x in r["reasons"])}</ul>'
                      f'<form class="form" method="post" action="/c/{c}/review"><input type="hidden" name="id" value="{r["id"]}">'
                      f'<label>Document type<select name="type">{type_options(e, ex.get("document_type"))}</select></label>'
                      f'<label>Card number<input name="number" value="{e_(str(vals.get("number", "")))}"></label>'
                      f'<label>Expiry<input type="date" name="expires" value="{e_(str(vals.get("expires", "")))}"></label>'
                      f'<label>&nbsp;<span class="actions"><button name="decision" value="accept">Accept</button>'
                      f'<button class="ghost" name="decision" value="reject">Reject</button></span></label></form></div>')
        parts.append(f"""<section><h2>{e_(name)}</h2>
<div class="kpis"><div class="kpi"><b>{metrics(e)['automation_rate']}%</b><span>of actions done without a person</span></div><div class="kpi"><b>{len(reviews)}</b><span>photos to check</span></div><div class="kpi"><b>{len(esc)}</b><span>escalated issues</span></div>
<div class="kpi"><b>{len(blocked)}</b><span>blocked steps</span></div><div class="kpi"><b>{len(waiting_customer)}</b><span>waiting on the customer</span></div></div>
{''.join(rv)}<div class="list">{''.join(issue_row(e, c, i) for i in esc[:10])}</div></section>""")
    sim = []
    for p in (sorted((portal.customers[cid] / "incoming").glob("*.json")) if portal.demo else []):
        doc = json.loads(p.read_text(encoding="utf-8"))
        sim.append(f'<form class="row" method="post" action="/c/{cid}/simulate"><div><h3>{e_(eng.kb.requirements.get(doc["type"], {}).get("name", doc["type"]))}</h3>'
                   f'<div class="meta">from {e_(eng.customer.holder_name(doc["holder"]))} · {e_(doc.get("received_via", ""))} · <span class="mono">{e_(p.name)}</span></div></div>'
                   f'<input type="hidden" name="file" value="{e_(p.name)}"><button class="ghost">Simulate arrival</button></form>')
    return f"""<section><h1>Ops queue</h1><p class="muted">The internal team's view across every customer: photos the AI wasn't sure about, escalations, and anything blocked.</p></section>
{''.join(parts)}<section {'' if portal.demo else 'hidden'}><h2>Simulate incoming documents ({e_(eng.customer.company['name'])})</h2><p class="note">For the demo: pretend these arrived by email or WhatsApp.</p><div class="list">{''.join(sim) or '<p class=muted>Nothing to simulate for this customer.</p>'}</div></section>"""


def view_reviewer(portal, eng, cid, role):
    items = []
    for c in portal.customers:
        e = portal.engine(c)
        for s in e.store.steps(state="awaiting_approval"):
            if s["approval_role"] != "safety_reviewer":
                continue
            prior = {p["action"]: p["result"] for p in e.store.steps(s["issue_id"]) if p["state"] in DONE and p["result"]}
            draft = (prior.get("draft_document") or {}).get("draft")
            link = f'<a href="/c/{c}/message?path={urllib.parse.quote(draft)}">Read the draft</a>' if draft else f'<a href="/c/{c}/issue/{s["issue_id"]}">See the evidence</a>'
            note, buttons = "", approve_buttons(c, s, role, "Release / sign off")
            if s["action"] == limits.ROUTINE_REVIEW_ACTION:
                if not limits.next_review_counts(e, s["id"]):
                    note = '<span class="chip ok">Amended resubmission: included in the original review</span>'
                try:
                    limits.check_review_allowed(e, s)
                except limits.LimitReached as exc:
                    note, buttons = f'<span class="chip warn">{e_(str(exc))}</span>', ""
            items.append(f'<div class="row"><div><h3>{e_(e.approval_summary(s, prior))}</h3><div class="meta">{e_(e.customer.company["name"])} · {link}</div>{note}</div>'
                         f'<div class="actions">{buttons}</div></div>')
    appointed = service().get("safety_reviewer", {}).get("appointed")
    warn = "" if appointed else ('<div class="flash err">No named, qualified safety reviewer is appointed yet (data/service.json). '
                                 'Safety reviews are not operational: nothing here may be released to a real customer.</div>')
    return (f'<section>{warn}<h1>For the safety reviewer</h1><p class="muted">Drafted Safety Statements and RAMS, and high-risk corrective actions, '
            f'wait here for a competent person. OpsEngine never releases or signs these off itself.</p>'
            f'<div class="list">{"".join(items) or "<p class=muted>Nothing waiting for review.</p>"}</div></section>')


def view_providers(portal, eng, cid, role):
    stats = eng.store.provider_stats()
    rows = []
    for p in eng.kb.providers:
        probs = provider_problems(p, portal.today)
        st = stats.get(p["id"])
        cred = '<span class="chip ok">Usable</span>' if not probs else f'<span class="chip bad">{e_(", ".join(probs))}</span>'
        record = f'{st["completed"]}/{st["booked"]} completed' if st else "new"
        rows.append(f'<tr><td>{e_(p["name"])}</td><td>{e_(p["category"].replace("_", " "))}</td><td>{money(p["price_eur"])}</td>'
                    f'<td>{cred}</td><td class="small">{e_(", ".join(p.get("service_areas", [])))}</td><td class="small">{record}</td></tr>')
    return ('<section><h1>Provider network</h1><p class="muted">Only vetted providers with in-date insurance and qualifications who cover the area are ever recommended. All SAMPLE.</p>'
            f'<div class="tbl"><table><thead><tr><th>Provider</th><th>Service</th><th>Price</th><th>Credentials</th><th>Areas</th><th>Record</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div></section>')


def plans_card(portal):
    """For our team: each customer's plan, monthly revenue, and plans that no longer fit."""
    from . import pricing
    prices = pricing.load()
    rows, total, notes = [], 0, []
    for c in portal.customers:
        e = portal.engine(c)
        mine = pricing.customer_plan(e.customer, prices, limits.extras(e))
        name = mine["plan"]["name"] if mine["plan"] else "No plan"
        amount = mine["monthly_total_eur"]
        total += amount or 0
        rows.append(f'<li>{e_(e.customer.company["name"])}: {e_(name)}, {money(amount) if amount is not None else "custom"} a month '
                    f'({pricing.active_workers(e.customer)} workers)</li>')
        notes += [f'{e.customer.company["name"]}: {n}' for n in pricing.fit_problems(e, prices)]
    fit = "".join(f"<li>{e_(n)}</li>" for n in notes) or "<li>Every customer's plan fits.</li>"
    return (f'<div class="card"><h3>Plans and revenue (excluding VAT)</h3><ul>{"".join(rows)}</ul>'
            f'<p>Monthly recurring revenue: <b>{money(total)}</b> · a year: <b>{money(total * 12)}</b></p>'
            f'<h3>Plan fit</h3><ul>{fit}</ul></div>')


def view_insights(portal, eng, cid, role):
    from .insights import insights
    r = insights([portal.engine(c) for c in portal.customers])
    li = lambda pairs: "".join(f"<li>{e_(str(n))} <b>({c})</b></li>" for n, c in pairs) or "<li class=muted>Nothing yet</li>"
    return f"""<section><h1>Insights across customers</h1><div class="grid">
<div class="card"><h3>Most common problems</h3><ul>{li(r['most_common_problems'])}</ul></div>
<div class="card"><h3>Often missing</h3><ul>{li(r['frequently_missing'])}</ul></div>
<div class="card"><h3>Hotspots</h3><ul>{li(r['hotspots'])}</ul></div>
<div class="card"><h3>Recurring</h3><ul>{li(r['recurring'])}</ul></div></div>
{plans_card(portal)}<div class="card"><h3>Recommendations</h3><ul>{''.join(f'<li>{e_(x)}</li>' for x in r['recommendations'])}</ul><p class="note">Suggestions for a person to accept. OpsEngine doesn't change its own rules.</p></div></section>"""


# ---------------- HTTP ----------------

COOKIE = "opsengine_session"
CUSTOMER_ACTS = {"approve", "reject", "approve-group", "upload", "raise", "evidence", "standing-approval"}
STAFF_ACTS = {"approve", "reject", "approve-group", "upload", "raise", "evidence", "review", "appointment", "simulate", "resubmit"}


class Handler(BaseHTTPRequestHandler):
    portal: Portal = None

    def log_message(self, fmt, *args):  # keep the console quiet
        pass

    # ---- sessions ----
    def token(self):
        for part in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == COOKIE:
                return v
        return None

    def session(self, stages=("active",)):
        return self.portal.accounts.session(self.token(), stages=stages)

    def cookie(self, token, clear=False):
        https = (config.flag("OPSENGINE_TRUST_PROXY") and self.headers.get("X-Forwarded-Proto", "").lower() == "https") \
            or config.flag("OPSENGINE_SECURE_COOKIES")
        attrs = "Path=/; HttpOnly; " + ("SameSite=None; Secure" if https else "SameSite=Lax")
        return f"{COOKIE}={'' if clear else token}; {attrs}" + ("; Max-Age=0" if clear else f"; Max-Age={auth.SESSION_HOURS * 3600}")

    def ip(self):
        if config.flag("OPSENGINE_TRUST_PROXY") and self.headers.get("X-Forwarded-For"):
            return self.headers["X-Forwarded-For"].split(",")[0].strip()
        return self.client_address[0] or ""

    # ---- responses ----
    def security_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("Cache-Control", "no-store")
        frame = "" if self.portal.demo else "frame-ancestors 'none'; "  # the demo may be shown in a preview pane
        if not self.portal.demo:
            self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
                         f"font-src https://fonts.gstatic.com; img-src 'self' data:; form-action 'self'; {frame}base-uri 'none'")

    def send_html(self, body, status=200, cookie=None):
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.security_headers()
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(data)

    def redirect(self, to, flash=None, cookie=None):
        if not to.startswith("/") or to.startswith("//"):
            to = "/"  # never redirect off-site
        if flash:
            to += ("&" if "?" in to else "?") + "flash=" + urllib.parse.quote(flash)
        self.send_response(303)
        self.send_header("Location", to)
        self.security_headers()
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()

    def home_for(self, user, cid=None):
        cid = user["customer_id"] if user["role"] == "customer" else (cid or next(iter(self.portal.customers), None))
        if not cid or cid not in self.portal.customers:
            return None
        return f"/c/{cid}/" + {"customer": "home", "ops": "ops", "admin": "ops", "reviewer": "reviewer"}[user["role"]]

    def allowed_customer(self, user, cid):
        return cid in self.portal.customers and (user["role"] != "customer" or user["customer_id"] == cid)

    def send_text(self, text, status=200):
        data = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.security_headers()
        self.end_headers()
        self.wfile.write(data)

    def link_engine(self, secret):
        if not re.fullmatch(r"[0-9a-f]{64}", secret or ""):
            return None, None
        for cid in self.portal.customers:
            eng = self.portal.engine(cid)
            if approval_links.owns(eng, secret):
                return eng, secret
        return None, None

    def webhook(self, parts):
        """Machine-to-machine: delivery reports and inbound WhatsApp. Signed, never signed in."""
        raw = self.rfile.read(min(int(self.headers.get("Content-Length") or 0), 1024 * 1024))
        p = self.portal
        if parts == ["hooks", "email"]:
            secret = os.environ.get("OPSENGINE_WEBHOOK_SECRET", "")
            sig = self.headers.get("X-OpsEngine-Signature", "")
            if len(secret) < 32 or not hmac.compare_digest(hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest(), sig):
                return self.send_text("bad signature", 403)
            try:
                events = json.loads(raw)
            except json.JSONDecodeError:
                return self.send_text("bad body", 400)
            matched = 0
            for ev in events if isinstance(events, list) else [events]:
                for cid in p.customers:
                    if delivery.report(p.engine(cid).store, str(ev.get("message_id", "")), str(ev.get("event", "")), str(ev.get("detail", ""))[:200]):
                        matched += 1
                        break
            return self.send_text(f"ok {matched}")
        if parts == ["hooks", "whatsapp"]:
            if not whatsapp.verify_signature(raw, self.headers.get("X-Hub-Signature-256", "")):
                return self.send_text("bad signature", 403)
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                return self.send_text("bad body", 400)
            inbound.handle_whatsapp(p.customers, p.state, payload, today=p.today)
            return self.send_text("ok")
        return self.send_text("not found", 404)

    # ---- GET ----
    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(url.query)
        parts = [p for p in url.path.split("/") if p]
        p = self.portal
        try:
            if parts == ["login"]:
                return self.send_html(view_login(p, notice=q.get("flash", [None])[0]))
            if parts == ["login", "code"]:
                pending = self.session(stages=("mfa", "mfa_setup"))
                if not pending:
                    return self.redirect("/login")
                setup = auth.new_totp_secret() if pending["stage"] == "mfa_setup" else None
                return self.send_html(view_code(p, setup, pending["user"]["email"]))
            if parts == ["healthz"]:  # for the host's monitoring: no data, no sign-in
                return self.send_html("ok")
            if len(parts) == 2 and parts[0] == "a":  # approve by link: the link itself is the credential
                eng, secret = self.link_engine(parts[1])
                if not eng:
                    return self.send_html(view_link(p, "", error="This link isn't valid. Use the portal, or ask the ops team for a new link."), 404)
                try:
                    link, step = approval_links.check(eng, secret)
                except ValueError as exc:
                    return self.send_html(view_link(p, "", error=str(exc)), 410)
                prior = {x["action"]: x["result"] for x in eng.store.steps(step["issue_id"]) if x["state"] in DONE and x["result"]}
                return self.send_html(view_link(p, secret, eng.approval_summary(step, prior), link["approver"]))
            if parts == ["hooks", "whatsapp"]:  # Meta's subscription check
                ok = q.get("hub.mode", [""])[0] == "subscribe" and os.environ.get("WHATSAPP_VERIFY_TOKEN") and \
                    hmac.compare_digest(q.get("hub.verify_token", [""])[0], os.environ.get("WHATSAPP_VERIFY_TOKEN", ""))
                return self.send_text(q.get("hub.challenge", [""])[0] if ok else "forbidden", 200 if ok else 403)
            s = self.session()
            if not s:
                return self.redirect("/login")
            user = s["user"]
            if parts == ["account", "password"]:
                return self.send_html(view_password(p, s["csrf"], forced=bool(user["must_change"]), user=user))
            if user["must_change"]:
                return self.redirect("/account/password")
            if parts == ["admin", "plans"]:
                if user["role"] != "admin":
                    return self.redirect(self.home_for(user) or "/", "!Only admins can change plans and limits.")
                return self.send_html(view_plans(p, s["csrf"], q.get("flash", [None])[0]))
            if parts == ["admin", "users"]:
                if user["role"] != "admin":
                    return self.redirect(self.home_for(user) or "/", "!Only admins can manage users.")
                return self.send_html(view_users(p, user, s["csrf"], q.get("flash", [None])[0]))
            if not parts:
                home = self.home_for(user)
                return self.redirect(home) if home else self.send_html(bare_page("No access", "<p>Your account isn't linked to a customer on this portal. Contact the ops team.</p>", p), 403)
            if parts == ["switch"]:
                to, tab = q.get("to", [""])[0], q.get("tab", ["home"])[0]
                if not self.allowed_customer(user, to) or not re.fullmatch(r"[a-z]+", tab):
                    return self.redirect("/")
                return self.redirect(f"/c/{to}/{tab}")
            if parts[0] == "file":
                f = p.safe_file(q.get("path", [""])[0], user)
                if not f:
                    return self.send_html("Not found", 404)
                data = f.read_bytes()
                ctype = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".pdf": "application/pdf"}.get(f.suffix.lower(), "text/plain; charset=utf-8")
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.security_headers()
                self.end_headers()
                return self.wfile.write(data)
            if parts[0] != "c" or len(parts) < 3:
                return self.send_html("Not found", 404)
            cid, tab = parts[1], parts[2]
            role = VIEW_ROLE[user["role"]]
            if not self.allowed_customer(user, cid):
                return self.redirect(self.home_for(user) or "/login", "!You don't have access to that company.")
            if tab not in TABS[role]:
                return self.redirect(self.home_for(user, cid) or "/", "!That page isn't available to you.")
            eng = p.engine(cid)
            views = {"home": view_home, "documents": view_documents, "actions": view_actions, "bookings": view_bookings,
                     "messages": view_messages, "report": view_report, "ops": view_ops, "reviewer": view_reviewer,
                     "providers": view_providers, "insights": view_insights, "how": view_how, "settings": view_settings}
            if tab in views:
                body = views[tab](p, eng, cid, role)
            elif tab == "console":
                body = view_console(p, eng, cid, role, q)
            elif tab == "issues":
                body = view_issues(p, eng, cid, role, q)
            elif tab == "issue" and len(parts) == 4:
                if not eng.store.issue(parts[3]):
                    body = f'<p class="flash err">No issue {e_(parts[3])} for this customer.</p><a href="/c/{cid}/issues">See all issues ›</a>'
                else:
                    body = view_issue(p, eng, cid, role, parts[3])
            elif tab == "message":
                path = q.get("path", [""])[0]
                body = view_message(p, eng, cid, role, path) if p.safe_file(path, user) else '<p class="flash err">Message not found.</p>'
            elif tab in ("people", "subcontractors", "equipment"):
                kind, title, intro = {
                    "people": ("worker", "People", "Each worker's cards, training and inductions."),
                    "subcontractors": ("subcontractor", "Subcontractors", "Your subcontractors' insurance, tax clearance, Safety Statement and operatives' cards."),
                    "equipment": ("asset", "Plant and equipment", "Inspections, examinations and servicing for your plant, equipment and site facilities.")}[tab]
                body = view_register(eng, cid, kind, title, intro)
            else:
                return self.send_html("Not found", 404)
            self.send_html(page(p, user, cid, "issues" if tab == "issue" else tab, tab.title(), body,
                                q.get("flash", [None])[0], csrf=s["csrf"]))
        except Exception as exc:  # show the problem instead of a blank page
            self.send_html(f"<pre>Something went wrong: {e_(type(exc).__name__)}</pre>", 500)

    def form(self):
        length = min(int(self.headers.get("Content-Length") or 0), 20 * 1024 * 1024)  # 20 MB upload cap
        raw = self.rfile.read(length)
        ctype = self.headers.get("Content-Type", "")
        if ctype.startswith("multipart/form-data"):
            msg = email.parser.BytesParser(policy=email.policy.HTTP).parsebytes(
                b"Content-Type: " + ctype.encode() + b"\r\n\r\n" + raw)
            fields, files = {}, {}
            for part in msg.iter_parts():
                name = part.get_param("name", header="content-disposition")
                if part.get_filename():
                    files[name] = (part.get_filename(), part.get_payload(decode=True))
                else:
                    fields[name] = part.get_payload(decode=True).decode("utf-8", "replace")
            return fields, files
        return {k: v[0] for k, v in urllib.parse.parse_qs(raw.decode("utf-8")).items()}, {}

    # ---- POST ----
    def do_POST(self):
        url = urllib.parse.urlparse(self.path)
        parts = [p for p in url.path.split("/") if p]
        p = self.portal
        if parts[:1] == ["hooks"]:
            return self.webhook(parts)
        f, files = self.form()
        if len(parts) == 2 and parts[0] == "a":
            eng, secret = self.link_engine(parts[1])
            if not eng:
                return self.send_html(view_link(p, "", error="This link isn't valid. Use the portal, or ask the ops team for a new link."), 404)
            try:
                approval_links.use(eng, secret, f.get("decision", ""), f.get("reason", "").strip(), ip=self.ip())
            except ValueError as exc:
                return self.send_html(view_link(p, "", error=str(exc)), 410)
            return self.send_html(view_link(p, "", done="Thank you. Your decision has been recorded."
                                            if f.get("decision") == "approved" else "Declined. The ops team will be in touch."))
        try:
            if parts == ["login"]:
                try:
                    token, stage = p.accounts.sign_in(f.get("email", ""), f.get("password", ""), ip=self.ip())
                except auth.AuthError as exc:
                    return self.send_html(view_login(p, str(exc), f.get("email", "")), 401)
                return self.redirect("/" if stage == "active" else "/login/code", cookie=self.cookie(token))
            if parts == ["login", "code"]:
                try:
                    token = p.accounts.verify_code(self.token(), f.get("code", ""), ip=self.ip(), new_secret=f.get("secret") or None)
                except auth.AuthError as exc:
                    pending = self.session(stages=("mfa", "mfa_setup"))
                    if not pending:
                        return self.redirect("/login")
                    return self.send_html(view_code(p, f.get("secret") or None, pending["user"]["email"], str(exc)), 401)
                return self.redirect("/", cookie=self.cookie(token))
            s = self.session()
            if not s:
                return self.redirect("/login")
            if not hmac.compare_digest(f.get("csrf", ""), s["csrf"]):
                p.accounts.audit(f"user:{s['user_id']}", "csrf_rejected", s["user_id"], {"path": url.path, "ip": self.ip()})
                return self.send_html(bare_page("Expired", '<p>This form expired. Go back, reload the page and try again.</p><a href="/">Home</a>', p), 403)
            user = s["user"]
            if parts == ["logout"]:
                p.accounts.sign_out(self.token())
                return self.redirect("/login", cookie=self.cookie("", clear=True))
            if parts == ["account", "codes"]:
                if user["role"] in auth.STAFF:
                    return self.redirect("/account/password")
                p.accounts.turn_on_codes(user["id"])
                return self.redirect("/login", "Sign in again to set up your sign-in code.", cookie=self.cookie("", clear=True))
            if parts == ["account", "password"]:
                if f.get("new", "") != f.get("again", ""):
                    return self.send_html(view_password(p, s["csrf"], bool(user["must_change"]), "The new passwords don't match."), 400)
                try:
                    p.accounts.change_own_password(self.token(), f.get("current", ""), f.get("new", ""))
                except auth.AuthError as exc:
                    return self.send_html(view_password(p, s["csrf"], bool(user["must_change"]), str(exc)), 400)
                return self.redirect(self.home_for(user) or "/", "Password changed. Other sessions were signed out.")
            if user["must_change"]:
                return self.redirect("/account/password")
            if parts[:2] == ["admin", "plans"]:
                if user["role"] != "admin":
                    p.accounts.audit(f"user:{user['id']}", "access_denied", user["id"], {"area": "plans"})
                    return self.redirect(self.home_for(user) or "/", "!Only admins can change plans and limits.")
                by = auth.identity(user)
                try:
                    if len(parts) == 3:
                        limits.set_plan_limits(p.state, parts[2], f, by, p.accounts.audit)
                    elif len(parts) == 4 and parts[2] == "customer" and parts[3] in p.customers:
                        limits.set_overrides(p.engine(parts[3]), f, by)
                        p.accounts.audit(by, "customer_limits_changed", parts[3], {k: v for k, v in f.items() if k != "csrf"})
                    else:
                        return self.redirect("/admin/plans", "!Unknown plan or customer.")
                except ValueError as exc:
                    return self.redirect("/admin/plans", f"!Not saved: {exc}")
                return self.redirect("/admin/plans", "Saved.")
            if parts[:2] == ["admin", "users"]:
                return self.admin_users(user, parts[2:], f, s["csrf"])
            home = self.home_for(user) or "/"
            if parts[:1] == ["demo"]:
                if not p.demo:
                    return self.redirect(home, "!That's only available in the demo.")
                if parts == ["demo", "next-day"]:
                    runs = p.next_day()
                    chased = sum(len(r["chased"]) for r in runs)
                    esc = sum(len(r["escalated"]) for r in runs)
                    nxt = f.get("next", "/")
                    return self.redirect(nxt if nxt.startswith("/c/") else home, f"Daily run for {p.today}: {chased} reminder(s) sent, {esc} escalation(s).")
                if parts == ["demo", "reset"]:
                    p.reset()
                    return self.redirect(home, "Demo reset to 2026-11-11 with fresh sample data.")
            if len(parts) != 3 or parts[0] != "c":
                return self.redirect(home, "!Unknown action.")
            cid, act = parts[1], parts[2]
            if not self.allowed_customer(user, cid):
                p.accounts.audit(f"user:{user['id']}", "access_denied", user["id"], {"customer": cid, "action": act})
                return self.redirect(home, "!You don't have access to that company.")
            role = VIEW_ROLE[user["role"]]
            if act not in (CUSTOMER_ACTS if role == "customer" else STAFF_ACTS):
                return self.redirect(home, "!That action isn't available to you.")
            eng = p.engine(cid)
            by = auth.identity(user)
            back = urllib.parse.urlparse(self.headers.get("Referer") or "").path
            back = back if back.startswith(f"/c/{cid}/") else home
            if act == "approve-group":
                steps = [eng.store.step(x) for x in f["steps"].split(",") if x]
                if not steps or any(not st or ROLE_APPROVES[role] != st["approval_role"] for st in steps):
                    return self.redirect(back, "!Only the right person can approve these.")
                try:
                    eng.approve_group([st["id"] for st in steps], by)
                except limits.LimitReached as exc:
                    return self.redirect(back, f"!{exc}")
                return self.redirect(back, f"Approved all {len(steps)} by {user['name']}. Each one is recorded separately.")
            if act == "resubmit":
                try:
                    eng.resubmit_draft(f.get("issue", ""), by, f.get("note", "").strip() or "amended")
                except ValueError as exc:
                    return self.redirect(back, f"!{exc}")
                return self.redirect(back, "Amended draft sent back to the safety reviewer (included in the original review).")
            if act in ("approve", "reject"):
                step = eng.store.step(f["step"])
                try:
                    limits.check_review_allowed(eng, step) if step else None
                except limits.LimitReached as exc:
                    return self.redirect(back, f"!{exc}")
                if not step or ROLE_APPROVES[role] != step["approval_role"]:
                    return self.redirect(back, "!Only the right person can approve this.")
                if act == "approve":
                    eng.approve(step["id"], by)
                    return self.redirect(back, f"Approved by {user['name']}. OpsEngine has carried on.")
                eng.reject(step["id"], by, f.get("reason", ""))
                return self.redirect(back, "Declined. Our team will follow up.")
            if act == "standing-approval":
                try:
                    limit = int(float(f.get("limit") or 0))
                    cap = int(float(f["cap"])) if f.get("cap") else None
                    eng.set_standing_approval(limit, cap, by)
                except ValueError as exc:
                    return self.redirect(f"/c/{cid}/settings", f"!Not saved: {exc}.")
                return self.redirect(f"/c/{cid}/settings", "Saved. New bookings under your limit will go ahead automatically." if limit
                                     else "Saved. Every booking will wait for your OK.")
            if act == "upload":
                p.uploads.mkdir(parents=True, exist_ok=True)
                if f.get("sample"):
                    path = p.safe_file(f["sample"], user) if p.demo else None
                    if not path:
                        return self.redirect(back, "!Sample not found.")
                else:
                    name, data = files.get("file", (None, None))
                    if not data:
                        return self.redirect(back, "!Choose a photo first.")
                    safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", Path(name).name)[-80:]
                    folder = p.state / cid / "uploads"
                    folder.mkdir(parents=True, exist_ok=True)
                    path = folder / f"{date.today().isoformat()}-{safe_name}"
                    path.write_bytes(data)
                r = eng.ingest_photo(path, f.get("holder", "company"), expected_type=f.get("type") or None)
                if r["status"] == "ingested":
                    tag = " (mock AI: recorded read of a sample photo)" if r.get("source") == "mock" else ""
                    return self.redirect(f"/c/{cid}/documents", f"Read with {r['confidence']:.0%} confidence and filed{tag}. Any matching issue has moved on.")
                return self.redirect(f"/c/{cid}/documents", f"Not sure enough to file it ({r['confidence']:.0%}): sent to a person to check ({r['review']}). Reason: {r['reasons'][0]}")
            if act == "review":
                if role != "ops":
                    return self.redirect(back, "!Photo reviews are done by the ops team.")
                if f.get("decision") == "accept":
                    fixes = {k: f[k] for k in ("number", "expires") if f.get(k)}
                    eng.accept_review(f["id"], by, doc_type=f.get("type"), corrections=fixes)
                    return self.redirect(back, f"{f['id']} accepted and filed.")
                eng.reject_review(f["id"], by, "Not readable; ask for a new photo")
                return self.redirect(back, f"{f['id']} rejected.")
            if act == "raise":
                owner = f.get("owner", "company")
                aid = eng.raise_corrective_action(f["title"], holder="company", owner=owner, due=f.get("due") or None,
                                                  severity=f.get("severity", "medium"), context=f.get("site") or None,
                                                  evidence_required=f.get("evidence") or "photo of the completed work", raised_by=by)
                eng._advance_issue(aid)
                return self.redirect(f"/c/{cid}/issue/{aid}", f"Raised {aid}. The owner has been told.")
            if act == "evidence":
                issue = eng.store.issue(f["issue"])
                if not issue or issue["requirement"] != "corrective_action":
                    return self.redirect(back, "!That isn't a corrective action.")
                n = len(eng.store.documents()) + 1
                eng.ingest({"id": f"ev-{issue['id']}-{n}", "type": "corrective_action", "holder": issue["holder"], "action": issue["id"],
                            "description": f.get("note", ""), "received_via": f"portal ({by})"})
                return self.redirect(f"/c/{cid}/issue/{issue['id']}", "Evidence received and checked.")
            if act == "appointment":
                if role != "ops":
                    return self.redirect(back, "!The ops team records booking outcomes.")
                eng.update_appointment(f["id"], f["status"], by)
                return self.redirect(back, f"{f['id']} marked {f['status'].replace('_', ' ')}.")
            if act == "simulate":
                if not p.demo or role != "ops":
                    return self.redirect(back, "!Simulated arrivals are only for the ops team in the demo.")
                src = p.customers[cid] / "incoming" / Path(f["file"]).name
                doc = json.loads(src.read_text(encoding="utf-8"))
                events = eng.ingest(doc)
                return self.redirect(back, f"{doc['id']} arrived: {len(events)} step(s) moved on.")
            return self.redirect(back, "!Unknown action.")
        except KeyError as exc:
            return self.redirect("/", f"!Missing field: {exc}")
        except (ValueError, PermissionError) as exc:
            return self.redirect("/", f"!{exc}")
        except Exception as exc:
            return self.redirect("/", f"!Something went wrong ({type(exc).__name__}).")


def _admin_users(self, user, rest, f, csrf):
    """POST /admin/users/add and /admin/users/<id>/<disable|enable|reset-password|reset-code>. Admins only."""
    p = self.portal
    if user["role"] != "admin":
        p.accounts.audit(f"user:{user['id']}", "access_denied", user["id"], {"area": "user admin"})
        return self.redirect(self.home_for(user) or "/", "!Only admins can manage users.")
    a = p.accounts
    by = auth.identity(user)
    try:
        if rest == ["add"]:
            role = f.get("role", "")
            customer = f.get("customer") or None if role == "customer" else None
            temp = a.temporary_password()
            a.add_user(f.get("email", ""), f.get("name", "").strip(), role, temp, customer_id=customer, by=by,
                       must_change=True, check_strength=False)
            return self.send_html(view_users(p, user, csrf, f"Added {f.get('email')}.", (f.get("email"), temp)))
        if len(rest) == 2:
            target = a.user(rest[0])
            if not target:
                return self.redirect("/admin/users", "!No such user.")
            act = rest[1]
            if act in ("disable", "enable"):
                if target["id"] == user["id"]:
                    return self.redirect("/admin/users", "!You can't disable your own account.")
                if act == "disable" and target["role"] == "admin" and len(a.active_admins()) <= 1:
                    return self.redirect("/admin/users", "!That's the last active admin.")
                a.set_disabled(target["id"], act == "disable", by=by)
                return self.redirect("/admin/users", f"{target['email']} {act}d.")
            if act == "reset-password":
                temp = a.temporary_password()
                a.db.execute("UPDATE users SET password_hash=?, must_change=1, failures=0, locked_until=NULL WHERE id=?",
                             (auth.hash_password(temp), target["id"]))
                a.db.execute("DELETE FROM sessions WHERE user_id=?", (target["id"],))
                a.db.commit()
                a.audit(f"admin:{by}", "password_reset", target["id"], {"must_change": True})
                return self.send_html(view_users(p, user, csrf, f"Password reset for {target['email']}.", (target["email"], temp)))
            if act == "reset-code" and target["role"] in auth.STAFF:
                a.reset_mfa(target["id"], by=by)
                return self.redirect("/admin/users", f"{target['email']} will set up a new sign-in code next time.")
        return self.redirect("/admin/users", "!Unknown action.")
    except ValueError as exc:
        return self.redirect("/admin/users", f"!{exc}")


Handler.admin_users = _admin_users


def serve(host="127.0.0.1", port=8000, customers=None, state_dir=None, fresh=False, demo=False):
    if demo:
        folders = customers or SAMPLES
        state = state_dir or ROOT / "state" / "web-demo"
    else:
        folders = customers or scheduler.customer_folders()
        state = state_dir or ROOT / "state"  # the same folder the daily run and `nightly` use
        if not folders:
            raise SystemExit("No customers in data/customers/. Add one with `opsengine new-customer`, or run `opsengine web --demo`.")
    portal = Portal(folders, state, demo=demo)
    if not demo and not portal.accounts.users():
        raise SystemExit("No users yet. Create one first:\n  python -m opsengine user add --email you@example.ie "
                         "--name \"Your Name\" --role admin")
    if fresh and demo:
        portal.reset()
    Handler.portal = portal
    httpd = ThreadingHTTPServer((host, port), Handler)
    kind = f"SAMPLE demo, demo date {portal.today}" if demo else f"{len(portal.customers)} customer(s)"
    print(f"OpsEngine portal on http://{host}:{port}  ({kind}; Ctrl+C to stop)")
    httpd.serve_forever()
