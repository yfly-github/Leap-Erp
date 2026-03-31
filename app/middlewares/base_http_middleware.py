from starlette.middleware.base import BaseHTTPMiddleware


class StripSlashMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        request.scope["path"] = request.scope["path"].rstrip("/")
        return await call_next(request)

