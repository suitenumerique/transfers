"""Management command to print user emails."""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

User = get_user_model()


class Command(BaseCommand):
    """Print a list of user emails."""

    help = "Print a list of user emails"

    def handle(self, *args, **options):
        users = User.objects.filter(email__isnull=False).exclude(email="")
        user_list = list(users.values_list("email", flat=True))
        user_list.sort()

        if not user_list:
            self.stdout.write(self.style.WARNING("No users found."))
            return

        self.stdout.write(self.style.SUCCESS(f"Found {len(user_list)} user(s):\n"))
        for email in user_list:
            self.stdout.write(email)
