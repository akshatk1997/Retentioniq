import io
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as app_module


def test_upload_csv_and_load_dashboard(tmp_path):
    db_path = tmp_path / "dashboard_test.db"
    os.environ["CHURN_DB"] = str(db_path)

    flask_app = app_module.create_app()
    flask_app.config.update(TESTING=True)
    client = flask_app.test_client()

    csv_data = b"customer_id,tenure_months,monthly_charges,total_charges,contract_type,internet_service,payment_method,region,support_tickets,payment_delays,product_usage,complaint_count,customer_satisfaction_score,churned\nU001,12,70,840,Month-to-month,DSL,Electronic check,North,3,1,40,2,3.2,1\nU002,24,80,1920,One year,Fiber optic,Credit card,South,1,0,85,0,4.5,0\n"

    response = client.post(
        "/api/upload",
        data={"file": (io.BytesIO(csv_data), "customers.csv")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["status"] == "ok"
    assert payload["rows"] == 2

    summary_response = client.get("/api/summary")
    assert summary_response.status_code == 200
    summary_payload = summary_response.get_json()
    assert summary_payload["summary"]

    predictions_response = client.get("/api/predictions")
    assert predictions_response.status_code == 200
    predictions_payload = predictions_response.get_json()
    assert predictions_payload["predictions"]

    insights_response = client.get("/api/insights?role=manager")
    assert insights_response.status_code == 200
    insights_payload = insights_response.get_json()
    assert insights_payload["recommendations"]
