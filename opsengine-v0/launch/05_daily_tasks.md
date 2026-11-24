# Daily tasks: one a day, 15 minutes or less

Rules: one task a day. If a day is bad, skip it; the plan waits for you. Ask Claude
*"OpsEngine, what's today's task?"* and it prepares everything for the next unticked box.
Tell Claude "done" when finished and it ticks the box.

## Week 1: get the story right and start conversations
- [x] **Day 1.** Read `01_one_page_pitch.md`. Tell Claude anything that's wrong, unclear or
      doesn't sound like you. (10 min)
- [x] **Day 2.** Choose a working name and email from Claude's shortlist. (10 min)
      Done: trading name **ClearToWork**, domain **cleartowork.ie** bought at Blacknight (24 Nov 2026).
- [ ] **Day 2b.** When Blacknight shows cleartowork.ie as **Active**: add Resend's 4 DNS records in
      Blacknight (copy each Name + Content from Resend > Domains > cleartowork.ie), then press
      "I've added the records" in Resend. (15 min) Domain already added in Resend (Ireland region,
      receiving off). Records:
      - TXT `resend._domainkey` (DKIM)
      - CNAME `rsend` (sending)
      - CNAME `send` (sending)
      - TXT `_dmarc` (DMARC, recommended)
- [ ] **Day 2c.** Free forwarding: hello@cleartowork.ie -> your Gmail via ImprovMX (free).
      Now: make an ImprovMX account, add cleartowork.ie, alias `hello` -> your Gmail.
      Done: ImprovMX account, alias hello@ -> Gmail, catch-all removed (24 Nov).
      When the domain is Active, add in Blacknight (host = cleartowork.ie / @):
      - MX priority 10 -> `mx1.improvmx.com`
      - MX priority 20 -> `mx2.improvmx.com`
      - TXT -> `v=spf1 include:spf.improvmx.com ~all` (check the exact value in ImprovMX)
      Then press "Check again" in ImprovMX.
      Then: Gmail "Send mail as" hello@cleartowork.ie through Resend SMTP (once Resend shows
      the domain verified). Upgrade to a real mailbox when the first pilot customer signs.
- [ ] **Day 2d.** Website on cleartowork.ie (Netlify, free). Done: site live at cleartowork.netlify.app,
      cleartowork.ie added in Netlify (24 Nov). When Blacknight's DNS page unlocks, add:
      - A `@` (cleartowork.ie) -> `75.2.60.5`
      - CNAME `www` -> `cleartowork.netlify.app`
      Netlify then turns on HTTPS by itself. (Blacknight has no ALIAS records, so the A record is right.)
      Full list for Blacknight = 9 records: 2 Netlify + 3 ImprovMX + 4 Resend.
- [ ] **Day 3.** Send Message 1 to 5 safety consultants (Claude gives you the search and the
      ready-to-paste notes). (15 min)
- [ ] **Day 4.** Send the first message to 5 subcontractors. (15 min)
- [ ] **Day 5.** Paste any replies to Claude; send the drafted answers back. (10 min)

## Week 2: conversations
- [ ] **Day 6.** 5 more subcontractor messages. (15 min)
- [ ] **Day 7.** Follow-ups to everyone who hasn't replied (drafted by Claude). (10 min)
- [ ] **Day 8.** First call: use the 5 questions; paste your notes to Claude afterwards. (15 min)
- [ ] **Day 9.** Call with a safety consultant. (15 min)
- [ ] **Day 10.** Review what you've heard with Claude: keep going, or adjust the offer? (15 min)

## Week 3: first pilot
- [ ] **Day 11.** Offer the free pilot to the keenest firm (Claude drafts it). (10 min)
- [ ] **Day 12.** Approve the pilot agreement draft. (15 min)
- [ ] **Day 13.** Book onboarding with the pilot firm. (10 min)
- [ ] **Day 14.** Onboarding: Claude walks you through loading their data into OpsEngine. (15 min)
- [ ] **Day 15.** Look at their first compliance check with Claude and approve sending it. (15 min)

Meanwhile, Claude keeps building the product (`../CLAUDE.md` roadmap): real message sending,
photo reading, logins and hosting, so it's ready for the pilot's real data.
