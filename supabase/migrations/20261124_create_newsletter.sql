create table if not exists public.newsletter_subscribers (
  id uuid primary key default gen_random_uuid(),
  full_name text not null check (char_length(btrim(full_name)) between 2 and 120),
  email text not null check (char_length(email) between 3 and 320),
  normalized_email text not null unique check (char_length(normalized_email) between 3 and 320),
  status text not null default 'na_cekanju'
    check (status in ('na_cekanju','aktivan','odjavljen','neispravna_dostava')),
  consent_given boolean not null default false,
  consent_given_at timestamptz,
  email_confirmed_at timestamptz,
  unsubscribed_at timestamptz,
  registered_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.newsletter_campaigns (
  id uuid primary key default gen_random_uuid(),
  title text not null check (char_length(btrim(title)) between 1 and 160),
  email_subject text not null check (char_length(btrim(email_subject)) between 1 and 160),
  html_content text not null,
  status text not null default 'nacrt'
    check (status in ('nacrt','zakazana','poslana','otkazana')),
  scheduled_at timestamptz,
  sent_at timestamptz,
  created_at timestamptz not null default now(),
  created_by uuid references auth.users(id)
);

create table if not exists public.newsletter_email_logs (
  id uuid primary key default gen_random_uuid(),
  subscriber_id uuid references public.newsletter_subscribers(id) on delete set null,
  campaign_id uuid references public.newsletter_campaigns(id) on delete set null,
  email_type text not null
    check (email_type in ('potvrda','aktivacija','kampanja','odjava','test')),
  provider_message_id text,
  delivery_status text not null default 'na_cekanju'
    check (delivery_status in ('na_cekanju','poslano','dostavljeno','neispravna_adresa','neuspjelo')),
  error_message text,
  sent_at timestamptz not null default now()
);

create table if not exists public.newsletter_confirmation_tokens (
  id uuid primary key default gen_random_uuid(),
  subscriber_id uuid not null references public.newsletter_subscribers(id) on delete cascade,
  token_hash text not null unique check (char_length(token_hash) = 64),
  expires_at timestamptz not null,
  used_at timestamptz,
  created_at timestamptz not null default now()
);

create table if not exists public.newsletter_unsubscribe_tokens (
  id uuid primary key default gen_random_uuid(),
  subscriber_id uuid not null unique references public.newsletter_subscribers(id) on delete cascade,
  security_token text not null unique check (char_length(security_token) >= 32),
  created_at timestamptz not null default now()
);

create table if not exists public.newsletter_admin_activity (
  id uuid primary key default gen_random_uuid(),
  admin_user_id uuid references auth.users(id),
  action text not null,
  details jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists public.newsletter_admins (
  user_id uuid primary key references auth.users(id) on delete cascade,
  email text not null unique,
  created_at timestamptz not null default now()
);

create index if not exists idx_newsletter_subscribers_status on public.newsletter_subscribers(status);
create index if not exists idx_newsletter_subscribers_registered on public.newsletter_subscribers(registered_at desc);
create index if not exists idx_newsletter_subscribers_email on public.newsletter_subscribers(normalized_email);
create index if not exists idx_newsletter_campaigns_status on public.newsletter_campaigns(status);
create index if not exists idx_newsletter_campaigns_schedule on public.newsletter_campaigns(scheduled_at);
create index if not exists idx_newsletter_email_logs_subscriber on public.newsletter_email_logs(subscriber_id);
create index if not exists idx_newsletter_email_logs_campaign on public.newsletter_email_logs(campaign_id);
create index if not exists idx_newsletter_confirmation_tokens_subscriber on public.newsletter_confirmation_tokens(subscriber_id);
create index if not exists idx_newsletter_confirmation_tokens_expiry on public.newsletter_confirmation_tokens(expires_at);

create or replace function public.set_newsletter_updated_at()
returns trigger
language plpgsql
set search_path = public
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists trg_newsletter_subscribers_updated_at on public.newsletter_subscribers;
create trigger trg_newsletter_subscribers_updated_at
before update on public.newsletter_subscribers
for each row execute function public.set_newsletter_updated_at();

alter table public.newsletter_subscribers enable row level security;
alter table public.newsletter_campaigns enable row level security;
alter table public.newsletter_email_logs enable row level security;
alter table public.newsletter_confirmation_tokens enable row level security;
alter table public.newsletter_unsubscribe_tokens enable row level security;
alter table public.newsletter_admin_activity enable row level security;
alter table public.newsletter_admins enable row level security;

create or replace function public.is_newsletter_admin()
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select exists (
    select 1
    from public.newsletter_admins
    where user_id = auth.uid()
  );
$$;

revoke execute on function public.is_newsletter_admin() from public, anon;
grant execute on function public.is_newsletter_admin() to authenticated;

revoke all on public.newsletter_subscribers from anon, authenticated;
revoke all on public.newsletter_campaigns from anon, authenticated;
revoke all on public.newsletter_email_logs from anon, authenticated;
revoke all on public.newsletter_confirmation_tokens from anon, authenticated;
revoke all on public.newsletter_unsubscribe_tokens from anon, authenticated;
revoke all on public.newsletter_admin_activity from anon, authenticated;
revoke all on public.newsletter_admins from anon, authenticated;

grant select, insert, update, delete on public.newsletter_subscribers to authenticated;
grant select, insert, update, delete on public.newsletter_campaigns to authenticated;
grant select, insert, update, delete on public.newsletter_email_logs to authenticated;
grant select, insert, update, delete on public.newsletter_confirmation_tokens to authenticated;
grant select, insert, update, delete on public.newsletter_unsubscribe_tokens to authenticated;
grant select, insert, update, delete on public.newsletter_admin_activity to authenticated;
grant select on public.newsletter_admins to authenticated;

drop policy if exists newsletter_subscribers_admin_all on public.newsletter_subscribers;
create policy newsletter_subscribers_admin_all
  on public.newsletter_subscribers for all to authenticated
  using (public.is_newsletter_admin())
  with check (public.is_newsletter_admin());

drop policy if exists newsletter_campaigns_admin_all on public.newsletter_campaigns;
create policy newsletter_campaigns_admin_all
  on public.newsletter_campaigns for all to authenticated
  using (public.is_newsletter_admin())
  with check (public.is_newsletter_admin());

drop policy if exists newsletter_email_logs_admin_all on public.newsletter_email_logs;
create policy newsletter_email_logs_admin_all
  on public.newsletter_email_logs for all to authenticated
  using (public.is_newsletter_admin())
  with check (public.is_newsletter_admin());

drop policy if exists newsletter_confirmation_tokens_admin_all on public.newsletter_confirmation_tokens;
create policy newsletter_confirmation_tokens_admin_all
  on public.newsletter_confirmation_tokens for all to authenticated
  using (public.is_newsletter_admin())
  with check (public.is_newsletter_admin());

drop policy if exists newsletter_unsubscribe_tokens_admin_all on public.newsletter_unsubscribe_tokens;
create policy newsletter_unsubscribe_tokens_admin_all
  on public.newsletter_unsubscribe_tokens for all to authenticated
  using (public.is_newsletter_admin())
  with check (public.is_newsletter_admin());

drop policy if exists newsletter_admin_activity_admin_all on public.newsletter_admin_activity;
create policy newsletter_admin_activity_admin_all
  on public.newsletter_admin_activity for all to authenticated
  using (public.is_newsletter_admin())
  with check (public.is_newsletter_admin());

drop policy if exists newsletter_admins_admin_select on public.newsletter_admins;
create policy newsletter_admins_admin_select
  on public.newsletter_admins for select to authenticated
  using (public.is_newsletter_admin());
