import sys
from pathlib import Path
import sqlite3
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import churn_analysis


def test_arbitrary_dataset_upload_and_training(tmp_path):
    db_path = tmp_path / "arbitrary.db"
    schema_path = Path(__file__).resolve().parents[1] / "sql" / "schema.sql"
    model_path = tmp_path / "arbitrary_model.pkl"
    config_path = Path(__file__).resolve().parents[1] / "config" / "company_config.json"

    config = churn_analysis.load_config(config_path)

    # 1. Create an arbitrary dataframe (few churn-like columns, so is_arbitrary = True)
    arbitrary_df = pd.DataFrame({
        "my_custom_id": ["A001", "A002", "A003", "A004", "A005", "A006", "A007", "A008", "A009", "A010", "A011"],
        "customer_score": [10.5, 20.0, 1.2, 5.0, 8.8, 9.9, 11.2, 12.0, 13.0, 14.0, 15.0],
        "city": ["Paris", "London", "Paris", "Berlin", "Paris", "Berlin", "Paris", "Berlin", "Paris", "Berlin", "Paris"],
        "status": ["active", "retained", "churned", "active", "churn", "retained", "active", "retained", "active", "retained", "active"]
    })

    # 2. Initialize DB first
    churn_analysis.ensure_database(db_path, schema_path, config=config)

    # 3. Import arbitrary dataframe. Under is_arbitrary, it should rebuild the table.
    row_count = churn_analysis.import_frame_to_sql(arbitrary_df, db_path, replace=True, config=config)
    assert row_count == 11

    # 4. Check database columns
    conn = sqlite3.connect(db_path)
    columns = [row[1] for row in conn.execute("PRAGMA table_info(customer_churn)").fetchall()]
    conn.close()

    # The table should have been rebuilt to match normalized arbitrary dataframe.
    # It must contain customer_id, customer_score, city, and churned (target).
    assert "customer_id" in columns
    assert "customer_score" in columns
    assert "city" in columns
    assert "churned" in columns  # Inferred and mapped from 'status'
    assert "status" not in columns  # Dropped and replaced by 'churned'

    # 5. Train model on the arbitrary dataset
    result = churn_analysis.train_model(db_path, model_path, config=config)
    assert result["accuracy"] >= 0.0
    assert model_path.exists()
