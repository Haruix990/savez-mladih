create table if not exists public.social_posts (
  id uuid primary key default gen_random_uuid(),
  platform text not null check (platform in ('TikTok', 'Instagram')),
  post_url text not null,
  title text not null,
  description text not null default '',
  created_at timestamptz not null default now()
);

alter table public.social_posts enable row level security;

grant select, insert, delete on public.social_posts to authenticated;

create policy social_posts_admin_select
  on public.social_posts
  for select
  to authenticated
  using ((auth.jwt() ->> 'email') = 'zeleneberetke.savezmladihsg@gmail.com');

create policy social_posts_admin_insert
  on public.social_posts
  for insert
  to authenticated
  with check ((auth.jwt() ->> 'email') = 'zeleneberetke.savezmladihsg@gmail.com');

create policy social_posts_admin_delete
  on public.social_posts
  for delete
  to authenticated
  using ((auth.jwt() ->> 'email') = 'zeleneberetke.savezmladihsg@gmail.com');
