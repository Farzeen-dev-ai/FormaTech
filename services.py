import base64, io, os, re, subprocess, tempfile, time
from pathlib import Path

import requests
import streamlit as st
import trimesh
from openai import OpenAI

from cadquery_runner import run_cadquery_script
from rag import retrieve_context

def get_secret(name, default=None):
    try:
        return st.secrets[name]
    except Exception:
        return os.getenv(name, default)

def run_rag(query):
    if not get_secret("OPENAI_API_KEY") or not get_secret("PINECONE_API_KEY"):
        return "RAG disabled: configure OPENAI_API_KEY and PINECONE_API_KEY."
    return retrieve_context(query)

def _openai():
    key = get_secret("OPENAI_API_KEY")
    if not key: raise RuntimeError("OPENAI_API_KEY is not configured.")
    return OpenAI(api_key=key)

def generate_cadquery_model(prompt, rag_context):
    client = _openai()
    instructions = (
        "Generate ONLY Python code for a simple deterministic CadQuery functional part. "
        "Use `import cadquery as cq`, millimeters, and define exactly one final object named `result`. "
        "Do not import os, sys, subprocess, pathlib, shutil, socket, requests, urllib, pickle, ctypes. "
        "Do not read/write files. Prefer primitives, sketches, extrusions, cuts, unions and fillets."
    )
    user = f"User request:\n{prompt}\n\nRAG context:\n{rag_context}"
    response = client.responses.create(
        model=get_secret("OPENAI_MODEL","gpt-5.6-luna"),
        instructions=instructions,
        input=user
    )
    code = response.output_text.strip()
    code = re.sub(r"^```(?:python)?\s*","",code)
    code = re.sub(r"\s*```$","",code)
    step_bytes, stl_bytes = run_cadquery_script(code)
    return step_bytes, stl_bytes, code

def generate_meshy_model(prompt, image_file=None):
    key = get_secret("MESHY_API_KEY")
    if not key: raise RuntimeError("MESHY_API_KEY is not configured.")
    headers = {"Authorization":f"Bearer {key}","Content-Type":"application/json"}

    if image_file:
        raw = image_file.getvalue()
        mime = image_file.type or "image/png"
        data_uri = f"data:{mime};base64,{base64.b64encode(raw).decode()}"
        payload = {"image_url":data_uri,"ai_model":"meshy-7.1","target_formats":["stl"]}
        create_url = "https://api.meshy.ai/openapi/v1/image-to-3d"
        status_url = "https://api.meshy.ai/openapi/v1/image-to-3d/{}/"
    else:
        payload = {"mode":"preview","prompt":prompt[:2000],"ai_model":"meshy-7.1","target_formats":["stl"]}
        create_url = "https://api.meshy.ai/openapi/v2/text-to-3d"
        status_url = "https://api.meshy.ai/openapi/v2/text-to-3d/{}/"

    r = requests.post(create_url, headers=headers, json=payload, timeout=60)
    if not r.ok: raise RuntimeError(f"Meshy task creation failed ({r.status_code}): {r.text}")
    task_id = r.json().get("result")
    if not task_id: raise RuntimeError("Meshy did not return a task ID.")

    for _ in range(120):
        time.sleep(5)
        s = requests.get(status_url.format(task_id).rstrip("/"),
                         headers={"Authorization":f"Bearer {key}"}, timeout=60)
        if not s.ok: raise RuntimeError(f"Meshy status failed ({s.status_code}): {s.text}")
        task = s.json()
        if task.get("status") == "SUCCEEDED":
            url = task.get("model_urls",{}).get("stl")
            if not url: raise RuntimeError("Meshy completed but returned no STL URL.")
            return requests.get(url, timeout=120).content
        if task.get("status") == "FAILED":
            raise RuntimeError(f"Meshy task failed: {task.get('task_error',{})}")
    raise TimeoutError("Meshy task timed out.")

def convert_step_to_stl(step_bytes):
    return run_cadquery_script(None, step_bytes=step_bytes, convert_only=True)[1]

def repair_and_validate_stl(stl_bytes):
    mesh = trimesh.load(io.BytesIO(stl_bytes), file_type="stl", force="mesh")
    if isinstance(mesh, trimesh.Scene):
        mesh = trimesh.util.concatenate(tuple(mesh.geometry.values()))
    if mesh.is_empty: raise RuntimeError("STL contains no geometry.")
    for fn in ["remove_duplicate_faces","remove_degenerate_faces","remove_unreferenced_vertices"]:
        try: getattr(mesh,fn)()
        except Exception: pass
    warnings=[]
    if not mesh.is_watertight: warnings.append("Mesh is not watertight after basic cleanup.")
    if not mesh.is_winding_consistent: warnings.append("Mesh winding is not consistent.")
    out=io.BytesIO(); mesh.export(out,file_type="stl")
    return out.getvalue(), {
        "is_watertight":bool(mesh.is_watertight),
        "is_winding_consistent":bool(mesh.is_winding_consistent),
        "faces":int(len(mesh.faces)), "vertices":int(len(mesh.vertices)),
        "warnings":warnings
    }

def render_stl(stl_bytes):
    import pyvista as pv
    from stpyvista import stpyvista
    with tempfile.NamedTemporaryFile(suffix=".stl",delete=False) as f:
        f.write(stl_bytes); path=f.name
    try:
        mesh=pv.read(path); plotter=pv.Plotter(window_size=(850,550))
        plotter.add_mesh(mesh); plotter.set_background("#11151a"); stpyvista(plotter)
    finally:
        try: os.remove(path)
        except OSError: pass

def slice_with_cura(stl_bytes, material, infill, supports, auto_orient):
    engine=get_secret("CURA_ENGINE_PATH")
    definition=get_secret("CURA_DEFINITION_PATH")
    if not engine: raise RuntimeError("CURA_ENGINE_PATH is not configured.")
    if not Path(engine).exists(): raise RuntimeError(f"CuraEngine not found: {engine}")
    if not definition: raise RuntimeError("CURA_DEFINITION_PATH is not configured.")
    with tempfile.TemporaryDirectory() as td:
        td=Path(td); stl=td/"model.stl"; gcode=td/"model.gcode"; stl.write_bytes(stl_bytes)
        cmd=[engine,"slice","-j",definition,
             "-s",f"infill_sparse_density={int(infill)}",
             "-s",f"support_enable={'true' if supports else 'false'}",
             "-l",str(stl),"-o",str(gcode)]
        p=subprocess.run(cmd,capture_output=True,text=True,timeout=180)
        if p.returncode!=0:
            raise RuntimeError("CuraEngine failed.\nSTDOUT:\n"+p.stdout[-4000:]+"\nSTDERR:\n"+p.stderr[-4000:])
        if not gcode.exists(): raise RuntimeError("CuraEngine produced no G-code.")
        return gcode.read_bytes()
