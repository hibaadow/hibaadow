# SAMPLE customer - Bremore Groundworks Ltd

**SAMPLE DATA - FICTIONAL.** This company, its people, sites, documents and numbers are invented
for development and demos. It is not a real customer. Real customers go in `data/customers/`
(git-ignored), never here.

- Groundworks subcontractor, Swords, Co. Dublin. 16 staff: plant operators, pipelayers,
  general operatives, an apprentice and a site engineer. Languages: English, Polish,
  Lithuanian, Romanian, Portuguese and Ukrainian.
- Site s1: apartment scheme, Clongriffin, for **Glenmara Construction (SAMPLE)**, whose
  sample prequalification form is in `rules/main_contractors/forms/`.
- Site s2: logistics warehouse, Ballycoolin, for Harbour Construction (sample).
- Two SAMPLE subcontractors (kerbing and paving; traffic management) and a SAMPLE plant and
  equipment register (`assets.json`: excavator, telehandler, lifting accessories, dumper, fire
  extinguishers, welfare cabin, 110V tools) with inspection and service records.
- Phone numbers use the fictional +353 87 000 range; emails use `.example.ie`.

The documents contain deliberate gaps so the engine has work to do on 2026-11-11 (31 issues,
including RAMS not covering dumper work, a subcontractor with expired insurance, overdue lifting
examinations, and two inspection defects that become corrective actions):
public liability below both contractors' minimums, no professional indemnity, tax clearance
and Safe-T-Cert expiring, a stale accident history, one trade reference missing, no RAMS for
s2, Safe Pass and CSCS cards expired or missing, manual handling gaps, missing inductions and
an unsigned contract.

`incoming/new_pi_certificate.json` is a sample professional indemnity certificate to test
the proof step; `incoming/a07_repair_evidence.json` is sample evidence that the dumper's seat belt
defect was repaired.

```bash
python -m opsengine --today 2026-11-11 scan    --customer data/sample/bremore_groundworks
python -m opsengine --today 2026-11-11 advance --customer data/sample/bremore_groundworks
python -m opsengine queue  --customer data/sample/bremore_groundworks
python -m opsengine --today 2026-11-11 daily   --customer data/sample/bremore_groundworks
```
