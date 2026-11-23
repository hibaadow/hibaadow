# THE 2AM DELIVERY — original second-person "what would you do" short.
# Each line: (scene, [(spoken words, caption chunk), ...]).  *word* = red key word, _word_ = blue key word.
LINES = [
    ("door",    [("It's two fourteen A.M....", "It's *2:14 AM*..."), ("and someone is knocking", "and someone is _knocking_"), ("on your door.", "on your door.")]),
    ("door2",   [("A courier hands you a box.", "A courier hands you a _box_."), ("Your apartment number...", "Your apartment number..."), ("but not your name.", "but *not your name.*")]),
    ("cash",    [("You open it. Inside...", "You open it. Inside..."), ("two hundred and fifty thousand dollars!", "*$250,000*"), ("In cash.", "in _cash._")]),
    ("note",    [("Taped to the lid,", "Taped to the lid,"), ("a note.", "a _note._"), ("Hold it for forty-eight hours.", "Hold it for *48 hours.*"), ("Tell no one.", "Tell _no one._")]),
    ("spend",   [("Your first thought", "Your first thought"), ("is to spend it.", "is to _spend it._"), ("Rent. Debt.", "Rent. Debt."), ("A new car.", "A new *car.*")]),
    ("report",  [("But any cash payment", "But any cash payment"), ("over ten thousand dollars", "over *$10,000*"), ("gets reported.", "gets _reported._"), ("One big purchase...", "One big purchase..."), ("and someone starts asking", "and someone starts _asking_"), ("where it came from.", "where it *came from.*")]),
    ("dial",    [("So you reach for your phone", "So you reach for your _phone_"), ("to call the police.", "to call the *police.*")]),
    ("burner",  [("Then a second phone", "Then a *second phone*"), ("in the box lights up.", "in the box _lights up._"), ("We see your light is on.", "\"We see your *light* is on.\"")]),
    ("window",  [("You look outside.", "You look _outside._"), ("A dark car", "A dark *car*"), ("is parked across the street...", "is parked across the street..."), ("engine running.", "engine _running._")]),
    ("search",  [("So you search the name", "So you _search_ the name"), ("on the label.", "on the label."), ("Daniel Cross.", "*Daniel Cross.*")]),
    ("missing", [("The first result...", "The first result..."), ("a missing person poster.", "a *missing person* poster."), ("Last seen three days ago.", "Last seen _3 days ago._")]),
    ("reveal",  [("The box was meant for him.", "The box was meant for _him._"), ("And whoever sent it...", "And whoever sent it..."), ("now thinks you're him.", "now thinks *you're him.*")]),
    ("garage",  [("Another message.", "Another _message._"), ("Parking garage. Level minus two.", "\"Parking garage. *Level -2.*"), ("Six A.M. Come alone.", "6 AM. _Come alone._\"")]),
    ("keep",    [("If you keep it...", "If you _keep_ it..."), ("they come looking for it.", "they come *looking* for it.")]),
    ("bring",   [("If you bring it...", "If you _bring_ it..."), ("you walk into an empty garage", "you walk into an *empty garage*"), ("alone.", "alone.")]),
    ("police",  [("If you call the police...", "If you call the _police_..."), ("you have to explain", "you have to *explain*"), ("why you opened it.", "why you opened it.")]),
    ("final",   [("So what do you do?", "So what do you do?"), ("Keep it, bring it,", "_Keep_ it, _bring_ it,"), ("or call the police?", "or call the *police?*")]),
]
# lines whose "..." leads into a reveal (longer pause) and lines with a quick breath first
REVEALS = {2, 10, 11}
BREATH_BEFORE = {1, 2, 7, 8, 11, 12, 14}
