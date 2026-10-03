import ast, tempfile, subprocess, sys
from pathlib import Path
import cadquery as cq

BLOCKED={"os","sys","subprocess","pathlib","shutil","socket","requests","urllib","pickle","ctypes"}

def validate_script(code):
    tree=ast.parse(code)
    for n in ast.walk(tree):
        if isinstance(n,ast.Import):
            for a in n.names:
                root=a.name.split(".")[0]
                if root!="cadquery" or root in BLOCKED: raise ValueError(f"Blocked import: {a.name}")
        if isinstance(n,ast.ImportFrom):
            root=(n.module or "").split(".")[0]
            if root!="cadquery": raise ValueError(f"Blocked import: {n.module}")
        if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id in {"exec","eval","compile","__import__","open"}:
            raise ValueError(f"Blocked operation: {n.func.id}")

def run_cadquery_script(code=None, step_bytes=None, convert_only=False):
    with tempfile.TemporaryDirectory() as td:
        td=Path(td); step=td/"input.step"; out_step=td/"model.step"; out_stl=td/"model.stl"
        if convert_only:
            step.write_bytes(step_bytes)
            result=cq.importers.importStep(str(step),unit="MM")
            result.export(str(out_stl))
            return None,out_stl.read_bytes()
        validate_script(code)
        script=td/"model.py"; script.write_text(code,encoding="utf-8")
        p=subprocess.run([sys.executable,str(script)],cwd=str(td),capture_output=True,text=True,timeout=90)
        if p.returncode!=0:
            raise RuntimeError("CadQuery failed.\nSTDOUT:\n"+p.stdout[-3000:]+"\nSTDERR:\n"+p.stderr[-3000:])
        namespace={"cq":cq}
        exec(compile(code,str(script),"exec"),{"__builtins__":{}},namespace)
        result=namespace.get("result")
        if result is None: raise RuntimeError("Generated script did not define `result`.")
        result.export(str(out_step)); result.export(str(out_stl))
        return out_step.read_bytes(),out_stl.read_bytes()
