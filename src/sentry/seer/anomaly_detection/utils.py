from datetime import datetime, timedelta
from typing import Any

from django.utils import timezone
from django.utils.datastructures import MultiValueDict

from sentry import release_health
from sentry.api.bases.organization_events import resolve_axis_column
from sentry.api.serializers.snuba import SnubaTSResultSerializer
from sentry.incidents.models.alert_rule import AlertRule, AlertRuleThresholdType
from sentry.models.organization import Organization
from sentry.models.project import Project
from sentry.search.events.types import SnubaParams
from sentry.seer.anomaly_detection.types import TimeSeriesPoint
from sentry.snuba import metrics_performance
from sentry.snuba.metrics.extraction import MetricSpecType
from sentry.snuba.models import SnubaQuery
from sentry.snuba.referrer import Referrer
from sentry.snuba.sessions_v2 import QueryDefinition
from sentry.snuba.utils import get_dataset
from sentry.utils.snuba import SnubaTSResult


def translate_direction(direction: int) -> str:
    """
    Temporary translation map to Seer's expected values
    """
    direction_map = {
        AlertRuleThresholdType.ABOVE: "up",
        AlertRuleThresholdType.BELOW: "down",
        AlertRuleThresholdType.ABOVE_AND_BELOW: "both",
    }
    return direction_map[AlertRuleThresholdType(direction)]


NUM_DAYS = 28


def get_crash_free_historical_data(
    start: datetime, end: datetime, project: Project, organization: Organization, granularity: int
):
    """
    Fetch the historical metrics data from Snuba for crash free user rate and crash free session rate metrics
    """

    params = {
        "start": start,
        "end": end,
        "project_id": [project.id],
        "project_objects": [project],
        "organization_id": organization.id,
    }
    query_params: MultiValueDict[str, Any] = MultiValueDict(
        {
            "project": [project.id],
            "statsPeriod": [f"{NUM_DAYS}d"],
            "field": ["sum(session)"],
            "groupBy": ["release"],
        }
    )
    query = QueryDefinition(
        query=query_params,
        params=params,
        offset=None,
        limit=None,
        query_config=release_health.backend.sessions_query_config(organization),
    )
    result = release_health.backend.run_sessions_query(
        organization.id, query, span_op="sessions.anomaly_detection"
    )
    return SnubaTSResult(
        {
            "data": result,
        },
        result.get("start"),
        result.get("end"),
        granularity,
    )


def format_historical_data(
    data: SnubaTSResult, query_columns: list[str], dataset: Any, organization: Organization
) -> list[TimeSeriesPoint]:
    """
    Format Snuba data into the format the Seer API expects.
    """
    serializer = SnubaTSResultSerializer(organization=organization, lookup=None, user=None)
    serialized_result = serializer.serialize(
        data,
        resolve_axis_column(query_columns[0]),
        allow_partial_buckets=False,
        zerofill_results=False,
        extra_columns=None,
    )
    formatted_data: list[TimeSeriesPoint] = []

    # CEO: need to validate this is still correct for sessions data
    # if dataset == metrics_performance:
    #     groups = nested_data.get("groups")
    #     if not len(groups):
    #         return formatted_data
    #     series = groups[0].get("series")

    #     for time, count in zip(nested_data.get("intervals"), series.get("sum(session)", 0)):
    #         date = datetime.strptime(time, "%Y-%m-%dT%H:%M:%SZ")
    #         ts_point = TimeSeriesPoint(timestamp=date.timestamp(), value=count)
    #         formatted_data.append(ts_point)

    for data in serialized_result.get("data"):
        if len(data) > 1:
            count_data = data[1]
            count = 0
            if len(count_data):
                count = count_data[0].get("count", 0)
            ts_point = TimeSeriesPoint(timestamp=data[0], value=count)
            formatted_data.append(ts_point)

    return formatted_data


def fetch_historical_data(
    alert_rule: AlertRule,
    snuba_query: SnubaQuery,
    query_columns: list[str],
    project: Project,
    start: datetime | None = None,
    end: datetime | None = None,
) -> SnubaTSResult | None:
    """
    Fetch 28 days of historical data from Snuba to pass to Seer to build the anomaly detection model
    """
    # TODO: if we can pass the existing timeseries data we have on the front end along here, we can shorten
    # the time period we query and combine the data
    is_store_data_request = False
    if end is None:
        is_store_data_request = True
        end = timezone.now()
    # doing it this way to suppress typing errors
    if start is None:
        start = end - timedelta(days=NUM_DAYS)
    granularity = snuba_query.time_window

    dataset_label = snuba_query.dataset
    if dataset_label == "events":
        # DATASET_OPTIONS expects the name 'errors'
        dataset_label = "errors"
    elif dataset_label == "generic_metrics":
        dataset_label = "transactions"
    dataset = get_dataset(dataset_label)

    if not project or not dataset or not alert_rule.organization:
        return None

    environments = []
    if snuba_query.environment:
        environments = [snuba_query.environment]

    if dataset == metrics_performance:
        return get_crash_free_historical_data(
            start, end, project, alert_rule.organization, granularity
        )
    else:
        historical_data = dataset.timeseries_query(
            selected_columns=query_columns,
            query=snuba_query.query,
            snuba_params=SnubaParams(
                organization=alert_rule.organization,
                projects=[project],
                start=start,
                end=end,
                stats_period=None,
                environments=environments,
            ),
            rollup=granularity,
            referrer=(
                Referrer.ANOMALY_DETECTION_HISTORICAL_DATA_QUERY.value
                if is_store_data_request
                else Referrer.ANOMALY_DETECTION_RETURN_HISTORICAL_ANOMALIES.value
            ),
            zerofill_results=True,
            allow_metric_aggregates=True,
            on_demand_metrics_type=MetricSpecType.SIMPLE_QUERY,
        )
    return historical_data
