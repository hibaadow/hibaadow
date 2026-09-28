# Sway waitlist: setup guide

You'll do 4 things, about 20 minutes in total:

1. Add your logos
2. Create the database (Supabase)
3. Put the site online (Vercel)
4. Check it works

Everything here is free.

---

## What's in this folder

| File | What it does |
|---|---|
| `index.html` | The waitlist page |
| `privacy.html` | The privacy policy page (at `/privacy`) |
| `styles.css` | Colours, fonts and layout |
| `script.js` | Makes the form work in the browser |
| `api/join.js` | Runs on Vercel's servers and saves sign-ups to your database. Your secret key is only used here, never in the public page. |
| `supabase-setup.sql` | You paste this into Supabase once to create the sign-ups table |
| `vercel.json` | Small settings for Vercel |

---

## Step 0: Put the code on your `main` branch

The site was built on a separate branch called `claude/sway-waitlist-site-cqre21`. Vercel publishes from `main`, so merge it in first:

1. Go to https://github.com/hibaadow/hibaadow
2. If you see a yellow bar saying **"claude/sway-waitlist-site-cqre21 had recent pushes"**, click **Compare & pull request**.
   (No yellow bar? Click **Pull requests** → **New pull request**, set **compare:** to `claude/sway-waitlist-site-cqre21`.)
3. Click **Create pull request**, then **Merge pull request**, then **Confirm merge**.

## Step 1: Add your logos

1. On GitHub, open your repo, then click the **sway-waitlist** folder.
2. Click **Add file** → **Upload files**.
3. Drag in both files. The names must be exactly:
   - `sway_logo_white.png`
   - `sway_girl_profile_picture.png`
4. Click **Commit changes**.

Until you do this, the page shows the word "sway" in white as the logo, so nothing looks broken.

## Step 2: Create the database (Supabase)

1. Go to https://supabase.com and click **Start your project**. Sign up (clicking **Continue with GitHub** is easiest).
2. Click **New project**.
   - **Name:** `sway`
   - **Database password:** click **Generate a password** and save it somewhere safe (you won't need it for this site).
   - **Region:** choose **West EU (Ireland)**. This keeps your users' data in the EU, which is good for GDPR.
   - Click **Create new project** and wait a minute or two.
3. In the left menu, click **SQL Editor** (the `>_` icon).
4. Open `supabase-setup.sql` from this folder on GitHub, click the **copy** icon (two squares, top right of the file), and paste it into the Supabase SQL Editor.
5. Click **Run**. You should see "Success. No rows returned".
6. Now copy two values. Keep this tab open, you'll paste them into Vercel:
   - **Project URL:** click **Project Settings** (gear icon, bottom left) → **Data API**. Copy the **URL** (it looks like `https://abcdefgh.supabase.co`).
   - **Secret key:** in Project Settings click **API Keys**. Under **Secret keys**, click the eye / **Reveal** button and copy the key (starts with `sb_secret_`).
     If you only see "Legacy API keys", copy the one labelled **service_role** instead.

⚠️ The secret key is like a password to your database. Only ever paste it into Vercel (Step 3). Never put it in a file on GitHub, in a message, or on the page.

## Step 3: Put the site online (Vercel)

1. Go to https://vercel.com/signup, choose **Hobby**, and click **Continue with GitHub**.
2. Click **Add New…** → **Project**.
3. Next to **hibaadow**, click **Import**. (If you don't see it, click **Adjust GitHub App Permissions** and allow access to the `hibaadow` repository.)
4. Change these settings on the next screen:
   - **Project Name:** `sway-waitlist` (this becomes your link: `sway-waitlist.vercel.app`; if it's taken, try `joinsway` or similar)
   - **Root Directory:** click **Edit**, pick the **sway-waitlist** folder, click **Continue**. **This one matters. Without it you'll get a "404" page.**
   - **Framework Preset:** leave as **Other**.
   - Open **Environment Variables** and add two:
     | Key | Value |
     |---|---|
     | `SUPABASE_URL` | the Project URL from Step 2 |
     | `SUPABASE_SECRET_KEY` | the secret key from Step 2 |
5. Click **Deploy**. After about 30 seconds you'll see confetti 🎉 and a preview of the site.
6. Click **Continue to Dashboard**. Your public link is under **Domains**, for example `https://sway-waitlist.vercel.app`. That's the link for your TikTok bio.

From now on, every change on the `main` branch (like uploading the logos) goes live by itself within a minute.

## Step 4: Check it works

1. Open your link on your phone and sign up with your own email.
2. In Supabase, click **Table Editor** (the grid icon) → **waitlist**. Your sign-up should be there.
3. Sign up again with the same email. You'll see the thank-you message, and Supabase still has just one row. ✅

If you see "sign-ups aren't working right now", the environment variables are missing or wrong. Fix them in Vercel → your project → **Settings** → **Environment Variables**, then go to **Deployments**, click the **⋯** next to the top one, and choose **Redeploy**.

---

## Seeing your sign-ups

- **See everyone:** Supabase → **Table Editor** → **waitlist**. Each row has the time they signed up (`created_at`, in UTC time, which is the same as Irish winter time).
- **Download as a spreadsheet (CSV):** in that same table, click **Export** (top right), then **Export table as CSV**. It opens in Excel, Google Sheets or Numbers.
- **Sign-ups per city:** Table Editor → **signups_per_city**. It shows each city with its number of sign-ups, biggest first. It groups "dublin", "Dublin" and "DUBLIN " together automatically. You can export this as CSV too.
  (People may still type "NYC" and "New York" differently. Those show as separate rows.)
- **Total count:** shown at the bottom of the waitlist table ("X records").

## Connecting your own domain later (e.g. joinsway.com)

1. Buy the domain from any seller (Namecheap, Porkbun, GoDaddy, or Vercel itself under **Domains**).
2. In Vercel: open your project → **Settings** → **Domains** → type `joinsway.com` → **Add**. Pick the option that also adds `www.joinsway.com`.
3. Vercel shows you 1–2 "DNS records" (a type, a name and a value). Log in to the site you bought the domain from, find **DNS settings**, and add those records exactly as shown.
4. Wait between 10 minutes and a few hours. Vercel shows a green tick when it's working, and sets up the padlock (https) for you.
5. Update your TikTok bio link. The old `.vercel.app` link keeps working too.

(If you buy the domain through Vercel, steps 3–4 happen automatically.)

## Editing text on the page

On GitHub, open `sway-waitlist/index.html`, click the ✏️ pencil icon, change the words, and click **Commit changes**. The live site updates within a minute.

## Good to know

- **Supabase free projects pause after 7 days with no activity.** Sign-ups count as activity, so this only matters if nobody signs up for a week. If it pauses, log in to Supabase and click **Restore project**. No data is lost.
- **Vercel's free Hobby plan is meant for personal and non-commercial projects.** It's fine for a pre-launch waitlist. Once Sway is a business making money, move to the Pro plan.
