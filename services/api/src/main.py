from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy import create_engine

from src import auth, catalog, operations_routes
from src.config import Settings
from src.errors import (
    ApiError,
    ErrorResponse,
    api_error_handler,
    validation_error_handler,
)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    engine = create_engine(settings.database_url, pool_pre_ping=True)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        engine.dispose()

    app = FastAPI(title="ReStock API", lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = engine
    app.add_exception_handler(ApiError, api_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "Authorization"],
    )
    api = APIRouter(
        prefix="/api/v1",
        responses={
            401: {"model": ErrorResponse},
            403: {"model": ErrorResponse},
            422: {"model": ErrorResponse},
        },
    )
    api.include_router(auth.router)
    api.include_router(catalog.router)
    api.include_router(operations_routes.router)
    app.include_router(api)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/connect", include_in_schema=False)
    def connect() -> FileResponse:
        return FileResponse(Path(__file__).parent / "static" / "connect.html")

    return app


app = create_app()
