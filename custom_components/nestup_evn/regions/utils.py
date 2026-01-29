import logging
import ssl
import json
from ..const import (
    CONF_SUCCESS,
    CONF_EMPTY,
    CONF_ERR_UNKNOWN,
    CONF_ERR_CANNOT_CONNECT,
    CONF_ERR_INVALID_AUTH,
)

_LOGGER = logging.getLogger(__name__)

async def json_processing(resp):
    """Common JSON processing with error handling."""
    if resp.status != 200:
        if resp.status in (400, 401): 
            return CONF_ERR_INVALID_AUTH, {"status": CONF_ERR_INVALID_AUTH, "data": resp.status}
        return CONF_ERR_CANNOT_CONNECT, {"status": CONF_ERR_CANNOT_CONNECT, "data": resp.status}
    
    try:
        resp_json = await resp.json(content_type=None)
        return (CONF_SUCCESS, resp_json) if resp_json else (CONF_EMPTY, {"status": CONF_EMPTY, "data": {}})
    except Exception:
        try:
            text = (await resp.text()).strip()
            return (CONF_SUCCESS, json.loads(text, strict=False)) if text else (CONF_EMPTY, {"status": CONF_EMPTY, "data": {}})
        except Exception as error:
            _LOGGER.error(f"JSON processing error: {error}")
            return CONF_ERR_UNKNOWN, {"status": CONF_ERR_UNKNOWN, "data": str(error)}

def safe_float(v, default=0.0):
    """Safely convert value to float, handling commas and None."""
    try:
        if v is None: return default
        return float(str(v).replace(",", ""))
    except (ValueError, TypeError):
        return default

_SSL_CONTEXT = None

def create_ssl_context():
    """Create a standard SSL context for EVN requests (Cached)."""
    global _SSL_CONTEXT
    if _SSL_CONTEXT is None:
        _SSL_CONTEXT = ssl.create_default_context()
        _SSL_CONTEXT.set_ciphers("ALL:@SECLEVEL=1")
    return _SSL_CONTEXT

async def fetch_with_retries(url, headers=None, params=None, data=None, session=None, method="GET", max_retries=3, allow_empty=False, api_name="API"):
    """Generic fetch with retry mechanism."""
    for attempt in range(max_retries):
        try:
            if method == "GET":
                resp = await session.get(url, headers=headers, params=params, ssl=False)
            else:
                resp = await session.post(url, headers=headers, data=data, ssl=False)
            
            status, body = await json_processing(resp)
            if status == CONF_SUCCESS or (allow_empty and status == CONF_EMPTY):
                return status, body
            
            if status == CONF_EMPTY:
                return CONF_EMPTY, []
                
        except Exception as e:
            if attempt == max_retries - 1:
                _LOGGER.error(f"Failed {api_name} after {max_retries} attempts: {e}")
    return CONF_ERR_UNKNOWN, None
