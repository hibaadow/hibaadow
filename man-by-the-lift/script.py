# "THE MAN BY THE LIFT" — condensed ~2 min short.
# Each item: (shot, voice, [(spoken, caption chunk), ...], options)
#   voices: her (narrator), him (the man / his texts), neigh (new neighbour), recep (receptionist)
#   caption chunk None = no captions (chapter card on screen). *word* lime, _word_ blue.
#   options: pre = gap before (s), breath = quick inhale first, reveal = longer "..." pause

ITEMS = [
    ("card1", "her", [("Chapter one. The missing lock.", None)], {}),
    ("hall", "her", [("I was unlocking my apartment", "I WAS *UNLOCKING*|MY APARTMENT"), ("when the guy by the lift said...", "WHEN THE GUY|BY THE _LIFT_...")], {}),
    ("hall", "him", [("You missed one.", "\"YOU *MISSED* ONE.\"")], {}),
    ("lock", "her", [("I always check the deadbolt the same way.", "I ALWAYS|CHECK THE _DEADBOLT_"), ("Lock. Unlock. Lock.", "*LOCK*. UNLOCK. LOCK.")], {}),
    ("lock", "him", [("There. That's better.", "\"THERE. THAT'S *BETTER*.\"")], {"pre": 0.4}),
    ("peep", "her", [("I'd never seen him before.", "I'D NEVER|_SEEN_ HIM BEFORE."), ("Through the peephole...", "THROUGH THE *PEEPHOLE*..."), ("he was still by the lift.", "HE WAS STILL|BY THE _LIFT_."), ("Facing my door.", "*FACING* MY DOOR.")], {"breath": True}),
    ("peep", "her", [("The lift opened behind him.", "THE LIFT|_OPENED_ BEHIND HIM."), ("He didn't turn around.", "HE DIDN'T|*TURN* AROUND.")], {}),
    ("phone1", "her", [("Then my phone buzzed.", "THEN MY|PHONE *BUZZED*.")], {}),
    ("phone1", "him", [("You forgot to check the handle.", "YOU FORGOT|TO CHECK|THE *HANDLE*.")], {}),
    ("phone1", "her", [("Nobody in this building had my number.", "NOBODY|IN THIS _BUILDING_|HAD MY *NUMBER*.")], {"breath": True}),
    ("knock", "her", [("Then...", "THEN..."), ("three quiet knocks.", "THREE *QUIET* KNOCKS.")], {"reveal": True}),
    ("phone2", "him", [("Don't open it.", "DON'T *OPEN* IT."), ("I'm still outside.", "I'M STILL _OUTSIDE_.")], {}),
    ("peep2", "her", [("The hallway was empty.", "THE HALLWAY|WAS *EMPTY*.")], {"breath": True}),
    ("phone3", "him", [("Good. You listened this time.", "GOOD.|YOU *LISTENED*|THIS _TIME_.")], {}),

    ("card2", "her", [("Chapter two. Apartment six oh four.", None)], {"pre": 0.6}),
    ("recep", "her", [("The next morning, I asked reception about him.", "THE NEXT *MORNING*,|I ASKED|_RECEPTION_.")], {}),
    ("recep", "recep", [("There's no apartment six oh four.", "THERE'S *NO*|APARTMENT _604_.")], {}),
    ("plan", "her", [("On the plan, the flat opposite mine said...", "THE FLAT|OPPOSITE MINE..."), ("six oh four B. Vacant.", "*604B*. _VACANT_."), ("The last tenant...", "THE LAST TENANT..."), ("was a man.", "WAS A *MAN*.")], {}),

    ("card3", "her", [("Chapter three. The previous tenant.", None)], {"pre": 0.6}),
    ("group", "her", [("Eight months ago...", "*8 MONTHS* AGO..."), ("everyone was looking for Daniel from six oh four.", "EVERYONE WAS|LOOKING FOR _DANIEL_.")], {}),
    ("group", "her", [("One reply said...", "ONE REPLY..."), ("I saw him by the lift.", "I SAW HIM|BY THE *LIFT*.")], {}),
    ("xmas", "her", [("Then I found a Christmas photo.", "THEN A|_CHRISTMAS_ PHOTO."), ("The man in the dark coat... by the lift.", "THE MAN IN|THE *DARK COAT*.")], {"breath": True}),
    ("xmas", "her", [("Uploaded by Daniel.", "UPLOADED BY|*DANIEL*."), ("One comment.", "ONE _COMMENT_.")], {}),
    ("xmas", "him", [("You missed one.", "\"YOU *MISSED* ONE.\"")], {}),

    ("card4", "her", [("Chapter four. The routine.", None)], {"pre": 0.6}),
    ("phone4", "her", [("I changed my routine.", "I _CHANGED_|MY ROUTINE."), ("The messages didn't stop.", "THE MESSAGES|DIDN'T *STOP*.")], {}),
    ("phone4", "him", [("You left the top lock. You forgot the chain.", "YOU LEFT|THE *TOP LOCK*.|YOU FORGOT|THE _CHAIN_.")], {}),
    ("cctv", "her", [("The police checked the CCTV.", "THE POLICE|CHECKED _CCTV_."), ("No man.", "*NO* MAN."), ("But every night at eleven forty seven...", "BUT AT *11:47*..."), ("my door opened.", "MY DOOR _OPENED_.")], {"breath": True}),
    ("cctv2", "her", [("I stepped out. Looked at the lift.", "I STEPPED OUT.|LOOKED AT|THE *LIFT*."), ("And behind me...", "AND _BEHIND_ ME..."), ("inside my apartment...", "INSIDE MY|APARTMENT..."), ("was him.", "WAS *HIM*.")], {"reveal": True}),

    ("card5", "her", [("Chapter five. The door.", None)], {"pre": 0.6}),
    ("wardrobe", "her", [("Behind my wardrobe...", "BEHIND MY|_WARDROBE_..."), ("a maintenance door.", "A *DOOR*."), ("A passage...", "A PASSAGE..."), ("to six oh four B.", "TO *604B*.")], {"breath": True}),
    ("lair", "her", [("A mattress.", "A _MATTRESS_."), ("And photos of me.", "AND *PHOTOS*|OF ME."), ("Sleeping. Cooking.", "SLEEPING. _COOKING_."), ("Some from before I moved in.", "SOME FROM|*BEFORE* I MOVED IN.")], {}),
    ("wall", "her", [("On the wall...", "ON THE _WALL_..."), ("She always locks it three times.", "SHE ALWAYS|LOCKS IT|*THREE* TIMES.")], {}),
    ("polaroid", "her", [("The last photo was taken that morning.", "THE LAST|_PHOTO_...|THAT *MORNING*."), ("And he was standing...", "HE WAS|STANDING..."), ("right behind me.", "RIGHT *BEHIND* ME.")], {"breath": True, "reveal": True}),

    ("card6", "her", [("Final chapter. One more time.", None)], {"pre": 0.6}),
    ("newhall", "her", [("They never found him.", "THEY NEVER|*FOUND* HIM."), ("I moved out.", "I MOVED _OUT_."), ("Months later...", "*MONTHS* LATER..."), ("a new neighbour stepped out of the lift.", "A NEW|_NEIGHBOUR_...")], {}),
    ("newhall", "neigh", [("Sorry. You missed one.", "\"SORRY.|YOU *MISSED* ONE."), ("Your top lock.", "YOUR _TOP LOCK_.\"")], {}),
    ("lock2", "her", [("I went inside.", "I WENT|_INSIDE_."), ("Lock. Unlock. Lock.", "*LOCK*. UNLOCK. LOCK.")], {}),
    ("lock2", "neigh", [("There. That's better.", "\"THERE. THAT'S *BETTER*.\"")], {"pre": 0.4}),
    ("phone5", "him", [("You can stop looking for me now.", "YOU CAN|STOP *LOOKING*|FOR ME NOW."), ("I'm not in the building anymore.", "I'M NOT IN|THE _BUILDING_|*ANYMORE*.")], {"breath": False}),
    ("twodoors", "her", [("My apartment had two front doors.", "MY APARTMENT|HAD *TWO*|FRONT DOORS."), ("The one I'd just locked...", "THE ONE|I'D JUST _LOCKED_..."), ("and the one behind me.", "AND THE ONE|*BEHIND* ME.")], {"breath": True}),
    ("open", "her", [("It was already open.", "IT WAS|ALREADY *OPEN*.")], {"pre": 0.7}),
    ("outro", "her", [("Follow... for more.", None)], {"pre": 0.8}),
]
