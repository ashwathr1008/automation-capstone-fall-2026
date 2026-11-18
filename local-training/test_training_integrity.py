import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from train_lanm import ROOT,check_output_identity,write_json

class RunIntegrityTests(unittest.TestCase):
    def setUp(self):
        (ROOT / 'tmp').mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=ROOT/'tmp')
        self.output = Path(self.temp.name)
        self.identity = {'data':'original','settings':{'rank':16}}
        self.args = SimpleNamespace(prepare_only=False,resume='auto')
    def tearDown(self):
        self.temp.cleanup()
    def existing(self,status='training'):
        write_json(self.output/'run-manifest.json',{'status':status,'identity':self.identity})
        self.checkpoint()
    def checkpoint(self):
        checkpoint = self.output/'checkpoints/checkpoint-10'
        checkpoint.mkdir(parents=True)
        write_json(checkpoint/'trainer_state.json',{'global_step':10})
        for name in ['adapter_model.safetensors','adapter_config.json','optimizer.pt','scheduler.pt','rng_state.pth']:
            (checkpoint/name).write_bytes(b'test-state')
    def test_fresh_output_allowed(self):
        check_output_identity(self.args,self.output,self.identity)
    def test_matching_checkpoint_resume_allowed(self):
        self.existing()
        check_output_identity(self.args,self.output,self.identity)
    def test_changed_identity_rejected_without_manifest_mutation(self):
        self.existing()
        original=(self.output/'run-manifest.json').read_bytes()
        with self.assertRaisesRegex(ValueError,'identity differs'):
            check_output_identity(self.args,self.output,{'data':'new'})
        self.assertEqual(original,(self.output/'run-manifest.json').read_bytes())
    def test_completed_output_immutable(self):
        self.existing('completed')
        with self.assertRaisesRegex(ValueError,'immutable'):
            check_output_identity(self.args,self.output,self.identity)
    def test_fresh_restart_rejected_for_existing_run(self):
        self.existing()
        self.args.resume='none'
        with self.assertRaisesRegex(ValueError,'matching checkpoint'):
            check_output_identity(self.args,self.output,self.identity)
    def test_orphan_checkpoint_rejected(self):
        self.checkpoint()
        with self.assertRaisesRegex(ValueError,'Orphan'):
            check_output_identity(self.args,self.output,self.identity)
    def test_partial_checkpoint_rejected(self):
        self.existing()
        (self.output/'checkpoints/checkpoint-10/optimizer.pt').unlink()
        with self.assertRaisesRegex(ValueError,'Incomplete'):
            check_output_identity(self.args,self.output,self.identity)
    def test_external_resume_checkpoint_rejected(self):
        self.existing()
        self.args.resume=str(ROOT/'models')
        with self.assertRaisesRegex(ValueError,'must belong'):
            check_output_identity(self.args,self.output,self.identity)
    def test_prepare_only_cannot_overwrite_running_manifest(self):
        self.existing()
        self.args.prepare_only=True
        with self.assertRaisesRegex(ValueError,'immutable'):
            check_output_identity(self.args,self.output,self.identity)

if __name__ == '__main__':
    unittest.main()
