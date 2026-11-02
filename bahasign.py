import os, json, sys, requests
from datetime import datetime

account = os.getenv('USER_ACCOUNT')
password = os.getenv('USER_PASSWORD')
webhook_url = os.getenv('DISCORD_WEBHOOK')

def send_discord_msg(content):
    if not webhook_url:
        print("Discord 發送失敗：未設定 DISCORD_WEBHOOK")
        return
    try:
        response = requests.post(webhook_url, json={
            "username": "簽到",
            "embeds": [{
                "title": "巴哈姆特簽到通知",
                "description": content,
                "color": 0xff5555 if content.startswith("❌") else 0x00ff99,
                "footer": {"text": "Auto Check-in Bot"},
                "timestamp": datetime.utcnow().isoformat()
            }]
        }, timeout=15)
        response.raise_for_status()
    except Exception as e:
        print(f"Discord 發送失敗: {type(e).__name__}: {e}")

def fail(message):
    notification = f"❌ **巴哈簽到失敗：{message}**"
    send_discord_msg(notification)
    print(notification)
    sys.exit(1)

# 1. 登入
try:
    resp = requests.post('https://api.gamer.com.tw/mobile_app/user/v3/do_login.php', headers={
        'User-Agent': 'Bahadroid (https://www.gamer.com.tw/)',
        'Cookie': 'ckAPP_VCODE=7045'
    }, data={
        'uid': account,
        'passwd': password,
        'vcode': '7045'
    }, timeout=20)
    resp.raise_for_status()
except Exception as e:
    fail(f"登入請求異常（{type(e).__name__}: {e}）")

rune = resp.cookies.get('BAHARUNE')
if rune is None:
    fail("登入失敗，請檢查帳密或兩步驟驗證")

# 2. 取得 CSRF Token
try:
    token_resp = requests.get('https://www.gamer.com.tw/ajax/get_csrf_token.php', headers={
        'User-Agent': 'Bahadroid (https://www.gamer.com.tw/)',
        'Cookie': 'BAHARUNE=' + rune
    }, timeout=20)
    token_resp.raise_for_status()
    token = token_resp.text
except Exception as e:
    fail(f"取得 CSRF Token 失敗（{type(e).__name__}: {e}）")

# 3. 執行簽到並解析回應
try:
    signin_resp = requests.post('https://www.gamer.com.tw/ajax/signin.php', headers={
        'User-Agent': 'Bahadroid (https://www.gamer.com.tw/)',
        'Cookie': 'BAHARUNE=' + rune
    }, data={
        'action': 1,
        'token': token
    }, timeout=20)
    signin_resp.raise_for_status()
    try:
        resp_json = signin_resp.json()
    except ValueError as e:
        raise RuntimeError(f"API 回傳非 JSON（HTTP {signin_resp.status_code}）") from e
except Exception as e:
    fail(f"簽到 API 請求異常（{type(e).__name__}: {e}）")

# 4. 判斷簽到結果
if 'error' in resp_json:
    err_msg = resp_json['error'].get('message', '未知錯誤')
    if "今天您已經簽到過了喔" in err_msg or "今日已簽到" in err_msg:
        discord_msg = "✅ **巴哈姆特 今日已簽到**"
        send_notification = False
    else:
        discord_msg = f"❌ **巴哈簽到失敗：{err_msg}**"
        send_notification = True
elif 'data' in resp_json:
    days = resp_json['data'].get('days', 0)
    discord_msg = f"✅ **巴哈姆特 簽到成功 (連續 {days} 天)**"
    send_notification = True
else:
    discord_msg = "❌ **巴哈簽到失敗：API 回傳未知格式**"
    send_notification = True

if send_notification:
    send_discord_msg(discord_msg)
print(discord_msg)

with open('README.md', 'w', encoding='utf-8') as f:
    f.write(f"{datetime.now().strftime('%Y/%m/%d %H:%M:%S')}\n")
    f.write(discord_msg + '\n\n')
    f.write(json.dumps(resp_json, ensure_ascii=False, indent=4))

if discord_msg.startswith("❌"):
    sys.exit(1)
