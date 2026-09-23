-- A health hold is shown in the phase table as its own block, so the plan
-- history stays honest about the days that were lost.
alter table phases drop constraint phases_kind_check;
alter table phases add constraint phases_kind_check
  check (kind in ('prep','base','build','peak','race','transition','return','hold'));

-- Where each exit criterion came from (reported, measured, pending verification).
alter table health_episodes add column notes text;
