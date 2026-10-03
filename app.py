import streamlit as st
from services import (
    get_secret, run_rag, generate_cadquery_model, generate_meshy_model,
    convert_step_to_stl, repair_and_validate_stl, render_stl, slice_with_cura
)

st.set_page_config(page_title="AI → 3D Printing Pipeline", page_icon="🧊", layout="wide")

st.markdown("""
<style>
.hero{padding:2rem;border-radius:18px;background:linear-gradient(135deg,#171a1f,#252c35);border:1px solid #3b4654}
.hero p{color:#b9c3d0}.badge{display:inline-block;padding:.25rem .65rem;border:1px solid #4ea1ff;border-radius:999px;color:#72b6ff;margin-right:.4rem;font-size:.8rem}
</style>
<div class="hero">
<span class="badge">AI</span><span class="badge">CAD</span><span class="badge">3D PRINT</span>
<h1>AI → 3D Printing Pipeline</h1>
<p>Describe or photograph an object, generate a model, validate the mesh, and prepare it for slicing.</p>
</div>
""", unsafe_allow_html=True)

with st.sidebar:
    st.header("⚙️ Pipeline")
    branch = st.radio("Generation branch", [
        "Parametric / Functional (CadQuery)",
        "Organic / Artistic (Meshy)"
    ])
    st.caption("API secrets are read through st.secrets.")

if "stl_bytes" not in st.session_state: st.session_state.stl_bytes = None
if "step_bytes" not in st.session_state: st.session_state.step_bytes = None
if "repair_report" not in st.session_state: st.session_state.repair_report = None

tab_text, tab_image = st.tabs(["✍️ Text", "🖼️ Image + Measurements"])

with tab_text:
    description = st.text_area(
        "Product / object description",
        placeholder="Example: a small wall-mount cable organizer with two screw holes...",
        height=170
    )
    image_file = None
    length = width = height = 0.0

with tab_image:
    image_file = st.file_uploader("Upload a reference image", type=["png","jpg","jpeg"])
    c1,c2,c3 = st.columns(3)
    with c1: length = st.number_input("Length (mm)", min_value=0.0, step=1.0)
    with c2: width = st.number_input("Width (mm)", min_value=0.0, step=1.0)
    with c3: height = st.number_input("Height (mm)", min_value=0.0, step=1.0)
    if image_file and not all([length,width,height]):
        st.warning("Please provide the required measurements to accurately scale the model")

if st.button("🚀 Generate 3D Model", type="primary", use_container_width=True):
    if image_file and not all([length,width,height]):
        st.warning("Please provide the required measurements to accurately scale the model")
        st.stop()
    if not description and image_file is None:
        st.error("Provide a text description or upload an image.")
        st.stop()

    with st.status("Running AI → 3D pipeline...", expanded=True) as status:
        st.write("🔎 Retrieving CAD / printing context...")
        try:
            context = run_rag(description or "3D printable object")
        except Exception as e:
            context = ""
            st.warning(f"RAG unavailable: {e}")
        progress = st.progress(20)
        try:
            if branch.startswith("Parametric"):
                prompt = description or "Create a functional 3D-printable part."
                if image_file:
                    prompt += f"\nReference dimensions: L={length} mm, W={width} mm, H={height} mm."
                st.write("🧩 Generating parametric CadQuery model...")
                step_bytes, stl_bytes, code = generate_cadquery_model(prompt, context)
                st.session_state.step_bytes = step_bytes
                st.session_state.generated_code = code
            else:
                st.write("🎨 Generating organic mesh with Meshy...")
                stl_bytes = generate_meshy_model(
                    description or "3D printable object based on the reference image.",
                    image_file
                )
                st.session_state.step_bytes = None

            progress.progress(70)
            st.write("🛠️ Running watertight/manifold validation...")
            repaired, report = repair_and_validate_stl(stl_bytes)
            st.session_state.stl_bytes = repaired
            st.session_state.repair_report = report
            progress.progress(100)
            status.update(label="Generation and validation complete.", state="complete")
        except Exception as e:
            status.update(label="Pipeline failed.", state="error")
            st.exception(e)

if st.session_state.stl_bytes:
    st.divider()
    st.subheader("2. Model Preview & Validation")
    left,right = st.columns([2,1])
    with left:
        try: render_stl(st.session_state.stl_bytes)
        except Exception as e: st.info(f"3D viewer unavailable: {e}")
    with right:
        r = st.session_state.repair_report or {}
        st.metric("Watertight", "Yes" if r.get("is_watertight") else "No")
        st.metric("Manifold / winding", "Yes" if r.get("is_winding_consistent") else "No")
        st.metric("Triangles", str(r.get("faces","—")))
        for w in r.get("warnings",[]): st.warning(w)

    st.subheader("3. Files")
    if st.session_state.step_bytes:
        st.download_button(
            "Download STEP (for CAD editing)",
            st.session_state.step_bytes, "generated_model.step", "application/step"
        )
        st.caption("Edit in SolidWorks or ANSYS")
    st.download_button(
        "Download STL (for 3D printing)",
        st.session_state.stl_bytes, "printable_model.stl", "model/stl"
    )

st.divider()
st.subheader("4. Upload Edited STEP")
edited_step = st.file_uploader("Upload an edited STEP file to convert it back to STL",
                               type=["step","stp"], key="edited_step")
if edited_step and st.button("Convert STEP → STL", use_container_width=True):
    try:
        converted = convert_step_to_stl(edited_step.getvalue())
        repaired, report = repair_and_validate_stl(converted)
        st.session_state.step_bytes = edited_step.getvalue()
        st.session_state.stl_bytes = repaired
        st.session_state.repair_report = report
        st.success("STEP converted and STL validated.")
    except Exception as e:
        st.error(f"STEP conversion failed: {e}")

st.divider()
st.subheader("5. Slicing Dashboard")
c1,c2,c3 = st.columns(3)
with c1: material = st.selectbox("Material", ["PLA","PETG","ABS","TPU"])
with c2: infill = st.slider("Infill (%)", 0, 100, 20, 5)
with c3: supports = st.toggle("Supports", False)
auto_orient = st.toggle("Auto-Orient", True)

if st.button("🧵 Slice & Export Print File", type="primary", use_container_width=True):
    if not st.session_state.stl_bytes:
        st.error("Generate or upload a valid STL first.")
        st.stop()
    with st.status("Preparing print file...", expanded=True) as status:
        progress = st.progress(20)
        try:
            gcode = slice_with_cura(
                st.session_state.stl_bytes, material, infill, supports, auto_orient
            )
            progress.progress(100)
            status.update(label="Slicing complete.", state="complete")
            st.download_button("Download G-code", gcode, "print_job.gcode", "text/plain",
                               use_container_width=True)
        except Exception as e:
            status.update(label="Slicing unavailable.", state="error")
            st.error(str(e))

with st.expander("🔐 Configuration status"):
    for name in ["OPENAI_API_KEY","MESHY_API_KEY","PINECONE_API_KEY"]:
        st.write(("✅ " if get_secret(name,"") else "❌ ") + name)
    st.caption("CURA_ENGINE_PATH and CURA_DEFINITION_PATH are native-tool settings, not API keys.")
