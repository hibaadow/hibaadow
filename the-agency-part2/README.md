# THE AGENCY (Part 2): what happened next

Follow-up to `../the-agency` (~110 s, 1080x1920), same house male voice (Kokoro `am_puck`, ~188 wpm, one continuous
read per line). **Facts only**, from the LA County DA's press release and CBS, ABC7, CNN, Courthouse News and Deseret
reporting (checked 27 Nov 2026). The couple pleaded not guilty and the trial is pending: every accusation is worded
as an allegation ("prosecutors allege", "accused of"), and the video says they are innocent until proven guilty.
Part 1's line "all under the age of 3" is corrected (the children were aged 2 months to 13 years).

    SCR=<scratch> python tts.py     # voiceover + timeline.json
    SCR=<scratch> python audio.py   # -> $SCR/agency2_mix.wav
    SCR=<scratch> python render.py --still 42 frame.png
