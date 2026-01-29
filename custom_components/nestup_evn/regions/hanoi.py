import logging
import json
import time
from datetime import date, timedelta
from dateutil import parser
from homeassistant.exceptions import ConfigEntryNotReady
from ..const import (
    CONF_SUCCESS,
    CONF_ERR_INVALID_AUTH,
    CONF_ERR_INVALID_ID,
    ID_ECON_DAILY_NEW,
    ID_ECON_DAILY_OLD,
    ID_ECON_MONTHLY_NEW,
    ID_ECON_TOTAL_NEW,
    ID_ECON_TOTAL_OLD,
    ID_PAYMENT_NEEDED,
    ID_M_PAYMENT_NEEDED,
    STATUS_PAYMENT_NEEDED,
    STATUS_N_PAYMENT_NEEDED,
)
from .base import EVNRegion
from ..utils import parse_evnhanoi_money
from ..types import EVNUpdateResponse, DailyHistoryRecord, MonthlyBillRecord

_LOGGER = logging.getLogger(__name__)

class HanoiRegion(EVNRegion):
    def __init__(self, hass, session, evn_area):
        super().__init__(hass, session, evn_area)
        self._evnhanoi_contract = None

    def is_token_expired(self) -> bool:
        expiry_time = self._evn_area.get("token_expiry", 0)
        return time.time() > expiry_time

    async def login(self, username, password, customer_id) -> str:
        headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
        payload = {"username": username, "password": password, "client_id": "httplocalhost4500", "client_secret": "secret", "grant_type": "password"}
        status, resp_json = await self._request("POST", self._evn_area.get("evn_login_url"), data=payload, headers=headers, api_name="Hanoi Login")
        if status != CONF_SUCCESS: return status

        if ("error" in resp_json) and (resp_json["error"] == "invalid_grant"):
            return CONF_ERR_INVALID_AUTH
        elif "access_token" in resp_json:
            self._evn_area["access_token"] = resp_json["access_token"]
            if "expires_in" in resp_json:
                self._evn_area["token_expiry"] = time.time() + resp_json["expires_in"]
            return CONF_SUCCESS
        return status

    async def request_update(self, username, password, customer_id, from_date, to_date) -> EVNUpdateResponse:
        return await self.request_update_evnhanoi(username, password, customer_id, from_date, to_date)

    async def request_update_evnhanoi(self, username, password, customer_id, from_date, to_date, last_index="001") -> EVNUpdateResponse:
        if self.is_token_expired():
            if await self.login(username, password, customer_id) != CONF_SUCCESS:
                return EVNUpdateResponse(status=CONF_ERR_INVALID_AUTH)

        headers = {"Authorization": f"Bearer {self._evn_area.get('access_token')}", "Content-Type": "application/json"}
        data = {"maDiemDo": f"{customer_id}{last_index}", "maDonVi": f"{customer_id[0:6]}", "maXacThuc": "EVNHN", "ngayDau": from_date, "ngayCuoi": to_date}
        
        status, resp_json = await self._request("POST", self._evn_area.get("evn_data_url"), json_data=data, headers=headers, api_name="Hanoi Data")
        if status != CONF_SUCCESS: return EVNUpdateResponse(status=status)

        if resp_json.get("isError"):
            if resp_json.get("code") == 400 and last_index == "001":
                return await self.request_update_evnhanoi(username, password, customer_id, from_date, to_date, last_index="1")
            return EVNUpdateResponse(status=CONF_ERR_INVALID_ID, data=resp_json)

        sub_data = resp_json["data"]["chiSoNgay"]
        f_date = parser.parse(sub_data[0]["ngay"], dayfirst=True).date()
        t_date = (parser.parse(sub_data[-1 if len(sub_data) > 1 else 0]["ngay"], dayfirst=True) - timedelta(days=1)).date()
        p_date = (parser.parse(sub_data[-2 if len(sub_data) > 2 else 0]["ngay"], dayfirst=True) - timedelta(days=1)).date()

        econ_total_new = round(float(str(sub_data[-1 if len(sub_data) > 1 else 0]["sg"])), 2)
        econ_total_old = round(float(str(sub_data[0]["sg"])), 2)
        econ_daily_new = round(float(sub_data[-1 if len(sub_data) > 1 else 0]["sg"]) - float(sub_data[-2 if len(sub_data) > 2 else 0]["sg"]), 2)
        econ_daily_old = round(float(sub_data[-2 if len(sub_data) > 2 else 0]["sg"]) - float(sub_data[-3 if len(sub_data) > 3 else 0]["sg"]), 2)

        record_response = EVNUpdateResponse(
            status=CONF_SUCCESS,
            econ_total_old=econ_total_old, econ_total_new=econ_total_new,
            econ_daily_old=econ_daily_old, econ_daily_new=econ_daily_new,
            econ_monthly_new=round(econ_total_new - econ_total_old, 2),
            to_date=t_date, from_date=f_date, previous_date=p_date,
            payment_needed=STATUS_N_PAYMENT_NEEDED, m_payment_needed=0
        )

        pay_data = {"maKhachHang": customer_id, "maDonViQuanLy": f"{customer_id[0:6]}"}
        p_status, p_json = await self._request("POST", self._evn_area.get("evn_payment_url"), json_data=pay_data, headers=headers, api_name="Hanoi Payment")

        if p_status == CONF_SUCCESS and not p_json["isError"]:
            if len(p_json["data"]["listThongTinNoKhachHangVm"]):
                record_response.payment_needed = STATUS_PAYMENT_NEEDED
                record_response.m_payment_needed = int(p_json["data"]["listThongTinNoKhachHangVm"][0]["tongTien"].replace(".", ""))
        
        return record_response

    async def fetch_contract(self, customer_id: str):
        if self._evnhanoi_contract: return self._evnhanoi_contract
        headers = {"Accept": "application/json", "Authorization": f"Bearer {self._evn_area.get('access_token')}"}
        status, data = await self._request("GET", "https://evnhanoi.vn/api/TraCuu/GetDanhSachHopDongByUserName", headers=headers, api_name="Hanoi Contract")
        if status == CONF_SUCCESS:
            contracts = data.get("data", {}).get("thongTinHopDongDtos", [])
            for c in contracts:
                if c.get("maKhachHang") == customer_id:
                    self._evnhanoi_contract = c
                    return c
        return None

    async def fetch_daily_range(self, customer_id: str, start: date, end: date):
        contract = await self.fetch_contract(customer_id)
        if not contract: return []
        payload = {"maDonVi": contract["maDonViQuanLy"], "maDiemDo": f"{contract['maKhachHang']}001", "maXacThuc": "EVNHN", "ngayDau": start.strftime("%d/%m/%Y"), "ngayCuoi": end.strftime("%d/%m/%Y")}
        headers = {"Authorization": f"Bearer {self._evn_area.get('access_token')}"}
        status, data = await self._request("POST", "https://evnhanoi.vn/api/TraCuu/LayChiSoDoXaPharse2", json_data=payload, headers=headers, api_name="Hanoi Daily Range")
        return data.get("data", {}).get("chiSoNgayFull", []) if status == CONF_SUCCESS else []

    async def fetch_monthly_bills(self, customer_idValue: str):
        today = date.today()
        contract = await self.fetch_contract(customer_idValue)
        if not contract: return []
        headers = {"Authorization": f"Bearer {self._evn_area.get('access_token')}"}
        params = {"maDvQly": contract["maDonViQuanLy"], "maKh": customer_idValue, "thang": today.month, "nam": today.year}
        status, data = await self._request("GET", "https://evnhanoi.vn/api/TraCuu/GetLichSuThanhToan", params=params, headers=headers, api_name="Hanoi Bills")
        return data.get("data", {}).get("dmLichSuThanhToanList", []) if status == CONF_SUCCESS else []

    async def fetch_daily_history(self, username, password, customer_id: str, start_date: date, end_date: date) -> list[DailyHistoryRecord]:
        if self.is_token_expired():
            if await self.login(username, password, customer_id) != CONF_SUCCESS:
                _LOGGER.error("Hanoi: Login failed during history fetch")
                return []

        # Request 1 day extra at the start to calculate first day difference
        f_dt = start_date - timedelta(days=1)
        
        async def _fetch(m_index):
            headers = {"Authorization": f"Bearer {self._evn_area.get('access_token')}", "Content-Type": "application/json"}
            payload = {
                "maDiemDo": f"{customer_id}{m_index}",
                "maDonVi": f"{customer_id[0:6]}",
                "maXacThuc": "EVNHN",
                "ngayDau": f_dt.strftime("%d/%m/%Y"),
                "ngayCuoi": end_date.strftime("%d/%m/%Y")
            }
            status, resp_json = await self._request("POST", self._evn_area.get("evn_data_url"), json_data=payload, headers=headers, api_name=f"Hanoi History ({m_index})")
            if status == CONF_SUCCESS:
                if isinstance(resp_json, list):
                    return resp_json
                elif isinstance(resp_json, dict):
                    return resp_json.get("data", {}).get("chiSoNgay", [])
            return None

        async def _fetch_phase2():
            contract = await self.fetch_contract(customer_id)
            if not contract: return []
            headers = {"Authorization": f"Bearer {self._evn_area.get('access_token')}", "Content-Type": "application/json"}
            payload = {
                "maDonVi": contract["maDonViQuanLy"], 
                "maDiemDo": f"{contract['maKhachHang']}001", 
                "maXacThuc": "EVNHN", 
                "ngayDau": f_dt.strftime("%d/%m/%Y"), 
                "ngayCuoi": end_date.strftime("%d/%m/%Y")
            }
            status, resp_json = await self._request("POST", "https://evnhanoi.vn/api/TraCuu/LayChiSoDoXaPharse2", json_data=payload, headers=headers, api_name="Hanoi History (P2)")
            if status == CONF_SUCCESS:
                if isinstance(resp_json, list):
                    return resp_json
                elif isinstance(resp_json, dict):
                    return resp_json.get("data", {}).get("chiSoNgayFull", [])
            return None

        # Try Phase 1 first (default)
        data = await _fetch("001")
        if not data:
            data = await _fetch("1")
        
        # Fallback to Phase 2 (newer)
        if not data:
            data = await _fetch_phase2()
        
        if not data or not isinstance(data, list):
            _LOGGER.debug("Hanoi: No daily data returned for %s", customer_id)
            return []

        # Parse indices: entries are usually chronological
        parsed = []
        for entry in data:
            try:
                dt = parser.parse(entry["ngay"], dayfirst=True).date()
                val = float(entry["sg"])
                parsed.append((dt, val))
            except: continue
        
        if len(parsed) < 2: return []
        parsed.sort(key=lambda x: x[0])

        results = []
        for i in range(len(parsed) - 1):
            prev_dt, prev_val = parsed[i]
            curr_dt, curr_val = parsed[i+1]
            # Record difference as consumption for prev_dt
            if start_date <= prev_dt <= end_date:
                results.append(DailyHistoryRecord(date=prev_dt, kwh=round(max(0.0, curr_val - prev_val), 3)))
        
        _LOGGER.debug("Hanoi: Fetched %d history records for %s", len(results), customer_id)
        return results

    async def fetch_monthly_history(self, username, password, customer_id: str, history_start_date: date) -> list[MonthlyBillRecord]:
        if self.is_token_expired():
            if await self.login(username, password, customer_id) != CONF_SUCCESS:
                return []
        raw = await self.fetch_monthly_bills(customer_id)
        if not isinstance(raw, list): return []
        results = []
        for b in raw:
            try:
                year = int(b.get("nam"))
                month = int(b.get("thang"))
                if (year, month) < (history_start_date.year, history_start_date.month): continue
                kwh = float(b.get("dienTthu"))
                cost = parse_evnhanoi_money(b.get("soTien"))
                results.append(MonthlyBillRecord(month=month, year=year, kwh=kwh, cost=cost))
            except Exception: continue
        return results
