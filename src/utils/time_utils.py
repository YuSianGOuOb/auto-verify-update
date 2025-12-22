import datetime
import re

# 純邏輯，不連 SSH
def to_utc8(timestr):
    """將 UTC 時間字串轉為台北時間格式"""
    # ... (保留原本邏輯) ...
    pass

def standard_to_redfish(ts):
    """格式轉換"""
    return ts.replace(" ", "T") if ts else None