-- اجرا در Supabase → SQL Editor

create table if not exists admins (
    user_id     bigint primary key,
    level       text not null default 'admin',   -- 'owner' | 'admin'
    added_by    bigint,
    created_at  timestamptz default now()
);

create table if not exists allowed_users (
    user_id     bigint primary key,
    added_by    bigint,
    created_at  timestamptz default now()
);

create table if not exists force_channels (
    id          bigserial primary key,
    chat_id     text not null,        -- @username یا -100xxxxxxxxxx
    title       text,
    created_at  timestamptz default now()
);

create table if not exists posts (
    id          bigserial primary key,
    creator_id  bigint not null,
    content_type text not null,       -- text | photo | video | document
    file_id     text,
    caption     text,
    buttons     jsonb not null default '[]',   -- [{"text": "...", "action": "vote|url|reply"}]
    active      boolean default true,
    created_at  timestamptz default now()
);

create table if not exists votes (
    post_id     bigint not null references posts(id) on delete cascade,
    user_id     bigint not null,
    button_index int not null,
    voted_at    timestamptz default now(),
    primary key (post_id, user_id)
);

create table if not exists source_channels (
    id          bigserial primary key,
    chat_id     text not null,
    title       text,
    created_at  timestamptz default now()
);
