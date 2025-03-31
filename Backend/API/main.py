from fastapi import FastAPI, APIRouter, HTTPException
from starlette import status
from fastapi.middleware.cors import CORSMiddleware
import auth

app = FastAPI()
app.include_router(auth.router)

@app.get('/', status_code = status.HTTP_200_OK)
async def root():
    return{"Status": "Server is up!"}

@app.get("/hello/{name}")
async def say_hello(name: str):
    return {"message": f"Hello {name}"}