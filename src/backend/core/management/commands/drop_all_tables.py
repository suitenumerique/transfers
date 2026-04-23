"""Drop all tables in the public schema of the PostgreSQL database."""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection

# Any env that may hold real user data — anything other than dev/test.
# Guard raises CommandError (exit 1) instead of printing + returning 0 so
# a chained deploy script fails loudly rather than silently proceeding.
FORBIDDEN_ENVIRONMENTS = {"production", "staging"}


class Command(BaseCommand):
    """Drop all tables in the public schema of the PostgreSQL database."""

    help = "Drops all tables in the public schema of the PostgreSQL database."

    def handle(self, *args, **options):
        """Drop all tables in the public schema of the PostgreSQL database."""

        env = settings.ENVIRONMENT
        if env in FORBIDDEN_ENVIRONMENTS:
            raise CommandError(
                f"drop_all_tables refuses to run in '{env}'. "
                f"Allowed environments: any except {sorted(FORBIDDEN_ENVIRONMENTS)}."
            )

        self.stdout.write("Dropping all tables...")

        with connection.cursor() as cursor:
            cursor.execute("""
                DO $$
                DECLARE
                    r RECORD;
                BEGIN
                    FOR r IN (SELECT tablename FROM pg_tables WHERE schemaname = 'public') LOOP
                        EXECUTE 'DROP TABLE IF EXISTS public.' || quote_ident(r.tablename) || ' CASCADE';
                    END LOOP;
                END
                $$;
            """)

        self.stdout.write(self.style.SUCCESS("All tables dropped successfully."))
