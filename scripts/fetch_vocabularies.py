"""Download official MONDO/HPO JSON snapshots for deterministic local resolution."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.request import urlopen
import json
import hashlib

ROOT = Path(__file__).resolve().parents[1] / 'data/raw'
URLS = {
 'mondo.json': 'https://github.com/monarch-initiative/mondo/releases/latest/download/mondo.json',
 'hp.json': 'https://github.com/obophenotype/human-phenotype-ontology/releases/latest/download/hp.json',
}

def fetch(item):
 name, url = item
 ROOT.mkdir(parents=True, exist_ok=True)
 dest = ROOT / name
 if not dest.exists():
  temp = dest.with_suffix('.download')
  with urlopen(url, timeout=120) as response, temp.open('wb') as output:
   while data := response.read(1024*1024):
    output.write(data)
  parsed = json.loads(temp.read_text())
  if not parsed.get('graphs'): raise ValueError('Invalid ontology')
  temp.replace(dest)
 print(name, dest.stat().st_size, hashlib.sha256(dest.read_bytes()).hexdigest(), flush=True)

if __name__ == '__main__':
 with ThreadPoolExecutor(max_workers=2) as pool:
  list(pool.map(fetch, URLS.items()))
