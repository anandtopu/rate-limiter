import pytest

from app.config import settings


@pytest.mark.asyncio
async def test_demo_dashboard_returns_html(client):
    response = await client.get("/demo")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Rate Limiter Demo" in response.text


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
