#!/usr/bin/env python3
"""Daily index from Naver News Search API. All links point to original 5 publishers."""
import os, re, html, json, time, sys
from datetime import datetime
from pathlib import Path
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse
from zoneinfo import ZoneInfo
import requests

OUT=Path(__file__).resolve().parents[1]/"docs"
SEOUL=ZoneInfo("Asia/Seoul")
PAPERS={"대전일보":"daejonilbo.com","중도일보":"joongdo.co.kr","충청투데이":"cctoday.co.kr","매일경제":"mk.co.kr","한국경제":"hankyung.com"}
QUERIES=["금리","환율","은행","주식","채권","증시","부동산","퇴직연금","연말정산","소득공제","정책금융","중소기업","반도체","제조업","기업투자","공장","수출","PF","대전 기업","충남 경제","세종 금융","대출","물가"]
CATEGORIES=[
 ("연금·세금",["퇴직연금","연금","irp","연말정산","세금","세제","상속","증여"],"PB RM","개인 절세 및 기업 퇴직연금 상담 시 최신 제도·시행시기를 확인하세요."),
 ("기업금융",["대출","여신","보증","운전자금","설비자금","부실","연체","유동성","자금조달"],"RM","거래처의 유동성, 차입구조 및 정책금융 활용 가능성을 점검해 보세요."),
 ("금리·외환",["금리","연준","환율","달러","채권","통화정책","국채"],"PB RM","금리·환율 위험이 금융자산과 기업 자금조달에 미치는 영향을 점검해 보세요."),
 ("부동산",["부동산","주택","아파트","pf","분양","재건축","미분양","재개발"],"PB RM","담보가치, 분양시장 및 부동산 자산 비중을 확인해 보세요."),
 ("주식·투자",["증시","코스피","주식","주가","etf","펀드","배당","상장"],"PB","시장 변동성과 자산배분, 고객 위험감내 수준을 점검해 보세요."),
 ("산업·경기",["반도체","제조업","수출","투자","바이오","공장","에너지","생산","소비","ai","산업","기업","경제","성장","경기"],"PB RM","업종별 경기 차이와 기업의 투자·운전자금 수요를 확인해 보세요."),
]
def clean(v):
 return re.sub(r"\\s+"," ",html.unescape(re.sub(r"<[^>]*>","",v or ""))).strip()
def publisher(url):
 u=urlparse(url)
 if u.scheme!="https" or u.username or u.password:return None
 host=(u.hostname or "").lower()
 for name,domain in PAPERS.items():
  if host==domain or host.endswith("."+domain): return name
 return None
def category(text):
 lo=text.lower()
 ranked=[(sum(4 if k in lo else 0 for k in terms),name,role,point) for name,terms,role,point in CATEGORIES]
 score,name,role,point=max(ranked)
 return (score,name,role,point) if score>0 else None
def main():
 today=datetime.now(SEOUL).date()
 if today.weekday()>4:
  print("Weekend: existing news remains");return
 key=os.getenv("NAVER_CLIENT_ID");secret=os.getenv("NAVER_CLIENT_SECRET")
 if not key or not secret:
  print("Naver credentials not configured. Existing site remains.");return
 ses=requests.Session();ses.headers.update({"X-Naver-Client-Id":key,"X-Naver-Client-Secret":secret})
 found={};successful=0
 for term in QUERIES:
  try:
   r=ses.get("https://openapi.naver.com/v1/search/news.json",params={"query":term,"display":100,"sort":"date"},timeout=20)
   r.raise_for_status();items=r.json().get("items",[]);successful+=1
  except (requests.RequestException,ValueError) as e:
   print("API error",term,str(e),file=sys.stderr);continue
  for it in items:
   url=html.unescape(it.get("originallink") or "")
   pub=publisher(url)
   if not pub:continue
   try:date=parsedate_to_datetime(it["pubDate"]).astimezone(SEOUL).date()
   except (KeyError,TypeError,ValueError,OverflowError):continue
   if date!=today:continue
   title=clean(it.get("title"));desc=clean(it.get("description"))
   if len(title)<10:continue
   classified=category(title+" "+desc)
   if not classified:continue
   score,cat,role,point=classified
   norm=re.sub(r"[^0-9a-z가-힣]","",title.lower())
   if not norm:continue
   score+=(2 if any(t in title for t in ("대전","충남","충북","세종","충청")) else 0)
   found[norm]=(score,[pub,title,url,role,point])
  time.sleep(.12)
 if successful==0:raise RuntimeError("All news API calls failed")
 pools={p:[] for p in PAPERS}
 for score,a in sorted(found.values(),key=lambda x:-x[0]):
  pools[a[0]].append(a)
 selected=[]
 while len(selected)<20 and any(pools.values()):
  for p in PAPERS:
   if pools[p] and len(selected)<20:selected.append(pools[p].pop(0))
 if not selected:
  print("No articles verified for today; retaining previous update.");return
 (OUT/"data").mkdir(parents=True,exist_ok=True)
 (OUT/"data"/(str(today)+".json")).write_text(json.dumps(selected,ensure_ascii=False,indent=2),encoding="utf8")
 dates=sorted([p.stem for p in (OUT/"data").glob("????-??-??.json")],reverse=True)
 (OUT/"dates.json").write_text(json.dumps(dates,ensure_ascii=False,indent=2),encoding="utf8")
 print("Created",str(today),len(selected),"articles")
if __name__=="__main__":main()
