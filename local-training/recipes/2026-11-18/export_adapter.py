"""Export LoRA with the exact source revision of benchmark llama.cpp b12323."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from train_lanm import ROOT, sha, write_json

COMMIT = '93cf736a8d1d46aa922e27eb64aa712bcd5ebc30'
SOURCE = ROOT/'vendor/ggml-org-llama.cpp-93cf736'

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--size', choices=['4B','9B'], required=True)
    parser.add_argument('--run')
    parser.add_argument('--synthetic-check', action='store_true')
    args = parser.parse_args()
    os.environ['CUDA_VISIBLE_DEVICES'] = ''
    base = ROOT/'models'/f'Qwen3.5-{args.size}'
    run = Path(args.run).resolve() if args.run else ROOT/'runs'/f'qwen-{args.size.lower()}-lanm'
    if not run.is_relative_to(ROOT):
        raise ValueError('Run and exports must stay within local-training')
    if args.synthetic_check:
        import torch
        from safetensors.torch import save_file
        cfg = json.loads((base/'config.json').read_text())['text_config']
        hidden, intermediate, head = cfg['hidden_size'],cfg['intermediate_size'],cfg['head_dim']
        qsize, kvsize = cfg['num_attention_heads']*head, cfg['num_key_value_heads']*head
        shapes = {'q_proj':(2*qsize,hidden),'k_proj':(kvsize,hidden),'v_proj':(kvsize,hidden),
            'o_proj':(hidden,qsize),'gate_proj':(intermediate,hidden),'up_proj':(intermediate,hidden),'down_proj':(hidden,intermediate)}
        run = ROOT/'export-checks'/args.size
        adapter = run/'synthetic-adapter'
        adapter.mkdir(parents=True, exist_ok=True)
        tensors = {}
        for name,(outputs,inputs) in shapes.items():
            component = 'self_attn' if name in ('q_proj','k_proj','v_proj','o_proj') else 'mlp'
            prefix = f'base_model.model.model.layers.3.{component}.{name}'
            tensors[prefix+'.lora_A.weight'] = torch.zeros((2,inputs),dtype=torch.float32)
            tensors[prefix+'.lora_B.weight'] = torch.zeros((outputs,2),dtype=torch.float32)
        save_file(tensors,str(adapter/'adapter_model.safetensors'))
        write_json(adapter/'adapter_config.json',{'base_model_name_or_path':str(base),'lora_alpha':2,'r':2,'peft_type':'LORA','bias':'none','target_modules':list(shapes)})
        artifact = run/'synthetic-compatibility.gguf'
    else:
        manifest = json.loads((run/'run-manifest.json').read_text())
        provenance = json.loads((base/'download-manifest.json').read_text())
        if manifest.get('status') != 'completed':
            raise RuntimeError('Training must complete before production export')
        if manifest['args']['size'] != args.size or manifest['base_repo'] != provenance['repo_id'] or manifest['base_revision'] != provenance['revision']:
            raise RuntimeError('Selected export size/base differs from the completed training run')
        if manifest['base_download_manifest_sha256'] != sha(base/'download-manifest.json'):
            raise RuntimeError('Base checkpoint provenance changed since training')
        if manifest['identity']['base_config_sha256'] != sha(base/'config.json'):
            raise RuntimeError('Base model configuration changed since training')
        adapter = run/'adapter'
        if sha(adapter/'adapter_model.safetensors') != manifest['adapter_sha256']:
            raise RuntimeError('Saved adapter hash changed')
        if sha(adapter/'adapter_config.json') != manifest['adapter_config_sha256']:
            raise RuntimeError('Saved adapter configuration hash changed')
        artifact = run/f'qwen-{args.size.lower()}-lanm-lora-f16.gguf'
    converter = SOURCE/'convert_lora_to_gguf.py'
    command = [sys.executable,str(converter),'--base',str(base),'--outtype','f16','--outfile',str(artifact),str(adapter)]
    subprocess.run(command,check=True,cwd=str(SOURCE))
    import numpy as np
    from gguf import GGUFReader
    reader = GGUFReader(str(artifact))
    if any(not bool(np.isfinite(tensor.data).all()) for tensor in reader.tensors):
        raise RuntimeError('Converted GGUF contains non-finite adapter values')
    nonzero_b = sum(int(np.count_nonzero(tensor.data)) for tensor in reader.tensors if tensor.name.endswith('.lora_b'))
    if not args.synthetic_check and (len(reader.tensors) != 2*len(manifest['targets']) or not nonzero_b):
        raise RuntimeError('Export lost expected adapter tensors or all learned B updates')
    write_json(run/'export-manifest.json',{'synthetic':args.synthetic_check,'llama_cpp_commit':COMMIT,
        'runtime':'llama.cpp b12323','converter_sha256':sha(converter),'base_config_sha256':sha(base/'config.json'),
        'adapter_sha256':sha(adapter/'adapter_model.safetensors'),'gguf_sha256':sha(artifact),
        'gguf_bytes':artifact.stat().st_size,'gguf':str(artifact),'load_flag':['--lora',str(artifact)],
        'tensor_count':len(reader.tensors),'finite_tensors':True,'nonzero_lora_b_elements':nonzero_b,
        'same_runtime_gpu_load_verified':False,
        'note':('Zero-valued synthetic check proves conversion only.' if args.synthetic_check else 'Real learned adapter export verified; production load/tool smoke is separately required.')})
    print(json.dumps({'exported':str(artifact),'sha256':sha(artifact),'synthetic':args.synthetic_check}))

if __name__ == '__main__':
    main()
