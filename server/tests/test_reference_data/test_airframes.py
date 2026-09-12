"""Tests for the tar1090-db airframe CSV loader."""

import gzip

from adsb_server.reference_data.airframes import _parse_rows


def _csv_gz(*lines: str) -> bytes:
    return gzip.compress(("\n".join(lines) + "\n").encode())


class TestParseRows:
    def test_identifiers_normalized(self) -> None:
        """icao24 lower-cases; registration and type designator upper-case and lose hyphens."""
        rows = _parse_rows(_csv_gz("4CA7B3;g-abcd;b738;0;Boeing 737-800;2015;Ryanair"))
        assert len(rows) == 1
        icao24, registration, icao_type = rows[0][0], rows[0][1], rows[0][2]
        assert icao24 == "4ca7b3"
        assert registration == "GABCD"
        assert icao_type == "B738"

    def test_blank_identifiers_become_none(self) -> None:
        rows = _parse_rows(_csv_gz("4ca7b3;  ;  ;0"))
        assert len(rows) == 1
        assert rows[0][1] is None
        assert rows[0][2] is None

    def test_model_is_left_alone(self) -> None:
        """Only the identifier columns are normalized; the model name keeps its case."""
        rows = _parse_rows(_csv_gz("4ca7b3;G-ABCD;B738;0;Boeing 737-800"))
        assert rows[0][4] == "Boeing 737-800"

    def test_short_and_malformed_rows_skipped(self) -> None:
        rows = _parse_rows(_csv_gz("4ca7b3;G-ABCD", "xyz;G-ABCD;B738;0", "4ca7b3;G-ABCD;B738;0"))
        assert len(rows) == 1
        assert rows[0][0] == "4ca7b3"
