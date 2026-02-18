
# ============================================
# File: core/management/commands/dedupe_animalitos.py
# ============================================
from __future__ import annotations

from collections import defaultdict
from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import AnimalitoResult


class Command(BaseCommand):
    help = (
        "Remove duplicate AnimalitoResult rows by keeping the newest per "
        "(provider, draw_date, draw_time)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what would be deleted, but do not delete anything.",
        )
        parser.add_argument(
            "--keep",
            choices=["newest", "oldest"],
            default="newest",
            help="Which row to keep within duplicates group.",
        )

    def handle(self, *args, **options):
        dry_run: bool = options["dry_run"]
        keep_policy: str = options["keep"]

        qs = AnimalitoResult.objects.all().only(
            "id", "provider_id", "draw_date", "draw_time", "created_at"
        )

        buckets: dict[tuple, list[tuple]] = defaultdict(list)
        for r in qs.iterator(chunk_size=2000):
            key = (r.provider_id, r.draw_date, r.draw_time)
            ts = getattr(r, "created_at", None) or r.id
            buckets[key].append((r.id, ts))

        to_delete: list[int] = []
        dup_groups = 0

        for key, rows in buckets.items():
            if len(rows) <= 1:
                continue

            dup_groups += 1
            rows.sort(key=lambda x: x[1], reverse=(keep_policy == "newest"))
            keep_id = rows[0][0]
            delete_ids = [rid for rid, _ in rows[1:]]
            to_delete.extend(delete_ids)

            if dry_run:
                self.stdout.write(f"[DRY] key={key} keep={keep_id} delete={delete_ids}")

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f"DRY RUN: groups_with_dupes={dup_groups}, would_delete={len(to_delete)}"
                )
            )
            return

        if not to_delete:
            self.stdout.write(self.style.SUCCESS("No duplicates found."))
            return

        with transaction.atomic():
            deleted, _ = AnimalitoResult.objects.filter(id__in=to_delete).delete()

        self.stdout.write(
            self.style.SUCCESS(
                f"Done. groups_with_dupes={dup_groups}, deleted_rows={deleted}"
            )
        )