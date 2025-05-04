from fastapi import FastAPI, APIRouter, HTTPException
from starlette import status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from dotenv import load_dotenv
import os
import auth
from models import RagResponse
from ragroute import RagModel

app = FastAPI()
app.include_router(auth.router)
load_dotenv("API.env")
INDEX_NAME = os.getenv("INDEX_NAME")
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
GENAI_API_KEY = os.getenv("GENAI_API_KEY")

namespaces = os.getenv("NAMESPACES","")
namespaces = [item.strip() for item in namespaces.split(',') if item]
Rag_Model = RagModel(PINECONE_API_KEY, GENAI_API_KEY, NameSpaces=namespaces, Index_Name=INDEX_NAME, min_score=0.75)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Allows all origins
    allow_credentials=True,
    allow_methods=["*"], # Allows all methods
    allow_headers=["*"], # Allows all headers
)

@app.get('/', status_code = status.HTTP_200_OK)
async def root():
    return{"Status": "Server is up!"}

@app.get("/hello/{name}")
async def say_hello(name: str):
    return {"message": f"Hello {name}"}

@app.post("/query")
async def rag_query(query: str):
    Rag_Resp = Rag_Model.Rag_Generator_caller(user_query=query)
    return {"message": RagResponse(query_resp=Rag_Resp)}
        
@app.post("/query-stream")
async def stream_rag_query(query: str):
    Rag_resp = Rag_Model.Rag_Generator_stream_caller
    return StreamingResponse(Rag_resp(user_query=query), media_type="text/plain")

@app.post("/submit-logreport")
async def create_log_entry():
    pass