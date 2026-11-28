-- Swap button changes get their own source in the change log and proposals.
alter table plan_changes drop constraint if exists plan_changes_source_check;
alter table plan_changes add constraint plan_changes_source_check
  check (source in ('chat','generator','coach','system','checkin','swap'));
alter table plan_proposals drop constraint if exists plan_proposals_source_check;
alter table plan_proposals add constraint plan_proposals_source_check
  check (source in ('chat','system','generator','swap'));

-- The monthly audit agent's reports: its memory between runs. Written only through
-- POST /admin/audit/reports with the read-only audit key (which can do nothing else).
create table audit_reports (
  id          bigint generated always as identity primary key,
  created_at  timestamptz not null default now(),
  title       text not null,
  summary     text not null,                 -- markdown, shown in the Reports tab
  findings    jsonb not null default '[]'::jsonb,   -- [{id, severity, area, text, status}]
  followups   jsonb not null default '[]'::jsonb    -- what the next run should re-check
);
