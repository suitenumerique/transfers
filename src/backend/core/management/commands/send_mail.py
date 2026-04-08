"""Management command to send a test email via Django's email backend."""

import logging

from django.core.mail import send_mail
from django.core.management.base import BaseCommand

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    """Send a test email to verify email configuration."""

    help = "Send a test email to verify email configuration"

    def add_arguments(self, parser):
        parser.add_argument("--from", dest="from_email", required=True)
        parser.add_argument("--to", dest="to_emails", nargs="+", required=True)
        parser.add_argument("--subject", default="Test email from Transferts")
        parser.add_argument("--body", default="This is a test email.")

    def handle(self, *args, **options):
        send_mail(
            subject=options["subject"],
            message=options["body"],
            from_email=options["from_email"],
            recipient_list=options["to_emails"],
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Email sent to {', '.join(options['to_emails'])}"
            )
        )
