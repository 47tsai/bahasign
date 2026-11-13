import os
import secrets
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests


LOGIN_URL = "https://api.gamer.com.tw/mobile_app/user/v3/do_login.php"
SIGNIN_URL = "https://api.gamer.com.tw/user/v1/signin.php"
LOGIN_USER_AGENT = "Bahadroid (https://www.gamer.com.tw/)"
SIGNIN_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
TIMEOUT = (10, 25)
NOTIFICATION_STATE = Path(".last-success-notification")


class SignInError(Exception):
    pass


def taipei_today():
    return datetime.now(ZoneInfo("Asia/Taipei")).date().isoformat()


def success_already_notified():
    try:
        return NOTIFICATION_STATE.read_text(encoding="utf-8").strip() == taipei_today()
    except FileNotFoundError:
        return False


def send_discord(message, success):
    webhook = os.getenv("DISCORD_WEBHOOK")
    if not webhook:
        print("⚠️ 未設定 DISCORD_WEBHOOK", file=sys.stderr)
        return False

    try:
        response = requests.post(
            webhook,
            json={
                "username": "簽到",
                "embeds": [{
                    "title": "巴哈姆特簽到通知",
                    "description": message,
                    "color": 0x00FF99 if success else 0xFF5555,
                    "footer": {"text": "Auto Check-in Bot"},
                    "timestamp": datetime.now(ZoneInfo("UTC")).isoformat(),
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


def signin_request(session, csrf_token, action):
    response = session.post(
        SIGNIN_URL,
        headers={
            "User-Agent": SIGNIN_USER_AGENT,
            "X-Bahamut-Csrf-Token": csrf_token,
        },
        data={"action": str(action)},
        timeout=TIMEOUT,
    )
    response.raise_for_status()

    try:
        payload = response.json()
    except ValueError as exc:
        content_type = response.headers.get("Content-Type", "unknown")
        raise SignInError(
            f"簽到 API 回傳非 JSON（HTTP {response.status_code}，"
            f"Content-Type: {content_type}）"
        ) from exc

    if not isinstance(payload, dict):
        raise SignInError("簽到 API 回傳格式不是 JSON 物件")
    return payload


def extract_days(payload):
    data = payload.get("data")
    if not isinstance(data, dict):
        return None

    days = data.get("days")
    if isinstance(days, int) and not isinstance(days, bool) and days >= 0:
        return days
    return None


def sign_in():
    account = os.getenv("USER_ACCOUNT")
    password = os.getenv("USER_PASSWORD")
    if not account or not password:
        raise SignInError("缺少 USER_ACCOUNT 或 USER_PASSWORD")

    session = requests.Session()

    try:
        login_response = session.post(
            LOGIN_URL,
            headers={
                "User-Agent": LOGIN_USER_AGENT,
                "Cookie": "ckAPP_VCODE=7045",
            },
            data={
                "uid": account,
                "passwd": password,
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
        raise SignInError(
            "登入失敗，未取得 BAHARUNE Cookie，請確認帳密或巴哈登入驗證機制"
        )

    session.cookies.set("BAHARUNE", rune)
    csrf_token = secrets.token_hex(8)
    session.cookies.set("ckBahamutCsrfToken", csrf_token)

    try:
        payload = signin_request(session, csrf_token, action=1)
    except requests.RequestException as exc:
        raise SignInError(
            f"簽到 API 請求失敗（{type(exc).__name__}: {exc}）"
        ) from exc

    if "error" in payload:
        error = payload.get("error")
        if isinstance(error, dict):
            error_message = str(error.get("message") or "未提供錯誤訊息")
        else:
            error_message = str(error)

        if any(term in error_message for term in (
            "今天您已經簽到過了喔",
            "今日已簽到",
            "已經簽到",
        )):
            # action=2 查詢當日簽到資料，取得目前連續簽到天數。
            try:
                status_payload = signin_request(session, csrf_token, action=2)
                days = extract_days(status_payload)
            except (requests.RequestException, SignInError) as exc:
                print(f"⚠️ 無法查詢目前簽到天數：{exc}", file=sys.stderr)
                days = None
            return "already_signed", days

        raise SignInError(f"巴哈姆特回報：{error_message}")

    return "success", extract_days(payload)


def main():
    try:
        status, days = sign_in()
    except Exception as exc:
        message = f"❌ **巴哈姆特簽到失敗：{type(exc).__name__}: {exc}**"

        # 成功通知已送達後，當天不再發送任何訊息。
        if success_already_notified():
            print(message)
            print("ℹ️ 今日成功通知已送達，依設定不再發送 Discord 訊息")
        else:
            print(message)
            if not send_discord(message, success=False):
                print("❌ 失敗通知未送達 Discord", file=sys.stderr)
        return 1

    if status == "success":
        label = "簽到成功"
    else:
        label = "今日已簽到"

    if days is None:
        message = f"✅ **巴哈姆特 {label}**"
        print("📅 連續簽到：暫無資料")
    else:
        message = f"✅ **巴哈姆特 {label}｜連續第 {days} 天**"
        print(f"📅 連續簽到：第 {days} 天")

    print(message)

    # 新簽到成功與「今日已簽到」都代表當日已完成。
    # 只有 Discord 確認送達後才寫入狀態，避免通知失敗後永久漏報。
    if success_already_notified():
        print("ℹ️ 今日成功通知已送達，不再發送 Discord 訊息")
        return 0

    if not send_discord(message, success=True):
        print(
            "❌ 簽到已完成，但成功通知未送達；保留重試機會",
            file=sys.stderr,
        )
        return 2

    NOTIFICATION_STATE.write_text(taipei_today() + "\n", encoding="utf-8")
    print("✅ 已記錄今日成功通知，當天後續不再發送 Discord 訊息")
    return 0


if __name__ == "__main__":
    sys.exit(main())
