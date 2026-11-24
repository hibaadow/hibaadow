# When someone says YES (free site paperwork check)

Goal: make it effortless for them, and deliver the report **within 48 hours** of getting their documents.
Paste their reply to Claude; Claude fills in the [brackets] and you send it (or Claude sends it with your OK).

## 1. Reply by email (send within a few hours)
**Subject:** Re: (keep their subject)

> Hi [name],
>
> Great, thanks for coming back to me. Here's all we need for your free site paperwork check.
> Send whatever you have; don't worry if some of it is missing, finding the gaps is the point.
>
> 1. **Your crew list:** names and what each person does (e.g. operative, foreman, excavator driver).
>    A photo of a list or a spreadsheet is fine.
> 2. **Your main contractors:** who you're working for now or soon, and any document list or
>    induction pack they've sent you.
> 3. **Cards:** photos of each person's Safe Pass and CSCS cards (front is enough), plus any other
>    tickets (manual handling, MEWP, working at height...).
> 4. **Company documents:** your public and employer's liability insurance certificates, Safety
>    Statement, tax clearance, and any RAMS you're using.
>
> Just reply to this email with the photos or files attached, or send them on WhatsApp to [number].
>
> Within 48 hours of getting them, I'll send you a report showing everything that's missing or
> expiring for each of your main contractors. We only use these documents for your check, keep them
> secure in the EU, and delete them if you decide not to go ahead.
>
> Thanks,
> Hiba
> Founder, ClearToWork
> hello@cleartowork.ie · https://cleartowork.ie

## 2. Reply on WhatsApp
> Great, thanks [name]! For your free check, just send me:
> 1. Your crew list (names + job)
> 2. Which main contractors you're working for (and their document list if you have one)
> 3. Photos of everyone's Safe Pass and CSCS cards
> 4. Your insurance certs, Safety Statement and tax clearance
>
> Send whatever you have, gaps are fine. You'll get your report within 48 hours. We only use these
> for your check and delete them if you don't go ahead.

## 3. If they ask "what does it cost after the trial?"
> The check and the 30-day trial are free. After that, pricing depends on the size of your crew;
> we'll agree it together before anything is charged, and you can stop at any time.
(Prices stay private for now: see `12_pricing.md`. Don't quote on a first reply.)

## 4. If they'd rather talk
> Of course. What time suits you for a quick 10-minute call? Or I'm happy to keep it all by email.

## Behind the scenes: making their report (Claude does this with you)
1. `python -m opsengine new-customer <id> --name "<Company>"` creates `data/customers/<id>/` (git-ignored:
   real customer data never goes into the repo).
2. Their crew list goes into `workers.json`; their contractors into `company.json` (sites + main contractor).
   If their main contractor isn't in `rules/main_contractors/`, Claude adds it from the document list they sent.
3. Card and certificate details go into `documents.json`. Without the AI key Claude reads the photos with
   you, and you check each one (boundary 9: nothing guessed).
4. `python -m opsengine check --customer data/customers/<id>` lists anything still missing.
5. `python3 launch/sample_check/build.py data/customers/<id> <out>.html`, then print to PDF.
6. Send the PDF with a short note offering the free 30-day trial (Claude drafts it).
7. Log it in `15_outreach_log.md`. If they say no: delete their folder and tell them it's deleted.
