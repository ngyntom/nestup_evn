"""Setup and manage the EVN API."""

import json
import logging
import os
from dataclasses import asdict
from datetime import datetime, timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import (
    async_create_clientsession,
    async_get_clientsession,
)

from .utils import calc_ecost
from .const import (
    CONF_SUCCESS,
    CONF_ERR_NOT_SUPPORTED,
    ID_ECON_DAILY_NEW,
    ID_ECON_DAILY_OLD,
    ID_ECON_MONTHLY_NEW,
    ID_ECON_TOTAL_NEW,
    ID_ECON_TOTAL_OLD,
    ID_ECOST_DAILY_NEW,
    ID_ECOST_DAILY_OLD,
    ID_ECOST_MONTHLY_NEW,
    ID_FROM_DATE,
    ID_LATEST_UPDATE,
    ID_M_PAYMENT_NEEDED,
    ID_PAYMENT_NEEDED,
    ID_TO_DATE,
    ID_LOADSHEDDING,
    STATUS_N_PAYMENT_NEEDED,
    STATUS_PAYMENT_NEEDED,
    STATUS_LOADSHEDDING,
)
from .regions import REGION_MAP
from .types import EVN_NAME, VIETNAM_EVN_AREA, Area, EVNUpdateResponse

_LOGGER = logging.getLogger(__name__)

class EVNAPI:
    def __init__(self, hass: HomeAssistant):
        """Construct EVNAPI wrapper."""
        self.hass = hass
        self._session = async_get_clientsession(hass)
        self._regions: dict[str, Any] = {}

    def get_region_instance(self, evn_area_input: Any, customer_id: str):
        if isinstance(evn_area_input, str):
            area_name = evn_area_input
            area_config = next((a for a in VIETNAM_EVN_AREA if a.name == area_name), None)
            if not area_config: return None
            evn_area = asdict(area_config)
        elif hasattr(evn_area_input, "get"):
            evn_area = evn_area_input
            area_name = evn_area.get("name")
        else:
            return None

        area_name = evn_area.get("name")
        # Use customer_id in cache key to prevent multi-account clobbering
        cache_key = f"{area_name}_{customer_id.strip()}"
        if cache_key not in self._regions:
            region_class = REGION_MAP.get(area_name)
            if region_class:
                self._regions[cache_key] = region_class(self.hass, self._session, evn_area)
            else:
                return None
        return self._regions[cache_key]

    async def login(self, evn_area, username, password, customer_id) -> str:
        customer_id = customer_id.strip()
        instance = self.get_region_instance(evn_area, customer_id)
        if not instance: return CONF_ERR_NOT_SUPPORTED
        return await instance.login(username, password, customer_id)

    async def request_update(self, evn_area: Area, username, password, customer_id, monthly_start=None) -> dict[str, Any]:
        customer_id = customer_id.strip()
        instance = self.get_region_instance(evn_area, customer_id)
        if not instance: return {"status": CONF_ERR_NOT_SUPPORTED}

        from_date, to_date = generate_datetime(1 if evn_area.get("name") == EVN_NAME.CPC else monthly_start, offset=1)
        resp = await instance.request_update(username, password, customer_id, from_date, to_date)
        
        if resp.status == CONF_SUCCESS:
            return formatted_result(resp)
        return {"status": resp.status, "data": resp.data}

    async def fetch_daily_range(self, evn_area: Area, customer_id: str, start=None, end=None):
        instance = self.get_region_instance(evn_area, customer_id)
        if not instance: return []
        return await instance.fetch_daily_history(customer_id, start, end)

    async def fetch_monthly_bills(self, evn_area: Area, customer_id: str, **kwargs):
        instance = self.get_region_instance(evn_area, customer_id)
        if not instance: return []
        return await instance.fetch_monthly_history(customer_id, kwargs.get("history_start_date"))

def formatted_result(resp: EVNUpdateResponse) -> dict:
    res = {"status": CONF_SUCCESS, "to_date": resp.to_date, "econ_daily_new": resp.econ_daily_new}
    time_obj = datetime.now()
    res[ID_ECON_TOTAL_NEW] = {"value": resp.econ_total_new, "info": resp.to_date}
    res[ID_ECON_TOTAL_OLD] = {"value": resp.econ_total_old}
    
    if resp.econ_monthly_new is not None:
        res[ID_ECON_MONTHLY_NEW] = {"value": resp.econ_monthly_new}
        res[ID_ECOST_MONTHLY_NEW] = {"value": calc_ecost(resp.econ_monthly_new)}

    for val, con_id, cost_id, dt in [
        (resp.econ_daily_new, ID_ECON_DAILY_NEW, ID_ECOST_DAILY_NEW, resp.to_date),
        (resp.econ_daily_old, ID_ECON_DAILY_OLD, ID_ECOST_DAILY_OLD, resp.previous_date)
    ]:
        if val is not None:
            if dt == time_obj.date(): info = "hôm nay"
            elif dt == (time_obj - timedelta(days=1)).date(): info = "hôm qua"
            elif dt == (time_obj - timedelta(days=2)).date(): info = "hôm kia"
            else: info = f"ngày {dt.strftime('%d/%m')}"
            res[con_id] = {"value": val, "info": info}
            res[cost_id] = {"value": calc_ecost(val), "info": info}

    res[ID_PAYMENT_NEEDED] = {
        "value": resp.payment_needed if resp.payment_needed in (STATUS_N_PAYMENT_NEEDED, STATUS_PAYMENT_NEEDED) else None,
        "info": "mdi:comment-alert-outline" if resp.payment_needed == STATUS_PAYMENT_NEEDED else "mdi:comment-check-outline" if resp.payment_needed == STATUS_N_PAYMENT_NEEDED else "mdi:comment-question-outline"
    }
    res[ID_M_PAYMENT_NEEDED] = {"value": str(resp.m_payment_needed), "info": "mdi:alert-circle-outline" if (resp.m_payment_needed or 0) > 0 else "mdi:checkbox-marked-circle-outline"}
    
    res[ID_LOADSHEDDING] = {"value": format_loadshedding(resp.loadshedding) if resp.loadshedding else "Không hỗ trợ", "info": "mdi:transmission-tower-off"}
    
    res[ID_FROM_DATE] = {"value": resp.from_date.strftime("%d/%m/%Y") if resp.from_date else "N/A"}
    res[ID_TO_DATE] = {"value": resp.to_date.strftime("%d/%m/%Y") if resp.to_date else "N/A"}
    res[ID_LATEST_UPDATE] = {"value": time_obj.astimezone()}
    return res

def format_loadshedding(raw_value: str) -> str:
    try:
        if not raw_value or 'đến' not in raw_value: return STATUS_LOADSHEDDING
        start, end = raw_value.replace('từ ', '').replace(' ngày', '').split('đến')
        s_parts, e_parts = start.strip().split(), end.strip().split()
        if len(s_parts) != 2 or len(e_parts) != 2: return STATUS_LOADSHEDDING
        return f"{s_parts[0][:-3]} {s_parts[1][:-5]} - {e_parts[0][:-3]} {e_parts[1][:-5]}"
    except: return STATUS_LOADSHEDDING

def get_evn_info_sync(customer_id: str, branches_data=None):
    for each_area in VIETNAM_EVN_AREA:
        for pat in each_area.pattern:
            if pat in customer_id:
                branch = "Unknown"
                if branches_data:
                    for eid in branches_data:
                        if eid in customer_id: branch = branches_data[eid]
                return {"status": CONF_SUCCESS, "customer_id": customer_id, "evn_area": asdict(each_area), "evn_name": each_area.name, "evn_location": each_area.location, "evn_branch": branch}
    return {"status": CONF_ERR_NOT_SUPPORTED}

_BRANCHES_CACHE = None

async def get_evn_info(hass: HomeAssistant, customer_id: str):
    """Get EVN information with global caching of branch data."""
    global _BRANCHES_CACHE
    if _BRANCHES_CACHE is None:
        file_path = os.path.join(os.path.dirname(__file__), "evn_branches.json")
        def _read_branches():
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        _BRANCHES_CACHE = await hass.async_add_executor_job(_read_branches)
    return get_evn_info_sync(customer_id, _BRANCHES_CACHE)

def generate_datetime(monthly_start=1, offset=0):
    time_obj = datetime.now()
    cur_day = int(time_obj.strftime("%d"))
    m_start_str = "{:02d}".format(monthly_start - 1 + offset)
    to_date = (time_obj - timedelta(days=1 - offset)).strftime("%d/%m/%Y")
    if cur_day > monthly_start: from_date = f"{m_start_str}/{time_obj.strftime('%m/%Y')}"
    else:
        lm = int(time_obj.strftime("%m")) - 1
        from_date = f"{m_start_str}/{lm:02d}/{time_obj.strftime('%Y')}" if lm else f"{m_start_str}/12/{int(time_obj.strftime('%Y')) - 1}"
    return from_date, to_date
