"""CPU-only native Python-extension smoke for the isolated Triton compiler."""
import importlib.util
import subprocess
import sysconfig
from train_lanm import ROOT,RUNTIME_ROOT,write_json

build = RUNTIME_ROOT/'tmp/compiler-check'
build.mkdir(parents=True,exist_ok=True)
source = build/'lanm_compiler_check.c'
source.write_text('''#include <Python.h>
static PyObject* answer(PyObject* self, PyObject* args) { return PyLong_FromLong(42); }
static PyMethodDef methods[] = {{"answer",answer,METH_NOARGS,"Compiler check"},{NULL,NULL,0,NULL}};
static struct PyModuleDef module = {PyModuleDef_HEAD_INIT,"lanm_compiler_check",NULL,-1,methods};
PyMODINIT_FUNC PyInit_lanm_compiler_check(void) { return PyModule_Create(&module); }
''')
artifact = build/('lanm_compiler_check'+sysconfig.get_config_var('EXT_SUFFIX'))
command = [str(RUNTIME_ROOT/'bin/cc'),'-shared','-fPIC','-O2','-I'+sysconfig.get_path('include'),str(source),'-l:libcuda.so.1','-o',str(artifact)]
subprocess.run(command,check=True)
spec = importlib.util.spec_from_file_location('lanm_compiler_check',artifact)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
assert module.answer() == 42
write_json(ROOT/'compiler-check.json',{'status':'passed','compiler':command[0],'python_include':sysconfig.get_path('include'),'artifact':str(artifact),'result':42,'gpu_used':False})
print('Native Python extension compilation and import passed; no GPU used.')
