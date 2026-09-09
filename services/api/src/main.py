from fastapi import FastAPI

app = FastAPI(title="ReStock API")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
