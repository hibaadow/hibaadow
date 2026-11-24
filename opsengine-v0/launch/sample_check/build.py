"""Build the free 'site paperwork check' report. Sample by default (Bremore, fictional);
pass a customer folder to make a real one:  python3 launch/sample_check/build.py [folder] [out.html]"""
import html, json, re, sys, tempfile
from datetime import date
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from opsengine.engine import Engine

folder = sys.argv[1] if len(sys.argv) > 1 else "data/sample/bremore_groundworks"
out = Path(sys.argv[2] if len(sys.argv) > 2 else Path(__file__).parent / "paperwork_check_sample.html")
today = date(2026, 11, 11) if "sample" in folder else date.today()
e = Engine(folder, state_dir=tempfile.mkdtemp(), today=today)
e.scan()
c = e.customer
sample = c.company.get("sample", False)
clean = lambda s: re.sub(r"\s*\((?:SAMPLE|sample)[^)]*\)", "", s).replace(" (SAMPLE)", "")
contractors = sorted({mc for s in c.company.get("sites", []) for mc in [s.get("main_contractor")] if mc})
mc_names = {}
for mc in contractors:
    p = Path("rules/main_contractors") / f"{mc}.json"
    mc_names[mc] = clean(json.loads(p.read_text()).get("name", mc)) if p.exists() else mc

GROUPS = [("critical", "Stops work on site now", "#c0392b"), ("high", "Fix within the next few weeks", "#d68910"),
          ("medium", "To tidy up", "#2471a3")]
ACTION = {"expired": "We arrange the renewal (course or certificate), with your OK on any cost",
          "expiring": "We arrange the renewal in good time, with your OK on any cost",
          "missing": "We get it from the right person (worker, broker or provider)",
          "incomplete": "We get the missing part and check it",
          "content_gap": "A qualified safety person updates it; we coordinate",
          "corrective": "We track the repair until there's proof it's done"}
def action(i):
    r, k = i["requirement"], i["kind"]
    if r in ("rams", "safety_statement") or k == "content_gap":
        return "A qualified safety person drafts or updates it; we coordinate and track sign-off"
    if "liability" in r or "indemnity" in r or "insurance" in r:
        return "We get the certificate from the broker" + (" and check the cover meets every contractor's minimum" if k == "incomplete" else "")
    if r == "site_induction":
        return "We book the induction with the main contractor and file the record"
    if r.startswith(("safe_pass", "cscs", "manual_handling")):
        return ("We ask the worker for a photo of the card; if they don't have one, we line up the course (your OK on any cost)"
                if k == "missing" else "We line up the renewal course in good time (your OK on any cost)")
    if "examination" in r or "inspection" in r or "test" in r or "service" in r:
        return "We book the inspection or service and file the certificate"
    return ACTION.get(k, "We sort it")

issues = [i for i in e.store.issues("open")]
rows = {g: [] for g, _, _ in GROUPS}
for i in issues:
    req = e.kb.requirements.get(i["requirement"], {}).get("name", i["requirement"])
    who = clean(c.holder_name(i["holder"])) if i["holder"] != "company" else "Company"
    rb = [mc_names.get(x, x) for x in json.loads(i.get("required_by") or "[]")]
    rows.setdefault(i["severity"], []).append(
        f"<tr><td>{html.escape(who)}</td><td>{html.escape(clean(req))}</td><td>{html.escape(clean(i['detail']))}</td>"
        f"<td>{html.escape(', '.join(rb) or 'All sites')}</td><td>{action(i)}</td></tr>")
counts = {g: len(rows.get(g, [])) for g, _, _ in GROUPS}
workers = len(c.workers)
sections = "".join(
    f'<h2 style="border-color:{col}"><span style="background:{col}">{counts[g]}</span>{lbl}</h2>'
    f'<table><tr><th>Who / what</th><th>Item</th><th>What we found</th><th>Needed by</th><th>What ClearToWork does</th></tr>{"".join(rows[g])}</table>'
    for g, lbl, col in GROUPS if rows.get(g))
banner = ('<div class="sample">SAMPLE REPORT: a fictional company, made up to show what you get. Your report uses your own crew and contractors.</div>'
          if sample else "")
page = f"""<!doctype html><html lang="en-IE"><head><meta charset="utf-8"><title>Site paperwork check</title><style>
@page{{size:A4;margin:12mm}}*{{box-sizing:border-box}}body{{font:10pt/1.4 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;color:#16181d;margin:0}}
.top{{display:flex;justify-content:space-between;align-items:center}}.logo{{font-weight:800;font-size:16pt}}.logo i{{display:inline-block;width:16px;height:16px;border-radius:4px;background:#1f9d55;margin-right:6px;vertical-align:-2px}}
.muted{{color:#5b6170}}h1{{font-size:20pt;margin:6mm 0 1mm}}.sample{{background:#fff3c4;border:1px solid #e8c547;padding:2mm 3mm;border-radius:6px;margin:3mm 0;font-weight:600}}
.kpis{{display:grid;grid-template-columns:repeat(4,1fr);gap:3mm;margin:4mm 0}}.k{{border:1px solid #e4e1d8;border-radius:8px;padding:3mm;background:#fbfaf7}}.k b{{font-size:18pt;display:block}}
h2{{font-size:12pt;border-left:4px solid;padding-left:3mm;margin:6mm 0 2mm}}h2 span{{color:#fff;border-radius:10px;padding:0 7px;margin-right:6px;font-size:10pt}}
table{{width:100%;border-collapse:collapse;font-size:8.8pt}}th{{text-align:left;background:#f1efe9;padding:1.6mm}}td{{padding:1.6mm;border-bottom:1px solid #eee;vertical-align:top}}tr{{page-break-inside:avoid}}
.foot{{margin-top:6mm;font-size:8pt;color:#5b6170;border-top:1px solid #e4e1d8;padding-top:2mm}}.next{{background:#16181d;color:#fff;border-radius:10px;padding:4mm 5mm;margin-top:5mm}}
</style></head><body>
<div class="top"><div class="logo"><i></i>ClearToWork</div><div class="muted">hello@cleartowork.ie · cleartowork.ie</div></div>
{banner}
<h1>Site paperwork check</h1>
<div class="muted">{html.escape(clean(c.company['name']))} · {workers} workers · checked against {', '.join(html.escape(n) for n in mc_names.values())} · {today:%d %b %Y}</div>
<div class="kpis"><div class="k"><b>{len(issues)}</b>items need action</div><div class="k" style="color:#c0392b"><b>{counts['critical']}</b>stop work on site now</div>
<div class="k" style="color:#d68910"><b>{counts['high']}</b>due in the next few weeks</div><div class="k" style="color:#2471a3"><b>{counts['medium']}</b>to tidy up</div></div>
{sections}
<div class="next"><b>What happens next.</b> On the free 30-day trial, ClearToWork works through this list for you: we chase workers for card photos,
get certificates from your broker, line up courses (nothing that costs money without your OK), and keep a ready-to-send pack for each main contractor.</div>
<div class="foot">ClearToWork coordinates and records compliance work. It does not certify compliance or take on legal duty-holder roles such as PSCS;
certificates and sign-offs come from the qualified people named on each document.</div>
</body></html>"""
out.write_text(page)
print(out, len(issues), counts)
