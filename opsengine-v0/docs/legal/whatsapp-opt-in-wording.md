> **DRAFT – AWAITING APPROVAL FROM AN IRISH DATA PROTECTION SOLICITOR.**
> Not legal advice. Not approved for use with real customers or workers. Prepared by Claude (an AI).
> The opt-in is a channel preference and a Meta WhatsApp Business requirement. It is **not** the GDPR
> legal basis (that is legitimate interests): do not describe it as consent to data processing.

# WhatsApp opt-in wording

## Asked in person, on paper, or in the onboarding form

> Can [EMPLOYER NAME] send you WhatsApp messages about your site cards, training and documents?
> These are work messages only, never marketing. They'll be in [LANGUAGE] where we can.
> You can reply STOP at any time and we'll contact you another way instead.
> How we use your information: [link or attached worker privacy notice].
>
> ☐ Yes, message me on WhatsApp at [phone number]   ☐ No, contact me another way

Record the date of the answer as `whatsapp_opt_in` in `workers.json`. No date means no WhatsApp messages.

## First WhatsApp message (approved template)

> Hi {{1}}, you have a message from {{2}} about {{3}}. Reply to this message to see it.
> Reply STOP to stop WhatsApp messages.

## Replies

- **STOP**: "OK, we won't message you on WhatsApp again. [EMPLOYER NAME] will contact you another way. Reply START to turn it back on."
- **START**: "Thanks, WhatsApp messages are back on. Reply STOP at any time."

[SOLICITOR: confirm wording, including for workers aged 16 or 17; translations need native-speaker review.]
