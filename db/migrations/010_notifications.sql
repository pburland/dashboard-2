-- Phone notifications (web push).
alter table integrations drop constraint integrations_provider_check;
alter table integrations add constraint integrations_provider_check
  check (provider in ('garmin','oura','hevy','vapid'));      -- vapid: this server's push signing key

create table notifications (
  id          bigint generated always as identity primary key,
  kind        text not null check (kind in ('workout','update','checkin','report','plan','safety','clearance','test')),
  title       text not null,
  body        text not null,
  url         text not null default '/',
  data        jsonb not null default '{}'::jsonb,
  dedupe_key  text unique,                     -- one per (kind, day/session): re-queueing is a no-op
  not_before  timestamptz not null default now(),
  status      text not null default 'queued' check (status in ('queued','sent','skipped','folded','failed')),
  sent_at     timestamptz,
  error       text,
  created_at  timestamptz not null default now()
);
create index on notifications (status, not_before);
alter table notifications enable row level security;

alter table profile add column notification_prefs jsonb not null default
  '{"workout": true, "plan": true, "safety": true, "checkin": true, "report": true, "clearance": true}'::jsonb;
alter table push_subscriptions add column user_agent text;
