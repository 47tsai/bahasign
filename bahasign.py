import json
import os
import sys
from datetime import datetime, timezone

import requests


LOGIN_URL = "https://api.gamer.com.tw/mobile_app/user/v3/do_login.php"
TOKEN_URL = "https://www.gamer.com.tw/ajax/get_csrf_token.php"
SIGNIN_URL = "https://www.gamer.com.tw/ajax/signin.php"
USER_AGENT = "Bahadroid (https://www.gamer.com.tw/)"
TIMEOUT = (10, 25)


class SignInError(Exception):
    """A known failure in the sign-in flow."""


def send_discord(content):
    webhook = os.getenv("DISCORD_WEBHOOK")
    if not webhook:
        print("⚠️ Discord 通知未送出：未設定 DISCORD_WEBHOOK", file=sys.stderr)
        return False

    try:
        response = requests.post(
            webhook,
            json={
                "username": "簽到",
                "embeds": [{
                    "title": "巴哈姆特簽到通知",
                    "description": content,
                    "color": 0x00FF99 if content.startswith("✅") else 0xFF5555,
                    "footer": {"text": "Auto Check-in Bot"},
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }],
            },
            timeout=TIMEOUT,
        )
        response.raise_for_status()
        return True
    except requests.RequestException as exc:
        print(f"⚠️ Discord 通知發送失敗：{type(exc).__name__}: {exc}", file=sys.stderr)
        return False


def request_headers(cookie=None):
    headers = {"User-Agent": USER_AGENT}
    if cookie:
        headers["Cookie"] = cookie
    return headers


def sign_in():
    account = os.getenv("USER_ACCOUNT")
    password = os.getenv("USER_PASSWORD")
    if not account or not password:
        raise SignInError("缺少帳號或密碼環境變數")

    session = requests.Session()

    # 1. 登入
    try:
        login_response = session.post(
            LOGIN_URL,
            headers={
                "User-Agent": USER_AGENT,
                "Cookie": "ckAPP_VCODE=7045",
            },
            data={"uid": account, "passwd": password, "vcode": "7045"},
            timeout=TIMEOUT,
        )
        login_response.raise_for_status()
    except requests.RequestException as exc:
        raise SignInError(
            f"登入請求失敗（{type(exc).__name__}: {exc}）"
        ) from exc

    rune = login_response.cookies.get("BAHARUNE")
    if not rune:
        raise SignInError("登入失敗，未取得 BAHARUNE Cookie，請檢查帳密或驗證狀態")

    cookie = f"BAHARUNE={rune}"

    # 2. 取得 CSRF Token
    try:
        token_response = session.get(
            TOKEN_URL,
            headers=request_headers(cookie),
            timeout=TIMEOUT,
        )
        token_response.raise_for_status()
        token = token_response.text.strip()
    except requests.RequestException as exc:
        raise SignInError(
            f"取得 CSRF Token 失敗（{type(exc).__name__}: {exc}）"
        ) from exc

    if not token:
        raise SignInError("CSRF Token 回傳空白")

    # 3. 執行簽到。非 JSON 回應不能視為成功。
    try:
        signin_response = session.post(
            SIGNIN_URL,
            headers=request_headers(cookie),
            data={"action": 1, "token": token},
            timeout=TIMEOUT,
        )
        signin_response.raise_for_status()
    except requests.RequestException as exc:
        raise SignInError(
            f"簽到 API 請求失敗（{type(exc).__name__}: {exc}）"
        ) from exc

    try:
        payload = signin_response.json()
    except ValueError as exc:
        content_type = signin_response.headers.get("Content-Type", "unknown")
        raise SignInError(
            f"簽到 API 回傳非 JSON（HTTP {signin_response.status_code}，"
            f"Content-Type: {content_type}）"
        ) from exc

    if not isinstance(payload, dict):
        raise SignInError("簽到 API 回傳格式不是 JSON 物件")

    # 4. 僅接受已知的成功或已簽到回應
    error = payload.get("error")
    if isinstance(error, dict):
        message = str(error.get("message") or "未提供錯誤訊息")
        if "今天您已經簽到過了喔" in message or "今日已簽到" in message:
            return "already_signed", "✅ **巴哈姆特 今日已簽到**"

        raise SignInError(f"巴哈姆特回報：{message}")

    data = payload.get("data")
    if isinstance(data, dict) and "days" in data:
        days = data.get("days")
        return "success", f"✅ **巴哈姆特 簽到成功 (連續 {days} 天)**"

    raise SignInError("簽到 API 回傳未知格式，無法確認是否成功")


def main():
    try:
        status, message = sign_in()
    except SignInError as exc:
        message = f"❌ **巴哈姆特簽到失敗：{exc}**"
        print(message)
        notified = send_discord(message)
        if not notified:
            print("❌ 失敗通知也未能送達 Discord，請查看 GitHub Actions 日誌", file=sys.stderr)
        return 1
    except Exception as exc:
        # 最後一道保護：任何未預期例外都要嘗試通知。
        message = f"❌ **巴哈姆特簽到發生未預期錯誤：{type(exc).__name__}: {exc}**"
        print(message)
        notified = send_discord(message)
        if not notified:
            print("❌ 失敗通知也未能送達 Discord，請查看 GitHub Actions 日誌", file=sys.stderr)
        return 1

    print(message)

    # 保留原本行為：已簽到不重複推播；新簽到成功則推播。
    if status == "success":
        if not send_discord(message):
            print("⚠️ 簽到成功，但 Discord 通知未送達", file=sys.stderr)
            return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
