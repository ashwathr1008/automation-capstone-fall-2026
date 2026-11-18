"""Tiny released-GPU test; verifies Triton runs on CUDA before model training."""
import argparse
from train_lanm import ROOT,require_gpu_ready,write_json,sha
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--gpu-ready', action='store_true')
args = parser.parse_args()
require_gpu_ready(args.gpu_ready)
import unsloth
import torch
import triton
import triton.language as tl

@triton.jit
def add_one(source,destination,N:tl.constexpr):
    offsets=tl.arange(0,128)
    values=tl.load(source+offsets,offsets<N,other=0)
    tl.store(destination+offsets,values+1,offsets<N)

target=triton.runtime.driver.active.get_current_target()
if target.backend != 'cuda':
    raise RuntimeError(f'Expected CUDA Triton, got {target}')
source=torch.arange(128,device='cuda',dtype=torch.float32)
destination=torch.empty_like(source)
add_one[(1,)](source,destination,128)
torch.cuda.synchronize()
assert torch.equal(destination,source+1)
result={'status':'passed','gpu':torch.cuda.get_device_name(),'triton_target':str(target),
    'cuda_runtime':torch.version.cuda,'vector_elements':128,'correct_output':True,
    'compiler_provenance_sha256':sha(ROOT/'compiler-provenance.json'),
    'gpu_peak_allocated_bytes':torch.cuda.max_memory_allocated()}
write_json(ROOT/'gpu-runtime-check.json',result)
print(result,flush=True)
