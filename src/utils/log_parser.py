def parse_sel_after_time(ssh_client, baseline_time):
    """
    透過 SSH 抓取 SEL 並解析
    baseline_time: MM/DD/YY HH:MM:SS
    """
    # 使用 awk 過濾時間
    cmd = f"ipmitool sel list | awk '$3\" \"$5 >= \"{baseline_time}\"'"
    raw_output = ssh_client.send_command(cmd)
    
    lines = []
    if raw_output:
        for line in raw_output.splitlines():
            if line.strip():
                lines.append(line.strip())
    return lines