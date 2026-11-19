import os
import sys
from pathlib import Path

def run_migrations(db_url: str):
    import psycopg

    migrations_dir = Path(__file__).parent.parent / "supabase" / "migrations"
    migration_files = sorted(migrations_dir.glob("*.sql"))

    if not migration_files:
        print("No migration files found in supabase/migrations/")
        return False

    print(f"Connecting to database...")
    try:
        with psycopg.connect(db_url, autocommit=True, connect_timeout=10) as conn:
            print("Connected successfully!")
            with conn.cursor() as cur:
                for sql_file in migration_files:
                    print(f"Applying {sql_file.name}...")
                    sql_content = sql_file.read_text(encoding="utf-8")
                    cur.execute(sql_content)
                    print(f"  ✓ {sql_file.name} applied successfully.")
        print("\nAll database migrations applied successfully!")
        return True
    except Exception as exc:
        print(f"Migration error: {exc}", file=sys.stderr)
        return False

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent.parent))
    if len(sys.argv) > 1:
        url = sys.argv[1]
    else:
        from backend.app.config.settings import settings
        url = settings.database_url
    if not url:
        print("Usage: python apply_migrations.py <DATABASE_URL>")
        sys.exit(1)
    success = run_migrations(url)
    sys.exit(0 if success else 1)
