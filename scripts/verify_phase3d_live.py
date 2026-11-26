"""Phase 3D Lite live acceptance test script for FinAssist AI Financial Analytics Dashboard."""

import json
import os
import sys
import time
from pathlib import Path
from uuid import uuid4

import httpx

ROOT = Path(__file__).resolve().parent.parent
BASE_URL = os.environ.get("FINASSIST_BASE_URL", "http://localhost:8000")
FIXTURES_DIR = ROOT / "reports" / "phase3b_fixtures"

def run_phase3d_live_acceptance() -> dict:
    results = {
        "tests": [],
        "overall_status": "PENDING",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    client = httpx.Client(base_url=BASE_URL, timeout=90.0)

    # 1. Health check
    print("[1] Checking backend health ready endpoint...")
    health_resp = client.get("/api/health/ready")
    assert health_resp.status_code == 200, f"Health check failed: {health_resp.text}"
    health_data = health_resp.json()
    assert health_data.get("status") == "ready", f"Service not ready: {health_data}"
    results["tests"].append({
        "name": "Health Ready Check",
        "status": "PASS",
        "details": health_data,
    })
    print("    [OK] Backend health ready:", health_data)

    # 2. Register User 1
    user1_email = f"phase3d-auditor-{uuid4().hex[:8]}@example.com"
    password = "SecurePhase3dPassword123!"
    reg_resp = client.post(
        "/api/auth/register",
        json={"full_name": "Phase 3D Lead Auditor", "email": user1_email, "password": password},
    )
    assert reg_resp.status_code == 201, f"Registration failed: {reg_resp.text}"

    login_resp = client.post(
        "/api/auth/login",
        json={"email": user1_email, "password": password},
    )
    assert login_resp.status_code == 200, f"Login failed: {login_resp.text}"
    user1_token = login_resp.json()["access_token"]
    user1_headers = {"Authorization": f"Bearer {user1_token}"}
    print("    [OK] User 1 registered and authenticated:", user1_email)

    # 3. Upload multi-year PDF (three_year.pdf)
    three_year_path = FIXTURES_DIR / "three_year.pdf"
    assert three_year_path.exists(), f"three_year.pdf not found at {three_year_path}"
    with open(three_year_path, "rb") as f:
        upload_resp = client.post(
            "/api/documents/upload",
            headers=user1_headers,
            files={"file": ("three_year.pdf", f, "application/pdf")},
        )
    assert upload_resp.status_code in (200, 201), f"Upload failed: {upload_resp.text}"
    upload_data = upload_resp.json()
    doc_id = upload_data["id"]
    print(f"    [OK] three_year.pdf uploaded. Document ID: {doc_id}, status: {upload_data.get('processing_status')}")

    # Wait for document processing to reach completed
    deadline = time.time() + 60
    while time.time() < deadline:
        status_resp = client.get(f"/api/documents/{doc_id}", headers=user1_headers)
        if status_resp.status_code == 200:
            doc_info = status_resp.json()
            if doc_info.get("processing_status") == "completed":
                print("    [OK] Document processing completed successfully.")
                break
            elif doc_info.get("processing_status") == "failed":
                raise RuntimeError(f"Document processing failed: {doc_info.get('processing_error')}")
        time.sleep(2)

    # 4. Query Financial Analytics Dashboard for multi-year document
    print("[2] Testing GET /api/dashboard/{doc_id} for multi-year report...")
    dash_resp = client.get(f"/api/dashboard/{doc_id}", headers=user1_headers)
    assert dash_resp.status_code == 200, f"Dashboard fetch failed: {dash_resp.text}"
    dash_data = dash_resp.json()

    # Validate high-level fields
    assert dash_data["document_id"] == doc_id
    assert dash_data["has_financial_data"] is True
    assert len(dash_data["available_years"]) >= 3

    # Validate KPI cards
    cards_by_label = {c["label"]: c for c in dash_data["kpi_cards"]}
    assert "Total Revenue" in cards_by_label
    assert "Gross Profit" in cards_by_label
    assert "Gross Margin" in cards_by_label
    assert "Net Income" in cards_by_label

    rev_card = cards_by_label["Total Revenue"]
    assert rev_card["value"] == 1200000.0
    assert rev_card["period"] == "FY2025"
    assert rev_card["yoy_change"] == 26.32
    assert rev_card["yoy_change_formatted"] == "+26.32%"
    assert rev_card["source_citation"] == "Page 1"
    print(f"    [OK] Revenue KPI: {rev_card['formatted_value']} ({rev_card['yoy_change_formatted']} YoY)")

    gp_card = cards_by_label["Gross Profit"]
    assert gp_card["value"] == 420000.0
    assert gp_card["period"] == "FY2025"
    assert gp_card["yoy_change"] == 31.25
    assert gp_card["yoy_change_formatted"] == "+31.25%"
    print(f"    [OK] Gross Profit KPI: {gp_card['formatted_value']} ({gp_card['yoy_change_formatted']} YoY)")

    gpm_card = cards_by_label["Gross Margin"]
    assert gpm_card["value"] == 35.0
    assert gpm_card["period"] == "FY2025"
    assert gpm_card["yoy_change"] == 1.32
    assert gpm_card["yoy_change_formatted"] == "+1.32 pp"
    assert gpm_card["yoy_change_unit"] == "pp"
    print(f"    [OK] Gross Margin KPI: {gpm_card['formatted_value']} ({gpm_card['yoy_change_formatted']})")

    ni_card = cards_by_label["Net Income"]
    assert ni_card["value"] == 91000.0
    assert ni_card["period"] == "FY2025"
    assert ni_card["yoy_change"] == 16.67
    print(f"    [OK] Net Income KPI: {ni_card['formatted_value']} ({ni_card['yoy_change_formatted']} YoY)")

    # Validate Trends
    assert len(dash_data["revenue_trend"]) == 3
    assert [p["fiscal_year"] for p in dash_data["revenue_trend"]] == ["FY2023", "FY2024", "FY2025"]
    assert [p["revenue"] for p in dash_data["revenue_trend"]] == [820000.0, 950000.0, 1200000.0]

    assert len(dash_data["margin_trend"]) == 3
    assert dash_data["margin_trend"][0]["gross_profit_margin"] == 31.71
    assert dash_data["margin_trend"][1]["gross_profit_margin"] == 33.68
    assert dash_data["margin_trend"][2]["gross_profit_margin"] == 35.00
    print("    [OK] Multi-year revenue and margin trends verified.")

    # Validate Summary
    summary = dash_data["summary"]
    assert summary is not None
    assert "26.32%" in summary["revenue_performance"] or "26.32%" in str(summary["key_observations"])
    assert "35.00%" in summary["profitability"] or "35.00%" in str(summary["key_observations"])
    assert len(summary["citations"]) > 0
    print("    [OK] AI Financial Performance Summary verified with grounded citations.")

    results["tests"].append({
        "name": "Multi-Year Dashboard & Trends",
        "status": "PASS",
        "kpi_cards": dash_data["kpi_cards"],
        "summary": summary,
    })

    # 5. Upload single-year PDF and verify YoY withholding
    print("[3] Testing single-year report YoY withholding...")
    simple_path = FIXTURES_DIR / "simple.pdf"
    with open(simple_path, "rb") as f:
        simple_upload = client.post(
            "/api/documents/upload",
            headers=user1_headers,
            files={"file": ("simple.pdf", f, "application/pdf")},
        )
    assert simple_upload.status_code in (200, 201)
    simple_doc_id = simple_upload.json()["id"]

    # Wait for completion
    deadline = time.time() + 60
    while time.time() < deadline:
        s_resp = client.get(f"/api/documents/{simple_doc_id}", headers=user1_headers)
        if s_resp.status_code == 200 and s_resp.json().get("processing_status") == "completed":
            break
        time.sleep(2)

    simple_dash = client.get(f"/api/dashboard/{simple_doc_id}", headers=user1_headers).json()
    assert simple_dash["has_financial_data"] is True
    # For a single-year report, all cards must have yoy_change == None
    for card in simple_dash["kpi_cards"]:
        assert card["yoy_change"] is None, f"Expected None YoY for single year, got {card['yoy_change']}"
    print("    [OK] Single-year report successfully withheld YoY change without error.")
    results["tests"].append({
        "name": "Single-Year YoY Withholding",
        "status": "PASS",
        "available_years": simple_dash["available_years"],
    })

    # 6. Verify User Isolation / Security Access Control
    print("[4] Testing Document Ownership & Access Control (User 2 Isolation)...")
    user2_email = f"phase3d-attacker-{uuid4().hex[:8]}@example.com"
    client.post(
        "/api/auth/register",
        json={"full_name": "Unauthorized User", "email": user2_email, "password": password},
    )
    user2_login = client.post("/api/auth/login", json={"email": user2_email, "password": password})
    user2_token = user2_login.json()["access_token"]
    user2_headers = {"Authorization": f"Bearer {user2_token}"}

    # User 2 tries to access User 1's document dashboard
    leak_resp = client.get(f"/api/dashboard/{doc_id}", headers=user2_headers)
    assert leak_resp.status_code == 404, f"Expected 404 for unauthorized document access, got {leak_resp.status_code}"
    print("    [OK] Unauthorized access strictly rejected with 404.")
    results["tests"].append({
        "name": "User Document Isolation (404 on Cross-Tenant)",
        "status": "PASS",
        "status_code": leak_resp.status_code,
    })

    results["overall_status"] = "PASS"
    out_file = ROOT / "reports" / "phase3d_lite_live_acceptance.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"\n[DONE] Live acceptance passed! Results saved to {out_file}")
    return results

if __name__ == "__main__":
    run_phase3d_live_acceptance()
