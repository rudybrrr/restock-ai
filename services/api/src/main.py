from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import FileResponse, HTMLResponse
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

    app = FastAPI(title="ReStock API", lifespan=lifespan, docs_url=None)
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

    @app.get("/docs", include_in_schema=False)
    def docs() -> HTMLResponse:
        page = get_swagger_ui_html(
            openapi_url="/openapi.json", title="ReStock API — testing"
        )
        html = (
            bytes(page.body)
            .decode()
            .replace("</head>", '<script defer src="/docs-ui.js"></script></head>')
        )
        return HTMLResponse(html, headers={"Cache-Control": "no-store"})

    @app.get("/docs-ui.js", include_in_schema=False)
    def docs_script() -> FileResponse:
        return FileResponse(
            Path(__file__).parent / "static" / "docs-ui.js",
            media_type="text/javascript",
        )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/connect", include_in_schema=False)
    def connect() -> FileResponse:
        return FileResponse(Path(__file__).parent / "static" / "connect.html")

    return app


app = create_app()
