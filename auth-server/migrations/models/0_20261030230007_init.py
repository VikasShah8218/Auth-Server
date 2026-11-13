from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE IF NOT EXISTS "aerich" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "version" VARCHAR(255) NOT NULL,
    "app" VARCHAR(100) NOT NULL,
    "content" JSONB NOT NULL
);
CREATE TABLE IF NOT EXISTS "applications" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "key" VARCHAR(32) NOT NULL UNIQUE,
    "name" VARCHAR(128) NOT NULL,
    "description" TEXT,
    "is_active" BOOL NOT NULL,
    "perm_map_version" INT NOT NULL,
    "created_at" TIMESTAMPTZ NOT NULL,
    "updated_at" TIMESTAMPTZ NOT NULL
);
CREATE TABLE IF NOT EXISTS "audit_logs" (
    "id" BIGSERIAL NOT NULL PRIMARY KEY,
    "actor" VARCHAR(64) NOT NULL,
    "action" VARCHAR(64) NOT NULL,
    "target" VARCHAR(128),
    "app" VARCHAR(32),
    "details" JSONB,
    "ip" VARCHAR(45),
    "created_at" TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS "idx_audit_logs_app_4d6266" ON "audit_logs" ("app", "created_at");
CREATE INDEX IF NOT EXISTS "idx_audit_logs_actor_b8aa57" ON "audit_logs" ("actor", "created_at");
COMMENT ON TABLE "audit_logs" IS 'Insert only. A database trigger rejects UPDATE and DELETE.';
CREATE TABLE IF NOT EXISTS "permissions" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "code" VARCHAR(128) NOT NULL,
    "description" TEXT,
    "bit" SMALLINT NOT NULL,
    "retired_at" TIMESTAMPTZ,
    "created_at" TIMESTAMPTZ NOT NULL,
    "updated_at" TIMESTAMPTZ NOT NULL,
    "app_id" INT NOT NULL REFERENCES "applications" ("id") ON DELETE CASCADE,
    CONSTRAINT "uid_permissions_app_id_9a010a" UNIQUE ("app_id", "code"),
    CONSTRAINT "uid_permissions_app_id_540db8" UNIQUE ("app_id", "bit")
);
CREATE TABLE IF NOT EXISTS "roles" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "name" VARCHAR(64) NOT NULL,
    "description" TEXT,
    "created_at" TIMESTAMPTZ NOT NULL,
    "updated_at" TIMESTAMPTZ NOT NULL,
    "app_id" INT NOT NULL REFERENCES "applications" ("id") ON DELETE CASCADE,
    CONSTRAINT "uid_roles_app_id_c9c47b" UNIQUE ("app_id", "name")
);
CREATE TABLE IF NOT EXISTS "role_permissions" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "created_at" TIMESTAMPTZ NOT NULL,
    "permission_id" INT NOT NULL REFERENCES "permissions" ("id") ON DELETE CASCADE,
    "role_id" INT NOT NULL REFERENCES "roles" ("id") ON DELETE CASCADE,
    CONSTRAINT "uid_role_permis_role_id_6a25fe" UNIQUE ("role_id", "permission_id")
);
CREATE TABLE IF NOT EXISTS "users" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "public_id" UUID NOT NULL UNIQUE,
    "username" VARCHAR(64) NOT NULL UNIQUE,
    "email" VARCHAR(254) UNIQUE,
    "first_name" VARCHAR(64),
    "last_name" VARCHAR(64),
    "password_hash" TEXT NOT NULL,
    "is_active" BOOL NOT NULL,
    "is_superuser" BOOL NOT NULL,
    "created_at" TIMESTAMPTZ NOT NULL,
    "updated_at" TIMESTAMPTZ NOT NULL
);
CREATE TABLE IF NOT EXISTS "user_app_states" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "version" INT NOT NULL,
    "app_id" INT NOT NULL REFERENCES "applications" ("id") ON DELETE CASCADE,
    "user_id" INT NOT NULL REFERENCES "users" ("id") ON DELETE CASCADE,
    CONSTRAINT "uid_user_app_st_user_id_cf3cbb" UNIQUE ("user_id", "app_id")
);
COMMENT ON TABLE "user_app_states" IS 'The token \"ver\" claim. Scoped per app, so one app''s change leaves the rest alone.';
CREATE TABLE IF NOT EXISTS "user_roles" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "created_at" TIMESTAMPTZ NOT NULL,
    "role_id" INT NOT NULL REFERENCES "roles" ("id") ON DELETE CASCADE,
    "user_id" INT NOT NULL REFERENCES "users" ("id") ON DELETE CASCADE,
    CONSTRAINT "uid_user_roles_user_id_63f1a8" UNIQUE ("user_id", "role_id")
);"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        """


MODELS_STATE = (
    "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"
    "/SQxs//V7znxFQd0NeV4gOPv4PEZ8rdw=="
)
