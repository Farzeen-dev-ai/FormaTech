import os
import streamlit as st
from openai import OpenAI
from pinecone import Pinecone, ServerlessSpec
from langchain_openai import OpenAIEmbeddings
from langchain_pinecone import PineconeVectorStore
from langchain_core.documents import Document

INDEX_NAME = "ai-3d-printing-rag"
EMBED_MODEL = "text-embedding-3-small"
DIMENSION = 1536

SEED_DOCUMENTS = [
    {"id":"cadquery-box","text":"CadQuery uses millimeters by default. A printable solid can be created with cq.Workplane().box(length,width,height).","topic":"CadQuery"},
    {"id":"cadquery-step","text":"CadQuery can import STEP with cq.importers.importStep(path) and export STEP or STL geometry.","topic":"STEP"},
    {"id":"watertight","text":"A printable mesh should normally be a closed solid. A watertight mesh has no open boundary edges.","topic":"3D printing"},
    {"id":"infill","text":"Infill percentage changes internal material. The suitable value depends on strength, weight, print time and material.","topic":"Slicing"},
    {"id":"supports","text":"Supports may be needed for overhangs and geometry that cannot print reliably without temporary structures.","topic":"Slicing"},
]

def secret(name, default=None):
    try:
        return st.secrets[name]
    except Exception:
        return os.getenv(name, default)

def pinecone_index():
    key = secret("PINECONE_API_KEY")
    okey = secret("OPENAI_API_KEY")
    if not key or not okey:
        raise RuntimeError("OPENAI_API_KEY and PINECONE_API_KEY are required for RAG.")
    pc = Pinecone(api_key=key)
    names = [x["name"] for x in pc.list_indexes()]
    if INDEX_NAME not in names:
        pc.create_index(
            name=INDEX_NAME,
            dimension=DIMENSION,
            metric="cosine",
            spec=ServerlessSpec(cloud="aws", region="us-east-1"),
        )
    return pc.Index(INDEX_NAME)

def embed(texts):
    client = OpenAI(api_key=secret("OPENAI_API_KEY"))
    result = client.embeddings.create(model=EMBED_MODEL, input=texts)
    return [item.embedding for item in result.data]

def seed():
    idx = pinecone_index()
    stats = idx.describe_index_stats()
    if stats.get("total_vector_count", 0) > 0:
        return

    vectors = embed([d["text"] for d in SEED_DOCUMENTS])
    idx.upsert(
        vectors=[
            {
                "id": d["id"],
                "values": vector,
                "metadata": {"text": d["text"], "topic": d["topic"]},
            }
            for d, vector in zip(SEED_DOCUMENTS, vectors)
        ]
    )

def retrieve_context(query, top_k=5):
    seed()

    embeddings = OpenAIEmbeddings(
        model=EMBED_MODEL,
        api_key=secret("OPENAI_API_KEY"),
    )

    vectorstore = PineconeVectorStore(
        index_name=INDEX_NAME,
        embedding=embeddings,
        pinecone_api_key=secret("PINECONE_API_KEY"),
    )

    docs = vectorstore.similarity_search(query, k=top_k)
    if not docs:
        return "No relevant context was retrieved."

    return "\n\n".join(
        f"[{doc.metadata.get('topic', 'unknown')}] {doc.page_content}"
        for doc in docs
    )
