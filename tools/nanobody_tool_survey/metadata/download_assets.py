#!/usr/bin/env python3
from __future__ import annotations
import hashlib, json, os, re, shutil, subprocess, sys, time
from pathlib import Path
from urllib.parse import urlparse
import requests

ROOT = Path(__file__).resolve().parents[1]
PAPERS = ROOT / 'papers'
CODE = ROOT / 'code'
LOGS = ROOT / 'logs'
META = ROOT / 'metadata'
sys.path.insert(0, str(META))
from asset_manifest import TOOLS

UA = 'Mozilla/5.0 nanobody-tool-survey/1.0 (open-access asset downloader)'


def slug(s: str) -> str:
    return re.sub(r'[^A-Za-z0-9._-]+', '_', s).strip('_').lower()[:120]


def is_pdf(path: Path) -> bool:
    try:
        return path.read_bytes()[:5] == b'%PDF-'
    except Exception:
        return False


def download_pdf(tool, url):
    folder = PAPERS / tool['category'] / tool['id']
    folder.mkdir(parents=True, exist_ok=True)
    fname = folder / f"{tool['id']}__{slug(urlparse(url).path.split('/')[-1] or 'paper')}.pdf"
    if fname.exists() and is_pdf(fname) and fname.stat().st_size > 10000:
        return {'url': url, 'status': 'exists', 'path': str(fname.relative_to(ROOT)), 'bytes': fname.stat().st_size}
    tmp = fname.with_suffix('.tmp')
    try:
        with requests.get(url, headers={'User-Agent': UA, 'Accept': 'application/pdf,*/*'}, timeout=45, stream=True, allow_redirects=True) as r:
            ctype = r.headers.get('content-type','').lower()
            if r.status_code >= 400:
                return {'url': url, 'status': f'http_{r.status_code}', 'content_type': ctype}
            total = 0
            with open(tmp, 'wb') as fh:
                for chunk in r.iter_content(chunk_size=65536):
                    if not chunk:
                        continue
                    fh.write(chunk); total += len(chunk)
                    if total > 80_000_000:
                        return {'url': url, 'status': 'too_large'}
            if not is_pdf(tmp) or tmp.stat().st_size < 5000:
                sample = tmp.read_bytes()[:120].decode('latin1', errors='replace') if tmp.exists() else ''
                tmp.unlink(missing_ok=True)
                return {'url': url, 'status': 'not_pdf', 'content_type': ctype, 'sample': sample[:80]}
            tmp.replace(fname)
            sha = hashlib.sha256(fname.read_bytes()).hexdigest()[:16]
            return {'url': url, 'status': 'downloaded', 'path': str(fname.relative_to(ROOT)), 'bytes': fname.stat().st_size, 'sha256_16': sha}
    except Exception as e:
        tmp.unlink(missing_ok=True)
        return {'url': url, 'status': 'error', 'error': repr(e)}


def repo_name(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path.strip('/').removesuffix('.git')
    return slug(path.replace('/', '__'))


def clone_repo(tool, url):
    folder = CODE / tool['category'] / tool['id']
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / repo_name(url)
    if dest.exists():
        head = ''
        try:
            head = subprocess.check_output(['git','-C',str(dest),'rev-parse','--short','HEAD'], text=True, timeout=10).strip()
        except Exception:
            pass
        return {'url': url, 'status': 'exists', 'path': str(dest.relative_to(ROOT)), 'head': head}
    try:
        cmd = ['git','clone','--depth','1',url,str(dest)]
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=240)
        if proc.returncode != 0:
            shutil.rmtree(dest, ignore_errors=True)
            return {'url': url, 'status': f'clone_failed_{proc.returncode}', 'output': proc.stdout[-2000:]}
        head = subprocess.check_output(['git','-C',str(dest),'rev-parse','--short','HEAD'], text=True, timeout=10).strip()
        return {'url': url, 'status': 'cloned', 'path': str(dest.relative_to(ROOT)), 'head': head}
    except Exception as e:
        shutil.rmtree(dest, ignore_errors=True)
        return {'url': url, 'status': 'error', 'error': repr(e)}


def main():
    PAPERS.mkdir(parents=True, exist_ok=True); CODE.mkdir(parents=True, exist_ok=True); LOGS.mkdir(parents=True, exist_ok=True)
    results = []
    for i, tool in enumerate(TOOLS, 1):
        print(f"[{i}/{len(TOOLS)}] {tool['id']} {tool['name']}", flush=True)
        item = {k: tool.get(k) for k in ['id','name','category','papers']}
        item['paper_downloads'] = [download_pdf(tool, u) for u in tool.get('pdf_urls', [])]
        item['code_downloads'] = [clone_repo(tool, u) for u in tool.get('code_urls', [])]
        results.append(item)
        time.sleep(0.2)
    out = META / 'asset_download_results.json'
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    # Human-readable summary
    lines = ['# Asset download results', '']
    for item in results:
        lines.append(f"## {item['name']} (`{item['id']}`)")
        lines.append(f"- Category: {item['category']}")
        for p in item['paper_downloads']:
            lines.append(f"- PDF: {p.get('status')} | {p.get('path','')} | {p.get('url')}")
        if not item['paper_downloads']:
            lines.append('- PDF: no direct open PDF candidate in manifest')
        for c in item['code_downloads']:
            lines.append(f"- Code: {c.get('status')} | {c.get('path','')} | {c.get('url')}")
        if not item['code_downloads']:
            lines.append('- Code: no public code repository in manifest / commercial or web-only')
        lines.append('')
    (META / 'asset_download_results.md').write_text('\n'.join(lines), encoding='utf-8')
    print(f"Wrote {out}")

if __name__ == '__main__':
    main()
