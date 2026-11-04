import tempfile
import unittest
from pathlib import Path
from lanm_platform.methods import Registry,execute_source

class MethodTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.registry=Registry(self.temp.name)
        self.manifest={"name":"Lifecycle capture cost","description":"Reference material-only calculation", "boundary":"Materials only", "assumptions":["Constant recovery per cycle"],"inputs":{"cost":{"unit":"USD/L"},"q":{"unit":"kg/L/cycle"},"cycles":{"unit":"cycle"}},"references":["Independent arithmetic reference"],"reference_cases":[{"name":"Hand calculation","inputs":{"cost":100,"q":.01,"cycles":100},"expected":{"usd_per_kg":100},"basis":"100 USD/L / (0.01 kg/L/cycle * 100 cycles) = 100 USD/kg"}]}
        self.code='def calculate(inputs):\n    if inputs["q"] <= 0 or inputs["cycles"] <= 0:\n        raise ValueError("Positive capacity and cycles required")\n    return {"usd_per_kg": inputs["cost"] / (inputs["q"] * inputs["cycles"])}\n'

    def tearDown(self): self.temp.cleanup()

    def test_checked_version_can_be_reused(self):
        self.registry.create_draft("material-cost",self.manifest,self.code)
        checked=self.registry.check("material-cost")
        self.assertTrue(checked["passed"])
        registered=self.registry.register("material-cost")
        run=self.registry.run(registered["id"],{"cost":100,"q":.02,"cycles":100})
        self.assertEqual(run["outputs"]["usd_per_kg"],50)

    def test_draft_change_invalidates_checks(self):
        self.registry.create_draft("material-cost",self.manifest,self.code)
        self.registry.check("material-cost")
        self.registry.create_draft("material-cost",self.manifest,self.code+'\n# revision\n')
        with self.assertRaises(ValueError): self.registry.register("material-cost")

    def test_bad_numerics_do_not_register(self):
        self.registry.create_draft("material-cost",self.manifest,'def calculate(inputs):\n    return {"usd_per_kg": 5}\n')
        self.assertFalse(self.registry.check("material-cost")["passed"])
        with self.assertRaises(ValueError): self.registry.register("material-cost")

    def test_modified_registered_source_cannot_impersonate_checked_version(self):
        self.registry.create_draft("material-cost",self.manifest,self.code)
        self.registry.check("material-cost")
        registered=self.registry.register("material-cost")
        (Path(registered["path"])/"method.py").write_text(self.code.replace('inputs["cost"] /','2 * inputs["cost"] /'))
        with self.assertRaisesRegex(ValueError,"checked version"):
            self.registry.run(registered["id"],{"cost":100,"q":.02,"cycles":100})

    def test_execution_is_numerical_only(self):
        with self.assertRaises(ValueError): execute_source('import os\ndef calculate(inputs):\n return {}',{})
        with self.assertRaises(ValueError): execute_source('def calculate(inputs):\n return inputs.__class__',{})
        with self.assertRaises(ValueError): self.registry.get("../outside")

if __name__=="__main__": unittest.main()
