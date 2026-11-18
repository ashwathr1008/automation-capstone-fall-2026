"""CPU-only checks with the real, pinned Qwen chat template/tokenizer."""
import os
os.environ['CUDA_VISIBLE_DEVICES'] = ''
from train_lanm import ROOT,encode_record,write_json
from transformers import AutoTokenizer

def main():
    tokenizer = AutoTokenizer.from_pretrained(str(ROOT/'models/Qwen3.5-4B'),local_files_only=True)
    row = {'id':'mask-check','messages':[
        {'role':'system','content':'SYSTEM_SENTINEL_MUST_BE_MASKED'},
        {'role':'user','content':'USER_SENTINEL_MUST_BE_MASKED'},
        {'role':'assistant','content':'','tool_calls':[{'id':'call1','type':'function','function':{'name':'project_state','arguments':{'project_id':'training-mask-test'}}}]},
        {'role':'tool','tool_call_id':'call1','name':'project_state','content':'TOOL_SENTINEL_MUST_BE_MASKED'},
        {'role':'assistant','content':'ANSWER_SENTINEL_MUST_BE_SUPERVISED'}],
        'tools':[{'type':'function','function':{'name':'project_state','description':'Read state','parameters':{'type':'object','properties':{'project_id':{'type':'string'}},'required':['project_id']}}}]}
    encoded = encode_record(tokenizer,row,4096)
    supervised = tokenizer.decode([token for token in encoded['labels'] if token != -100])
    for sentinel in ['SYSTEM_SENTINEL_MUST_BE_MASKED','USER_SENTINEL_MUST_BE_MASKED','TOOL_SENTINEL_MUST_BE_MASKED']:
        assert sentinel not in supervised, sentinel
    for required in ['ANSWER_SENTINEL_MUST_BE_SUPERVISED','<function=project_state>','training-mask-test']:
        assert required in supervised, required
    assert '<think>' not in supervised and '</think>' not in supervised
    assert supervised.count('<|im_end|>') == 2
    assert sum(token == tokenizer.eos_token_id for token in encoded['labels']) == 2
    for tag in ['<tool_call>','</tool_call>']:
        assert tokenizer.convert_tokens_to_ids(tag) in encoded['labels']
    for tag in ['<think>','</think>']:
        assert tokenizer.convert_tokens_to_ids(tag) not in encoded['labels']
    try:
        encode_record(tokenizer,row,10)
    except ValueError as error:
        assert 'never truncate' in str(error)
    else:
        raise AssertionError('Oversized record was not rejected')
    result = {'status':'passed','checks':['system masked','user masked','tool result masked','assistant text supervised','tool call supervised','assistant EOS supervised','empty thinking delimiters masked','oversized row rejected'],
        'tokens':len(encoded['input_ids']),'supervised_tokens':sum(t != -100 for t in encoded['labels']),'supervised_preview':supervised}
    write_json(ROOT/'token-mask-check.json',result)
    print(result)

if __name__ == '__main__':
    main()
