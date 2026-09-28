-- Sway waitlist: run this once in Supabase → SQL Editor → New query → Run.

-- 1. The table that stores every sign-up
create table if not exists public.waitlist (
  id            bigint generated always as identity primary key,
  created_at    timestamptz not null default now(),   -- when they signed up
  first_name    text not null,
  email         text not null unique,                 -- one row per email, no duplicates
  city          text not null,
  age_range     text,
  activities    text,                                 -- e.g. "Coffee, Brunch, Walks"
  social_handle text,
  consent       boolean not null default false,
  consent_text  text                                  -- the exact wording they agreed to (GDPR proof)
);

-- 2. Lock it down: nobody on the public internet can read or change it.
--    Only the website's server (using your secret key) can add rows.
alter table public.waitlist enable row level security;
revoke all on public.waitlist from anon, authenticated;

-- 3. A ready-made "sign-ups per city" view you can open any time
create or replace view public.signups_per_city
with (security_invoker = true) as
select
  initcap(lower(trim(city))) as city,
  count(*)                   as signups,
  max(created_at)            as latest_signup
from public.waitlist
group by 1
order by signups desc, city;

revoke all on public.signups_per_city from anon, authenticated;
