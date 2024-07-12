from __future__ import annotations

from operator import itemgetter
from typing import NotRequired, TypedDict
from unittest.mock import patch

import pytest
from django.apps import apps
from django.db.models import Max, QuerySet

from sentry.backup.scopes import RelocationScope
from sentry.db.models import Model, region_silo_model
from sentry.db.models.fields.hybrid_cloud_foreign_key import HybridCloudForeignKey
from sentry.discover.models import DiscoverSavedQuery
from sentry.models.group import Group
from sentry.models.integrations.external_issue import ExternalIssue
from sentry.models.integrations.integration import Integration
from sentry.models.organization import Organization
from sentry.models.outbox import ControlOutbox, OutboxScope, outbox_context
from sentry.models.project import Project
from sentry.models.savedsearch import SavedSearch
from sentry.models.tombstone import RegionTombstone
from sentry.monitors.models import Monitor
from sentry.silo.base import SiloMode
from sentry.tasks.deletion.hybrid_cloud import (
    WatermarkBatch,
    get_ids_cross_db_for_row_watermark,
    get_ids_cross_db_for_tombstone_watermark,
    get_watermark,
    schedule_hybrid_cloud_foreign_key_jobs,
    schedule_hybrid_cloud_foreign_key_jobs_control,
    set_watermark,
)
from sentry.testutils.cases import TestCase
from sentry.testutils.factories import Factories
from sentry.testutils.helpers import override_options
from sentry.testutils.helpers.task_runner import BurstTaskRunner
from sentry.testutils.outbox import outbox_runner
from sentry.testutils.pytest.fixtures import django_db_all
from sentry.testutils.silo import (
    assume_test_silo_mode,
    assume_test_silo_mode_of,
    control_silo_test,
    region_silo_test,
)
from sentry.types.region import find_regions_for_user
from sentry.users.models.user import User


@region_silo_model
class DoNothingIntegrationModel(Model):
    __relocation_scope__ = RelocationScope.Excluded
    integration_id = HybridCloudForeignKey("sentry.Integration", on_delete="DO_NOTHING")

    class Meta:
        app_label = "fixtures"


@pytest.fixture(autouse=True)
def batch_size_one():
    with (
        patch("sentry.deletions.base.ModelDeletionTask.DEFAULT_QUERY_LIMIT", new=1),
        patch("sentry.tasks.deletion.hybrid_cloud.get_batch_size", return_value=1),
    ):
        yield


def reset_watermarks():
    """
    Reset watermarks to simulate that we are 'caught up'
    Without this, the records generated by tests elsewhere in CI
    result in the delta between max(id) and 0 is too wide. Because
    we also mock the batch size to 1 in this module we run out of stack
    frames spawning celery jobs inside of each other (which are run immediately).
    """
    silo_mode = SiloMode.get_current_mode()
    for app_models in apps.all_models.values():
        for model in app_models.values():
            if not hasattr(model._meta, "silo_limit"):
                continue
            if silo_mode not in model._meta.silo_limit.modes:
                continue
            for field in model._meta.fields:
                if not isinstance(field, HybridCloudForeignKey):
                    continue
                max_val = model.objects.aggregate(Max("id"))["id__max"] or 0
                set_watermark("tombstone", field, max_val, "abc123")
                set_watermark("row", field, max_val, "abc123")


@pytest.fixture
def saved_search_owner_id_field():
    return SavedSearch._meta.get_field("owner_id")


@django_db_all
def test_no_work_is_no_op(task_runner, saved_search_owner_id_field):
    reset_watermarks()

    # Transaction id should not change when no processing occurs.  (this would happen if setting the next cursor
    # to the same, previous value.)
    level, tid = get_watermark("tombstone", saved_search_owner_id_field)
    assert level == 0

    with task_runner():
        schedule_hybrid_cloud_foreign_key_jobs()

    assert get_watermark("tombstone", saved_search_owner_id_field) == (0, tid)


@django_db_all
def test_watermark_and_transaction_id(task_runner, saved_search_owner_id_field):
    _, tid1 = get_watermark("tombstone", saved_search_owner_id_field)
    # TODO: Add another test to validate the tid is unique per field

    _, tid2 = get_watermark("row", saved_search_owner_id_field)

    assert tid1
    assert tid2
    assert tid1 != tid2

    set_watermark("tombstone", saved_search_owner_id_field, 5, tid1)
    wm, new_tid1 = get_watermark("tombstone", saved_search_owner_id_field)

    assert new_tid1 != tid1
    assert wm == 5

    assert get_watermark("tombstone", saved_search_owner_id_field) == (wm, new_tid1)


@assume_test_silo_mode(SiloMode.MONOLITH)
def setup_deletable_objects(
    count=1, send_tombstones=True, u_id=None
) -> tuple[QuerySet, ControlOutbox]:
    if u_id is None:
        u = Factories.create_user()
        u_id = u.id
        with outbox_context(flush=False):
            u.delete()

    for i in range(count):
        Factories.create_saved_search(f"s-{i}", owner_id=u_id)

    for region_name in find_regions_for_user(u_id):
        shard = ControlOutbox(
            shard_scope=OutboxScope.USER_SCOPE, shard_identifier=u_id, region_name=region_name
        )
        if send_tombstones:
            shard.drain_shard()

        return SavedSearch.objects.filter(owner_id=u_id), shard
    assert False, "find_regions_for_user could not determine a region for production."


@django_db_all
@override_options({"hybrid_cloud.allow_cross_db_tombstones": True})
def test_region_processing(task_runner):
    reset_watermarks()

    # Assume we have two groups of objects
    # Both of them have been deleted, but only the first set has their tombstones sent yet.
    results1, shard1 = setup_deletable_objects(10)
    results2, shard2 = setup_deletable_objects(10, send_tombstones=False)

    # Test validation
    assert results1.exists()
    assert results2.exists()

    # Processing now only removes the first set
    with BurstTaskRunner() as burst:
        schedule_hybrid_cloud_foreign_key_jobs()

        burst()

    assert not results1.exists()
    assert results2.exists()

    # Processing after the tombstones arrives, still converges later.
    with assume_test_silo_mode(SiloMode.MONOLITH):
        shard2.drain_shard()
    with task_runner():
        schedule_hybrid_cloud_foreign_key_jobs()
    assert not results2.exists()

    # Processing for a new record created after its tombstone is processed, still converges.
    results3, shard3 = setup_deletable_objects(10, u_id=shard1.object_identifier)
    assert results3.exists()
    with task_runner():
        schedule_hybrid_cloud_foreign_key_jobs()
    assert not results3.exists()


@django_db_all
@control_silo_test
def test_control_processing(task_runner):
    reset_watermarks()

    with assume_test_silo_mode(SiloMode.CONTROL):
        results, _ = setup_deletable_objects(10)
        with BurstTaskRunner() as burst:
            schedule_hybrid_cloud_foreign_key_jobs_control()

            burst()

        # Do not process
        assert results.exists()


def setup_deletion_test():
    user = Factories.create_user()
    organization = Factories.create_organization(owner=user)
    project = Factories.create_project(organization=organization)
    integration = Factories.create_integration(organization=organization, external_id="123")
    group = Factories.create_group(project=project)
    external_issue = Factories.create_integration_external_issue(
        group=group, integration=integration, key="abc123"
    )
    saved_query = DiscoverSavedQuery.objects.create(
        name="disco-query",
        organization=organization,
        created_by_id=user.id,
    )
    return {
        "user": user,
        "organization": organization,
        "project": project,
        "integration": integration,
        "group": group,
        "external_issue": external_issue,
        "saved_query": saved_query,
    }


@django_db_all
@override_options({"hybrid_cloud.allow_cross_db_tombstones": True})
def test_cascade_deletion_behavior(task_runner):
    data = setup_deletion_test()
    integration = data["integration"]
    external_issue = data["external_issue"]

    integration_id = integration.id
    with assume_test_silo_mode(SiloMode.CONTROL), outbox_runner():
        integration.delete()

        assert not Integration.objects.filter(id=integration_id).exists()

    with BurstTaskRunner() as burst:
        schedule_hybrid_cloud_foreign_key_jobs()

        burst()

    # Deletion cascaded
    assert not ExternalIssue.objects.filter(id=external_issue.id).exists()


@django_db_all
@override_options({"hybrid_cloud.allow_cross_db_tombstones": True})
def test_do_nothing_deletion_behavior(task_runner):
    data = setup_deletion_test()
    integration = data["integration"]

    integration_id = integration.id
    model = DoNothingIntegrationModel.objects.create(integration_id=integration_id)

    with assume_test_silo_mode(SiloMode.CONTROL), outbox_runner():
        integration.delete()

        assert not Integration.objects.filter(id=integration_id).exists()

    with BurstTaskRunner() as burst:
        schedule_hybrid_cloud_foreign_key_jobs()

        burst()

    # Deletion did nothing
    model = DoNothingIntegrationModel.objects.get(id=model.id)
    assert model.integration_id == integration_id


@django_db_all
@override_options({"hybrid_cloud.allow_cross_db_tombstones": True})
def test_set_null_deletion_behavior(task_runner):
    data = setup_deletion_test()
    user = data["user"]
    saved_query = data["saved_query"]

    user_id = user.id
    with assume_test_silo_mode(SiloMode.CONTROL), outbox_runner():
        user.delete()

        assert not User.objects.filter(id=user_id).exists()

    with BurstTaskRunner() as burst:
        schedule_hybrid_cloud_foreign_key_jobs()

        burst()

    # Deletion set field to null
    saved_query = DiscoverSavedQuery.objects.get(id=saved_query.id)
    assert saved_query.created_by_id is None


class _IdParams(TypedDict):
    id: NotRequired[int]


class _CrossDbDeletionData(TypedDict):
    user: User
    organization: Organization
    project: Project
    monitor: Monitor
    group: Group
    saved_query: DiscoverSavedQuery


def setup_cross_db_deletion_data(
    desired_user_id: int | None = None,
    desired_monitor_id: int | None = None,
) -> _CrossDbDeletionData:
    if desired_user_id is not None:
        user_params: _IdParams = {"id": desired_user_id}
    else:
        user_params = {}

    if desired_monitor_id is not None:
        monitor_params = {"id": desired_monitor_id}
    else:
        monitor_params = {}

    user = Factories.create_user(**user_params)
    organization = Factories.create_organization(owner=user, name="Delete Me")
    project = Factories.create_project(organization=organization)
    group = Factories.create_group(project=project)
    with assume_test_silo_mode_of(DiscoverSavedQuery, Monitor):
        saved_query = DiscoverSavedQuery.objects.create(
            name="disco-query",
            organization=organization,
            created_by_id=user.id,
        )
        monitor = Monitor.objects.create(
            **monitor_params,
            organization_id=organization.id,
            project_id=project.id,
            slug="test-monitor",
            name="Test Monitor",
            owner_user_id=user.id,
        )

        assert monitor.owner_user_id == user.id

    return dict(
        user=user,
        organization=organization,
        project=project,
        monitor=monitor,
        group=group,
        saved_query=saved_query,
    )


@region_silo_test
class TestCrossDatabaseTombstoneCascadeBehavior(TestCase):
    def setUp(self) -> None:
        super().setUp()
        reset_watermarks()

    def assert_monitors_unchanged(self, unaffected_data: list[_CrossDbDeletionData]) -> None:
        for u_data in unaffected_data:
            u_user, u_monitor = itemgetter("user", "monitor")(u_data)
            queried_monitor = Monitor.objects.get(id=u_monitor.id)
            # Validate that none of the existing user's monitors have been affected
            assert u_monitor.owner_user_id is not None
            assert u_monitor.owner_user_id == queried_monitor.owner_user_id
            assert u_monitor.owner_user_id == u_user.id

    def assert_monitors_user_ids_null(self, monitors: list[Monitor]) -> None:
        for monitor in monitors:
            monitor.refresh_from_db()
            assert monitor.owner_user_id is None

    def run_hybrid_cloud_fk_jobs(self) -> None:
        with override_options({"hybrid_cloud.allow_cross_db_tombstones": True}):
            with BurstTaskRunner() as burst:
                schedule_hybrid_cloud_foreign_key_jobs()

                burst()

    def test_raises_when_option_disabled(self):
        data = setup_cross_db_deletion_data()
        user, monitor = itemgetter("user", "monitor")(data)
        with assume_test_silo_mode_of(User), outbox_runner():
            User.objects.get(id=user.id).delete()

        assert Monitor.objects.filter(id=monitor.id).exists()

        with (
            pytest.raises(Exception) as exc,
            override_options({"hybrid_cloud.allow_cross_db_tombstones": False}),
        ):
            with BurstTaskRunner() as burst:
                schedule_hybrid_cloud_foreign_key_jobs()

                burst()

        assert exc.match("Cannot process tombstones due to model living in separate database.")
        assert Monitor.objects.filter(id=monitor.id).exists()

    def test_cross_db_deletion(self):
        data = setup_cross_db_deletion_data()
        user, monitor, organization, project = itemgetter(
            "user", "monitor", "organization", "project"
        )(data)
        unaffected_data = [setup_cross_db_deletion_data() for _ in range(3)]

        affected_monitors = [monitor]

        affected_monitors.extend(
            [
                Monitor.objects.create(
                    id=5 + i * 2,  # Ensure that each monitor is in its own batch
                    organization_id=organization.id,
                    project_id=project.id,
                    slug=f"test-monitor-{i}",
                    name="Test Monitor",
                    owner_user_id=user.id,
                )
                for i in range(4)
            ]
        )

        with assume_test_silo_mode_of(User), outbox_runner():
            User.objects.get(id=user.id).delete()

        assert Monitor.objects.filter(id=monitor.id).exists()
        assert monitor.owner_user_id == user.id

        self.run_hybrid_cloud_fk_jobs()

        self.assert_monitors_unchanged(unaffected_data=unaffected_data)
        self.assert_monitors_user_ids_null(monitors=affected_monitors)

    def test_deletion_row_after_tombstone(self):
        data = setup_cross_db_deletion_data()
        user, monitor, organization, project = itemgetter(
            "user", "monitor", "organization", "project"
        )(data)
        unaffected_data = [setup_cross_db_deletion_data() for _ in range(3)]

        affected_monitors = [monitor]

        user_id = user.id
        with assume_test_silo_mode_of(User), outbox_runner():
            User.objects.get(id=user_id).delete()

        assert Monitor.objects.filter(id=monitor.id).exists()
        assert monitor.owner_user_id == user.id

        self.run_hybrid_cloud_fk_jobs()

        self.assert_monitors_unchanged(unaffected_data=unaffected_data)
        self.assert_monitors_user_ids_null(monitors=affected_monitors)

        # Same as previous test, but this time with monitors created after
        # the tombstone has been processed
        start_id = monitor.id + 10
        affected_monitors.extend(
            [
                Monitor.objects.create(
                    id=start_id + i * 2,  # Ensure that each monitor is in its own batch
                    organization_id=organization.id,
                    project_id=project.id,
                    slug=f"test-monitor-{i}",
                    name=f"Row After Tombstone {i}",
                    owner_user_id=user_id,
                )
                for i in range(4)
            ]
        )

        self.run_hybrid_cloud_fk_jobs()

        self.assert_monitors_unchanged(unaffected_data=unaffected_data)
        self.assert_monitors_user_ids_null(monitors=affected_monitors)

    def test_empty_tombstones_table(self):
        unaffected_data = [setup_cross_db_deletion_data() for _ in range(3)]
        assert RegionTombstone.objects.count() == 0

        self.run_hybrid_cloud_fk_jobs()
        self.assert_monitors_unchanged(unaffected_data=unaffected_data)


@region_silo_test
class TestGetIdsForTombstoneCascadeCrossDbTombstoneWatermarking(TestCase):
    def test_get_ids_for_tombstone_cascade_cross_db(self):
        data = setup_cross_db_deletion_data()

        unaffected_data = []
        for i in range(3):
            unaffected_data.append(setup_cross_db_deletion_data())

        user = data["user"]
        user_id = user.id
        monitor = data["monitor"]
        with assume_test_silo_mode_of(User), outbox_runner():
            user.delete()

        tombstone = RegionTombstone.objects.get(
            object_identifier=user_id, table_name=User._meta.db_table
        )

        highest_tombstone_id = RegionTombstone.objects.aggregate(Max("id"))
        monitor_owner_field = Monitor._meta.get_field("owner_user_id")

        ids, oldest_obj = get_ids_cross_db_for_tombstone_watermark(
            tombstone_cls=RegionTombstone,
            model=Monitor,
            field=monitor_owner_field,
            tombstone_watermark_batch=WatermarkBatch(
                low=0,
                up=highest_tombstone_id["id__max"] + 1,
                has_more=False,
                transaction_id="foobar",
            ),
        )
        assert ids == [monitor.id]
        assert oldest_obj == tombstone.created_at

    def test_get_ids_for_tombstone_cascade_cross_db_watermark_bounds(self):
        cascade_data = [setup_cross_db_deletion_data() for _ in range(3)]

        # Create some additional filler data
        [setup_cross_db_deletion_data() for _ in range(3)]

        in_order_tombstones = []
        for data in cascade_data:
            user = data["user"]
            user_id = user.id
            with assume_test_silo_mode_of(User), outbox_runner():
                user.delete()

            in_order_tombstones.append(
                RegionTombstone.objects.get(
                    object_identifier=user_id, table_name=User._meta.db_table
                )
            )

        bounds_with_expected_results_tests = [
            (
                {"low": 0, "up": in_order_tombstones[1].id},
                [cascade_data[0]["monitor"].id, cascade_data[1]["monitor"].id],
            ),
            (
                {"low": in_order_tombstones[1].id, "up": in_order_tombstones[2].id},
                [cascade_data[2]["monitor"].id],
            ),
            (
                {"low": 0, "up": in_order_tombstones[0].id - 1},
                [],
            ),
            (
                {"low": in_order_tombstones[2].id + 1, "up": in_order_tombstones[2].id + 5},
                [],
            ),
            (
                {"low": -1, "up": in_order_tombstones[2].id + 1},
                [
                    cascade_data[0]["monitor"].id,
                    cascade_data[1]["monitor"].id,
                    cascade_data[2]["monitor"].id,
                ],
            ),
        ]

        for bounds, bounds_with_expected_results in bounds_with_expected_results_tests:
            monitor_owner_field = Monitor._meta.get_field("owner_user_id")

            ids, oldest_obj = get_ids_cross_db_for_tombstone_watermark(
                tombstone_cls=RegionTombstone,
                model=Monitor,
                field=monitor_owner_field,
                tombstone_watermark_batch=WatermarkBatch(
                    low=bounds["low"],
                    up=bounds["up"],
                    has_more=False,
                    transaction_id="foobar",
                ),
            )
            assert ids == bounds_with_expected_results

    def test_get_ids_for_tombstone_cascade_cross_db_with_multiple_tombstone_types(self):
        data = setup_cross_db_deletion_data()
        unaffected_data = [setup_cross_db_deletion_data() for _ in range(3)]

        # Pollute the tombstone data with references to relationships in other
        # tables matching other User IDs just to ensure we are filtering on the
        # correct table name.
        for udata in unaffected_data:
            unaffected_user = udata["user"]
            RegionTombstone.objects.create(
                table_name="something_table", object_identifier=unaffected_user.id
            )

        user, monitor = itemgetter("user", "monitor")(data)
        user_id = user.id
        with assume_test_silo_mode_of(User), outbox_runner():
            user.delete()

        tombstone = RegionTombstone.objects.get(
            object_identifier=user_id, table_name=User._meta.db_table
        )

        highest_tombstone_id = RegionTombstone.objects.aggregate(Max("id"))

        ids, oldest_obj = get_ids_cross_db_for_tombstone_watermark(
            tombstone_cls=RegionTombstone,
            model=Monitor,
            field=Monitor._meta.get_field("owner_user_id"),
            tombstone_watermark_batch=WatermarkBatch(
                low=0,
                up=highest_tombstone_id["id__max"] + 1,
                has_more=False,
                transaction_id="foobar",
            ),
        )
        assert ids == [monitor.id]
        assert oldest_obj == tombstone.created_at


@region_silo_test
class TestGetIdsForTombstoneCascadeCrossDbRowWatermarking(TestCase):
    def test_with_simple_tombstone_intersection(self):
        data = setup_cross_db_deletion_data(desired_user_id=10, desired_monitor_id=42)
        user, monitor = itemgetter("user", "monitor")(data)

        assert user.id == 10
        user_id = user.id
        assert monitor.id == 42

        with assume_test_silo_mode_of(User), outbox_runner():
            user.delete()

        highest_model_id = Monitor.objects.aggregate(Max("id"))
        tombstone = RegionTombstone.objects.get(
            object_identifier=user_id, table_name=User._meta.db_table
        )
        ids, oldest_obj = get_ids_cross_db_for_row_watermark(
            tombstone_cls=RegionTombstone,
            model=Monitor,
            field=Monitor._meta.get_field("owner_user_id"),
            row_watermark_batch=WatermarkBatch(
                low=0,
                up=highest_model_id["id__max"] + 1,
                has_more=False,
                transaction_id="foobar",
            ),
        )

        assert ids == [monitor.id]
        assert oldest_obj == tombstone.created_at

    def test_with_empty_tombstones_table(self):
        # Set up some sample data that shouldn't be affected
        with outbox_runner():
            [setup_cross_db_deletion_data() for _ in range(3)]

        highest_model_id = Monitor.objects.aggregate(Max("id"))["id__max"]

        assert highest_model_id is not None
        assert not RegionTombstone.objects.filter().exists()

        ids, oldest_obj = get_ids_cross_db_for_row_watermark(
            tombstone_cls=RegionTombstone,
            model=Monitor,
            field=Monitor._meta.get_field("owner_user_id"),
            row_watermark_batch=WatermarkBatch(
                low=0,
                up=highest_model_id + 1,
                has_more=False,
                transaction_id="foobar",
            ),
        )

        assert ids == []

    def test_row_watermarking_bounds(self):
        # In testing, the IDs for these models will be low, sequential values
        # so adding some seed data to space the IDs out gives better insight
        # on filter correctness.
        desired_user_and_monitor_ids = [(10, 9), (42, 30), (77, 120)]
        cascade_data = [
            setup_cross_db_deletion_data(desired_user_id=user_id, desired_monitor_id=monitor_id)
            for user_id, monitor_id in desired_user_and_monitor_ids
        ]

        # Create some additional filler data
        [setup_cross_db_deletion_data() for _ in range(3)]

        with assume_test_silo_mode_of(User), outbox_runner():
            for data in cascade_data:
                user = data["user"]
                User.objects.get(id=user.id).delete()

        bounds_with_expected_results_tests = [
            # Get batch containing first 2 monitors
            (
                {"low": 0, "up": cascade_data[1]["monitor"].id},
                [cascade_data[0]["monitor"].id, cascade_data[1]["monitor"].id],
            ),
            # Get batch containing only the last monitor
            (
                {"low": cascade_data[1]["monitor"].id, "up": cascade_data[2]["monitor"].id},
                [cascade_data[2]["monitor"].id],
            ),
            # Get batch after all current monitors, testing upper bound
            (
                {"low": 0, "up": cascade_data[0]["monitor"].id - 1},
                [],
            ),
            # Get batch with all 3 monitors
            (
                {"low": -1, "up": cascade_data[2]["monitor"].id + 1},
                [
                    cascade_data[0]["monitor"].id,
                    cascade_data[1]["monitor"].id,
                    cascade_data[2]["monitor"].id,
                ],
            ),
            # Get batch preceeding all monitors
            (
                {"low": cascade_data[1]["monitor"].id, "up": cascade_data[2]["monitor"].id - 1},
                [],
            ),
        ]

        for bounds, bounds_with_expected_results in bounds_with_expected_results_tests:
            monitor_owner_field = Monitor._meta.get_field("owner_user_id")

            ids, oldest_obj = get_ids_cross_db_for_row_watermark(
                tombstone_cls=RegionTombstone,
                model=Monitor,
                field=monitor_owner_field,
                row_watermark_batch=WatermarkBatch(
                    low=bounds["low"],
                    up=bounds["up"],
                    has_more=False,
                    transaction_id="foobar",
                ),
            )
            assert (
                ids == bounds_with_expected_results
            ), f"Expected  IDs '{bounds_with_expected_results}', got '{ids}', for input: '{bounds}'"

    def test_get_ids_for_tombstone_cascade_cross_db_with_multiple_tombstone_types(self):
        data = setup_cross_db_deletion_data()
        unaffected_data = [setup_cross_db_deletion_data() for _ in range(3)]

        # Similar to the test in the tombstone watermarking code, we pollute
        # the data with same user IDs, but different table to ensure we only
        # select the intersection of IDs from the monitor tombstones.
        for udata in unaffected_data:
            unaffected_user = udata["user"]
            RegionTombstone.objects.create(
                table_name="something_table", object_identifier=unaffected_user.id
            )

        user, monitor = itemgetter("user", "monitor")(data)
        user_id = user.id
        with assume_test_silo_mode_of(User), outbox_runner():
            user.delete()

        tombstone = RegionTombstone.objects.get(
            object_identifier=user_id, table_name=User._meta.db_table
        )

        highest_model_id = Monitor.objects.aggregate(Max("id"))["id__max"]

        ids, oldest_obj = get_ids_cross_db_for_row_watermark(
            tombstone_cls=RegionTombstone,
            model=Monitor,
            field=Monitor._meta.get_field("owner_user_id"),
            row_watermark_batch=WatermarkBatch(
                low=0,
                up=highest_model_id + 1,
                has_more=False,
                transaction_id="foobar",
            ),
        )
        assert ids == [monitor.id]
        assert oldest_obj == tombstone.created_at
