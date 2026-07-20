from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import churn_analysis


def test_configurable_training_and_summary(tmp_path):
    config_path = Path(__file__).resolve().parents[1] / "config" / "company_config.json"
    db_path = tmp_path / "configurable_churn.db"
    schema_path = Path(__file__).resolve().parents[1] / "sql" / "schema.sql"
    model_path = tmp_path / "model.pkl"

    config = churn_analysis.load_config(config_path)
    churn_analysis.ensure_database(db_path, schema_path, config=config)
    result = churn_analysis.train_model(db_path, model_path, config=config)

    assert result["accuracy"] >= 0.5
    assert model_path.exists()

    summary = churn_analysis.build_business_summary(db_path, config)
    assert "high_risk" in summary
    assert "low_risk" in summary
