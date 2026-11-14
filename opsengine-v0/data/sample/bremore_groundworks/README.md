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
- Phone numbers use the fictional +353 87 000 range; emails use `.example.ie`.

The documents contain deliberate gaps so the engine has work to do on 2026-11-11 (19 issues):
public liability below both contractors' minimums, no professional indemnity, tax clearance
and Safe-T-Cert expiring, a stale accident history, one trade reference missing, no RAMS for
s2, Safe Pass and CSCS cards expired or missing, manual handling gaps, missing inductions and
an unsigned contract.

`incoming/new_pi_certificate.json` is a sample professional indemnity certificate to test
the proof step.

```bash
python -m opsengine --today 2026-11-11 scan    --customer data/sample/bremore_groundworks
python -m opsengine --today 2026-11-11 advance --customer data/sample/bremore_groundworks
python -m opsengine queue  --customer data/sample/bremore_groundworks
python -m opsengine --today 2026-11-11 daily   --customer data/sample/bremore_groundworks
```
