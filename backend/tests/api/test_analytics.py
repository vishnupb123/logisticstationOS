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
    build_metrics_duckdb(db_path, induct_rows=[(datetime(2026, 1, 1, 3, tzinfo=UTC), 17)])
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
    build_metrics_duckdb(db_path, stow_rows=[(datetime(2026, 1, 1, 3, tzinfo=UTC), "STOWER-02", 9)])
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


def test_end_to_end_computes_funnel_and_stage_times(client, monkeypatch, tmp_path):
    import duckdb

    import app.api.routes.analytics as route

    db_path = tmp_path / "lifecycle.duckdb"
    con = duckdb.connect(str(db_path))
    con.execute(
        "CREATE TABLE curated_parcel_lifecycle (parcel_id VARCHAR, inducted_at TIMESTAMP, "
        "classification VARCHAR, first_jackpot_diverted_at TIMESTAMP, sorted_at TIMESTAMP, "
        "stowed_at TIMESTAMP)"
    )
    t0 = "TIMESTAMP '2026-01-01 03:00:00'"
    con.execute(
        "INSERT INTO curated_parcel_lifecycle VALUES "
        # stowed: 60s to sort, 100s to stow (160s total)
        f"('p1', {t0}, 'normal_cycle1', NULL, {t0} + INTERVAL 60 SECOND, "
        f"{t0} + INTERVAL 160 SECOND),"
        # jackpotted then stowed: 120s to sort, 200s to stow (320s total)
        f"('p2', {t0}, 'normal_cycle1', {t0} + INTERVAL 10 SECOND, "
        f"{t0} + INTERVAL 120 SECOND, {t0} + INTERVAL 320 SECOND),"
        # exception: never sorted
        f"('p3', {t0}, 'high_value', NULL, NULL, NULL)"
    )
    con.close()
    monkeypatch.setattr(route, "resolve_duckdb_path", lambda: db_path)

    response = client.get("/analytics/end-to-end")

    assert response.status_code == 200
    body = response.json()
    assert body["parcels_inducted"] == 3
    assert body["parcels_exception"] == 1
    assert body["parcels_sorted"] == 2
    assert body["parcels_ever_jackpotted"] == 1
    assert body["parcels_stowed"] == 2
    assert body["induct_to_stow"]["count"] == 2
    assert body["induct_to_stow"]["avg_seconds"] == 240
    assert body["induct_to_sort"]["p50_seconds"] == 90
    assert body["sort_to_stow"]["avg_seconds"] == 150


def test_end_to_end_returns_503_when_analytics_not_built(client, monkeypatch, tmp_path):
    import app.api.routes.analytics as route

    monkeypatch.setattr(route, "resolve_duckdb_path", lambda: tmp_path / "missing.duckdb")

    assert client.get("/analytics/end-to-end").status_code == 503
