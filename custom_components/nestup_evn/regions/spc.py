import logging
import json
from datetime import date, timedelta
from dateutil import parser
from ..const import (
    CONF_SUCCESS,
    ID_ECON_DAILY_NEW,
    ID_ECON_DAILY_OLD,
    ID_ECON_MONTHLY_NEW,
    ID_ECON_TOTAL_NEW,
    ID_ECON_TOTAL_OLD,
    STATUS_PAYMENT_NEEDED,
    STATUS_N_PAYMENT_NEEDED,
    STATUS_LOADSHEDDING,
)
from .base import EVNRegion
from .utils import safe_float
from ..types import EVNUpdateResponse, DailyHistoryRecord, MonthlyBillRecord

_LOGGER = logging.getLogger(__name__)

class SPCRegion(EVNRegion):
    def __init__(self, hass, session, evn_area):
        super().__init__(hass, session, evn_area)

    async def login(self, username, password, customer_id) -> str:
        payload = {"strUsername": username, "strPassword": password, "strDeviceID": customer_id}
        headers = {"Content-Type": "application/json; charset=utf-8"}
        status, resp_json = await self._request("POST", self._evn_area.get("evn_login_url"), json_data=payload, headers=headers, use_ssl=False, api_name="SPC Login")
        if status == CONF_SUCCESS and "maKH" in resp_json and resp_json["maKH"] != "" and "token" in resp_json:
            self._evn_area["access_token"] = resp_json["token"]
            return CONF_SUCCESS
        return "invalid_auth"

    async def request_update(self, username, password, customer_id, from_date, to_date, last_index="001") -> EVNUpdateResponse:
        f_str = (parser.parse(from_date, dayfirst=True) - timedelta(days=1)).strftime("%Y%m%d")
        t_str = parser.parse(to_date, dayfirst=True).strftime("%Y%m%d")
        headers = {
            "Authorization": f"Bearer {self._evn_area.get('access_token')}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Connection": "keep-alive"
        }
        params = {"strMaDiemDo": f"{customer_id}{last_index}", "strFromDate": f_str, "strToDate": t_str}
        
        status, data = await self._request("GET", self._evn_area.get("evn_data_url"), params=params, headers=headers, use_ssl=False, api_name="SPC Data")
        if status != CONF_SUCCESS or not data: return EVNUpdateResponse(status="error")

        f_dt = parser.parse(data[0]["strTime"], dayfirst=True).date() + timedelta(days=1)
        t_dt = parser.parse(data[-1]["strTime"], dayfirst=True).date()
        p_dt = parser.parse(data[-2]["strTime"], dayfirst=True).date() if len(data) > 1 else t_dt

        record_response = EVNUpdateResponse(
            status=CONF_SUCCESS,
            econ_total_old=round(safe_float(data[0].get("dGiaoBT")), 2),
            econ_total_new=round(safe_float(data[-1].get("dGiaoBT")), 2),
            econ_daily_new=round(safe_float(data[-1].get("dSanLuongBT")), 2),
            econ_daily_old=round(safe_float(data[-2].get("dSanLuongBT")), 2) if len(data) > 1 else 0.0,
            econ_monthly_new=round(safe_float(data[-1].get("dGiaoBT")) - safe_float(data[0].get("dGiaoBT")), 2),
            to_date=t_dt, from_date=f_dt, previous_date=p_dt,
            payment_needed=STATUS_N_PAYMENT_NEEDED, m_payment_needed=0, loadshedding="Không hỗ trợ"
        )

        headers = {
            "User-Agent": "evnapp/59 CFNetwork/1240.0.4 Darwin/20.6.0",
            "Authorization": f"Bearer {self._evn_area.get('access_token')}",
            "Accept": "application/json",
            "Accept-Encoding": "identity",
            "Accept-Language": "vi-vn",
            "Connection": "keep-alive",
        }
        p_status, p_data = await self._request("GET", self._evn_area.get("evn_payment_url"), params={"strMaKH": customer_id}, headers=headers, use_ssl=False, api_name="SPC Bill")
        if p_status == CONF_SUCCESS and p_data:
            record_response.payment_needed = STATUS_PAYMENT_NEEDED
            record_response.m_payment_needed = int(p_data[0].get("lTongTien", 0))

        ls_status, ls_data = await self._request("GET", self._evn_area.get("evn_loadshedding_url"), params={"strMaKH": customer_id}, headers=headers, api_name="SPC Shed")
        if ls_status == CONF_SUCCESS and ls_data:
            record_response.loadshedding = ls_data[0].get("strThoiGianMatDien") or STATUS_LOADSHEDDING
        
        return record_response

    async def fetch_daily_range(self, customer_id: str, from_date_str: str, to_date_str: str, last_index: str = "001"):
        headers = {
            "User-Agent": "evnapp/59 CFNetwork/1240.0.4 Darwin/20.6.0",
            "Authorization": f"Bearer {self._evn_area.get('access_token')}",
            "Accept": "application/json",
            "Accept-Encoding": "identity",
            "Accept-Language": "vi-vn",
            "Connection": "keep-alive",
        }
        # Correctly format dates as YYYYMMDD for SPC API as verified by user
        try:
            f_dt = parser.parse(from_date_str, dayfirst=True)
            t_dt = parser.parse(to_date_str, dayfirst=True)
            f_s, t_s = f_dt.strftime("%Y%m%d"), t_dt.strftime("%Y%m%d")
        except:
            f_s, t_s = from_date_str.replace("-", ""), to_date_str.replace("-", "")

        ma_ddo = customer_id if len(customer_id) >= 16 else f"{customer_id}{last_index}"
        params = {"strMaDiemDo": ma_ddo, "strFromDate": f_s, "strToDate": t_s}
        
        # Use the URL from area config as in the legacy implementation
        url = self._evn_area.get("evn_data_url") or "https://api.cskh.evnspc.vn/api/NghiepVu/LayThongTinSanLuongTheoNgay_v2"
        status, data = await self._request("GET", url, params=params, headers=headers, use_ssl=False, api_name="SPC Daily Range")
        return data if status == CONF_SUCCESS else []

    async def fetch_monthly_bills(self, customer_idValue: str, f_m, f_y, t_m, t_y):
        headers = {"Authorization": f"Bearer {self._evn_area.get('access_token')}"}
        status, data = await self._request("GET", "https://api.cskh.evnspc.vn/api/NghiepVu/TraCuuHoaDon", params={"strMaKH": customer_idValue, "iTuThang": f_m, "iTuNam": f_y, "iDenThang": t_m, "iDenNam": t_y}, headers=headers, api_name="SPC Monthly Bills")
        return data if status == CONF_SUCCESS else []

    async def fetch_daily_history(self, username, password, customer_id: str, start_date: date, end_date: date) -> list[DailyHistoryRecord]:
        customer_id = customer_id.strip()
        _LOGGER.debug("SPC: Fetching daily history for %s (%s to %s)", customer_id, start_date, end_date)
        # Always re-login for history backfill to ensure fresh token
        if await self.login(username, password, customer_id) != CONF_SUCCESS:
            _LOGGER.error("SPC: Login failed during history fetch")
            return []
            
        raw = await self.fetch_daily_range(customer_id, start_date.strftime("%d-%m-%Y"), end_date.strftime("%d-%m-%Y"))
        _LOGGER.debug("SPC: Raw API returned %d records for %s", len(raw) if isinstance(raw, list) else 0, customer_id)
        if not isinstance(raw, list):
            return []
        results = []
        for d in raw:
            try:
                # Use parser.parse for robustness against various date formats
                d_date = parser.parse(d.get("strTime"), dayfirst=True).date()
                if start_date <= d_date <= end_date:
                    results.append(DailyHistoryRecord(date=d_date, kwh=float(d.get("dSanLuongBT") or 0)))
            except Exception: continue
        return results

    async def fetch_monthly_history(self, username, password, customer_id: str, history_start_date: date) -> list[MonthlyBillRecord]:
        if not self._evn_area.get("access_token"):
            if await self.login(username, password, customer_id) != CONF_SUCCESS:
                return []
        today = date.today()
        raw = await self.fetch_monthly_bills(customer_id, history_start_date.month, history_start_date.year, today.month - 1 or 12, today.year if today.month > 1 else today.year - 1)
        if not isinstance(raw, list): return []
        results = []
        for b in raw:
            try:
                results.append(MonthlyBillRecord(month=b.get("iThang"), year=b.get("iNam"), kwh=b.get("dSanLuong"), cost=b.get("lTongTien")))
            except Exception: continue
        return results
