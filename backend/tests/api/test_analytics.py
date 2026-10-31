from tests.helpers.duckdb_fixtures import build_metrics_duckdb


def test_jackpot_volume_returns_503_when_analytics_not_built(client, monkeypatch, tmp_path):
    import app.api.routes.analytics as route

    monkeypatch.setattr(route, "resolve_duckdb_path", lambda: tmp_path / "missing.duckdb")

    response = client.get("/analytics/jackpot-volume")

    assert response.status_code == 503


def test_jackpot_volume_returns_real_numbers(client, monkeypatch, tmp_path):
    import app.api.routes.analytics as route

    db_path = tmp_path / "metrics.duckdb"
    build_metrics_duckdb(db_path, cumulative_diverts=12, cumulative_clears=4, wip_count=8)
    monkeypatch.setattr(route, "resolve_duckdb_path", lambda: db_path)

    response = client.get("/analytics/jackpot-volume")

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "cumulative_diverts": 12,
        "cumulative_clears": 4,
        "currently_in_jackpot": 8,
    }


def test_wips_returns_real_numbers(client, monkeypatch, tmp_path):
    import app.api.routes.analytics as route

    db_path = tmp_path / "metrics.duckdb"
    build_metrics_duckdb(db_path, wip_count=42)
    monkeypatch.setattr(route, "resolve_duckdb_path", lambda: db_path)

    response = client.get("/analytics/wips")

    assert response.status_code == 200
    assert response.json() == {"wip_count": 42}


def test_induct_throughput_returns_real_rows(client, monkeypatch, tmp_path):
    from datetime import UTC, datetime

    import app.api.routes.analytics as route

    db_path = tmp_path / "metrics.duckdb"
    build_metrics_duckdb(
        db_path, induct_rows=[(datetime(2026, 1, 1, 3, tzinfo=UTC), 17)]
    )
    monkeypatch.setattr(route, "resolve_duckdb_path", lambda: db_path)

    response = client.get("/analytics/induct-throughput")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["parcels_inducted"] == 17


def test_stow_throughput_returns_real_rows(client, monkeypatch, tmp_path):
    from datetime import UTC, datetime

    import app.api.routes.analytics as route

    db_path = tmp_path / "metrics.duckdb"
    build_metrics_duckdb(
        db_path, stow_rows=[(datetime(2026, 1, 1, 3, tzinfo=UTC), "STOWER-02", 9)]
    )
    monkeypatch.setattr(route, "resolve_duckdb_path", lambda: db_path)

    response = client.get("/analytics/stow-throughput")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["stower_code"] == "STOWER-02"
    assert body[0]["parcels_stowed"] == 9


def test_parcel_dwell_time_returns_real_stats(client, monkeypatch, tmp_path):
    from datetime import UTC, datetime

    import app.api.routes.analytics as route

    db_path = tmp_path / "metrics.duckdb"
    build_metrics_duckdb(
        db_path,
        dwell_rows=[
            ("P1", datetime(2026, 1, 1, 2, tzinfo=UTC), datetime(2026, 1, 1, 2, 5, tzinfo=UTC)),
        ],
    )
    monkeypatch.setattr(route, "resolve_duckdb_path", lambda: db_path)

    response = client.get("/analytics/parcel-dwell-time")

    assert response.status_code == 200
    body = response.json()
    assert body["parcel_count"] == 1
