# Generated by Django 5.0.8 on 2024-08-22 19:52

import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models

import sentry.db.models.fields.bounded
import sentry.db.models.fields.foreignkey
import sentry.db.models.fields.hybrid_cloud_foreign_key
import sentry.db.models.fields.jsonfield
from sentry.new_migrations.migrations import CheckedMigration


class Migration(CheckedMigration):
    # This flag is used to mark that a migration shouldn't be automatically run in production.
    # This should only be used for operations where it's safe to run the migration after your
    # code has deployed. So this should not be used for most operations that alter the schema
    # of a table.
    # Here are some things that make sense to mark as post deployment:
    # - Large data migrations. Typically we want these to be run manually so that they can be
    #   monitored and not block the deploy for a long period of time while they run.
    # - Adding indexes to large tables. Since this can take a long time, we'd generally prefer to
    #   run this outside deployments so that we don't block them. Note that while adding an index
    #   is a schema change, it's completely safe to run the operation after the code has deployed.
    # Once deployed, run these manually via: https://develop.sentry.dev/database-migrations/#migration-deployment

    is_post_deployment = False

    dependencies = [
        ("sentry", "0751_grouphashmetadata_use_one_to_one_field_for_grouphash"),
    ]

    operations = [
        migrations.CreateModel(
            name="NotificationHistory",
            fields=[
                (
                    "id",
                    sentry.db.models.fields.bounded.BoundedBigAutoField(
                        primary_key=True, serialize=False
                    ),
                ),
                ("date_updated", models.DateTimeField(default=django.utils.timezone.now)),
                ("date_added", models.DateTimeField(default=django.utils.timezone.now, null=True)),
                (
                    "user_id",
                    sentry.db.models.fields.hybrid_cloud_foreign_key.HybridCloudForeignKey(
                        "sentry.User", db_index=True, null=True, on_delete="CASCADE"
                    ),
                ),
                ("title", models.CharField()),
                ("description", models.CharField()),
                ("status", models.CharField()),
                ("source", models.CharField()),
                ("content", sentry.db.models.fields.jsonfield.JSONField(default={})),
                (
                    "team",
                    sentry.db.models.fields.foreignkey.FlexibleForeignKey(
                        null=True, on_delete=django.db.models.deletion.CASCADE, to="sentry.team"
                    ),
                ),
            ],
            options={
                "db_table": "sentry_notificationhistory",
            },
        ),
        migrations.AddConstraint(
            model_name="notificationhistory",
            constraint=models.CheckConstraint(
                check=models.Q(
                    models.Q(("user_id__isnull", True), ("team__isnull", False)),
                    models.Q(("user_id__isnull", False), ("team__isnull", True)),
                    _connector="OR",
                ),
                name="user_xor_team_required",
            ),
        ),
    ]
