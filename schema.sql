-- currency-intel-mcp schema (standalone currency-intel Supabase project). Idempotent.
--
-- Tables:
--   fx_latest       — current rate snapshot, base=EUR (pivot), one row per quote
--   fx_rates        — historical daily rates, base=EUR, (date,base,quote)
--   cur_query_usage — per-agent/day free-tier counter (+ cur_claim_free_query)
--   cur_payments    — verified x402 payments ledger (double-spend guard)
--   daily_briefs    — curated daily brief (+ increment_brief_purchase)

-- ── fx_latest (current snapshot) ──────────────────────────────────────────────
create table if not exists fx_latest (
  base        text not null,
  quote       text not null,
  rate        numeric not null,
  as_of       date,
  updated_at  timestamptz not null default now(),
  primary key (base, quote)
);

-- ── fx_rates (historical daily) ───────────────────────────────────────────────
create table if not exists fx_rates (
  date   date not null,
  base   text not null,
  quote  text not null,
  rate   numeric not null,
  primary key (date, base, quote)
);
create index if not exists idx_fxrates_quote_date on fx_rates (quote, date desc);

-- ── cur_query_usage (free-tier counter) ───────────────────────────────────────
create table if not exists cur_query_usage (
  agent_key   text not null,
  day         date not null,
  count       integer not null default 0,
  updated_at  timestamptz not null default now(),
  primary key (agent_key, day)
);

-- ── cur_payments (x402 ledger / double-spend guard) ───────────────────────────
create table if not exists cur_payments (
  tx_signature  text primary key,
  intent        text,
  agent_key     text,
  tool          text,
  amount_usdc   numeric,
  payer_wallet  text,
  recipient     text,
  status        text,
  block_time    bigint,
  created_at    timestamptz not null default now()
);

-- ── daily_briefs ──────────────────────────────────────────────────────────────
create table if not exists daily_briefs (
  brief_date        date primary key,
  brief_data        jsonb not null,
  signal_count      integer not null default 0,
  attestation_hash  text,
  purchase_count    integer not null default 0,
  expires_at        timestamptz,
  created_at        timestamptz not null default now()
);

create or replace function cur_claim_free_query(p_agent_key text, p_day date, p_cap integer)
returns jsonb language plpgsql as $$
declare cur integer; ok boolean;
begin
  insert into cur_query_usage (agent_key, day, count, updated_at)
  values (p_agent_key, p_day, 0, now())
  on conflict (agent_key, day) do nothing;

  select count into cur from cur_query_usage
    where agent_key = p_agent_key and day = p_day for update;

  if cur < p_cap then
    update cur_query_usage set count = count + 1, updated_at = now()
      where agent_key = p_agent_key and day = p_day;
    ok := true; cur := cur + 1;
  else
    ok := false;
  end if;
  return jsonb_build_object('allowed', ok, 'count', cur, 'cap', p_cap);
end;
$$;

create or replace function increment_brief_purchase(p_brief_date date)
returns void language sql as $$
  update daily_briefs set purchase_count = purchase_count + 1 where brief_date = p_brief_date;
$$;
