# SOC Analyst Roadmap

Hibo's plan: **Microsoft-focused SOC Analyst**, free only, in Ireland 🇮🇪
- **Phase 1 (Nov–Feb, 12 weeks + Christmas break):** skills, Microsoft SOC tools, portfolio
- **Phase 2 (Feb–May):** free certs, CV and job applications
- **After that:** grow from SOC analyst to cybersecurity engineer

Study time: 3 hours a day. Every topic gets a Professor Byte video episode.

> Free offers, prices and links change. Check each official site before relying on it.

---

## Phase 1 — November to February

### Weeks 1–3: IT foundations

| Week | Dates | Topic | Free practice |
|---|---|---|---|
| 1 | 9–15 Nov | **Networking:** IP, packets, routers, ports, TCP/UDP, OSI model (Episodes 1–2 ✅) | TryHackMe Pre Security: What is Networking?, Intro to LAN, OSI Model |
| 2 | 16–22 Nov | **IP addresses and DNS:** public vs private IPs, subnets basics, DHCP, DNS records and lookups | TryHackMe "DNS in Detail"; run `ipconfig` / `nslookup` on your own laptop |
| 3 | 23–29 Nov | **Windows fundamentals + Linux basics:** users, processes, services, Event Viewer, PowerShell; Linux files, permissions, `grep`, logs | TryHackMe Windows Fundamentals 1 + Linux Fundamentals 1; OverTheWire Bandit levels 0–10 |

### Weeks 4–6: Cybersecurity

| Week | Dates | Topic | Free practice |
|---|---|---|---|
| 4 | 30 Nov–6 Dec | **Malware and phishing:** malware types, ransomware, phishing emails, headers, SPF/DKIM/DMARC, suspicious links | Professor Messer Security+ malware + social engineering videos; LetsDefend free phishing alerts |
| 5 | 7–13 Dec | **Brute-force attacks + authentication and access control:** failed logons (event 4625), password spraying, MFA, least privilege, Entra ID basics | Microsoft Learn SC-900 identity modules; read real 4624/4625 log examples |
| 6 | 14–20 Dec | **Firewalls and endpoint security:** firewall rules and logs, IDS/IPS, antivirus vs EDR, what an endpoint alert looks like | Professor Messer Security+ security architecture videos; Microsoft Learn Defender for Endpoint intro module |
| 🎄 | 21–27 Dec | **Christmas break.** Rest! Optional: rewatch episodes | |

### Weeks 7–10: SOC tools (Microsoft)

| Week | Dates | Topic | Free practice |
|---|---|---|---|
| 7 | 28 Dec–3 Jan | **SIEM investigation + Microsoft Sentinel:** what a SIEM does, logs → analytics rules → incidents, workbooks | Microsoft Learn SC-200 path (Sentinel modules); Microsoft Sentinel Ninja Training (free) |
| 8 | 4–10 Jan | **KQL queries:** `where`, `project`, `summarize`, `count`, `bin`, `join`; hunting failed logons and suspicious processes | Microsoft Learn "Write your first query with KQL"; [Kusto Detective Agency](https://detective.kusto.io) (free KQL game); [Must Learn KQL](https://github.com/rod-trent/MustLearnKQL); Log Analytics demo workspace ([aka.ms/LADemo](https://aka.ms/LADemo)) |
| 9 | 11–17 Jan | **Microsoft Defender XDR:** Defender for Endpoint, Office 365, Identity; incidents, device timeline, advanced hunting | Microsoft Learn SC-200 Defender XDR modules; Microsoft's free Defender interactive guides |
| 10 | 18–24 Jan | **Security alert triage:** true vs false positive, severity, evidence, MITRE ATT&CK, escalate / contain / close | LetsDefend free alerts; daily Professor Byte alert drills |

**Lab note:** a free Azure account lets you try Microsoft Sentinel on a small trial, but Azure asks for a bank card to prove you're real. If you'd rather not, the Log Analytics demo workspace, Kusto Detective Agency and Microsoft Learn sandboxes cover KQL for free with no card.

### Weeks 11–12: Practical experience

| Week | Dates | Topic | Free practice |
|---|---|---|---|
| 11 | 25–31 Jan | **Investigate simulated attacks + SOC labs:** phishing, brute force, malware, data theft scenarios | CyberDefenders free labs; Blue Team Labs Online free investigations; LetsDefend free alerts |
| 12 | 1–7 Feb | **Investigation reports + small portfolio:** write 3 reports like a real ticket; publish them on GitHub with your KQL queries | Professor Byte reviews each report; pin them on this GitHub profile |

**End of Phase 1 goal:** 3 written investigation reports, a folder of your own KQL hunting queries, and confidence explaining a phishing, brute-force and malware investigation.

---

## Phase 2 — February to May: certs and jobs

| Weeks | Dates | Goal |
|---|---|---|
| 13–15 | Feb | **ISC2 Certified in Cybersecurity (CC)**: free course and, through ISC2's One Million Certified programme, a free exam (check it is still running on isc2.org) |
| 16–18 | Mar | **SC-200 study** (Microsoft Security Operations Analyst) on Microsoft Learn, free to study. Matches your Sentinel/Defender/KQL skills. The exam is paid: check for Microsoft free exam offers or Springboard+ funding, or ask your first employer |
| 19–20 | Mar–Apr | **CV and LinkedIn:** one page, projects first, keywords from job ads (Microsoft Sentinel, Defender, KQL, SIEM, phishing, incident response, MITRE ATT&CK) |
| 21–26 | Apr–May | **Apply:** 5–10 tailored applications a week on IrishJobs.ie, Jobs.ie and LinkedIn. SOC Analyst, Security Analyst, MSSP / MDR roles in Dublin, Cork and remote. Daily mock interviews and alert drills |

---

## Free resources

| What | Use it for |
|---|---|
| [Microsoft Learn](https://learn.microsoft.com/training/) | Sentinel, Defender, KQL, SC-900 and SC-200 paths, free sandboxes |
| [TryHackMe](https://tryhackme.com) | Free rooms for networking, Windows, Linux, DNS |
| [LetsDefend](https://letsdefend.io) | Free SOC alert practice |
| [CyberDefenders](https://cyberdefenders.org) and [Blue Team Labs Online](https://blueteamlabs.online) | Free investigation labs for your portfolio |
| [OverTheWire Bandit](https://overthewire.org/wargames/bandit/) | Linux command line by playing |
| [MITRE ATT&CK](https://attack.mitre.org) | The common language of every SOC |
| [Kusto Detective Agency](https://detective.kusto.io) | Learn KQL as a detective game |

**Real YouTube teachers (free):** [Professor Messer](https://www.youtube.com/@professormesser) (Network+ / Security+), [Practical Networking](https://www.youtube.com/@PracticalNetworking), [NetworkChuck](https://www.youtube.com/@NetworkChuck), [MyDFIR](https://www.youtube.com/@MyDFIR) (SOC analyst life), [John Hammond](https://www.youtube.com/@_JohnHammond), [13Cubed](https://www.youtube.com/@13Cubed), [Simply Cyber](https://www.youtube.com/@SimplyCyber).

**Ireland extras:** check **Springboard+** and **Skillnet Ireland** for government-funded cyber courses that can be free if you're eligible; **Cyber Ireland** for events and meet-ups.

---

## After the SOC job — path to engineer

Year 1–2 in the SOC, then:
- **Automation:** Python, PowerShell, Logic Apps / SOAR playbooks in Sentinel (your JavaScript helps here)
- **Detection engineering:** writing and tuning KQL analytics rules, Sigma
- **Cloud security:** Azure security, AZ-500, then Microsoft SC-100 or cloud engineering roles
- Target roles: SOC Tier 2/3 → Detection Engineer → Security Engineer / Cloud Security Engineer
