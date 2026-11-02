import json
import os
import secrets
import sys
from datetime import datetime, timezone

import pyotp
import requests


LOGIN_URL = "https://api.gamer.com.tw/mobile_app/user/v3/do_login.php"
SIGNIN_URL = "https://api.gamer.com.tw/user/v1/signin.php"
LOGIN_USER_AGENT = "Bahadroid (https://www.gamer.com.tw/)"
SIGNIN_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
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
        print(
            f"⚠️ Discord 通知發送失敗：{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return False


def sign_in():
    account = os.getenv("USER_ACCOUNT")
    password = os.getenv("USER_PASSWORD")
    totp_secret = os.getenv("TOTP_SECRET")

    if not account or not password:
        raise SignInError("缺少帳號或密碼環境變數")
    if not totp_secret:
        raise SignInError("缺少 TOTP_SECRET，請確認 GitHub Repository Secret")

    # 1. 依照原作者流程，使用帳號、密碼及 TOTP 登入。
    try:
        login_response = requests.post(
            LOGIN_URL,
            headers={
                "User-Agent": LOGIN_USER_AGENT,
                "Cookie": "ckAPP_VCODE=7045",
            },
            data={
                "uid": account,
                "passwd": password,
                "twoStepAuth": pyotp.TOTP(totp_secret).now(),
                "vcode": "7045",
            },
            timeout=TIMEOUT,
        )
        login_response.raise_for_status()
    except requests.RequestException as exc:
        raise SignInError(
            f"登入請求失敗（{type(exc).__name__}: {exc}）"
        ) from exc

    rune = login_response.cookies.get("BAHARUNE")
    if not rune:
        # 不輸出登入回應內容，避免意外洩漏帳號或驗證資訊。
        raise SignInError("登入失敗，未取得 BAHARUNE Cookie，請檢查帳密及 TOTP_SECRET")

    # 2. 原作者的簽到 API 不需要另外取得 CSRF Token。
    #    隨機 Token 同時放入 Header 與 Cookie。
    csrf_token = secrets.token_hex(8)
    try:
        signin_response = requests.post(
            SIGNIN_URL,
            headers={
                "User-Agent": SIGNIN_USER_AGENT,
                "X-Bahamut-Csrf-Token": csrf_token,
                "Cookie": f"BAHARUNE={rune}; ckBahamutCsrfToken={csrf_token}",
            },
            data={"action": 1},
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

    if "error" in payload:
        error = payload.get("error")
        if isinstance(error, dict):
            message = str(error.get("message") or "未提供錯誤訊息")
        else:
            message = str(error)

        if "今天您已經簽到過了喔" in message or "今日已簽到" in message:
            return "already_signed", "✅ **巴哈姆特 今日已簽到**"

        raise SignInError(f"巴哈姆特回報：{message}")

    return "success", "✅ **巴哈姆特 簽到成功**"


def main():
    try:
        status, message = sign_in()
    except SignInError as exc:
        message = f"❌ **巴哈姆特簽到失敗：{exc}**"
        print(message)
        if not send_discord(message):
            print(
                "❌ 失敗通知未能送達 Discord，請查看 GitHub Actions 日誌",
                file=sys.stderr,
            )
        return 1
    except Exception as exc:
        message = (
            "❌ **巴哈姆特簽到發生未預期錯誤："
            f"{type(exc).__name__}: {exc}**"
        )
        print(message)
        if not send_discord(message):
            print(
                "❌ 失敗通知未能送達 Discord，請查看 GitHub Actions 日誌",
                file=sys.stderr,
            )
        return 1

    print(message)

    # 已簽到不重複推播；新簽到成功才發送成功通知。
    if status == "success" and not send_discord(message):
        print("⚠️ 簽到成功，但 Discord 通知未送達", file=sys.stderr)
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
