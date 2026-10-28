import os, json, sys, requests
from datetime import datetime

# 從環境變數讀取資料
account = os.getenv('USER_ACCOUNT')
password = os.getenv('USER_PASSWORD')
webhook_url = os.getenv('DISCORD_WEBHOOK')

def send_discord_msg(content):
    if webhook_url:
        try:
            requests.post(webhook_url, json={
                "username": "簽到",
                "embeds": [
                    {
                        "title": "巴哈姆特簽到通知",
                        "description": content,
                        "color": 0x00ff99,
                        "footer": {
                            "text": "Auto Check-in Bot"
                        },
                        "timestamp": datetime.utcnow().isoformat()
                    }
                ]
            })
        except Exception as e:
            print(f"Discord 發送失敗: {e}")

# 1. 執行登入
resp = requests.post('https://api.gamer.com.tw/mobile_app/user/v3/do_login.php', headers = {
    'User-Agent': 'Bahadroid (https://www.gamer.com.tw/)',
    'Cookie': 'ckAPP_VCODE=7045'
}, data = {
    'uid': account,
    'passwd': password,
    'vcode': '7045'
})

rune = resp.cookies.get('BAHARUNE')

# 處理登入失敗
if rune is None:
    msg = "❌ **巴哈簽到失敗：密碼錯誤或觸發兩步驟驗證**"
    send_discord_msg(msg)
    print(msg)
    sys.exit("Login Failed")

# 2. 獲取 CSRF Token
token = requests.get('https://www.gamer.com.tw/ajax/get_csrf_token.php', headers = {
    'User-Agent': 'Bahadroid (https://www.gamer.com.tw/)',
    'Cookie': 'BAHARUNE=' + rune
}).text

# 3. 執行簽到
resp_json = requests.post('https://www.gamer.com.tw/ajax/signin.php', headers = {
    'User-Agent': 'Bahadroid (https://www.gamer.com.tw/)',
    'Cookie': 'BAHARUNE=' + rune
}, data = {
    'action': 1,
    'token': token
}).json()

# 4. 判斷訊息格式
discord_msg = ""
send_notification = True

if 'error' in resp_json:
    err_msg = resp_json['error']['message']
    if "今天您已經簽到過了喔" in err_msg or "今日已簽到" in err_msg:
        discord_msg = "✅ **巴哈姆特 今日已簽到**"
        # 已簽到代表當日成功通知應已在首次簽到時送出，避免重複通知。
        send_notification = False
    else:
        discord_msg = f"❌ **巴哈簽到失敗：{err_msg}**"

elif 'data' in resp_json:
    days = resp_json['data'].get('days', 0)
    discord_msg = f"✅ **巴哈姆特 簽到成功 (連續 {days} 天)**"

else:
    discord_msg = "❌ **巴哈簽到失敗：發生未知錯誤**"

# 5. 發送 Discord 通知
# 新簽到成功時通知；「今日已簽到」不重複通知；失敗仍照常通知。
if send_notification:
    send_discord_msg(discord_msg)
print(discord_msg)

# 6. 更新 README 紀錄
with open('README.md', 'w', encoding='utf-8') as f:
    f.write(f"{datetime.now().strftime('%Y/%m/%d %H:%M:%S')}\n")
    f.write(discord_msg + '\n\n')
    f.write(json.dumps(resp_json, ensure_ascii=False, indent=4))
