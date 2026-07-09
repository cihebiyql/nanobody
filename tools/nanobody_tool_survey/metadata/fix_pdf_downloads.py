#!/usr/bin/env python3
from __future__ import annotations
import json, re, sys, hashlib
from pathlib import Path
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup
ROOT=Path(__file__).resolve().parents[1]
PAPERS=ROOT/'papers'; META=ROOT/'metadata'
sys.path.insert(0,str(META))
from asset_manifest import TOOLS
UA='Mozilla/5.0 nanobody-tool-survey/1.1'

def slug(s):
    return re.sub(r'[^A-Za-z0-9._-]+','_',s).strip('_').lower()[:100]

def is_pdf(p):
    try: return p.read_bytes()[:5]==b'%PDF-'
    except: return False

def download(tool,url,tag='resolved'):
    folder=PAPERS/tool['category']/tool['id']; folder.mkdir(parents=True,exist_ok=True)
    name=f"{tool['id']}__{tag}__{slug(url.split('?')[0].split('/')[-1] or 'paper')}.pdf"
    out=folder/name
    if out.exists() and is_pdf(out): return {'url':url,'status':'exists','path':str(out.relative_to(ROOT)),'bytes':out.stat().st_size}
    tmp=out.with_suffix('.tmp')
    try:
        r=requests.get(url,headers={'User-Agent':UA,'Accept':'application/pdf,*/*','Referer':'https://pmc.ncbi.nlm.nih.gov/'},timeout=45,stream=True,allow_redirects=True)
        if r.status_code>=400: return {'url':url,'status':f'http_{r.status_code}'}
        with open(tmp,'wb') as f:
            for ch in r.iter_content(65536):
                if ch: f.write(ch)
        if not is_pdf(tmp) or tmp.stat().st_size<5000:
            tmp.unlink(missing_ok=True); return {'url':url,'status':'not_pdf','content_type':r.headers.get('content-type','')}
        tmp.replace(out)
        return {'url':url,'status':'downloaded','path':str(out.relative_to(ROOT)),'bytes':out.stat().st_size,'sha256_16':hashlib.sha256(out.read_bytes()).hexdigest()[:16]}
    except Exception as e:
        tmp.unlink(missing_ok=True); return {'url':url,'status':'error','error':repr(e)}

def find_pdf(url):
    try:
        r=requests.get(url,headers={'User-Agent':UA},timeout=30)
        if r.status_code>=400: return []
        soup=BeautifulSoup(r.text,'html.parser')
        links=[]
        for a in soup.find_all('a',href=True):
            href=a['href']
            text=' '.join(a.get_text(' ',strip=True).lower().split())
            if '.pdf' in href.lower() or 'pdf'==text or 'pdf' in text[:40]:
                links.append(urljoin(url,href))
        # prioritize actual article pdf URLs
        seen=[]
        for l in links:
            if l not in seen and ('pdf' in l.lower()): seen.append(l)
        return seen[:5]
    except Exception:
        return []

def main():
    results=json.load(open(META/'asset_download_results.json',encoding='utf-8'))
    byid={t['id']:t for t in TOOLS}
    added=[]
    for item in results:
        tool=byid[item['id']]
        # if any pdf downloaded already, still skip only failed PMC/HTML direct candidates
        failed=[p for p in item['paper_downloads'] if p['status'] in ('not_pdf','http_403','http_406','error')]
        for p in failed:
            url=p['url']
            if 'pmc.ncbi.nlm.nih.gov/articles/' not in url and 'elifesciences.org/articles/' not in url and 'mdpi.com/' not in url:
                continue
            base=url
            if '/pdf' in base:
                base=base.split('/pdf')[0]+'/'
            cands=find_pdf(base)
            for j,c in enumerate(cands):
                res=download(tool,c,tag=f'resolved{j+1}')
                added.append({'id':item['id'],'name':item['name'],'source':url,'candidate':c,**res})
                if res['status'] in ('downloaded','exists'):
                    break
    (META/'pdf_resolution_results.json').write_text(json.dumps(added,ensure_ascii=False,indent=2),encoding='utf-8')
    lines=['# PDF resolution retry results','']
    for a in added:
        lines.append(f"- {a['id']}: {a['status']} | {a.get('path','')} | {a['candidate']}")
    (META/'pdf_resolution_results.md').write_text('\n'.join(lines),encoding='utf-8')
    print('attempts',len(added),'downloaded',sum(1 for a in added if a['status']=='downloaded'),'exists',sum(1 for a in added if a['status']=='exists'))
if __name__=='__main__': main()
