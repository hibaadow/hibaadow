# 6-Month SOC Analyst Roadmap

Starts **Monday 9 November 2026** · finishes early May 2027.

Goal: job-ready **SOC Analyst Tier 1** in 26 weeks (~15–20 hrs/week), then grow into a **cybersecurity engineer**.

> Prices, exam versions and free offers change. Check each official site before paying.

## The core stack (what you'll use most)

| What | Why | Cost |
|---|---|---|
| [TryHackMe](https://tryhackme.com) — Pre Security, Cyber Security 101, **SOC Level 1**, SOC Level 2 | Best guided hands-on path for SOC work | Free tier + premium monthly |
| [Professor Messer](https://www.professormesser.com) — Network+ and Security+ videos | Free, complete exam video courses | Free |
| [LetsDefend](https://letsdefend.io) — SOC Analyst path + alert practice | Feels like a real SOC console | Free tier + premium |
| [Splunk free training](https://www.splunk.com/en_us/training/free-courses/overview.html) + Boss of the SOC datasets | Splunk is the most asked-for SIEM in job ads | Free |
| [CyberDefenders](https://cyberdefenders.org) and [Blue Team Labs Online](https://blueteamlabs.online) | Real investigations for your portfolio | Free tier |
| [Malware-Traffic-Analysis.net](https://www.malware-traffic-analysis.net) | Free Wireshark exercises with answers | Free |
| [OverTheWire Bandit](https://overthewire.org/wargames/bandit/) | Linux command line by playing | Free |
| [MITRE ATT&CK](https://attack.mitre.org) | The common language of every SOC | Free |

**Real YouTube teachers (free):** [Professor Messer](https://www.youtube.com/@professormesser) (Network+ / Security+), [Practical Networking](https://www.youtube.com/@PracticalNetworking) (networking explained simply), [NetworkChuck](https://www.youtube.com/@NetworkChuck) (fun intros, Linux, labs), [MyDFIR](https://www.youtube.com/@MyDFIR) (SOC analyst life and home labs), [John Hammond](https://www.youtube.com/@_JohnHammond) (malware and CTFs), [13Cubed](https://www.youtube.com/@13Cubed) (Windows forensics), [Simply Cyber](https://www.youtube.com/@SimplyCyber) (careers and getting hired).

**Certs, in order:** CompTIA **Security+** (most UK/US SOC job ads ask for it) → **BTL1** (Security Blue Team, practical) *or* **CySA+** *or* Microsoft **SC-200** (pick one based on job ads near you). Optional to fill gaps: Google Cybersecurity Certificate (Coursera, financial aid available).

---

## Month 1 — Foundations (weeks 1–4)

- **Week 1 — How computers and networks talk.** OSI and TCP/IP models, IP addresses, subnets, ports, TCP vs UDP. *Do:* TryHackMe Pre Security (Network Fundamentals); Messer Network+ sections 1.x.
- **Week 2 — Network protocols.** DNS, HTTP/HTTPS, DHCP, ARP, SMTP, common ports you must know by heart. *Do:* TryHackMe "Networking" rooms; capture your own traffic in Wireshark.
- **Week 3 — Linux.** Files, permissions, users, processes, grep/awk/cut, logs in `/var/log`. *Do:* OverTheWire Bandit levels 0–15; TryHackMe Linux Fundamentals 1–3.
- **Week 4 — Windows.** Users, groups, Active Directory basics, registry, services, PowerShell basics, Event Viewer. *Do:* TryHackMe Windows Fundamentals 1–3, Active Directory Basics. **Checkpoint quiz.**

## Month 2 — Security fundamentals + Security+ (weeks 5–8)

- **Week 5 — Core concepts.** CIA triad, threats vs vulnerabilities vs risk, attack types (phishing, malware, ransomware, brute force, MITM), social engineering. *Do:* Messer Security+ domain 1–2.
- **Week 6 — Security architecture & controls.** Firewalls, IDS/IPS, VPN, proxies, EDR, SIEM, encryption, hashing, PKI, authentication/MFA. *Do:* Messer Security+ domain 3.
- **Week 7 — Operations & IR.** Incident response lifecycle (NIST SP 800-61), vulnerability management, logging, governance basics. *Do:* Messer Security+ domains 4–5.
- **Week 8 — Exam prep.** Practice exams (Messer, Jason Dion), review weak areas. **Book Security+** for end of week 9 or 10.

## Month 3 — SOC core skills (weeks 9–12)

- **Week 9 — Security+ exam week** + intro to the SOC: tiers, shifts, tickets, SLAs, playbooks, true/false positives. *Do:* TryHackMe SOC Level 1 intro rooms.
- **Week 10 — SIEM with Splunk.** Indexes, SPL searches, stats, timecharts, dashboards, alerts. *Do:* Splunk free "Intro to Splunk"; TryHackMe Splunk rooms; Boss of the SOC v1.
- **Week 11 — Windows logs.** Event IDs that matter (4624, 4625, 4688, 4720, 4732, 7045, 1102), Sysmon, PowerShell logging. *Do:* TryHackMe Windows Event Logs, Sysmon rooms.
- **Week 12 — MITRE ATT&CK & Cyber Kill Chain.** Map alerts to techniques. *Do:* TryHackMe MITRE, Pyramid of Pain, Cyber Kill Chain. **Alert drills ×3.**

## Month 4 — Investigation skills (weeks 13–16)

- **Week 13 — Phishing analysis.** Email headers, SPF/DKIM/DMARC, URL and attachment analysis, sandboxes (Any.Run, VirusTotal). *Do:* TryHackMe Phishing module; LetsDefend phishing alerts.
- **Week 14 — Network traffic analysis.** Wireshark, Zeek, Snort/Suricata, spotting beacons and exfiltration. *Do:* 3 Malware-Traffic-Analysis exercises; TryHackMe Wireshark + Snort.
- **Week 15 — Endpoint & malware basics.** EDR, processes, persistence, IOCs, basic static analysis, YARA. *Do:* TryHackMe Endpoint Security module.
- **Week 16 — Threat intel & IR.** OSINT, threat intel feeds, IOC enrichment, writing incident reports. *Do:* LetsDefend 10 alerts, written up like a real ticket. **Checkpoint quiz + mock interview.**

## Month 5 — Home lab + second cert (weeks 17–21)

- **Week 17 — Build a home lab.** VirtualBox/VMware: Windows VM + Sysmon, Ubuntu VM, **Wazuh** or Elastic or Splunk Free as your SIEM. Document every step on GitHub.
- **Week 18 — Attack & detect your own lab.** Run safe simulations (Atomic Red Team) against your own VMs and build detections for them. Write it up.
- **Week 19 — Cloud & identity basics.** Microsoft Entra ID / Azure logs, AWS CloudTrail, impossible travel, MFA fatigue. *Do:* TryHackMe cloud rooms; SC-200 Microsoft Learn path (free).
- **Week 20–21 — Second cert.** BTL1 (practical, 24-hr exam) *or* CySA+ *or* SC-200. Pick the one job ads near you mention most.

## Month 6 — Get hired (weeks 22–26)

- **Week 22 — Portfolio.** GitHub with: home-lab write-up, 3–5 investigation reports (CyberDefenders/BTLO), detection rules, this roadmap's notes. Pin them on this profile README.
- **Week 23 — CV & LinkedIn.** One-page CV with projects, certs, keywords from job ads (SIEM, Splunk, EDR, phishing, incident response, MITRE ATT&CK). Start posting what you learn on LinkedIn.
- **Week 24 — Interview prep.** Daily mock interviews and alert drills with your teacher; STAR stories ready.
- **Week 25–26 — Apply.** 5–10 tailored applications per week: SOC Analyst, Security Analyst, Cyber Security Analyst, MSSP / MDR roles, graduate schemes. Keep doing 2–3 labs a week so skills stay sharp.

---

## After you land the SOC job — path to engineer

Year 1–2 in the SOC, then grow towards engineering:
- **Scripting/automation:** Python, PowerShell, Bash; SOAR playbooks. (Your JavaScript helps here.)
- **Detection engineering:** Sigma, KQL, SPL, writing and tuning detections.
- **Cloud security:** AWS/Azure security, infrastructure as code, AWS Security Specialty or AZ-500.
- **Next certs:** SC-200 / CySA+ (if not done), GCIH, then cloud or engineering certs.
- Target roles: SOC Tier 2/3 → Detection Engineer → Security Engineer / Cloud Security Engineer.
