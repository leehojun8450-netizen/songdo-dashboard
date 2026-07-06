# -*- coding: utf-8 -*-
"""
송도 1공구 부동산 대시보드 — 데이터 수집기 (v3)

네이버 부동산 fin.land.naver.com front-api/v1 로 단지별 매물을 가져옵니다.
단지목록.json의 각 단지에 hscpNo(complexNumber)가 들어있어야 합니다.
hscpNo 찾는 법: _find_complex_ids.bat 실행 후 Claude에게 알려주세요.

표준 라이브러리만 사용 — pip install 불필요.
"""

import json
import sys
import time
import os
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime
from http.cookiejar import CookieJar

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TRACK_FILE = os.path.join(BASE_DIR, "단지목록.json")
DATA_FILE = os.path.join(BASE_DIR, "data.json")
JS_FILE = os.path.join(BASE_DIR, "data.js")

BASE_URL = "https://fin.land.naver.com"
API_BASE = f"{BASE_URL}/front-api/v1"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)

DIRECTION_MAP = {
    "N": "북", "S": "남", "E": "동", "W": "서",
    "NE": "북동", "NW": "북서", "SE": "남동", "SW": "남서",
    "SS": "남남서", "NN": "북북동", "EE": "동동남", "WW": "서서북",
    "EN": "북동", "ES": "동남", "WN": "북서", "WS": "서남",
}

TRADE_NAME = {"B1": "전세", "B2": "월세", "A1": "매매", "B3": "단기임대"}

_jar = CookieJar()
_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(_jar))
urllib.request.install_opener(_opener)


def warm_session():
    try:
        req = urllib.request.Request(
            f"{BASE_URL}/",
            headers={"User-Agent": UA, "Accept-Language": "ko-KR,ko;q=0.9"},
        )
        urllib.request.urlopen(req, timeout=10).read()
    except Exception as e:
        print(f"[warn] 세션 워밍 실패 (계속 진행): {e}", file=sys.stderr)


def _get(url, retries=3, timeout=15):
    headers = {
        "User-Agent": UA,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
        "Referer": f"{BASE_URL}/",
    }
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8", errors="ignore"))
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (429, 503):
                wait = 10 + i * 10
                print(f"  [rate-limit] {e.code} → {wait}초 대기", file=sys.stderr)
                time.sleep(wait)
                continue
            raise
        except Exception as e:
            last = e
            time.sleep(3 + i * 3)
    if last:
        raise last


def _post(url, body, referer=None, retries=3, timeout=15):
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    headers = {
        "User-Agent": UA,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
        "Content-Type": "application/json",
        "Referer": referer or f"{BASE_URL}/",
        "Origin": BASE_URL,
    }
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, data=data, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8", errors="ignore"))
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (429, 503):
                wait = 10 + i * 10
                print(f"  [rate-limit] {e.code} → {wait}초 대기", file=sys.stderr)
                time.sleep(wait)
                continue
            raise
        except Exception as e:
            last = e
            time.sleep(3 + i * 3)
    if last:
        raise last


def fetch_complex_name(hscp_no):
    url = f"{API_BASE}/complex?complexNumber={hscp_no}"
    try:
        d = _get(url)
        if d and d.get("isSuccess") and d.get("result"):
            return d["result"].get("name", "")
    except Exception:
        pass
    return ""


def fetch_articles_page(hscp_no, trade_type, page=1, size=30):
    url = f"{API_BASE}/complex/article/list"
    referer = f"{BASE_URL}/complexes/{hscp_no}"
    body = {
        "complexNumber": str(hscp_no),
        "tradeTypes": [trade_type],
        "page": page,
        "size": size,
    }
    return _post(url, body, referer=referer)


def fetch_all_articles(hscp_no, trade_type, max_pages=30):
    out = []
    page = 1
    while True:
        try:
            resp = fetch_articles_page(hscp_no, trade_type, page=page, size=30)
        except Exception as e:
            print(f"    [warn] page {page} 실패: {e}", file=sys.stderr)
            break
        if not resp or not resp.get("isSuccess"):
            break
        result = resp.get("result") or {}
        items = result.get("list") or []
        if not items:
            break
        out.extend(items)
        if not result.get("hasNextPage", False):
            break
        page += 1
        if page > max_pages:
            break
        time.sleep(0.7)
    return out


def won_to_man(won):
    if not won:
        return 0
    return int(won) // 10000


def format_man(v_man):
    if not v_man:
        return "0"
    eok = v_man // 10000
    man = v_man % 10000
    if eok and man:
        return f"{eok}억 {man:,}"
    if eok:
        return f"{eok}억"
    return f"{man:,}"


def normalize_article(raw_item, complex_name):
    info = raw_item.get("representativeArticleInfo") or raw_item
    space = info.get("spaceInfo") or {}
    price = info.get("priceInfo") or {}
    detail = info.get("articleDetail") or {}
    broker = info.get("brokerInfo") or {}
    verify = info.get("verificationInfo") or {}
    addr = info.get("address") or {}

    spc1 = float(space.get("supplySpace") or 0)
    spc2 = float(space.get("exclusiveSpace") or 0)
    pyeong_supply = round(spc1 / 3.3058, 1) if spc1 else 0
    pyeong_excl = round(spc2 / 3.3058, 1) if spc2 else 0

    # fin.land API는 원(won) 단위 반환 → 만원으로 변환
    trad_cd = info.get("tradeType") or ""
    trad_nm = TRADE_NAME.get(trad_cd, trad_cd)
    if trad_cd == "A1":  # 매매: dealPrice 우선
        prc_man = won_to_man(price.get("dealPrice") or price.get("warrantyPrice") or 0)
    else:
        prc_man = won_to_man(price.get("warrantyPrice") or 0)
    rent_man = won_to_man(price.get("rentPrice") or 0)

    jeonse_equiv = None
    if trad_cd == "B2" and rent_man:
        jeonse_equiv = prc_man + rent_man * 200

    no = info.get("articleNumber") or ""
    direction_code = detail.get("direction") or ""
    direction = DIRECTION_MAP.get(direction_code, direction_code)

    return {
        "단지": info.get("complexName") or complex_name,
        "거래": trad_nm,
        "거래코드": trad_cd,
        "보증금_만원": prc_man,
        "월세_만원": rent_man,
        "전세환산_만원": jeonse_equiv,
        "보증금_표시": format_man(prc_man),
        "월세_표시": format_man(rent_man) if rent_man else "",
        "공급m2": spc1,
        "전용m2": spc2,
        "공급평": pyeong_supply,
        "전용평": pyeong_excl,
        "층": detail.get("floorInfo") or "",
        "향": direction,
        "동": info.get("dongName") or "",
        "확인일": verify.get("articleConfirmDate") or "",
        "설명": info.get("articleName") or "",
        "중개": broker.get("brokerageName") or "",
        "매물명": info.get("articleName") or "",
        "기사번호": no,
        "링크": f"{BASE_URL}/articles/{no}" if no else "",
    }


def load_tracking():
    if not os.path.exists(TRACK_FILE):
        print(f"❌ {TRACK_FILE} 없음", file=sys.stderr)
        sys.exit(1)
    with open(TRACK_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_tracking(t):
    with open(TRACK_FILE, "w", encoding="utf-8") as f:
        json.dump(t, f, ensure_ascii=False, indent=2)


def main():
    tracking = load_tracking()
    min_p = float(tracking.get("필터", {}).get("최소평형", 33))
    min_m2 = min_p * 3.3058

    print(f"=== 송도 1공구 부동산 수집 (v3 — fin.land API) ===")
    print(f"필터: 공급 {min_p}평({min_m2:.1f}m²) 이상")
    print(f"시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

    warm_session()
    time.sleep(1.0)

    all_articles = []
    complex_summary = []
    no_hscp_warnings = []
    save_tracking_needed = False

    for entry in tracking["단지"]:
        keyword = (entry.get("keyword") or "").strip()
        hscp_no = (entry.get("hscpNo") or "").strip()
        if not keyword:
            continue

        if not hscp_no:
            no_hscp_warnings.append(keyword)
            print(f"⚠️  {keyword} → hscpNo 미설정 (건너뜀)")
            continue

        # 단지명 자동 보완
        display_name = entry.get("_매칭이름")
        if not display_name:
            print(f"  단지명 조회: {keyword} (hscpNo={hscp_no}) ... ", end="", flush=True)
            try:
                name = fetch_complex_name(hscp_no)
                if name:
                    entry["_매칭이름"] = name
                    display_name = name
                    save_tracking_needed = True
                    print(f"→ {name}")
                else:
                    print("→ 조회 실패, keyword 사용")
            except Exception as e:
                print(f"→ 오류: {e}")
            time.sleep(0.5)
        if not display_name:
            display_name = keyword

        # 단지별 최소평형 개별 설정 가능 (없으면 전역 기본값 사용)
        entry_min_p = entry.get("최소평형")
        eff_min_p = float(entry_min_p) if entry_min_p is not None else min_p
        eff_min_m2 = eff_min_p * 3.3058

        for code, label in [("B1", "전세"), ("B2", "월세"), ("A1", "매매")]:
            print(f"  [{label}] {display_name} (hscpNo={hscp_no}) ... ", end="", flush=True)
            try:
                max_pg = 3 if code == "A1" else 30  # 매매는 최근 90건만
                items = fetch_all_articles(hscp_no, code, max_pages=max_pg)
            except Exception as e:
                print(f"실패: {e}")
                continue

            normed = []
            for it in items:
                try:
                    normed.append(normalize_article(it, display_name))
                except Exception as e:
                    print(f"\n    [warn] normalize 실패: {e}", file=sys.stderr)

            if eff_min_p > 0:
                filtered = [
                    a for a in normed
                    if (a["공급m2"] >= eff_min_m2 or a["공급평"] >= eff_min_p)
                ]
                label_filter = f"{eff_min_p:.0f}평+"
            else:
                filtered = normed
                label_filter = "전 평형"
            all_articles.extend(filtered)
            print(f"전체 {len(normed)} → {label_filter} {len(filtered)}건")
            time.sleep(0.8)

        cnt_j = sum(1 for a in all_articles if a["단지"] == display_name and a["거래코드"] == "B1")
        cnt_w = sum(1 for a in all_articles if a["단지"] == display_name and a["거래코드"] == "B2")
        complex_summary.append(
            {"단지": display_name, "hscpNo": hscp_no, "전세건수": cnt_j, "월세건수": cnt_w}
        )

    if save_tracking_needed:
        save_tracking(tracking)

    out = {
        "갱신시각": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "필터": {"최소평형": min_p, "최소m2": round(min_m2, 1)},
        "단지요약": complex_summary,
        "매물": all_articles,
        "통계": {
            "총매물": len(all_articles),
            "전세건수": sum(1 for a in all_articles if a["거래코드"] == "B1"),
            "월세건수": sum(1 for a in all_articles if a["거래코드"] == "B2"),
            "매매건수": sum(1 for a in all_articles if a["거래코드"] == "A1"),
        },
        "미설정단지": no_hscp_warnings,
    }

    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    with open(JS_FILE, "w", encoding="utf-8") as f:
        f.write("window.__DATA__ = ")
        json.dump(out, f, ensure_ascii=False)
        f.write(";")

    print(f"\n✅ 저장 완료: {DATA_FILE}")
    print(
        f"   총 {out['통계']['총매물']}건 (전세 {out['통계']['전세건수']} / 월세 {out['통계']['월세건수']} / 매매 {out['통계']['매매건수']})"
    )
    if no_hscp_warnings:
        print(f"\n⚠️  hscpNo 미설정 단지 {len(no_hscp_warnings)}개: {', '.join(no_hscp_warnings)}")
        print(f"   → _find_complex_ids.bat 또는 fin.land.naver.com에서 확인 필요")


if __name__ == "__main__":
    main()
