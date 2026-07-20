import sys
from pathlib import Path
import os
import json

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as app_module
import churn_analysis


def test_business_analytics_api_seeding(tmp_path):
    flask_app = app_module.create_app()
    flask_app.config.update(TESTING=True)
    client = flask_app.test_client()

    response = client.get("/api/business-analytics")
    assert response.status_code == 200
    payload = response.get_json()

    # The seeded DB has 24 customers.
    assert "total_customers" in payload
    assert payload["total_customers"] >= 24
    assert "total_charges" in payload
    assert "expected_loss" in payload
    assert "risk_exposure_pct" in payload
    assert "segments" in payload

    # Verify segments list has sorted expected losses
    segments = payload["segments"]
    assert len(segments) > 0
    
    # Assert sorted order: expected_loss descending
    for i in range(len(segments) - 1):
        assert segments[i]["expected_loss"] >= segments[i + 1]["expected_loss"]
