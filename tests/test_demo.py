import pytest

from app.config import settings


@pytest.mark.asyncio
async def test_demo_dashboard_returns_html(client):
    response = await client.get("/demo")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Rate Limiter Demo" in response.text
    assert "Persisted Telemetry" in response.text
    assert "persistentRangeSelect" in response.text
    assert "Rule Change Controls" in response.text
    assert "auditReasonInput" in response.text
    assert "Pending Approvals" in response.text
    assert "approvalIdInput" in response.text
    assert "includeResolvedApprovalsInput" in response.text
    assert "Rule Audit" in response.text
    assert "auditRouteFilterInput" in response.text
    assert "auditSensitivityFilterSelect" in response.text
    assert "recommendationDraftBtn" in response.text
    assert "Anomalies" in response.text
    assert "anomaliesBtn" in response.text
    assert "AI Research Report" in response.text
    assert "aiResearchReportBtn" in response.text
    assert "aiResearchReportDownloadBtn" in response.text
    assert "Policy Copilot" in response.text
    assert "policyCopilotBtn" in response.text


@pytest.mark.asyncio
async def test_demo_dashboard_can_be_disabled(client):
    settings.expose_demo_dashboard = False

    response = await client.get("/demo")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_demo_static_assets_are_served(client):
    css_response = await client.get("/static/demo.css")
    js_response = await client.get("/static/demo.js")

    assert css_response.status_code == 200
    assert "text/css" in css_response.headers["content-type"]
    assert js_response.status_code == 200
    assert "javascript" in js_response.headers["content-type"]
    assert "loadPersistentTelemetry" in js_response.text
    assert "persistentTelemetryQuery" in js_response.text
    assert "since" in js_response.text
    assert "applyRulesUpdate" in js_response.text
    assert "loadPendingApprovals" in js_response.text
    assert "decidePendingApproval" in js_response.text
    assert "/admin/rules/pending" in js_response.text
    assert "loadAuditView" in js_response.text
    assert "auditViewQuery" in js_response.text
    assert "/admin/rules/audit" in js_response.text
    assert "draftRecommendationPolicy" in js_response.text
    assert "/admin/rules/recommendation-draft" in js_response.text
    assert "loadAnomalies" in js_response.text
    assert "/admin/ai/anomalies" in js_response.text
    assert "loadAIResearchReport" in js_response.text
    assert "downloadAIResearchReport" in js_response.text
    assert "downloadFilename" in js_response.text
    assert "/admin/ai/research-report" in js_response.text
    assert "format=markdown&download=true" in js_response.text
    assert "Content-Disposition" in js_response.text
    assert "AI_RESEARCH_REPORT.md" in js_response.text
    assert "runPolicyCopilot" in js_response.text
    assert "/admin/ai/policy-copilot" in js_response.text
    assert "X-Audit-Reason" in js_response.text
    assert "summary-strip" in css_response.text
    assert "telemetry-controls" in css_response.text
    assert "audit-grid" in css_response.text
    assert "audit-filter-grid" in css_response.text
    assert "approval-grid" in css_response.text
