"""Unit tests for UTC normalisation of request timestamps.

Callers routinely omit the UTC offset (`"2025-03-01"`, `"2025-03-01T00:00:00"`).
Before normalisation, mixing a naive bound with an offset-aware one raised
`TypeError` from the comparison in `QueryRequest._validate_dates`, which
FastAPI surfaces as a 500 rather than a 422.  No database is required.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from adsb_server.query.models import (
    EndpointWithinValue,
    QueryRequest,
    SpatioTemporalAltitudeValue,
    decode_cursor,
    encode_cursor,
    to_utc,
)


class TestToUtc:
    def test_naive_is_treated_as_utc(self) -> None:
        assert to_utc(datetime(2025, 3, 1, 12, 0)) == datetime(2025, 3, 1, 12, 0, tzinfo=UTC)

    def test_aware_is_converted_to_utc(self) -> None:
        aware = datetime(2025, 3, 1, 12, 0, tzinfo=timezone(timedelta(hours=-5)))
        assert to_utc(aware) == datetime(2025, 3, 1, 17, 0, tzinfo=UTC)
        assert to_utc(aware).tzinfo is UTC

    def test_offset_is_applied(self) -> None:
        plus_two = datetime.fromisoformat("2025-03-01T00:00:00+02:00")
        assert to_utc(plus_two) == datetime(2025, 2, 28, 22, 0, tzinfo=UTC)


class TestQueryRequestTimestamps:
    @pytest.mark.parametrize(
        "start_from",
        ["2025-03-01", "2025-03-01T00:00:00", "2025-03-01T00:00:00Z", "2025-03-01T02:00:00+02:00"],
        ids=["date-only", "naive", "aware-z", "aware-offset"],
    )
    def test_mixed_awareness_bounds_validate(self, start_from: str) -> None:
        """Any spelling of the same instant must validate, not raise TypeError."""
        req = QueryRequest.model_validate(
            {"end_date": "2025-04-02T00:00:00Z", "start_from": start_from}
        )
        assert req.start_from == datetime(2025, 3, 1, 0, 0, tzinfo=UTC)
        assert req.end_date == datetime(2025, 4, 2, 0, 0, tzinfo=UTC)

    def test_naive_end_date_with_aware_start_from(self) -> None:
        req = QueryRequest.model_validate(
            {"end_date": "2025-04-02T00:00:00", "start_from": "2025-03-01T00:00:00Z"}
        )
        assert req.end_date == datetime(2025, 4, 2, 0, 0, tzinfo=UTC)
        assert req.start_from == datetime(2025, 3, 1, 0, 0, tzinfo=UTC)

    def test_start_from_after_end_date_still_rejected(self) -> None:
        """Normalisation must not swallow the genuine ordering error."""
        with pytest.raises(ValidationError, match="strictly before"):
            QueryRequest.model_validate(
                {"end_date": "2025-03-01T00:00:00Z", "start_from": "2025-04-02"}
            )

    def test_ordering_compared_after_normalisation(self) -> None:
        """A naive start_from one hour past a UTC end_date is rejected, not accepted."""
        with pytest.raises(ValidationError, match="strictly before"):
            QueryRequest.model_validate(
                {"end_date": "2025-03-01T00:00:00Z", "start_from": "2025-03-01T01:00:00"}
            )

    def test_equivalent_spellings_share_a_cache_key(self) -> None:
        """model_dump_json backs the result cache key, so spellings must converge."""
        a = QueryRequest.model_validate({"end_date": "2025-04-02T00:00:00Z"})
        b = QueryRequest.model_validate({"end_date": "2025-04-02"})
        assert a.model_dump_json() == b.model_dump_json()


class TestPredicateTimestamps:
    def test_endpoint_within_bounds_normalised(self) -> None:
        value = EndpointWithinValue.model_validate(
            {
                "mode": "start",
                "start_time_from": "2025-04-01T06:00:00",
                "start_time_to": "2025-04-01T12:00:00Z",
                "end_time_from": "2025-04-01",
                "end_time_to": "2025-04-01T14:00:00+02:00",
            }
        )
        assert value.start_time_from == datetime(2025, 4, 1, 6, 0, tzinfo=UTC)
        assert value.start_time_to == datetime(2025, 4, 1, 12, 0, tzinfo=UTC)
        assert value.end_time_from == datetime(2025, 4, 1, 0, 0, tzinfo=UTC)
        assert value.end_time_to == datetime(2025, 4, 1, 12, 0, tzinfo=UTC)

    def test_spatio_temporal_bounds_normalised(self) -> None:
        value = SpatioTemporalAltitudeValue.model_validate(
            {"time_from": "2025-04-01T06:00:00", "time_to": "2025-04-01"}
        )
        assert value.time_from == datetime(2025, 4, 1, 6, 0, tzinfo=UTC)
        assert value.time_to == datetime(2025, 4, 1, 0, 0, tzinfo=UTC)


class TestCursorTimestamps:
    def test_roundtrip_is_utc_aware(self) -> None:
        ts = datetime(2025, 4, 1, 10, 0, tzinfo=UTC)
        decoded, icao = decode_cursor(encode_cursor(ts, "aabbcc"))
        assert decoded == ts
        assert decoded.tzinfo is UTC
        assert icao == "aabbcc"

    def test_decoded_cursor_comparable_with_naive_end_date(self) -> None:
        """Page two of a naive-end_date query previously raised TypeError in min()."""
        req = QueryRequest.model_validate(
            {
                "end_date": "2025-04-02T00:00:00",
                "cursor": encode_cursor(datetime(2025, 4, 1, 10, 0, tzinfo=UTC), "aabbcc"),
            }
        )
        assert req.cursor is not None
        cursor_ts, _ = decode_cursor(req.cursor)
        assert min(req.end_date, cursor_ts) == cursor_ts
