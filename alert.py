# -*- coding: utf-8 -*-
"""
송도 1공구 부동산 알림 체크 — fetch.py 실행 후 자동 호출됩니다.

조건에 맞는 매물이 있으면:
  1. Windows 토스트 알림 (Windows 로컬 실행 시만)
  2. 카카오톡 나에게 보내기
     - 로컬: 카카오_토큰.json 파일 읽기
     - GitHub Actions: KAKAO_TOKEN_JSON 환경변수 읽기
"""

import json
import os
import sys
import platform
import subprocess
from datetime import datetime

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
DATA_FILE   = os.path.join(BASE_DIR, "data.json")
RESULT_FILE = os.path.join(BASE_DIR, "알림결과.json")
TOKEN_FILE  = os.path.join(BASE_DIR, "카카오_토큰.json")

IS_WINDOWS = platform.system() == "Windows"

# ──────────────────────────────────────────────
# 알림 조건 설정
# ──────────────────────────────────────────────
MIN_PYEONG         = 33     # 공급 33평 이상
JEONSE_MAX         = 50000  # 전세 보증금 5억 이하 (단위: 만원)
WOLSE_DEPOSIT_MAX  = 150    # 월세 보증금 150만원 이하 (단위: 만원)
# ──────────────────────────────────────────────


def _fmt_item_jeonse(a):
    return f"• {a['단지']} {a['공급평']}평 {a['보증금']} ({a['층']})"

def _fmt_item_wolse(a):
    rent = f"/{a['월세']}" if a.get("월세") else ""
    return f"• {a['단지']} {a['공급평']}평 보{a['보증금']}{rent} ({a['층']})"


def build_kakao_message(result, today_str):
    lines = [f"🏠 송도매물알림 {today_str}"]
    lines.append(f"조건: 33평↑ 전세{JEONSE_MAX//10000}억↓/월세보증{WOLSE_DEPOSIT_MAX}만↓")
    lines.append("")

    j_list = result.get("전세_목록", [])
    w_list = result.get("월세_목록", [])

    if j_list:
        lines.append(f"전세 {result['전세_매칭']}건:")
        for a in j_list[:3]:
            lines.append(_fmt_item_jeonse(a))
    if w_list:
        lines.append(f"월세 {result['월세_매칭']}건:")
        for a in w_list[:3]:
            lines.append(_fmt_item_wolse(a))

    return "\n".join(lines)


def send_windows_toast(title, body):
    if not IS_WINDOWS:
        return
    body_esc = body.replace("'", "\\'").replace('"', '\\"').replace("\n", "\\n")
    script = f"""
Add-Type -AssemblyName System.Windows.Forms
$balloon = New-Object System.Windows.Forms.NotifyIcon
$balloon.Icon = [System.Drawing.SystemIcons]::Information
$balloon.BalloonTipTitle = '{title}'
$balloon.BalloonTipText = '{body_esc}'
$balloon.Visible = $true
$balloon.ShowBalloonTip(10000)
Start-Sleep -Seconds 3
$balloon.Dispose()
"""
    try:
        subprocess.run(
            ["powershell", "-WindowStyle", "Hidden", "-Command", script],
            capture_output=True, timeout=15
        )
        print("  ✅ Windows 알림 발송")
    except Exception as e:
        print(f"  ⚠️  Windows 알림 실패: {e}")


def _load_token():
    """로컬 파일 또는 GitHub Actions 환경변수에서 토큰 로드."""
    # GitHub Actions: KAKAO_TOKEN_JSON 환경변수 우선
    env_json = os.environ.get("KAKAO_TOKEN_JSON", "").strip()
    if env_json:
        try:
            return json.loads(env_json)
        except Exception as e:
            print(f"  ⚠️  KAKAO_TOKEN_JSON 파싱 실패: {e}")
            return None

    # 로컬: 파일 읽기
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "r", encoding="utf-8") as f:
            return json.load(f)

    return None


def send_kakao(message):
    import urllib.request, urllib.parse

    tok = _load_token()
    if not tok:
        print("  ℹ️  카카오 토큰 없음 — KakaoTalk 발송 건너뜀")
        return False

    rest_api_key  = tok.get("rest_api_key", "")
    refresh_token = tok.get("refresh_token", "")
    if not rest_api_key or not refresh_token:
        print("  ⚠️  카카오_토큰에 rest_api_key 또는 refresh_token 없음")
        return False

    # 1) access_token 갱신
    refresh_data = urllib.parse.urlencode({
        "grant_type":    "refresh_token",
        "client_id":     rest_api_key,
        "refresh_token": refresh_token,
    }).encode()
    req = urllib.request.Request(
        "https://kauth.kakao.com/oauth/token",
        data=refresh_data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            token_res = json.loads(r.read().decode())
    except Exception as e:
        print(f"  ⚠️  카카오 토큰 갱신 실패: {e}")
        return False

    access_token = token_res.get("access_token", "")
    if not access_token:
        print(f"  ⚠️  access_token 없음: {token_res}")
        return False

    # refresh_token 갱신 시 로컬 파일에만 저장 (Actions에서는 무시)
    if token_res.get("refresh_token") and IS_WINDOWS and os.path.exists(TOKEN_FILE):
        tok["refresh_token"] = token_res["refresh_token"]
        with open(TOKEN_FILE, "w", encoding="utf-8") as f:
            json.dump(tok, f, ensure_ascii=False, indent=2)

    # 2) 나에게 보내기
    template = json.dumps({
        "object_type": "text",
        "text":        message,
        "link": {"web_url": "", "mobile_web_url": ""},
    }, ensure_ascii=False)
    send_data = urllib.parse.urlencode({"template_object": template}).encode()
    req2 = urllib.request.Request(
        "https://kapi.kakao.com/v2/api/talk/memo/default/send",
        data=send_data,
        headers={
            "Content-Type":  "application/x-www-form-urlencoded",
            "Authorization": f"Bearer {access_token}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req2, timeout=10) as r:
            res = json.loads(r.read().decode())
        if res.get("result_code") == 0:
            print("  ✅ 카카오톡 발송 성공")
            return True
        print(f"  ⚠️  카카오 응답: {res}")
        return False
    except Exception as e:
        print(f"  ⚠️  카카오톡 발송 실패: {e}")
        return False


def check():
    if not os.path.exists(DATA_FILE):
        print("❌ data.json 없음 — fetch.py를 먼저 실행하세요", file=sys.stderr)
        return

    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    articles = data.get("매물", [])
    갱신시각  = data.get("갱신시각", "")

    jeonse_hits = [
        a for a in articles
        if a.get("거래코드") == "B1"
        and float(a.get("공급평") or 0) >= MIN_PYEONG
        and 0 < a.get("보증금_만원", 0) <= JEONSE_MAX
    ]
    wolse_hits = [
        a for a in articles
        if a.get("거래코드") == "B2"
        and float(a.get("공급평") or 0) >= MIN_PYEONG
        and 0 < a.get("보증금_만원", 0) <= WOLSE_DEPOSIT_MAX
    ]

    seen = set()
    def dedup(lst):
        out = []
        for a in lst:
            k = a.get("기사번호") or a.get("링크") or str(a)
            if k not in seen:
                seen.add(k)
                out.append(a)
        return out
    jeonse_hits = dedup(jeonse_hits)
    wolse_hits  = dedup(wolse_hits)

    result = {
        "체크시각": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "갱신시각": 갱신시각,
        "조건": {
            "최소평형": MIN_PYEONG,
            "전세최대보증금_만원": JEONSE_MAX,
            "월세최대보증금_만원": WOLSE_DEPOSIT_MAX,
        },
        "전세_매칭": len(jeonse_hits),
        "월세_매칭": len(wolse_hits),
        "전세_목록": [
            {"단지": a["단지"], "공급평": a["공급평"], "보증금": a["보증금_표시"],
             "층": a.get("층",""), "향": a.get("향",""), "링크": a.get("링크","")}
            for a in jeonse_hits[:10]
        ],
        "월세_목록": [
            {"단지": a["단지"], "공급평": a["공급평"], "보증금": a["보증금_표시"],
             "월세": a.get("월세_표시",""), "층": a.get("층",""), "링크": a.get("링크","")}
            for a in wolse_hits[:10]
        ],
    }

    with open(RESULT_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    total = len(jeonse_hits) + len(wolse_hits)
    print(f"✅ 알림체크: 전세 {len(jeonse_hits)}건 / 월세 {len(wolse_hits)}건 (합계 {total}건)")

    if total == 0:
        print("   조건 매칭 없음 — 알림 발송 안 함")
        return

    today = datetime.now().strftime("%m/%d")
    msg = build_kakao_message(result, today)
    print("\n[ 발송 메시지 미리보기 ]")
    print(msg)
    print()

    send_windows_toast("🏠 송도 매물 알림", msg)
    send_kakao(msg)


if __name__ == "__main__":
    check()
