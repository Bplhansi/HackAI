-- CareNest AI: run this once in Supabase -> SQL Editor -> New query -> Run.

create table if not exists medications (
  id                  uuid primary key default gen_random_uuid(),
  user_id             uuid not null,           -- Supabase Auth user id (or the demo user id)
  name                text not null,
  quantity_collected  integer not null check (quantity_collected > 0),
  collection_date     date not null,
  daily_quantity      numeric not null check (daily_quantity > 0),
  estimated_end_date  date not null,
  created_at          timestamptz not null default now()
);

create table if not exists reminders (
  id             uuid primary key default gen_random_uuid(),
  user_id        uuid not null,
  medication_id  uuid not null references medications(id) on delete cascade,
  remind_on      date not null,
  kind           text not null check (kind in ('14_day', '7_day', 'repeat')),
  status         text not null default 'pending'
                 check (status in ('pending', 'acknowledged', 'snoozed', 'cancelled')),
  snoozed_until  date,
  acknowledged_at date,
  created_at     timestamptz not null default now()
);

create index if not exists medications_user_idx on medications (user_id);
create index if not exists reminders_user_idx on reminders (user_id, status);

-- Block direct access from the browser with the public (anon) key.
-- Only our backend, using the service-role key, can read or write these tables.
alter table medications enable row level security;
alter table reminders enable row level security;
