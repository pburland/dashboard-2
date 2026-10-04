-- DEXA and metabolic-rate results.
alter table body_metrics
  add column lean_lb  real,
  add column fat_lb   real,
  add column bmd      real,              -- g/cm², whole body
  add column detail   jsonb not null default '{}'::jsonb;

alter table profile
  add column rmr_kcal         integer,   -- measured resting energy expenditure
  add column rmr_measured_on  date,
  add column rmr_note         text;
