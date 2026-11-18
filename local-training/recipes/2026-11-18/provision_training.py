"""Download public, pinned training assets into this directory, without GPU work."""
from __future__ import annotations
import argparse
import concurrent.futures
import hashlib
import json
from pathlib import Path
import tarfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parent

def fetch_json(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent":"lanm-training-provision/1.0"}), timeout=90) as response:
        return json.load(response)

def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda:stream.read(8*1024*1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

def download(url, destination, expected_size=None, expected_sha=None):
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and (expected_size is None or destination.stat().st_size == expected_size):
        if expected_sha is None or sha256(destination) == expected_sha:
            return
    partial = destination.with_name(destination.name + ".partial")
    for attempt in range(6):
        offset = partial.stat().st_size if partial.exists() else 0
        request = urllib.request.Request(url, headers={"User-Agent":"lanm-training-provision/1.0", **({"Range":f"bytes={offset}-"} if offset else {})})
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                append = offset > 0 and response.status == 206
                with partial.open("ab" if append else "wb") as stream:
                    for chunk in iter(lambda:response.read(8*1024*1024), b""):
                        stream.write(chunk)
            if expected_size is not None and partial.stat().st_size != expected_size:
                raise ValueError(f"Size mismatch for {destination.name}")
            if expected_sha is not None and sha256(partial) != expected_sha:
                raise ValueError(f"SHA256 mismatch for {destination.name}")
            partial.replace(destination)
            print(json.dumps({"downloaded":str(destination.relative_to(ROOT)),"bytes":destination.stat().st_size}),flush=True)
            return
        except Exception as exc:
            print(json.dumps({"retry":attempt+1,"file":destination.name,"error":str(exc)}),flush=True)
            if attempt == 5:
                raise
            time.sleep(min(2**attempt,30))

def uv():
    version = "0.13.9"
    basename = "uv-x86_64-unknown-linux-gnu.tar.gz"
    base = f"https://github.com/astral-sh/uv/releases/download/{version}/{basename}"
    with urllib.request.urlopen(base+".sha256",timeout=60) as response:
        digest = response.read().decode().split()[0]
    archive = ROOT / "downloads" / basename
    download(base,archive,expected_sha=digest)
    with tarfile.open(archive) as tar:
        member = next(item for item in tar.getmembers() if item.name.endswith("/uv") and item.isfile())
        target = ROOT/"bin"/"uv"
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(tar.extractfile(member).read())
        target.chmod(0o755)
    (ROOT/"uv-provenance.json").write_text(json.dumps({"version":version,"url":base,"sha256":digest},indent=2))

def compiler():
    name='zig-x86_64-linux-0.15.2'
    url=f'https://ziglang.org/download/0.15.2/{name}.tar.xz'
    digest='02aa270f183da276e5b5920b1dac44a63f1a49e55050ebde3aecc9eb82f93239'
    archive=ROOT/'vendor'/f'{name}.tar.xz'
    download(url,archive,expected_sha=digest)
    if not (ROOT/'vendor'/name/'zig').exists():
        with tarfile.open(archive) as tar:
            tar.extractall(ROOT/'vendor',filter='data')
    (ROOT/'vendor'/name/'zig').chmod(0o755)
    for wrapper,mode in [('cc','cc'),('cxx','c++')]:
        path=ROOT/'bin'/wrapper
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text('#!/bin/bash\nSCRIPT_PATH="$(readlink -f "$0")"\nCOMPILER_ROOT="$(CDPATH= cd -- "$(dirname -- "$SCRIPT_PATH")/../vendor/'+name+'" && pwd)"\ntask_args=()\nfor token in "$@"; do\n  if [[ "$token" == "-l:libcuda.so.1" ]]; then\n    task_args+=("/usr/lib/wsl/lib/libcuda.so.1")\n  else\n    task_args+=("$token")\n  fi\ndone\nexec "$COMPILER_ROOT/zig" '+mode+' -target x86_64-linux-gnu -L/usr/lib/wsl/lib -Wl,-rpath,/usr/lib/wsl/lib "${task_args[@]}"\n',newline='\n')
        path.chmod(0o755)
    (ROOT/'compiler-provenance.json').write_text(json.dumps({'url':url,'sha256':digest,'version':'0.15.2','scope':'Portable clang C/C++ wrapper for Triton; workspace only','wsl_cuda_driver':'/usr/lib/wsl/lib/libcuda.so.1','link_compatibility':'Map GNU exact-library -l:libcuda.so.1 flag to the existing absolute WSL driver path for Zig','cc_wrapper_sha256':sha256(ROOT/'bin/cc'),'cxx_wrapper_sha256':sha256(ROOT/'bin/cxx')},indent=2))

def converter():
    revision='93cf736a8d1d46aa922e27eb64aa712bcd5ebc30'
    url=f'https://api.github.com/repos/ggml-org/llama.cpp/tarball/{revision}'
    archive=ROOT/'vendor/llama.cpp-b12323.tar.gz'
    download(url,archive)
    if not (ROOT/'vendor/ggml-org-llama.cpp-93cf736/convert_lora_to_gguf.py').exists():
        with tarfile.open(archive) as tar:
            tar.extractall(ROOT/'vendor',filter='data')
    (ROOT/'converter-provenance.json').write_text(json.dumps({'url':url,'commit':revision,'sha256':sha256(archive),'runtime':'llama.cpp b12323'},indent=2))

def model(name):
    repo = f"Qwen/Qwen3.5-{name}"
    path = ROOT/"models"/f"Qwen3.5-{name}"
    path.mkdir(parents=True,exist_ok=True)
    manifest_path=path/"download-manifest.json"
    if manifest_path.exists():
        manifest=json.loads(manifest_path.read_text())
    else:
        info=fetch_json(f"https://huggingface.co/api/models/{repo}?blobs=true")
        selected=[row for row in info['siblings'] if row['rfilename'].endswith(('.json','.jinja','.safetensors','.txt','.model','.md')) and '/' not in row['rfilename']]
        manifest={"repo_id":repo,"revision":info['sha'],"license":"apache-2.0","files":[{"path":row['rfilename'],"bytes":row.get('size'),"sha256":row.get('lfs',{}).get('sha256')} for row in selected]}
        manifest_path.write_text(json.dumps(manifest,indent=2))
    print(json.dumps({"model":repo,"revision":manifest['revision'],"download_bytes":sum(row.get('bytes') or 0 for row in manifest['files'])}),flush=True)
    def one(row):
        download(f"https://huggingface.co/{repo}/resolve/{manifest['revision']}/{row['path']}",path/row['path'],row.get('bytes'),row.get('sha256'))
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(one,manifest['files']))
    manifest['verified_files']=[{"path":row['path'],"bytes":(path/row['path']).stat().st_size,"sha256":sha256(path/row['path'])} for row in manifest['files']]
    manifest['complete']=True
    manifest_path.write_text(json.dumps(manifest,indent=2))
    print(json.dumps({"complete":repo}),flush=True)

if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--uv-only',action='store_true')
    parser.add_argument('--compiler-only',action='store_true')
    parser.add_argument('--converter-only',action='store_true')
    parser.add_argument('--model',choices=['4B','9B','both'],default='both')
    args=parser.parse_args()
    if args.uv_only:
        uv()
    elif args.compiler_only:
        compiler()
    elif args.converter_only:
        converter()
    else:
        for size in (['4B','9B'] if args.model=='both' else [args.model]):
            model(size)
