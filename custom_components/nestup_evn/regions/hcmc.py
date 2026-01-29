import logging
from datetime import datetime, timezone
from dateutil import parser
from homeassistant.exceptions import ConfigEntryNotReady
from ..const import (
    CONF_SUCCESS,
    CONF_ERR_INVALID_AUTH,
    STATUS_PAYMENT_NEEDED,
    STATUS_N_PAYMENT_NEEDED,
)
from .base import EVNRegion
from ..types import EVNUpdateResponse, DailyHistoryRecord, MonthlyBillRecord

_LOGGER = logging.getLogger(__name__)

def strip_date_range(date_str):
    return parser.parse(date_str, dayfirst=True)

class HCMCRegion(EVNRegion):
    def __init__(self, hass, session, evn_area):
        super().__init__(hass, session, evn_area)

    async def login(self, username, password, customer_id=None) -> str:
        payload = {"u": username, "p": password}
        status, resp_json = await self._request("POST", self._evn_area.get("evn_login_url"), data=payload, api_name="HCMC Login")
        if status != CONF_SUCCESS or not isinstance(resp_json, dict) or resp_json.get("state") not in ("success", "login"):
            return CONF_ERR_INVALID_AUTH
        
        cookies = self._session.cookie_jar.filter_cookies("https://cskh.evnhcmc.vn")
        evn_cookie = cookies.get("evn_session")
        if not evn_cookie: return CONF_ERR_INVALID_AUTH
        
        self._evn_area["evn_session"] = evn_cookie.value
        if evn_cookie["expires"]:
            self._evn_area["expires"] = parser.parse(evn_cookie["expires"]).astimezone(timezone.utc)
        return CONF_SUCCESS

    async def request_update(self, username, password, customer_id, from_date, to_date) -> EVNUpdateResponse:
        expires = self._evn_area.get("expires")
        if isinstance(expires, str):
            expires = parser.parse(expires)
        if not expires or datetime.now(tz=timezone.utc) >= expires:
            if await self.login(username, password) != CONF_SUCCESS:
                return EVNUpdateResponse(status=CONF_ERR_INVALID_AUTH)
        
        headers = {"Cookie": f"evn_session={self._evn_area.get('evn_session')}"}
        payload = {"input_makh": customer_id, "input_tungay": from_date, "input_denngay": to_date}
        status, resp_json = await self._request("POST", self._evn_area.get("evn_data_url"), data=payload, headers=headers, api_name="HCMC Data")
        if status != CONF_SUCCESS: return EVNUpdateResponse(status=status)
        
        if resp_json.get("state") != CONF_SUCCESS:
            return EVNUpdateResponse(status=CONF_ERR_INVALID_AUTH if resp_json.get("state") == "error_login" else resp_json.get("state"), data=resp_json)

        data_list = resp_json["data"]["sanluong_tungngay"]
        f_date = strip_date_range(data_list[0]["ngayFull"]).date()
        t_date = strip_date_range(data_list[-2 if len(data_list) > 2 else 0]["ngayFull"]).date()
        p_date = strip_date_range(data_list[-3 if len(data_list) > 3 else 0]["ngayFull"]).date()
        
        econ_total_new = round(float(str(data_list[-1 if len(data_list) > 1 else 0]["tong_p_giao"]).replace(",", "")), 2)
        econ_total_old = round(float(str(data_list[0]["tong_p_giao"]).replace(",", "")), 2)
        
        record_response = EVNUpdateResponse(
            status=CONF_SUCCESS,
            econ_total_old=econ_total_old, econ_total_new=econ_total_new,
            econ_daily_new=round(float(str(data_list[-2 if len(data_list) > 2 else 0]["Tong"]).replace(",", "")), 2),
            econ_daily_old=round(float(str(data_list[-3 if len(data_list) > 3 else 0]["Tong"]).replace(",", "")), 2),
            econ_monthly_new=round(econ_total_new - econ_total_old, 2),
            to_date=t_date, from_date=f_date, previous_date=p_date,
            payment_needed=STATUS_N_PAYMENT_NEEDED, m_payment_needed=0
        )
        
        p_status, p_json = await self._request("POST", self._evn_area.get("evn_payment_url"), data={"input_makh": customer_id}, headers=headers, api_name="HCMC Payment")
        if p_status == CONF_SUCCESS:
            if p_json["data"].get("isNo") == 1:
                record_response.payment_needed = STATUS_PAYMENT_NEEDED
                record_response.m_payment_needed = int(p_json["data"]["info_no"].get("TONG_TIEN").replace(".", ""))
            elif p_json["data"].get("isNo") == 0:
                record_response.payment_needed = STATUS_N_PAYMENT_NEEDED
        
        return record_response

    async def fetch_daily_range(self, customer_id: str, start_date_str: str, end_date_str: str):
        headers = {"Cookie": f"evn_session={self._evn_area.get('evn_session')}"}
        status, resp_json = await self._request("POST", "https://cskh.evnhcmc.vn/Tracuu/ajax_dienNangTieuThuTheoNgay", headers=headers, data={"input_makh": customer_id, "input_tungay": start_date_str, "input_denngay": end_date_str}, api_name="HCMC Daily Range")
        return resp_json.get("data", {}).get("sanluong_tungngay", []) if status == CONF_SUCCESS else []

    async def fetch_monthly_bills(self, customer_idValue: str):
        headers = {"Cookie": f"evn_session={self._evn_area.get('evn_session')}"}
        # Use cskh subdomain which was confirmed working by the user
        status, resp_json = await self._request("POST", "https://cskh.evnhcmc.vn/Tracuu/ajax_dienNangTieuThuTheoKyHoaDon", headers=headers, data={"input_makh": customer_idValue}, api_name="HCMC Bills")
        return resp_json.get("data", {}).get("sanluong_hoadon", []) if status == CONF_SUCCESS else []

    async def fetch_daily_history(self, username, password, customer_id: str, start_date, end_date) -> list[DailyHistoryRecord]:
        expires = self._evn_area.get("expires")
        if isinstance(expires, str): expires = parser.parse(expires)
        if not expires or datetime.now(tz=timezone.utc) >= expires:
            _LOGGER.debug("HCMC: Session expired, logging in for daily history")
            if await self.login(username, password) != CONF_SUCCESS: return []
        raw = await self.fetch_daily_range(customer_id, start_date.strftime("%d/%m/%Y"), end_date.strftime("%d/%m/%Y"))
        if not raw:
            _LOGGER.debug("HCMC: No daily range data returned for %s", customer_id)
            return []
        results = []
        for d in raw:
            ngay_str = d.get("ngayFull")
            kwh = d.get("Tong")
            if not ngay_str or kwh is None: continue
            try:
                results.append(DailyHistoryRecord(date=parser.parse(ngay_str, dayfirst=True).date(), kwh=float(kwh)))
            except: continue
        _LOGGER.debug("HCMC: Fetched %d daily records for %s", len(results), customer_id)
        return results

    async def fetch_monthly_history(self, username, password, customer_id: str, history_start_date) -> list[MonthlyBillRecord]:
        expires = self._evn_area.get("expires")
        if isinstance(expires, str): expires = parser.parse(expires)
        if not expires or datetime.now(tz=timezone.utc) >= expires:
            if await self.login(username, password) != CONF_SUCCESS: return []
        raw = await self.fetch_monthly_bills(customer_id)
        results = []
        for b in raw:
            try:
                year, month = int(b.get("NAM")), int(b.get("THANG"))
                if (year, month) < (history_start_date.year, history_start_date.month): continue
                results.append(MonthlyBillRecord(month=month, year=year, kwh=float(b.get("SAN_LUONG", 0)), cost=int(float(b.get("TONG_TIEN", 0)))))
            except Exception: continue
        return results
