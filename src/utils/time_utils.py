import datetime
from datetime import timezone, timedelta

def to_utc8(timestr):
    """
    將 UTC 時間字串 (例如 '2023-10-01T12:00:00Z') 轉為台北時間格式字串
    回傳格式: YYYY-MM-DD HH:MM:SS
    """
    if not timestr:
        return "Unknown"
        
    try:
        # 處理 Redfish 常見的格式
        # 有些是 2023-10-01T12:00:00+00:00 或 2023-10-01T12:00:00Z
        timestr = timestr.replace("Z", "+00:00")
        
        # 解析時間 (支援 ISO 格式)
        dt = datetime.datetime.fromisoformat(timestr)
        
        # 定義 UTC+8 時區
        tz_tpe = timezone(timedelta(hours=8))
        
        # 轉換時區
        dt_tpe = dt.astimezone(tz_tpe)
        
        return dt_tpe.strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        # 如果格式解析失敗，回傳原始字串
        return timestr

def standard_to_redfish(ts):
    """將標準時間字串 (空格分隔) 轉為 Redfish 格式 (T 分隔)"""
    return ts.replace(" ", "T") if ts else None