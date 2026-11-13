from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE IF NOT EXISTS "signing_keys" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "kid" VARCHAR(64) NOT NULL UNIQUE,
    "algorithm" VARCHAR(16) NOT NULL,
    "encrypted_private_key" TEXT NOT NULL,
    "public_jwk" JSONB NOT NULL,
    "status" VARCHAR(16) NOT NULL,
    "activated_at" TIMESTAMPTZ,
    "not_after" TIMESTAMPTZ,
    "created_at" TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS "idx_signing_key_status_3f7a12" ON "signing_keys" ("status");
        CREATE TABLE IF NOT EXISTS "app_event_counters" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "last_seq" BIGINT NOT NULL,
    "app_id" INT NOT NULL UNIQUE REFERENCES "applications" ("id") ON DELETE CASCADE
);
COMMENT ON TABLE "app_event_counters" IS 'The last sequence number per app. Updating this row inside the publishing';
        CREATE TABLE IF NOT EXISTS "outbox_events" (
    "id" BIGSERIAL NOT NULL PRIMARY KEY,
    "seq" BIGINT NOT NULL,
    "type" VARCHAR(64) NOT NULL,
    "payload" JSONB NOT NULL,
    "created_at" TIMESTAMPTZ NOT NULL,
    "app_id" INT NOT NULL REFERENCES "applications" ("id") ON DELETE CASCADE,
    CONSTRAINT "uid_outbox_even_app_id_487769" UNIQUE ("app_id", "seq")
);
CREATE INDEX IF NOT EXISTS "idx_outbox_even_created_a91cde" ON "outbox_events" ("created_at");
        CREATE TABLE IF NOT EXISTS "mfa_factors" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "public_id" UUID NOT NULL UNIQUE,
    "type" VARCHAR(16) NOT NULL,
    "name" VARCHAR(64),
    "confirmed_at" TIMESTAMPTZ,
    "encrypted_secret" TEXT,
    "last_used_step" BIGINT,
    "credential_id" VARCHAR(512) UNIQUE,
    "public_key" TEXT,
    "sign_count" BIGINT NOT NULL,
    "created_at" TIMESTAMPTZ NOT NULL,
    "user_id" INT NOT NULL REFERENCES "users" ("id") ON DELETE CASCADE
);
        CREATE TABLE IF NOT EXISTS "sessions" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "public_id" UUID NOT NULL UNIQUE,
    "token_hash" VARCHAR(64) NOT NULL UNIQUE,
    "auth_time" TIMESTAMPTZ NOT NULL,
    "amr" JSONB NOT NULL,
    "ip" VARCHAR(45),
    "user_agent" VARCHAR(256),
    "expires_at" TIMESTAMPTZ NOT NULL,
    "revoked_at" TIMESTAMPTZ,
    "created_at" TIMESTAMPTZ NOT NULL,
    "user_id" INT NOT NULL REFERENCES "users" ("id") ON DELETE CASCADE
);
COMMENT ON TABLE "sessions" IS 'One SSO login. Its public_id is the token \"sid\" claim.';
        CREATE TABLE IF NOT EXISTS "bff_sessions" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "handle_hash" VARCHAR(64) NOT NULL UNIQUE,
    "encrypted_access_token" TEXT NOT NULL,
    "encrypted_refresh_token" TEXT NOT NULL,
    "access_expires_at" TIMESTAMPTZ NOT NULL,
    "csrf_token" VARCHAR(64) NOT NULL,
    "expires_at" TIMESTAMPTZ NOT NULL,
    "session_id" INT NOT NULL REFERENCES "sessions" ("id") ON DELETE CASCADE
);
COMMENT ON TABLE "bff_sessions" IS 'The console''s server-side session. The browser holds only an opaque cookie.';
        CREATE TABLE IF NOT EXISTS "oauth_clients" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "client_id" VARCHAR(128) NOT NULL UNIQUE,
    "name" VARCHAR(128) NOT NULL,
    "type" VARCHAR(16) NOT NULL,
    "secret_hash" TEXT,
    "redirect_uris" JSONB NOT NULL,
    "scopes" JSONB NOT NULL,
    "audiences" JSONB NOT NULL,
    "is_active" BOOL NOT NULL,
    "version" INT NOT NULL,
    "created_at" TIMESTAMPTZ NOT NULL,
    "updated_at" TIMESTAMPTZ NOT NULL,
    "app_id" INT NOT NULL REFERENCES "applications" ("id") ON DELETE CASCADE
);
        CREATE TABLE IF NOT EXISTS "downstream_cursors" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "instance_id" VARCHAR(128) NOT NULL,
    "last_acked_seq" BIGINT NOT NULL,
    "last_seen_at" TIMESTAMPTZ NOT NULL,
    "client_id" INT NOT NULL REFERENCES "oauth_clients" ("id") ON DELETE CASCADE,
    CONSTRAINT "uid_downstream__client__a74c3c" UNIQUE ("client_id", "instance_id")
);
COMMENT ON TABLE "downstream_cursors" IS 'What one running instance of a downstream server has applied.';
        CREATE TABLE IF NOT EXISTS "authorization_codes" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "code_hash" VARCHAR(64) NOT NULL UNIQUE,
    "family_id" UUID NOT NULL,
    "pkce_challenge" VARCHAR(128) NOT NULL,
    "redirect_uri" TEXT NOT NULL,
    "scope" TEXT NOT NULL,
    "nonce" VARCHAR(256),
    "expires_at" TIMESTAMPTZ NOT NULL,
    "used_at" TIMESTAMPTZ,
    "client_id" INT NOT NULL REFERENCES "oauth_clients" ("id") ON DELETE CASCADE,
    "session_id" INT NOT NULL REFERENCES "sessions" ("id") ON DELETE CASCADE
);
        CREATE TABLE IF NOT EXISTS "refresh_tokens" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "token_hash" VARCHAR(64) NOT NULL UNIQUE,
    "family_id" UUID NOT NULL,
    "scope" TEXT NOT NULL,
    "expires_at" TIMESTAMPTZ NOT NULL,
    "used_at" TIMESTAMPTZ,
    "revoked_at" TIMESTAMPTZ,
    "created_at" TIMESTAMPTZ NOT NULL,
    "client_id" INT NOT NULL REFERENCES "oauth_clients" ("id") ON DELETE CASCADE,
    "session_id" INT NOT NULL REFERENCES "sessions" ("id") ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS "idx_refresh_tok_family__59d0e5" ON "refresh_tokens" ("family_id");"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        DROP TABLE IF EXISTS "signing_keys";
        DROP TABLE IF EXISTS "app_event_counters";
        DROP TABLE IF EXISTS "bff_sessions";
        DROP TABLE IF EXISTS "oauth_clients";
        DROP TABLE IF EXISTS "downstream_cursors";
        DROP TABLE IF EXISTS "outbox_events";
        DROP TABLE IF EXISTS "refresh_tokens";
        DROP TABLE IF EXISTS "authorization_codes";
        DROP TABLE IF EXISTS "mfa_factors";
        DROP TABLE IF EXISTS "sessions";"""


MODELS_STATE = (
    "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"
    "Y9iw2pWqxnhkfqcj3+7f+izUMA"
)
