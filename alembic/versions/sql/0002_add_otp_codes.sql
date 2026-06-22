create table otp_codes (
  id           uuid primary key default gen_random_uuid(),
  phone_number text not null,
  code_hash    text not null,
  expires_at   timestamptz not null,
  attempts     int not null default 0,
  created_at   timestamptz not null default now()
);

create index idx_otp_phone on otp_codes(phone_number);
alter table otp_codes enable row level security;
