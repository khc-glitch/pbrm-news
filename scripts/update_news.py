#!/usr/bin/env python3
"""Collect same-day PB/RM news from publisher RSS feeds, with Google News RSS fallback.
No API keys or paid services. Verifies original publisher URL and RSS publication date.
"""
import html
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import feedparser
import requests

OUT = Path(__file__).resolve().parents[1] / "docs"
SEOUL = ZoneInfo("Asia/Seoul")
DOMAINS = {
    "대전일보": "daejonilbo.com",
    "중도일보": "joongdo.co.kr",
    "충청투데이": "cctoday.co.kr",
    "매일경제": "mk.co.kr",
    "한국경제": "hankyung.com",
}
FEEDS = {
    "대전일보": ["https://www.daejonilbo.com/rss/allArticle.xml"],
    "중도일보": [],
    "충청투데이": ["https://www.cctoday.co.kr/rss/allArticle.xml"],
    "매일경제": [
        "https://www.mk.co.kr/rss/30100041/",
        "https://www.mk.co.kr/rss/50200011/",
        "https://www.mk.co.kr/rss/50300009/",
        "https://www.mk.co.kr/rss/50100032/",
    ],
    "한국경제": [
        "https://www.hankyung.com/feed/economy",
        "https://www.hankyung.com/feed/finance",
        "https://www.hankyung.com/feed/realestate",
    ],
}
CATEGORIES = [
    (["퇴직연금", "연금", "irp", "연말정산", "상속", "증여", "세금", "절세"], "PB RM",
     "PB·RM: 개인 절세·연금자산 및 기업 퇴직연금 제도 변화를 확인할 만한 기사입니다."),
    (["대출", "여신", "보증", "운전자금", "차입", "부실", "연체", "신용", "유동성", "자금조달"], "RM",
     "RM: 관련 업종의 차입구조와 유동성 및 금융지원 수요를 점검할 만한 기사입니다."),
    (["금리", "환율", "달러", "채권", "국채", "연준", "통화정책", "기준금리", "예금"], "PB RM",
     "PB·RM: 금리·외환 변화가 고객 자산과 기업 조달비용에 미치는 영향을 살펴보세요."),
    (["부동산", "아파트", "분양", "주택", "pf", "미분양", "재개발", "건설"], "PB RM",
     "PB·RM: 부동산 자산·담보가치와 사업성 위험을 점검할 만한 기사입니다."),
    (["코스피", "코스닥", "주식", "증시", "증권", "etf", "펀드", "배당", "주가"], "PB",
     "PB: 위험자산 비중과 시장 변동성에 관한 고객 상담 참고자료입니다."),
    (["반도체", "제조업", "수출", "투자", "바이오", "공장", "산업", "생산", "소비", "ai", "고용", "기업", "경제", "경기", "무역"], "PB RM",
     "PB·RM: 산업·경기 변화에 따른 투자와 기업금융 수요를 살펴볼 만한 기사입니다."),
]
BLOCK = ["스포츠", "날씨", "축구", "야구", "드라마", "연예", "가수", "사망", "교통사고"]
SESSION = requests.Session()
SESSION.headers.update({"User-Agent":"Mozilla/5.0 (compatible; PBRM-News-RSS/1.0)"})

def clean(s):
    s = re.sub(r"<[^>]+>", " ", s or "")
    return re.sub(r"\s+", " ", html.unescape(s)).strip()

def publisher(url):
    u = urlparse(url)
    if u.scheme not in ("https", "http") or u.username or u.password:
        return None
    host = (u.hostname or "").lower()
    for name, domain in DOMAINS.items():
        if host == domain or host.endswith("." + domain):
            return name
    return None

def published(entry):
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed:
        from datetime import timezone
        return datetime(*parsed[:6], tzinfo=timezone.utc).astimezone(SEOUL).date()
    raw = entry.get("published") or entry.get("updated") or ""
    try:
        return parsedate_to_datetime(raw).astimezone(SEOUL).date()
    except (TypeError, ValueError, OverflowError):
        return None

def score_article(title, description):
    if len(title) < 10 or any(x in title for x in BLOCK):
        return None
    title_l = title.lower()
    combined = (title + " " + description).lower()
    ranked = []
    for i, (terms, role, point) in enumerate(CATEGORIES):
        hits_title = sum(1 for t in terms if t in title_l)
        hits_all = sum(1 for t in terms if t in combined)
        if hits_title or hits_all:
            ranked.append((hits_title * 5 + hits_all * 1.5, -i, role, point))
    if not ranked:
        return None
    strength, _, role, point = max(ranked)
    if strength < 2:
        return None
    if any(x in title for x in ["대전", "충남", "충북", "세종", "충청"]):
        strength += 3
    return strength, role, point

def fetch_feed(url):
    r = SESSION.get(url, timeout=22)
    r.raise_for_status()
    parsed = feedparser.parse(r.content)
    if not parsed.entries:
        print("No entries in feed:", url, file=sys.stderr)
    return parsed.entries[:100]

def google_feed(paper):
    from urllib.parse import urlencode
    domain = DOMAINS[paper]
    q = "site:" + domain + " when:1d"
    url = "https://news.google.com/rss/search?" + urlencode({
        "q":q,"hl":"ko","gl":"KR","ceid":"KR:ko"})
    return fetch_feed(url)

def decode_original(items):
    if not items:
        return {}
    try:
        from googlenewsdecoder import gnewsdecoder
        urls = list(dict.fromkeys(x.get("link", "") for x in items if x.get("link", "").startswith("https://news.google.com/")))
        if not urls:
            return {}
        result = gnewsdecoder(urls, interval=0.3, timeout=12, concurrency=3)
        if isinstance(result, dict):
            result = [result]
        return {url: obj.get("decoded_url") for url,obj in zip(urls,result)
                if isinstance(obj,dict) and obj.get("success") and obj.get("decoded_url")}
    except Exception as exc:
        print("Google RSS URL resolution unavailable:", exc, file=sys.stderr)
        return {}

def main():
    today = datetime.now(SEOUL).date()
    if today.weekday() >= 5:
        print("Weekend. Existing archive retained.")
        return
    entries = []
    successful = 0
    for paper, urls in FEEDS.items():
        got_direct = False
        for url in urls:
            try:
                items = fetch_feed(url)
                if items:
                    successful += 1
                    got_direct = True
                    entries.extend((paper, e, False) for e in items)
            except Exception as exc:
                print("RSS unavailable:",url,str(exc),file=sys.stderr)
        if not got_direct:
            try:
                items = google_feed(paper)
                if items:
                    successful += 1
                    entries.extend((paper,e,True) for e in items)
            except Exception as exc:
                print("Google RSS unavailable:",paper,str(exc),file=sys.stderr)
    if not successful:
        raise RuntimeError("No RSS sources were reachable; existing news retained.")
    google_items = [e for _,e,g in entries if g and published(e)==today]
    decoded = decode_original(google_items)
    seen_urls = set()
    scored = []
    for paper,e,google in entries:
        if published(e) != today:
            continue
        url = decoded.get(e.get("link", ""), "") if google else e.get("link", "")
        if publisher(url) != paper or url in seen_urls:
            continue
        title = clean(e.get("title", ""))
        # Some Google News RSS titles end with " - Publication"
        if google and title.endswith(" - "+paper):
            title = title[:-(len(paper)+3)].strip()
        desc = clean(e.get("summary", ""))
        rec = score_article(title,desc)
        if not rec:
            continue
        seen_urls.add(url)
        score,role,point = rec
        scored.append((score,paper,[paper,title,url,role,point]))
    pools = {paper:[] for paper in DOMAINS}
    for score,paper,item in sorted(scored,key=lambda x:-x[0]):
        pools[paper].append(item)
    chosen=[]
    while len(chosen)<20 and any(pools.values()):
        for paper in DOMAINS:
            if pools[paper] and len(chosen)<20:
                chosen.append(pools[paper].pop(0))
    if not chosen:
        print("No same-day articles verified. Keeping previous archive.")
        return
    data_dir = OUT / "data"
    data_dir.mkdir(parents=True,exist_ok=True)
    (data_dir/(str(today)+".json")).write_text(
        json.dumps(chosen,ensure_ascii=False,indent=2),encoding="utf-8")
    dates = sorted([p.stem for p in data_dir.glob("????-??-??.json")],reverse=True)
    (OUT/"dates.json").write_text(json.dumps(dates,ensure_ascii=False,indent=2),encoding="utf-8")
    print("Generated",today,len(chosen),"articles")

if __name__ == "__main__":
    main()
