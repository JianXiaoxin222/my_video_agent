"""Launch the local Video Agent Studio backend."""

if __name__ == "__main__":
    try:
        import uvicorn
    except ImportError as exc:
        raise SystemExit("Install backend dependencies first: .venv\\Scripts\\python.exe -m pip install -r requirements.txt") from exc
    from studio.api import create_app
    uvicorn.run(create_app(), host="127.0.0.1", port=8000, reload=False)
