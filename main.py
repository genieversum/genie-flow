from fastapi import FastAPI, Request

app = FastAPI()


@app.get("/")
def get_root():
    return "Hello World!"


@