"""Resumable Qwen LoRA training. Never reads benchmark examples or truncates answers."""
from __future__ import annotations
import argparse
import copy
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import re
import time

ROOT = Path(__file__).resolve().parent
RUNTIME_ROOT = ROOT
if os.name == 'posix' and (ROOT/'runtime.json').exists():
    RUNTIME_ROOT = Path(json.loads((ROOT/'runtime.json').read_text())['runtime_root'])
if os.environ.get('LANM_TRAINING_RUNTIME_ROOT'):
    RUNTIME_ROOT = Path(os.environ['LANM_TRAINING_RUNTIME_ROOT'])
for key, value in {
    'HF_HOME': RUNTIME_ROOT/'cache/huggingface', 'XDG_CACHE_HOME': RUNTIME_ROOT/'cache',
    'TORCH_HOME': RUNTIME_ROOT/'cache/torch', 'TRITON_CACHE_DIR': RUNTIME_ROOT/'cache/triton',
    'TORCHINDUCTOR_CACHE_DIR': RUNTIME_ROOT/'cache/torchinductor', 'TMPDIR': RUNTIME_ROOT/'tmp',
    'UNSLOTH_COMPILE_LOCATION': RUNTIME_ROOT/'cache/unsloth_compiled',
}.items():
    os.environ[key] = str(value)
    Path(value).mkdir(parents=True, exist_ok=True)
os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
os.environ['WANDB_DISABLED'] = 'true'
os.environ['TOKENIZERS_PARALLELISM'] = 'false'
os.environ['CC'] = str(RUNTIME_ROOT/'bin/cc')
os.environ['CXX'] = str(RUNTIME_ROOT/'bin/cxx')
os.environ['ZIG_GLOBAL_CACHE_DIR'] = str(RUNTIME_ROOT/'cache/zig')
os.environ['ZIG_LOCAL_CACHE_DIR'] = str(RUNTIME_ROOT/'cache/zig-local')
os.environ['PATH'] = str(RUNTIME_ROOT/'bin') + os.pathsep + os.environ.get('PATH','')
TARGETS = ['q_proj', 'k_proj', 'v_proj', 'o_proj', 'gate_proj', 'up_proj', 'down_proj']
RELEASE = ROOT.parent/'benchmark-results/2026-11-18-expanded/gpu-baselines-finished.json'

def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(8*1024*1024), b''):
            digest.update(chunk)
    return digest.hexdigest()

def write_json(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')

def run_identity(args, base):
    if any(not Path(path).resolve().is_relative_to(ROOT) for path in [args.train,args.validation]):
        raise ValueError('Training inputs must stay within local-training')
    return {'base_manifest_sha256':sha(base/'download-manifest.json'),
        'native_template_sha256':sha(base/'chat_template.jinja'),
        'tokenizer_sha256':sha(base/'tokenizer.json'),'tokenizer_config_sha256':sha(base/'tokenizer_config.json'),
        'base_config_sha256':sha(base/'config.json'),
        'environment_lock_sha256':sha(ROOT/'environment-lock.txt'),
        'compiler_provenance_sha256':sha(ROOT/'compiler-provenance.json'),
        'train_sha256':sha(Path(args.train).resolve()), 'validation_sha256':sha(Path(args.validation).resolve()),
        'settings':{key:getattr(args,key) for key in ['size','max_length','precision','epochs','learning_rate','accumulation','rank','seed']},
        'targets':TARGETS, 'masking_version':1,'trainer_sha256':sha(Path(__file__))}

def check_output_identity(args, output, identity):
    previous_path = output/'run-manifest.json'
    checkpoints = list((output/'checkpoints').glob('checkpoint-*')) if (output/'checkpoints').exists() else []
    if checkpoints:
        for checkpoint in checkpoints:
            match = re.fullmatch(r'checkpoint-(\d+)',checkpoint.name)
            required = ['trainer_state.json','adapter_model.safetensors','adapter_config.json','optimizer.pt','scheduler.pt','rng_state.pth']
            if not match or not checkpoint.is_dir() or any(not (checkpoint/name).is_file() for name in required):
                raise ValueError('Incomplete checkpoint state; refusing an unsafe resume')
            state = json.loads((checkpoint/'trainer_state.json').read_text())
            if state.get('global_step') != int(match.group(1)) or state['global_step'] <= 0:
                raise ValueError('Checkpoint trainer state does not match its directory')
    if previous_path.exists():
        previous = json.loads(previous_path.read_text())
        if args.prepare_only or previous.get('status') == 'completed':
            raise ValueError('Existing run is immutable; use a fresh --output directory')
        if previous.get('identity') != identity:
            raise ValueError('Resume dataset/base/tokenizer/settings identity differs from the existing run')
        if args.resume == 'none' or not checkpoints:
            raise ValueError('Existing run requires a matching checkpoint resume; use a fresh output for a restart')
    elif checkpoints:
        raise ValueError('Orphan checkpoints without a run manifest; refusing to resume')
    if args.resume not in ('auto','none'):
        checkpoint = Path(args.resume).resolve()
        if not previous_path.exists() or checkpoint not in {path.resolve() for path in checkpoints}:
            raise ValueError('Explicit resume checkpoint must belong to this verified run')

def read_records(path):
    records = [json.loads(line) for line in path.read_text(encoding='utf-8-sig').splitlines() if line.strip()]
    if not records or len({row['id'] for row in records}) != len(records):
        raise ValueError(f'Empty dataset or duplicate ids: {path}')
    for row in records:
        if not row.get('provenance'):
            raise ValueError(f"Missing provenance: {row['id']}")
        for message in row['messages']:
            if any(token in str(message.get('content', '')) for token in ('<|im_start|>', '<|im_end|>')):
                raise ValueError(f"Unescaped chat delimiters: {row['id']}")
            for call in message.get('tool_calls', []):
                arguments = call['function'].get('arguments', {})
                if isinstance(arguments, str):
                    arguments = json.loads(arguments)
                if not isinstance(arguments, dict):
                    raise ValueError(f"Non-object tool arguments: {row['id']}")
                call['function']['arguments'] = arguments
    return records

def encode_record(tokenizer, row, max_length):
    messages = copy.deepcopy(row['messages'])
    text = tokenizer.apply_chat_template(messages, tools=row.get('tools') or None,
        tokenize=False, add_generation_prompt=False, enable_thinking=False)
    spans = []
    for match in re.finditer(r'<\|im_start\|>assistant\n(.*?)<\|im_end\|>', text, re.DOTALL):
        start = match.start(1)
        empty_think = '<think>\n\n</think>\n\n'
        if text.startswith(empty_think, start):
            start += len(empty_think)
        spans.append((start, match.end()))
    if len(spans) != sum(message['role'] == 'assistant' for message in messages):
        raise ValueError(f"Assistant span mismatch: {row['id']}")
    encoded = tokenizer(text, add_special_tokens=False, return_offsets_mapping=True)
    ids = encoded['input_ids']
    if len(ids) > max_length:
        raise ValueError(f"Record {row['id']} has {len(ids)} tokens > {max_length}; shorten/split upstream, never truncate answers")
    labels = [token if end > start and any(start >= a and end <= b for a, b in spans) else -100
              for token, (start, end) in zip(ids, encoded['offset_mapping'])]
    if not any(token != -100 for token in labels):
        raise ValueError(f"No supervised tokens: {row['id']}")
    return {'input_ids': ids, 'attention_mask': [1]*len(ids), 'labels': labels}

class LabelPreservingCollator:
    def __init__(self, tokenizer):
        self.tokenizer = tokenizer
    def __call__(self, examples):
        import torch
        width = ((max(len(row['input_ids']) for row in examples)+7)//8)*8
        return {key: torch.tensor([row[key]+[pad]*(width-len(row[key])) for row in examples], dtype=torch.long)
                for key,pad in [('input_ids', self.tokenizer.pad_token_id), ('attention_mask', 0), ('labels', -100)]}

def prepare(args, tokenizer, output):
    train_path, val_path = Path(args.train).resolve(), Path(args.validation).resolve()
    if not train_path.is_relative_to(ROOT) or not val_path.is_relative_to(ROOT):
        raise ValueError('Training inputs must live within local-training, never benchmark-results')
    training, validation = read_records(train_path), read_records(val_path)
    if {row['id'] for row in training} & {row['id'] for row in validation}:
        raise ValueError('Train/validation ids overlap')
    train_groups = {row.get('split_group', row.get('group')) for row in training}
    val_groups = {row.get('split_group', row.get('group')) for row in validation}
    if None in train_groups | val_groups or train_groups & val_groups:
        raise ValueError('Missing or overlapping train/validation groups')
    encoded = {}
    manifest = {'train_file':str(train_path), 'validation_file':str(val_path),
        'train_sha256':sha(train_path), 'validation_sha256':sha(val_path),
        'masking':'Assistant content/tool calls/EOS only; user/system/tool results and empty think prefix masked',
        'thinking_training':'Direct-answer supervision; no generated reasoning traces', 'truncation':False,
        'max_length':args.max_length, 'split_groups_disjoint':True,
        'tokenizer_template_sha256':hashlib.sha256(tokenizer.chat_template.encode()).hexdigest()}
    for name,records in [('train',training), ('validation',validation)]:
        encoded[name] = [encode_record(tokenizer,row,args.max_length) for row in records]
        manifest[name] = {'examples':len(records), 'ids':[row['id'] for row in records],
            'groups':sorted({row.get('split_group',row.get('group')) for row in records}),
            'tokens':sum(len(row['input_ids']) for row in encoded[name]),
            'supervised_tokens':sum(sum(token != -100 for token in row['labels']) for row in encoded[name]),
            'max_tokens':max(len(row['input_ids']) for row in encoded[name])}
    write_json(output/'prepared-data-manifest.json',manifest)
    return encoded,manifest

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--size',choices=['4B','9B'],required=True)
    parser.add_argument('--train',default=str(ROOT/'data/train.jsonl'))
    parser.add_argument('--validation',default=str(ROOT/'data/validation.jsonl'))
    parser.add_argument('--output')
    parser.add_argument('--max-length',type=int,default=4096)
    parser.add_argument('--precision',choices=['qlora4','bf16'],default='qlora4')
    parser.add_argument('--epochs',type=float,default=1.0)
    parser.add_argument('--learning-rate',type=float,default=1e-4)
    parser.add_argument('--accumulation',type=int,default=8)
    parser.add_argument('--rank',type=int,default=16)
    parser.add_argument('--seed',type=int,default=42)
    parser.add_argument('--resume',default='auto')
    parser.add_argument('--prepare-only',action='store_true')
    args = parser.parse_args()
    base = ROOT/'models'/f'Qwen3.5-{args.size}'
    output = Path(args.output).resolve() if args.output else ROOT/'runs'/f'qwen-{args.size.lower()}-lanm'
    if not output.is_relative_to(ROOT):
        raise ValueError('Output must stay within local-training')
    identity = run_identity(args,base)
    check_output_identity(args,output,identity)
    output.mkdir(parents=True,exist_ok=True)
    if args.prepare_only:
        os.environ['CUDA_VISIBLE_DEVICES'] = ''
        from transformers import AutoTokenizer
        tokenizer = AutoTokenizer.from_pretrained(str(base),local_files_only=True)
        _,manifest = prepare(args,tokenizer,output)
        print(json.dumps(manifest,indent=2))
        return
    if not RELEASE.exists():
        raise RuntimeError(f'GPU reserved for baselines; await coordinator release: {RELEASE}')
    if args.epochs < 1:
        raise ValueError('Meaningful run requires at least one epoch')
    provenance_path = base/'download-manifest.json'
    provenance = json.loads(provenance_path.read_text())
    if not provenance.get('complete'):
        raise RuntimeError('Official model download/checksum verification not complete')
    started = time.time()
    # Unsloth must be imported before transformers/TRL.
    from unsloth import FastLanguageModel
    import torch
    import triton
    from datasets import Dataset
    from trl import SFTTrainer,SFTConfig
    from transformers import TrainerCallback,set_seed
    from transformers.trainer_utils import get_last_checkpoint
    set_seed(args.seed)
    triton_target = triton.runtime.driver.active.get_current_target()
    if triton_target.backend != 'cuda':
        raise RuntimeError('Triton GPU kernels are unavailable; refusing CPU fallback training')
    free_bytes,total_bytes = torch.cuda.mem_get_info()
    if free_bytes < total_bytes*0.8:
        raise RuntimeError('GPU still occupied: stop inference servers before isolated training')
    torch.cuda.reset_peak_memory_stats()
    model,tokenizer = FastLanguageModel.from_pretrained(model_name=str(base),max_seq_length=args.max_length,
        dtype=torch.bfloat16,load_in_4bit=args.precision=='qlora4',load_in_16bit=args.precision=='bf16',
        full_finetuning=False,local_files_only=True,trust_remote_code=False,device_map={'':0},fast_inference=False,
        text_only=True,fix_tokenizer=False,use_exact_model_name=True)
    encoded,data_manifest = prepare(args,tokenizer,output)
    module_targets = [name for name,_ in model.named_modules()
        if name.rsplit('.',1)[-1] in TARGETS and '.layers.' in '.'+name+'.'
        and not any(part in '.'+name+'.' for part in ['.visual.','.vision.','.mtp.'])]
    if not module_targets:
        raise RuntimeError('No supported language decoder LoRA targets found')
    target_pattern = '^(?:'+'|'.join(re.escape(name) for name in module_targets)+')$'
    model = FastLanguageModel.get_peft_model(model,r=args.rank,target_modules=target_pattern,lora_alpha=args.rank,
        lora_dropout=0,bias='none',use_gradient_checkpointing='unsloth',random_state=args.seed,max_seq_length=args.max_length)
    trainable = [(name,p.numel()) for name,p in model.named_parameters() if p.requires_grad]
    if not trainable or any('lora_' not in name or '.layers.' not in name or any(part in name for part in ['.visual.','.vision','.mtp.']) for name,_ in trainable):
        raise RuntimeError('Only language LoRA parameters may be trainable')
    actual_targets = {name.split('.lora_',1)[0].removeprefix('base_model.model.') for name,_ in trainable}
    if actual_targets != set(module_targets):
        raise RuntimeError('Actual trainable decoder modules differ from the exact selected target set')
    quantization = getattr(model.config,'quantization_config',None)
    if hasattr(quantization,'to_dict'):
        quantization = quantization.to_dict()
    quantization = json.loads(json.dumps(quantization,default=str))
    manifest = {'status':'training','identity':identity,'args':vars(args),'base_repo':provenance['repo_id'],'base_revision':provenance['revision'],
        'base_download_manifest_sha256':sha(provenance_path),'data':data_manifest,'target_suffixes':TARGETS,'targets':module_targets,
        'trainable_parameters':sum(count for _,count in trainable),'trainable_parameter_names':[name for name,_ in trainable],
        'packages':{name:importlib.metadata.version(name) for name in ['torch','transformers','unsloth','unsloth_zoo','trl','peft','bitsandbytes']},
        'gpu':torch.cuda.get_device_name(),'cuda_runtime':torch.version.cuda,
        'triton_target':str(triton_target),'verified_exact_trainable_target_set':True,
        'quantization_config':quantization,'model_dtype':str(model.dtype),'runtime_root':str(RUNTIME_ROOT),
        'quantization_limitation':'Unsloth recommends bf16 for Qwen3.5; QLoRA4 may be used under 16GB hardware limit, with the same setting for both sizes.',
        'benchmark_excluded':True,'started_unix':started}
    write_json(output/'run-manifest.json',manifest)
    class Progress(TrainerCallback):
        def on_log(self,args,state,control,logs=None,**kwargs):
            write_json(output/'progress.json',{'global_step':state.global_step,'epoch':state.epoch,'logs':logs,'elapsed_seconds':time.time()-started})
    config = SFTConfig(output_dir=str(output/'checkpoints'),num_train_epochs=args.epochs,
        per_device_train_batch_size=1,per_device_eval_batch_size=1,gradient_accumulation_steps=args.accumulation,
        learning_rate=args.learning_rate,warmup_steps=0.1,lr_scheduler_type='linear',weight_decay=0.01,
        optim='adamw_8bit',bf16=True,fp16=False,logging_steps=1,save_strategy='steps',save_steps=10,save_total_limit=2,
        eval_strategy='epoch',eval_accumulation_steps=1,seed=args.seed,data_seed=args.seed,
        max_length=args.max_length,packing=False,dataset_kwargs={'skip_prepare_dataset':True},remove_unused_columns=False,
        report_to='none',dataloader_num_workers=0,gradient_checkpointing=True)
    trainer = SFTTrainer(model=model,processing_class=tokenizer,args=config,
        train_dataset=Dataset.from_list(encoded['train']),eval_dataset=Dataset.from_list(encoded['validation']),
        data_collator=LabelPreservingCollator(tokenizer),callbacks=[Progress()])
    resume = get_last_checkpoint(str(output/'checkpoints')) if args.resume=='auto' and (output/'checkpoints').exists() else None
    if args.resume not in ('auto','none'):
        resume = args.resume
    if not resume:
        before = trainer.evaluate(metric_key_prefix='before')
        write_json(output/'validation-before.json',before)
        if not math.isfinite(before['before_loss']):
            raise RuntimeError('Initial held-out loss is non-finite; training was not started')
    result = trainer.train(resume_from_checkpoint=resume)
    after = trainer.evaluate(metric_key_prefix='after')
    trainer.save_model(str(output/'adapter'))
    tokenizer.save_pretrained(str(output/'adapter'))
    trainer.save_state()
    adapter = output/'adapter/adapter_model.safetensors'
    if not adapter.exists():
        raise RuntimeError('Missing saved adapter weights')
    from safetensors.torch import load_file
    tensors = load_file(str(adapter),device='cpu')
    if any(not bool(torch.isfinite(tensor).all()) for tensor in tensors.values()):
        raise RuntimeError('Saved adapter contains NaN or infinite values')
    before = json.loads((output/'validation-before.json').read_text())
    measured_losses = [before['before_loss'],after['after_loss'],result.metrics['train_loss']]
    if not all(math.isfinite(value) for value in measured_losses):
        raise RuntimeError('Training or held-out validation produced non-finite loss')
    if trainer.state.global_step <= 0 or trainer.state.epoch is None or trainer.state.epoch+1e-6 < args.epochs:
        raise RuntimeError('Requested training epochs did not complete')
    b_nonzero = sum(int(torch.count_nonzero(tensor)) for name,tensor in tensors.items() if 'lora_B' in name)
    if not b_nonzero:
        raise RuntimeError('Adapter B matrices remain zero: effective weights were not trained')
    manifest.update(status='completed',elapsed_seconds=time.time()-started,train_metrics=result.metrics,
        validation_before=before,validation_after=after,global_step=trainer.state.global_step,completed_epochs=trainer.state.epoch,
        adapter_sha256=sha(adapter),adapter_config_sha256=sha(output/'adapter/adapter_config.json'),
        adapter_bytes=adapter.stat().st_size,nonzero_lora_b_elements=b_nonzero,
        peak_cuda_allocated_bytes=torch.cuda.max_memory_allocated(),peak_cuda_reserved_bytes=torch.cuda.max_memory_reserved())
    write_json(output/'run-manifest.json',manifest)
    print(json.dumps({key:manifest[key] for key in ['status','global_step','completed_epochs','adapter_sha256','elapsed_seconds','validation_after']},indent=2))

if __name__ == '__main__':
    main()
