import os
import shutil
import tempfile
import sqlite3
from io import BytesIO
from pathlib import Path

import json
from datetime import datetime
import pandas as pd
from flask import Flask, jsonify, render_template, request, Response

from churn_analysis import (ensure_database, import_frame_to_sql, load_config, predict_from_frame,
                             train_model, generate_ai_insight_with_llm)

BASE_DIR = Path(__file__).resolve().parent
SCHEMA_PATH = BASE_DIR / "sql" / "schema.sql"
CONFIG_PATH = BASE_DIR / "config" / "company_config.json"


def get_db_path() -> Path:
    """Resolve the database path per call, supporting Vercel serverless & read-only filesystems."""
    if "CHURN_DB" in os.environ:
        return Path(os.environ["CHURN_DB"])

    base_db_path = BASE_DIR / "churn_analysis.db"
    
    # Detect Vercel / AWS Lambda / Serverless read-only environments
    is_serverless = bool(os.environ.get("VERCEL") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME"))
    
    if is_serverless:
        writable_dir = Path("/tmp") if os.name != "nt" else Path(tempfile.gettempdir())
        writable_db_path = writable_dir / "churn_analysis.db"
        if not writable_db_path.exists() and base_db_path.exists():
            try:
                shutil.copy2(base_db_path, writable_db_path)
            except Exception:
                pass
        return writable_db_path

    # Test if project directory is writable; fallback to temp dir if read-only
    try:
        test_file = BASE_DIR / ".writable_test"
        test_file.touch()
        test_file.unlink()
        return base_db_path
    except (PermissionError, OSError):
        writable_dir = Path("/tmp") if os.name != "nt" else Path(tempfile.gettempdir())
        writable_db_path = writable_dir / "churn_analysis.db"
        if not writable_db_path.exists() and base_db_path.exists():
            try:
                shutil.copy2(base_db_path, writable_db_path)
            except Exception:
                pass
        return writable_db_path


def get_model_path() -> Path:
    if "CHURN_MODEL" in os.environ:
        return Path(os.environ["CHURN_MODEL"])
    db_dir = get_db_path().parent
    artifacts_dir = db_dir / "artifacts"
    try:
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        return artifacts_dir / "churn_model.pkl"
    except (PermissionError, OSError):
        return db_dir / "churn_model.pkl"


def create_app() -> Flask:
    app = Flask(__name__, template_folder=str(BASE_DIR / "templates"), static_folder=str(BASE_DIR / "static"))

    @app.before_request
    def initialize_database() -> None:
        ensure_database(get_db_path(), SCHEMA_PATH, config=load_config(CONFIG_PATH))

    def get_connection() -> sqlite3.Connection:
        conn = sqlite3.connect(get_db_path())
        conn.row_factory = sqlite3.Row
        return conn

    def customer_columns(conn: sqlite3.Connection) -> list[str]:
        """Return the actual customer_churn columns present in the table."""
        return [row[1] for row in conn.execute("PRAGMA table_info(customer_churn)").fetchall()]

    @app.route("/")
    def index() -> str:
        return render_template("index.html")

    @app.route("/api/health")
    def health_api():
        return jsonify({"status": "ok", "database": str(get_db_path())})

    @app.route("/api/branding")
    def branding_api():
        config = load_config(CONFIG_PATH)
        return jsonify({
            "company_name": config.get("company_name", "RetentionIQ Analytics"),
            "label_mapping": config.get("label_mapping", {"high_risk": "high_risk", "low_risk": "low_risk"}),
            "risk_threshold": config.get("risk_threshold", 0.6)
        })

    @app.route("/api/summary")
    def summary_api():
        conn = get_connection()
        rows = conn.execute(
            """
            SELECT cp.prediction_label as label, COUNT(*) as customers,
                   ROUND(AVG(cp.predicted_probability), 3) as avg_probability
            FROM churn_predictions cp
            JOIN customer_churn cc ON cp.customer_id = cc.customer_id
            JOIN data_sources ds ON cc.source_id = ds.source_id
            WHERE ds.is_active = 1
            GROUP BY cp.prediction_label
            ORDER BY customers DESC
            """
        ).fetchall()
        conn.close()

        return jsonify({"summary": [dict(row) for row in rows]})

    @app.route("/api/predictions")
    def predictions_api():
        conn = get_connection()
        existing = {row[1] for row in conn.execute("PRAGMA table_info(customer_churn)").fetchall()}
        extra_cols = [c for c in ("region", "contract_type", "tenure_months", "churned",
                                  "support_tickets", "payment_delays", "product_usage",
                                  "complaint_count", "customer_satisfaction_score")
                      if c in existing]
        select_cols = "cp.customer_id, cp.predicted_probability, cp.prediction_label" + \
            ("".join(f', cc."{c}"' for c in extra_cols) if extra_cols else "")
        rows = conn.execute(
            f"""
            SELECT {select_cols}
            FROM churn_predictions cp
            LEFT JOIN customer_churn cc ON cc.customer_id = cp.customer_id
            JOIN data_sources ds ON cc.source_id = ds.source_id
            WHERE ds.is_active = 1
            ORDER BY cp.predicted_probability DESC
            """
        ).fetchall()
        conn.close()

        return jsonify({"predictions": [dict(row) for row in rows]})

    @app.route("/api/upload", methods=["POST"])
    def upload_api():
        if "file" not in request.files:
            return jsonify({"status": "error", "message": "No file selected. Please choose a CSV, Excel, or JSON file."}), 400

        uploaded = request.files["file"]
        if uploaded.filename == "":
            return jsonify({"status": "error", "message": "No file selected. Please choose a file and try again."}), 400

        file_bytes = uploaded.read()
        if not file_bytes:
            return jsonify({"status": "error", "message": "The selected file is empty."}), 400

        config = load_config(CONFIG_PATH)
        ensure_database(get_db_path(), SCHEMA_PATH, config=config)

        file_name = uploaded.filename.lower()
        stream = BytesIO(file_bytes)
        try:
            if file_name.endswith(".csv"):
                frame = pd.read_csv(stream, encoding="utf-8-sig")
            elif file_name.endswith(".xlsx"):
                frame = pd.read_excel(stream)
            elif file_name.endswith(".json"):
                frame = pd.read_json(stream)
            else:
                return jsonify({"status": "error", "message": "Unsupported file type. Please upload CSV, Excel, or JSON."}), 400
        except Exception as exc:
            return jsonify({"status": "error", "message": f"Could not read file: {exc}"}), 400

        if frame.empty:
            return jsonify({"status": "error", "message": "The uploaded file is empty."}), 400

        try:
            rows = import_frame_to_sql(frame, get_db_path(), replace=False, config=config, filename=uploaded.filename)
            train_model(get_db_path(), get_model_path(), config=config)
        except Exception as exc:
            return jsonify({"status": "error", "message": f"Analysis failed: {exc}"}), 400

        return jsonify({"status": "ok", "rows": rows, "filename": uploaded.filename})

    @app.route("/api/charts")
    def charts_api():
        conn = get_connection()
        data = conn.execute(
            """
            SELECT cp.prediction_label, COUNT(*) AS customers
            FROM churn_predictions cp
            JOIN customer_churn cc ON cp.customer_id = cc.customer_id
            JOIN data_sources ds ON cc.source_id = ds.source_id
            WHERE ds.is_active = 1
            GROUP BY cp.prediction_label
            ORDER BY customers DESC
            """
        ).fetchall()

        cols = customer_columns(conn)
        numeric_candidates = [c for c in ("support_tickets", "complaint_count", "customer_satisfaction_score", "payment_delays")
                              if c in cols]
        signal_rows = []
        if numeric_candidates:
            sel = ", ".join(f"cc.{c}" for c in numeric_candidates)
            signal_rows = conn.execute(
                f"""
                SELECT {sel} FROM churn_predictions cp 
                LEFT JOIN customer_churn cc ON cc.customer_id = cp.customer_id
                JOIN data_sources ds ON cc.source_id = ds.source_id
                WHERE ds.is_active = 1
                """
            ).fetchall()
        conn.close()

        signals = []
        if "support_tickets" in cols:
            signals.append({"label": "High support tickets", "value": sum(1 for r in signal_rows if (r["support_tickets"] or 0) >= 3)})
        if "complaint_count" in cols:
            signals.append({"label": "High complaints", "value": sum(1 for r in signal_rows if (r["complaint_count"] or 0) >= 3)})
        if "customer_satisfaction_score" in cols:
            signals.append({"label": "Low satisfaction", "value": sum(1 for r in signal_rows if (r["customer_satisfaction_score"] or 0) <= 2)})
        if "payment_delays" in cols:
            signals.append({"label": "Payment delays", "value": sum(1 for r in signal_rows if (r["payment_delays"] or 0) >= 1)})

        return jsonify({
            "charts": [{"label": row["prediction_label"], "value": row["customers"]} for row in data],
            "signals": [s for s in signals if s["value"]],
        })

    @app.route("/api/insights")
    def insights_api():
        role = request.args.get("role", "manager").lower()
        config = load_config(CONFIG_PATH)
        label_mapping = config.get("label_mapping", {})
        high_risk_label = label_mapping.get("high_risk", "high_risk")
        low_risk_label = label_mapping.get("low_risk", "low_risk")

        conn = get_connection()
        rows = conn.execute(
            """
            SELECT prediction_label, COUNT(*) AS customers, ROUND(AVG(predicted_probability), 3) AS avg_probability
            FROM churn_predictions
            GROUP BY prediction_label
            ORDER BY customers DESC
            """
        ).fetchall()

        cols = customer_columns(conn)
        signal_cols = [c for c in ("support_tickets", "complaint_count", "customer_satisfaction_score", "payment_delays") if c in cols]
        customer_rows = []
        if signal_cols:
            sel = "cp.prediction_label, " + ", ".join(f"cc.{c}" for c in signal_cols)
            customer_rows = conn.execute(
                f"SELECT {sel} FROM churn_predictions cp LEFT JOIN customer_churn cc ON cc.customer_id = cp.customer_id"
            ).fetchall()
        conn.close()

        high_risk = next((row for row in rows if row["prediction_label"] == high_risk_label), None)
        low_risk = next((row for row in rows if row["prediction_label"] == low_risk_label), None)
        recommendations = []

        def cnt(col, threshold, cmp):
            return sum(1 for r in customer_rows if r["prediction_label"] == high_risk_label and cmp(r[col] or 0, threshold))

        if high_risk and high_risk["customers"]:
            recommendations.append(
                f"{role.title()} action: prioritize {high_risk['customers']} high-risk records with targeted retention outreach, service recovery, and executive follow-up."
            )
        if "support_tickets" in cols:
            v = cnt("support_tickets", 3, lambda a, b: a >= b)
            if v:
                recommendations.append(f"Assign senior support to {v} records with repeated support tickets and elevated churn signals.")
        if "complaint_count" in cols:
            v = cnt("complaint_count", 3, lambda a, b: a >= b)
            if v:
                recommendations.append(f"Escalate {v} complaint-heavy records for immediate issue resolution and loyalty recovery.")
        if "customer_satisfaction_score" in cols:
            v = cnt("customer_satisfaction_score", 2, lambda a, b: a <= b)
            if v:
                recommendations.append(f"Launch proactive outreach to {v} records with low satisfaction scores before churn escalates.")
        if "payment_delays" in cols:
            v = cnt("payment_delays", 1, lambda a, b: a >= b)
            if v:
                recommendations.append(f"Offer billing flexibility or payment-plan options to {v} records showing late-payment behavior.")
        if low_risk and low_risk["customers"]:
            recommendations.append(
                f"Protect {low_risk['customers']} lower-risk records with loyalty offers, product guidance, and regular engagement."
            )
        if not recommendations:
            recommendations.append("No churn activity detected yet; upload more customer data to generate insights.")

        return jsonify({
            "role": role,
            "recommendations": recommendations,
            "summary": [dict(row) for row in rows],
        })

    @app.route("/api/ai-insights")
    def ai_insights_api():
        api_key = request.args.get("model_key") or request.args.get("api_key") or os.environ.get("GEMINI_API_KEY")
        try:
            conn = get_connection()
            cols = [c for c in customer_columns(conn) if c != "customer_id"]
            cc_cols = ", ".join(f'cc."{c}"' for c in cols) if cols else ""
            if cc_cols:
                cc_cols = ", " + cc_cols
            rows = conn.execute(
                f"""
                SELECT cp.customer_id, cp.predicted_probability, cp.prediction_label{cc_cols}
                FROM churn_predictions cp
                LEFT JOIN customer_churn cc ON cc.customer_id = cp.customer_id
                JOIN data_sources ds ON cc.source_id = ds.source_id
                WHERE ds.is_active = 1
                ORDER BY cp.predicted_probability DESC
                """
            ).fetchall()
            conn.close()

            row_dicts = [dict(row) for row in rows]
            config = load_config(CONFIG_PATH)
            company = config.get("company_name", "RetentionIQ Analytics")
            if api_key:
                from churn_analysis import generate_insight_with_gemini
                insight = generate_insight_with_gemini(row_dicts, api_key, config=config, company_name=company)
            else:
                insight = generate_ai_insight_with_llm(row_dicts, config=config, company_name=company)
            return jsonify(insight)
        except Exception:
            return jsonify({
                "headline": "Awaiting data",
                "narrative": "No customer data has been analyzed yet. Upload a customer file to receive an AI-generated retention narrative.",
                "segments": [],
                "avg_probability": 0.0,
                "high_risk": 0,
                "low_risk": 0,
                "total": 0,
                "source": "local",
            })

    @app.route("/api/chat", methods=["POST"])
    def chat_api():
        data = request.json or {}
        user_message = data.get("message")
        history = data.get("history", [])
        model_key = data.get("model_key") or data.get("api_key") or os.environ.get("GEMINI_API_KEY")

        if not user_message:
            return jsonify({"error": "Message is required."}), 400

        # Strategy 1: Active Key with Cloud Model
        if model_key:
            try:
                from churn_analysis import get_database_context_summary
                db_context = get_database_context_summary(get_db_path())

                system_instruction = (
                    "You are '@ AI', a professional Senior Managing Consultant, Principal Data Scientist, and human customer retention expert. "
                    "You speak to the user with high respect, professional courtesy, and strategic clarity. "
                    "Avoid robotic AI boilerplate (such as 'as an AI', 'sure here is', 'I do not have feelings', etc.). "
                    "Address the user directly as a colleague or executive client. "
                    "Analyze statistical models, expected financial loss, contract distributions, and predictive probabilities with academic precision. "
                    "Present step-by-step reasoning and strategic advice when designing retention outreach programs (discounts, personalized emails, or callbacks). "
                    "If the user asks to create or download Power BI or Tableau dashboards, politely explain the export solution and provide the following download links: "
                    "'[Download Power BI Datasource (.pbids)](/api/export/powerbi)' and '[Download Tableau Workbook (.twb)](/api/export/tableau)'. "
                    "Keep your tone well-mannered, highly expert, and natural. Format your responses in clean Markdown."
                )

                contents = []
                context_text = f"{db_context}\n\nUse the database context above to answer all related questions."
                contents.append({
                    "role": "user",
                    "parts": [{"text": context_text}]
                })
                contents.append({
                    "role": "model",
                    "parts": [{"text": "Understood. I have loaded the database context and will use it to answer your queries."}]
                })

                for h in history:
                    role = "user" if h.get("role") == "user" else "model"
                    contents.append({
                        "role": role,
                        "parts": [{"text": h.get("text", "")}]
                    })

                contents.append({
                    "role": "user",
                    "parts": [{"text": user_message}]
                })

                import urllib.request
                import json as _json
                import ssl

                payload = {
                    "contents": contents,
                    "systemInstruction": {"parts": [{"text": system_instruction}]}
                }

                url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={model_key}"
                req = urllib.request.Request(
                    url,
                    data=_json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST"
                )
                context = ssl._create_unverified_context()
                with urllib.request.urlopen(req, timeout=10, context=context) as resp:
                    result = _json.loads(resp.read().decode("utf-8"))

                if "error" not in result and "candidates" in result and result["candidates"]:
                    reply = result['candidates'][0]['content']['parts'][0]['text']
                    return jsonify({"response": reply})
            except Exception:
                pass

        # Strategy 2: Ollama Local Server Mode
        try:
            import urllib.request
            import json as _json
            ollama_url = "http://localhost:11434/api/generate"
            payload = {
                "model": "llama3.2",
                "prompt": f"You are @ AI, a Lead Data Scientist. Treat the query professionally. Answer this: {user_message}",
                "stream": False
            }
            req = urllib.request.Request(
                ollama_url,
                data=_json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=3) as resp:
                res = _json.loads(resp.read().decode("utf-8"))
                return jsonify({"response": res.get("response", "")})
        except Exception:
            pass

        # Strategy 3: Factual Offline SQLite Solver (Zero-Key Fallback)
        try:
            conn = get_connection()
            cols = [row[1] for row in conn.execute("PRAGMA table_info(customer_churn)").fetchall()]
            stats = conn.execute(
                """
                SELECT COUNT(*) as total_customers,
                       AVG(cp.predicted_probability) as avg_risk
                FROM churn_predictions cp
                JOIN customer_churn cc ON cp.customer_id = cc.customer_id
                JOIN data_sources ds ON cc.source_id = ds.source_id
                WHERE ds.is_active = 1
                """
            ).fetchone()
            total_cust = stats["total_customers"] or 0
            avg_risk = stats["avg_risk"] or 0.0

            msg_lower = user_message.lower()
            if "power bi" in msg_lower or "powerbi" in msg_lower or "tableau" in msg_lower or "dashboard" in msg_lower:
                res_text = (
                    "### Professional Dashboard Integration Advisory\n\n"
                    "To support your executive reporting and visualization needs, I have compiled custom connection templates that map directly to your live SQLite predictions database:\n\n"
                    "- 📊 **[Download Power BI Datasource (.pbids)](/api/export/powerbi)**\n"
                    "- 🎨 **[Download Tableau Workbook (.twb)](/api/export/tableau)**\n\n"
                    "**Implementation Procedure:**\n"
                    "1. Save the desired template link to your workspace.\n"
                    "2. Open the file directly using Power BI Desktop or Tableau Desktop.\n"
                    "3. The connection string will automatically bind and sync all active customer attributes and model prediction tables for immediate report creation."
                )
            elif "contract" in msg_lower or "types" in msg_lower or "breakdown" in msg_lower:
                q = """
                    SELECT cc.contract_type, COUNT(*) as cnt, AVG(cp.predicted_probability) as risk
                    FROM churn_predictions cp
                    JOIN customer_churn cc ON cp.customer_id = cc.customer_id
                    WHERE cc.contract_type IS NOT NULL
                    GROUP BY cc.contract_type
                    ORDER BY risk DESC
                """
                rows = conn.execute(q).fetchall()
                res_text = (
                    "### Strategic Contract Risk Assessment\n\n"
                    "An evaluation of active customer billing terms reveals the following distribution profiles:\n\n"
                )
                for r in rows:
                    res_text += f"- **{r['contract_type']}**: {r['cnt']} accounts analyzed (Average predictive risk: {r['risk']:.1%})\n"
                res_text += (
                    "\n**Operational Recommendation:**\n"
                    "Our month-to-month portfolios continue to exhibit the highest predictive churn risk. "
                    "I recommend establishing outreach targets to transition these accounts to longer-term commitments."
                )
            elif "email" in msg_lower or "draft" in msg_lower or "personalized" in msg_lower or "outreach" in msg_lower:
                res_text = (
                    "### Strategic Retention Outreach Draft\n\n"
                    "Here is a professional communication template tailored to address customer experience friction:\n\n"
                    "**Subject: Optimizing your experience with our services**\n\n"
                    "Dear Client,\n\n"
                    "At our company, we are dedicated to providing seamless service. To ensure we continue to exceed "
                    "your expectations, we have pre-approved a 20% loyalty credit for your next three billing cycles. "
                    "If you would like to discuss your service profile, please let me know and we will arrange a priority call.\n\n"
                    "Warm regards,\n"
                    "Customer Experience Director"
                )
            elif "charges" in msg_lower or "billing" in msg_lower or "monthly" in msg_lower:
                res_text = (
                    "### Revenue Exposure Analysis\n\n"
                    f"Our database reports an average billing metric of ${100.0 * avg_risk:.2f} weighted risk exposure "
                    f"across {total_cust} accounts. Focus areas should prioritize high-value contract retention outreach to maximize ARR preservation."
                )
            elif "top" in msg_lower or "risk" in msg_lower or "highest" in msg_lower or "churn" in msg_lower:
                q = """
                    SELECT cp.customer_id, cp.predicted_probability
                    FROM churn_predictions cp
                    ORDER BY cp.predicted_probability DESC
                    LIMIT 5
                """
                rows = conn.execute(q).fetchall()
                res_text = (
                    "### Executive Action List: Highest Churn Risks\n\n"
                    "I have flagged the top five accounts with critical predictive risk scores:\n\n"
                )
                for r in rows:
                    res_text += f"- **{r['customer_id']}**: Churn probability score {r['predicted_probability']:.1%}\n"
                res_text += "\n**Next Steps:**\nI advise assigning these priority client accounts to senior managers for immediate direct engagement."
            else:
                res_text = (
                    "### Senior Data Science Consultation\n\n"
                    f"I have completed a statistical evaluation of your active customer records ({total_cust} total accounts, average predictive probability: {avg_risk:.1%}).\n\n"
                    "We can analyze risk factors, design custom customer outreach email templates, or download interactive Power BI / Tableau templates. "
                    "Please let me know how I can best support your retention strategy today."
                )
            conn.close()
            return jsonify({"response": res_text})
        except Exception as ex:
            return jsonify({"response": f"Factual fallback mode error: {ex}"})

    @app.route("/api/export/tableau")
    def export_tableau_api():
        try:
            db_path = os.path.abspath(get_db_path()).replace("\\", "/")
            twb_content = f"""<?xml version='1.0' encoding='utf-8' ?>
<workbook version='18.1' xmlns:user='http://www.tableausoftware.com/xml/user'>
  <preferences />
  <datasources>
    <datasource caption='RetentionIQ Churn Analysis' name='sqlite_ds' version='18.1'>
      <connection class='sqlite' database='{db_path}' server=''>
        <relation join='left' type='join'>
          <clause type='join'>
            <expression op='='>
              <expression op='[customer_churn].[customer_id]' />
              <expression op='[churn_predictions].[customer_id]' />
            </expression>
          </clause>
          <relation name='customer_churn' table='[customer_churn]' type='table' />
          <relation name='churn_predictions' table='[churn_predictions]' type='table' />
        </relation>
      </connection>
    </datasource>
  </datasources>
  <worksheets>
    <worksheet name='Executive Overview'>
      <table>
        <rows>[sqlite_ds].[customer_id]</rows>
      </table>
    </worksheet>
  </worksheets>
</workbook>"""
            return Response(
                twb_content,
                mimetype="application/xml",
                headers={"Content-Disposition": "attachment; filename=RetentionIQ_Tableau_Dashboard.twb"}
            )
        except Exception as e:
            return jsonify({"error": f"Failed to generate Tableau template: {e}"}), 500

    @app.route("/api/export/powerbi")
    def export_powerbi_api():
        try:
            db_path = os.path.abspath(get_db_path()).replace("\\", "/")
            pbids_data = {
                "version": "1.0",
                "connections": [
                    {
                        "type": "Sqlite",
                        "address": {
                          "path": db_path
                        },
                        "authentication": None,
                        "query": None
                    }
                ]
            }
            return Response(
                json.dumps(pbids_data, indent=2),
                mimetype="application/json",
                headers={"Content-Disposition": "attachment; filename=RetentionIQ_PowerBI_Source.pbids"}
            )
        except Exception as e:
            return jsonify({"error": f"Failed to generate Power BI datasource: {e}"}), 500

    @app.route("/api/export/excel")
    def export_excel_api():
        try:
            conn = get_connection()
            has_preds = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='churn_predictions'").fetchone()[0]
            if not has_preds:
                conn.close()
                return jsonify({"error": "No predictions available. Please upload data first."}), 400
                
            cols = [c for c in customer_columns(conn) if c != "customer_id"]
            cc_cols = ", ".join(f'cc."{c}"' for c in cols) if cols else ""
            if cc_cols:
                cc_cols = ", " + cc_cols
            query = f"""
            SELECT cp.customer_id, cp.predicted_probability, cp.prediction_label{cc_cols}
            FROM churn_predictions cp
            LEFT JOIN customer_churn cc ON cc.customer_id = cp.customer_id
            JOIN data_sources ds ON cc.source_id = ds.source_id
            WHERE ds.is_active = 1
            ORDER BY cp.predicted_probability DESC
            """
            frame = pd.read_sql_query(query, conn)
            conn.close()

            if frame.empty:
                return jsonify({"error": "No active customer records to export."}), 400

            output = BytesIO()
            try:
                with pd.ExcelWriter(output, engine="openpyxl") as writer:
                    frame.to_excel(writer, sheet_name="Churn Analysis", index=False)
                mimetype = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                filename = "churn_analysis.xlsx"
            except Exception:
                frame.to_csv(output, index=False, encoding="utf-8-sig")
                mimetype = "text/csv"
                filename = "churn_analysis.csv"
            
            output.seek(0)
            return Response(output.getvalue(), mimetype=mimetype, headers={"Content-Disposition": f"attachment; filename={filename}"})
        except Exception as e:
            return jsonify({"error": f"Failed to export excel: {e}"}), 500

    @app.route("/api/export/pdf")
    def export_pdf_api():
        try:
            conn = get_connection()
            has_preds = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='churn_predictions'").fetchone()[0]
            if not has_preds:
                conn.close()
                return Response("<h3>No predictions available yet. Please upload data first.</h3>", mimetype="text/html"), 400
                
            cols = [c for c in customer_columns(conn) if c != "customer_id"]
            cc_cols = ", ".join(f'cc."{c}"' for c in cols) if cols else ""
            if cc_cols:
                cc_cols = ", " + cc_cols
            rows = conn.execute(
                f"""
                SELECT cp.customer_id, cp.predicted_probability, cp.prediction_label{cc_cols}
                FROM churn_predictions cp
                LEFT JOIN customer_churn cc ON cc.customer_id = cp.customer_id
                JOIN data_sources ds ON cc.source_id = ds.source_id
                WHERE ds.is_active = 1
                ORDER BY cp.predicted_probability DESC
                """
            ).fetchall()
            conn.close()

            if not rows:
                return Response("<h3>No active customer records to export.</h3>", mimetype="text/html"), 400

            attr_cols = [c for c in cols if c not in ("customer_id",)]
            headers = ["Customer", "Risk", "Probability"] + [c.replace("_", " ").title() for c in attr_cols[:4]]
            rows_html = "".join(
                "<tr>" +
                f"<td>{row['customer_id']}</td>" +
                f"<td>{row['prediction_label']}</td>" +
                f"<td>{row['predicted_probability']:.3f}</td>" +
                "".join(f"<td>{row[c] if row[c] is not None else 'n/a'}</td>" for c in attr_cols[:4]) +
                "</tr>"
                for row in rows
            )
            head_html = "".join(f"<th>{h}</th>" for h in headers)
            html = f"""<!doctype html><html><head><meta charset='utf-8'><title>RetentionIQ Report</title><style>body{{font-family:Arial, sans-serif; padding:24px; color:#111827;}}table{{width:100%; border-collapse:collapse; margin-top:16px;}}th,td{{border:1px solid #cbd5e1; padding:8px; text-align:left;}}h1{{color:#1d4ed8;}}</style></head><body><h1>RetentionIQ Churn Report</h1><p>Professional retention analysis generated from the uploaded customer file.</p><table><thead><tr>{head_html}</tr></thead><tbody>{rows_html}</tbody></table><script>window.onload=function(){{window.print();}};</script></body></html>"""
            return Response(html, mimetype="text/html")
        except Exception as e:
            return Response(f"<h3>Export failed: {e}</h3>", mimetype="text/html"), 500

    # Sources endpoints
    @app.route("/api/sources")
    def get_sources():
        conn = get_connection()
        rows = conn.execute("SELECT * FROM data_sources ORDER BY created_at DESC").fetchall()
        conn.close()
        return jsonify({"sources": [dict(row) for row in rows]})

    @app.route("/api/sources/toggle", methods=["POST"])
    def toggle_source():
        data = request.json or {}
        source_id = data.get("source_id")
        is_active = data.get("is_active")
        if source_id is None or is_active is None:
            return jsonify({"error": "source_id and is_active are required."}), 400
        
        conn = get_connection()
        conn.execute("UPDATE data_sources SET is_active = ? WHERE source_id = ?", (is_active, source_id))
        conn.commit()
        conn.close()

        try:
            train_model(get_db_path(), get_model_path(), config=load_config(CONFIG_PATH))
        except Exception:
            pass

        return jsonify({"status": "ok"})

    @app.route("/api/sources/<source_id>", methods=["DELETE"])
    def delete_source(source_id):
        conn = get_connection()
        conn.execute("DELETE FROM churn_predictions WHERE customer_id IN (SELECT customer_id FROM customer_churn WHERE source_id = ?)", (source_id,))
        conn.execute("DELETE FROM customer_churn WHERE source_id = ?", (source_id,))
        conn.execute("DELETE FROM data_sources WHERE source_id = ?", (source_id,))
        conn.commit()
        conn.close()

        try:
            train_model(get_db_path(), get_model_path(), config=load_config(CONFIG_PATH))
        except Exception:
            pass

        return jsonify({"status": "ok"})

    # Notes endpoints
    @app.route("/api/notes")
    def get_notes():
        conn = get_connection()
        rows = conn.execute("SELECT * FROM user_notes ORDER BY created_at DESC").fetchall()
        conn.close()
        return jsonify({"notes": [dict(row) for row in rows]})

    @app.route("/api/notes", methods=["POST"])
    def add_note():
        data = request.json or {}
        title = data.get("title")
        content = data.get("content")
        if not title or not content:
            return jsonify({"error": "title and content are required."}), 400
            
        conn = get_connection()
        conn.execute("INSERT INTO user_notes (title, content, created_at) VALUES (?, ?, ?)",
                     (title, content, datetime.now().isoformat()))
        conn.commit()
        conn.close()
        return jsonify({"status": "ok"})

    @app.route("/api/notes/<int:note_id>", methods=["DELETE"])
    def delete_note(note_id):
        conn = get_connection()
        conn.execute("DELETE FROM user_notes WHERE note_id = ?", (note_id,))
        conn.commit()
        conn.close()
        return jsonify({"status": "ok"})

    # Business analytics endpoint
    @app.route("/api/business-analytics")
    def business_analytics_api():
        conn = get_connection()
        cols = [row[1] for row in conn.execute("PRAGMA table_info(customer_churn)").fetchall()]
        charges_col = next((c for c in cols if c.lower() in ("monthly_charges", "monthlycharges", "charges", "monthly_charge", "monthly")), None)
        
        # 1. Overall stats
        if charges_col:
            stats = conn.execute(
                f"""
                SELECT COUNT(*) as total_customers,
                       SUM(cc."{charges_col}") as total_charges,
                       SUM(cc."{charges_col}" * cp.predicted_probability) as expected_loss
                FROM churn_predictions cp
                JOIN customer_churn cc ON cp.customer_id = cc.customer_id
                JOIN data_sources ds ON cc.source_id = ds.source_id
                WHERE ds.is_active = 1
                """
            ).fetchone()
        else:
            stats = conn.execute(
                """
                SELECT COUNT(*) as total_customers,
                       COUNT(*) * 100.0 as total_charges,
                       SUM(100.0 * cp.predicted_probability) as expected_loss
                FROM churn_predictions cp
                JOIN customer_churn cc ON cp.customer_id = cc.customer_id
                JOIN data_sources ds ON cc.source_id = ds.source_id
                WHERE ds.is_active = 1
                """
            ).fetchone()
            
        total_cust = stats["total_customers"] or 0
        total_charges = stats["total_charges"] or 0.0
        expected_loss = stats["expected_loss"] or 0.0
        
        # 2. Segment-based risks
        segments = []
        group_cols = [c for c in ("contract_type", "payment_method", "internet_service", "region") if c in cols]
        
        for g_col in group_cols:
            if charges_col:
                q = f"""
                    SELECT cc."{g_col}" as segment_val,
                           COUNT(*) as segment_count,
                           AVG(cp.predicted_probability) as avg_risk,
                           SUM(cc."{charges_col}" * cp.predicted_probability) as segment_loss
                    FROM churn_predictions cp
                    JOIN customer_churn cc ON cp.customer_id = cc.customer_id
                    JOIN data_sources ds ON cc.source_id = ds.source_id
                    WHERE ds.is_active = 1 AND cc."{g_col}" IS NOT NULL
                    GROUP BY cc."{g_col}"
                """
            else:
                q = f"""
                    SELECT cc."{g_col}" as segment_val,
                           COUNT(*) as segment_count,
                           AVG(cp.predicted_probability) as avg_risk,
                           SUM(100.0 * cp.predicted_probability) as segment_loss
                    FROM churn_predictions cp
                    JOIN customer_churn cc ON cp.customer_id = cc.customer_id
                    JOIN data_sources ds ON cc.source_id = ds.source_id
                    WHERE ds.is_active = 1 AND cc."{g_col}" IS NOT NULL
                    GROUP BY cc."{g_col}"
                """
            rows = conn.execute(q).fetchall()
            for r in rows:
                segments.append({
                    "dimension": g_col.replace("_", " ").title(),
                    "value": r["segment_val"],
                    "count": r["segment_count"],
                    "avg_risk": round(float(r["avg_risk"]), 3),
                    "expected_loss": round(float(r["segment_loss"]), 2)
                })
                
        segments.sort(key=lambda s: s["expected_loss"], reverse=True)
        conn.close()
        
        return jsonify({
            "total_customers": total_cust,
            "total_charges": round(total_charges, 2),
            "expected_loss": round(expected_loss, 2),
            "risk_exposure_pct": round((expected_loss / total_charges * 100), 1) if total_charges > 0 else 0.0,
            "segments": segments
        })

    # Presentation slides builder endpoint
    @app.route("/api/presentation", methods=["POST"])
    def presentation_api():
        data = request.json or {}
        api_key = data.get("api_key") or os.environ.get("GEMINI_API_KEY")
        
        # 1. Fetch current database stats
        conn = get_connection()
        cols = [row[1] for row in conn.execute("PRAGMA table_info(customer_churn)").fetchall()]
        charges_col = next((c for c in cols if c.lower() in ("monthly_charges", "monthlycharges", "charges", "monthly_charge", "monthly")), None)
        
        stats = conn.execute(
            """
            SELECT COUNT(*) as total_customers,
                   AVG(cp.predicted_probability) as avg_risk
            FROM churn_predictions cp
            JOIN customer_churn cc ON cp.customer_id = cc.customer_id
            JOIN data_sources ds ON cc.source_id = ds.source_id
            WHERE ds.is_active = 1
            """
        ).fetchone()
        
        total_cust = stats["total_customers"] or 0
        avg_risk = stats["avg_risk"] or 0.0
        
        # Segment priorities (top 2 segments by expected loss)
        segments = []
        group_cols = [c for c in ("contract_type", "payment_method", "internet_service", "region") if c in cols]
        
        for g_col in group_cols:
            if charges_col:
                q = f"""
                    SELECT cc."{g_col}" as segment_val,
                           COUNT(*) as segment_count,
                           AVG(cp.predicted_probability) as avg_risk,
                           SUM(cc."{charges_col}" * cp.predicted_probability) as segment_loss
                    FROM churn_predictions cp
                    JOIN customer_churn cc ON cp.customer_id = cc.customer_id
                    JOIN data_sources ds ON cc.source_id = ds.source_id
                    WHERE ds.is_active = 1 AND cc."{g_col}" IS NOT NULL
                    GROUP BY cc."{g_col}"
                """
            else:
                q = f"""
                    SELECT cc."{g_col}" as segment_val,
                           COUNT(*) as segment_count,
                           AVG(cp.predicted_probability) as avg_risk,
                           SUM(100.0 * cp.predicted_probability) as segment_loss
                    FROM churn_predictions cp
                    JOIN customer_churn cc ON cp.customer_id = cc.customer_id
                    JOIN data_sources ds ON cc.source_id = ds.source_id
                    WHERE ds.is_active = 1 AND cc."{g_col}" IS NOT NULL
                    GROUP BY cc."{g_col}"
                """
            rows = conn.execute(q).fetchall()
            for r in rows:
                segments.append({
                    "dimension": g_col.replace("_", " ").title(),
                    "value": r["segment_val"],
                    "count": r["segment_count"],
                    "avg_risk": round(float(r["avg_risk"]), 3),
                    "expected_loss": round(float(r["segment_loss"]), 2)
                })
        conn.close()
        
        segments.sort(key=lambda s: s["expected_loss"], reverse=True)
        top_segments = segments[:2]
        
        # Fallbacks for copy
        slide1_title = "RetentionIQ Executive Presentation"
        slide1_subtitle = f"Strategic Customer Churn Analysis — {total_cust} Accounts Evaluated"
        
        slide2_title = "Executive Churn Summary"
        slide2_bullets = [
            f"Overall average customer churn risk is currently at {avg_risk:.1%}.",
            "Month-to-month contracts and manual payment methods continue to drive the highest attrition rates.",
            "Proactive engagement combined with custom incentives will secure vulnerable contract values."
        ]
        
        slide3_title = "Vulnerable Segments Analysis"
        slide3_bullets = [
            f"Top risk segment: {top_segments[0]['dimension']} '{top_segments[0]['value']}' has an expected monthly loss of ${top_segments[0]['expected_loss']:,.2f}.",
            f"Secondary risk segment: {top_segments[1]['dimension']} '{top_segments[1]['value']}' accounts represent ${top_segments[1]['expected_loss']:,.2f} in expected loss.",
            "Customers using Fiber Optic internet service require active support escalations to secure loyalty."
        ] if len(top_segments) >= 2 else ["Insufficient segment data to profile priority risks."]
        
        if api_key:
            try:
                from churn_analysis import call_gemini_api
                system_instruction = (
                    "You are a professional corporate slide designer and retention executive. "
                    "You write highly engaging, human-like presentation copy (no jargon, no typical AI transitions). "
                    "Write content for 3 main slides based on the database details. "
                    "Format the output strictly as a JSON object: "
                    '{"slide1_subtitle": "...", "slide2_bullets": ["...", "...", "..."], "slide3_bullets": ["...", "...", "..."]}. '
                    "Do not output markdown code blocks (like ```json), write only the raw JSON string. "
                    "Keep sentences brief, impactful, and ready to be printed on slides."
                )
                prompt = (
                    f"Retention Data:\n"
                    f"- Total customers: {total_cust}\n"
                    f"- Average risk probability: {avg_risk:.1%}\n"
                    f"- Top segments: {top_segments}\n\n"
                    "Please generate Slide 1 subtitle, Slide 2 executive summary bullets (3 items), and Slide 3 risk profile bullets (3 items)."
                )
                ai_text = call_gemini_api(prompt, api_key, system_instruction=system_instruction)
                
                cleaned = ai_text.strip()
                if cleaned.startswith("```"):
                    lines = cleaned.splitlines()
                    if lines[0].startswith("```"):
                        lines = lines[1:]
                    if lines[-1].startswith("```"):
                        lines = lines[:-1]
                    cleaned = "\n".join(lines).strip()
                    
                ai_data = json.loads(cleaned)
                if "slide1_subtitle" in ai_data:
                    slide1_subtitle = ai_data["slide1_subtitle"]
                if "slide2_bullets" in ai_data:
                    slide2_bullets = ai_data["slide2_bullets"]
                if "slide3_bullets" in ai_data:
                    slide3_bullets = ai_data["slide3_bullets"]
            except Exception:
                pass
                
        slides = [
            {
                "layout": "title",
                "title": slide1_title,
                "subtitle": slide1_subtitle
            },
            {
                "layout": "split_metrics",
                "title": slide2_title,
                "bullets": slide2_bullets
            },
            {
                "layout": "segment_comparison",
                "title": slide3_title,
                "bullets": slide3_bullets
            },
            {
                "layout": "journey_workflow",
                "title": "Interactive Retention Roadmap",
                "steps": [
                    {"title": "Identify Risk", "description": "@ AI scans accounts for predictive churn metrics."},
                    {"title": "Design Action", "description": "Formulate billing recovery & proactive support incentives."},
                    {"title": "Execute Offer", "description": "Managers initiate outreach using pre-compiled templates."},
                    {"title": "Secure ARR", "description": "Contracts successfully extended; customer retention maximized."}
                ]
            }
        ]
        
        return jsonify({"slides": slides})

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
