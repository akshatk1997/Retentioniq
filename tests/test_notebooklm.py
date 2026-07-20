import sys
from pathlib import Path
import os
import json
import sqlite3
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as app_module
import churn_analysis


def test_source_management_workflow(tmp_path):
    db_path = tmp_path / "notebooklm_test.db"
    schema_path = Path(__file__).resolve().parents[1] / "sql" / "schema.sql"
    
    churn_analysis.ensure_database(db_path, schema_path)
    
    # Verify initial database seeding creates default sample_data source
    conn = sqlite3.connect(db_path)
    sources = conn.execute("SELECT * FROM data_sources").fetchall()
    assert len(sources) == 1
    assert sources[0][0] == "sample_data"
    assert sources[0][4] == 1 # is_active = 1
    
    # Count customers linked to sample_data
    cust_count = conn.execute("SELECT COUNT(*) FROM customer_churn WHERE source_id = 'sample_data'").fetchone()[0]
    assert cust_count > 0
    conn.close()

    # Import another source frame
    df = pd.DataFrame({
        "customer_id": ["TEST001", "TEST002"],
        "tenure_months": [12, 24],
        "monthly_charges": [50.0, 80.0],
        "total_charges": [600.0, 1920.0],
        "contract_type": ["month-to-month", "two-year"],
        "internet_service": ["DSL", "Fiber optic"],
        "payment_method": ["Electronic check", "Mailed check"],
        "region": ["North", "South"],
        "support_tickets": [1, 0],
        "payment_delays": [0, 0],
        "product_usage": [80.0, 95.0],
        "complaint_count": [0, 0],
        "customer_satisfaction_score": [4.0, 5.0],
        "churned": [0, 0]
    })
    
    rows_imported = churn_analysis.import_frame_to_sql(df, db_path, replace=False, filename="test_upload.csv")
    assert rows_imported == 2
    
    # Check that it registers in sources
    conn = sqlite3.connect(db_path)
    sources = conn.execute("SELECT * FROM data_sources ORDER BY created_at DESC").fetchall()
    assert len(sources) == 2
    new_source_id = [s[0] for s in sources if s[0] != "sample_data"][0]
    
    # Toggle it inactive
    conn.execute("UPDATE data_sources SET is_active = 0 WHERE source_id = ?", (new_source_id,))
    conn.commit()
    conn.close()
    
    # Verify load_training_data only returns active source data
    active_df = churn_analysis.load_training_data(db_path)
    assert "TEST001" not in active_df["customer_id"].values
    
    # Delete the new source
    conn = sqlite3.connect(db_path)
    conn.execute("DELETE FROM data_sources WHERE source_id = ?", (new_source_id,))
    conn.execute("DELETE FROM customer_churn WHERE source_id = ?", (new_source_id,))
    conn.commit()
    
    # Assert cascade deletion worked
    test_cust_count = conn.execute("SELECT COUNT(*) FROM customer_churn WHERE customer_id = 'TEST001'").fetchone()[0]
    assert test_cust_count == 0
    conn.close()
