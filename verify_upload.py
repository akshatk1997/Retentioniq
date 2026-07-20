import io
import os
import tempfile
from pathlib import Path
import app as app_module

with tempfile.TemporaryDirectory() as tmpdir:
    db_path = Path(tmpdir) / 'dashboard_test.db'
    os.environ['CHURN_DB'] = str(db_path)
    flask_app = app_module.create_app()
    flask_app.config.update(TESTING=True)
    client = flask_app.test_client()
    csv_data = b'customer_id,tenure_months,monthly_charges,total_charges,contract_type,internet_service,payment_method,region,support_tickets,payment_delays,product_usage,complaint_count,customer_satisfaction_score,churned\nU001,12,70,840,Month-to-month,DSL,Electronic check,North,3,1,40,2,3.2,1\nU002,24,80,1920,One year,Fiber optic,Credit card,South,1,0,85,0,4.5,0\n'
    response = client.post('/api/upload', data={'file': (io.BytesIO(csv_data), 'customers.csv')}, content_type='multipart/form-data')
    print('UPLOAD_STATUS', response.status_code)
    print('UPLOAD_BODY', response.get_json())
    summary = client.get('/api/summary')
    print('SUMMARY_STATUS', summary.status_code)
    print('SUMMARY_BODY', summary.get_json())
    predictions = client.get('/api/predictions')
    print('PREDICTIONS_STATUS', predictions.status_code)
    print('PREDICTIONS_BODY', predictions.get_json())
    insights = client.get('/api/insights?role=manager')
    print('INSIGHTS_STATUS', insights.status_code)
    print('INSIGHTS_BODY', insights.get_json())
