import pytest
import httpx
import respx
from datetime import timedelta
from src.vigilant_ai.checker import SiteChecker
from src.vigilant_ai.models import Site

@pytest.fixture
def sample_site():
    return Site(
        id=1,
        url="https://example.com",
        name="Example Test",
        timeout_seconds=5,
        headers={"User-Agent": "VigilantAI/1.0"}
    )

@pytest.fixture
def checker():
    return SiteChecker()

@pytest.mark.asyncio
@respx.mock
async def test_check_site_success(checker, sample_site):
    """Test a successful 200 OK response."""
    respx.get("https://example.com").mock(
        return_value=httpx.Response(200, content=b"Welcome to Example Domain")
    )

    result = await checker.check_site(sample_site)

    assert result.site_id == sample_site.id
    assert result.status_code == 200
    assert "Welcome to Example Domain" in result.response_body
    assert result.latency_ms > 0
    assert result.error_message is None
    assert result.is_up is True

@pytest.mark.asyncio
@respx.mock
async def test_check_site_404_error(checker, sample_site):
    """Test that a 404 is still recorded correctly as a non-exception check."""
    respx.get("https://example.com").mock(
        return_value=httpx.Response(404, content=b"Not Found")
    )

    result = await checker.check_site(sample_site)

    assert result.status_code == 404
    assert "Not Found" in result.response_body
    assert result.is_up is False  # Checker considers non-2xx as down usually
    assert result.error_message is None

@pytest.mark.asyncio
@respx.mock
async def test_check_site_timeout(checker, sample_site):
    """Test handling of request timeouts."""
    respx.get("https://example.com").mock(side_effect=httpx.TimeoutException("Request timed out"))

    result = await checker.check_site(sample_site)

    assert result.status_code == 0
    assert result.is_up is False
    assert "TimeoutException" in result.error_message
    assert result.response_body == ""

@pytest.mark.asyncio
@respx.mock
async def test_check_site_connection_error(checker, sample_site):
    """Test handling of DNS or connection failures."""
    respx.get("https://example.com").mock(side_effect=httpx.ConnectError("Failed to resolve host"))

    result = await checker.check_site(sample_site)

    assert result.status_code == 0
    assert result.is_up is False
    assert "ConnectError" in result.error_message

@pytest.mark.asyncio
@respx.mock
async def test_check_site_custom_headers(checker, sample_site):
    """Ensure custom headers from the site model are sent."""
    route = respx.get("https://example.com").mock(return_value=httpx.Response(200))
    
    await checker.check_site(sample_site)
    
    # Verify the User-Agent we set in the fixture was actually used
    assert route.calls.last.request.headers["user-agent"] == "VigilantAI/1.0"

@pytest.mark.asyncio
@respx.mock
async def test_check_site_large_payload_truncation(checker, sample_site):
    """Ensure we don't store megabytes of HTML in the database."""
    large_content = b"A" * 1_000_000 # 1MB
    respx.get("https://example.com").mock(
        return_value=httpx.Response(200, content=large_content)
    )

    result = await checker.check_site(sample_site)

    # Check if the result body is capped (assuming a 100kb limit in implementation)
    assert len(result.response_body) < len(large_content)
    assert len(result.response_body) <= 100000 

@pytest.mark.asyncio
@respx.mock
async def test_check_site_latency_calculation(checker, sample_site):
    """Verify latency is recorded as a positive float/int."""
    respx.get("https://example.com").mock(
        return_value=httpx.Response(200, content=b"ok")
    )

    result = await checker.check_site(sample_site)
    
    assert isinstance(result.latency_ms, (int, float))
    assert result.latency_ms >= 0

@pytest.mark.asyncio
@respx.mock
async def test_check_site_redirect_handling(checker, sample_site):
    """Test if the checker follows or records redirects based on implementation."""
    # If checker follows redirects:
    respx.get("https://example.com").mock(
        side_effect=[
            httpx.Response(301, headers={"Location": "https://www.example.com"}),
            httpx.Response(200, content=b"Redirected content")
        ]
    )

    result = await checker.check_site(sample_site)

    assert result.status_code == 200
    assert "Redirected content" in result.response_body
    assert result.is_up is True

@pytest.mark.asyncio
@respx.mock
async def test_check_site_malformed_url(checker):
    """Test behavior with an invalid URL string."""
    invalid_site = Site(id=2, url="not-a-url", name="Invalid")
    
    result = await checker.check_site(invalid_site)
    
    assert result.is_up is False
    assert result.error_message is not None
    assert result.status_code == 0
