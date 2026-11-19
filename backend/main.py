"""RootPatch backend entry point.

Run from the `backend/` directory:
    uvicorn main:app --reload --port 8000
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.errors import CodedHTTPException, coded_http_exception_handler
from app.api.router import api_router
from app.core.config import settings


def create_app() -> FastAPI:
    application = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=settings.app_description,
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    application.add_exception_handler(CodedHTTPException, coded_http_exception_handler)
    application.include_router(api_router)
    return application


app = create_app()
