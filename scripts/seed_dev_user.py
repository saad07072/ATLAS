import sys
import json
sys.path.insert(0, ".")
import psycopg
from backend.app.config.settings import settings

DEV_USERS = [
    {
        "id": "96cbc646-5fef-4a35-961f-713701bd7a79",
        "email": "developer@atlas.local",
        "raw_user_meta_data": json.dumps({"name": "ATLAS Developer"}),
    },
    {
        "id": "ef3e7347-a8e9-4d63-90cf-a21d5c855515",
        "email": "test-user-a@atlas.local",
        "raw_user_meta_data": json.dumps({"name": "Test User A"}),
    },
    {
        "id": "43ad3973-5d96-4608-8b7b-3e774106429a",
        "email": "test-user-b@atlas.local",
        "raw_user_meta_data": json.dumps({"name": "Test User B"}),
    },
]

def seed_users():
    print(f"Connecting to database to seed dev users...")
    with psycopg.connect(settings.database_url, connect_timeout=10) as conn:
        with conn.cursor() as cur:
            for user in DEV_USERS:
                cur.execute(
                    """
                    INSERT INTO auth.users (
                        instance_id,
                        id,
                        aud,
                        role,
                        email,
                        raw_app_meta_data,
                        raw_user_meta_data,
                        is_super_admin,
                        created_at,
                        updated_at
                    ) VALUES (
                        '00000000-0000-0000-0000-000000000000',
                        %(id)s::uuid,
                        'authenticated',
                        'authenticated',
                        %(email)s,
                        '{"provider": "email", "providers": ["email"]}'::jsonb,
                        %(raw_user_meta_data)s::jsonb,
                        false,
                        NOW(),
                        NOW()
                    )
                    ON CONFLICT (id) DO UPDATE
                    SET email = EXCLUDED.email,
                        raw_user_meta_data = EXCLUDED.raw_user_meta_data,
                        updated_at = NOW();
                    """,
                    user,
                )
                print(f"Seeded user: {user['id']} ({user['email']})")
        conn.commit()
    print("All dev users successfully seeded into auth.users.")

if __name__ == "__main__":
    seed_users()
