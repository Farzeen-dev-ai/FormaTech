# AI → 3D Printing Pipeline

GitHub-ready Streamlit project for an AI-to-3D-printing workflow.

## Files
- `app.py` — Streamlit UI and workflow
- `services.py` — OpenAI, Meshy, validation, viewer and slicing services
- `rag.py` — Pinecone + OpenAI embedding RAG
- `cadquery_runner.py` — STEP conversion and CadQuery execution
- `requirements.txt` — Python dependencies
- `.streamlit/config.toml` — dark metallic UI
- `.streamlit/secrets.toml.example` — secret template

## Important
Do NOT commit `.streamlit/secrets.toml` or API keys.

CuraEngine and CadQuery are native/system-heavy tools. Streamlit Community Cloud may not provide a complete native environment for them. For a production version, keep Streamlit as the UI and run CAD/slicing in a separate worker service.

## Run locally
```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

Set the secrets in `.streamlit/secrets.toml`.

## RAG
The app creates a Pinecone serverless index named `ai-3d-printing-rag` and seeds a small project-owned starter knowledge set. Replace/extend it with properly licensed open-source/public-domain material for a larger project.

## CuraEngine
Set `CURA_ENGINE_PATH` to the executable and `CURA_DEFINITION_PATH` to the correct printer definition/settings JSON. Exact profiles depend on the target printer.
