"""Temporary loopback-only offline integration review, never a production host."""
import argparse
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).parent))
from fixtures import ReviewAuthority, ACCOUNTS
from papyrus_content.curation_host import create_curation_host
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

parser = argparse.ArgumentParser()
parser.add_argument('--port', type=int, default=8930)
parser.add_argument('--state', type=Path, required=True)
args = parser.parse_args()
authority = ReviewAuthority(args.state)

@asynccontextmanager
async def lifespan(app):
    for workspace in authority.workspaces.values():
        await workspace.seed()
    yield
    authority.close()

app = FastAPI(lifespan=lifespan)

@app.get('/')
@app.get('/newsroom/references')
async def index():
    return FileResponse(ROOT / '.papyrus-runs/curation-review-ui/index.html', headers={'Cache-Control': 'no-store'})

@app.post('/review/selection')
async def selection(request: Request):
    if request.headers.get('origin') and urlsplit(request.headers['origin']).netloc != request.headers.get('host'):
        return JSONResponse({'error': 'cross-origin fixture selection refused'}, status_code=403)
    if request.headers.get('content-type') != 'application/json' or int(request.headers.get('content-length', '0')) > 1000:
        return JSONResponse({'error': 'bounded JSON fixture selection required'}, status_code=400)
    body = await request.json()
    if set(body) != {'account', 'mode'} or body['account'] not in ACCOUNTS or body['mode'] not in ('embedded', 'remote'):
        return JSONResponse({'error': 'unknown fixture'}, status_code=400)
    authority.account, authority.mode = body['account'], body['mode']
    return {'fixture': True}

@app.get('/review/proof')
async def proof():
    return {'syntheticOnly': True, 'hostedActivation': False, 'accounts': authority.proof()}

app.mount('/curation-review-assets', StaticFiles(directory=ROOT / '.papyrus-runs/curation-review-ui'))
app.mount('/', create_curation_host(authority.context))
if __name__ == '__main__':
    uvicorn.run(app, host='127.0.0.1', port=args.port)
