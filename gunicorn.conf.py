"""
Gunicorn configuration for Render (free tier, 512 MB RAM).

--preload loads the app once in the master process; workers fork from it,
sharing the read-only pages via copy-on-write.  The post_fork hook disposes
SQLAlchemy's connection pool so each worker opens its own fresh connections
rather than sharing the master's file descriptors.
"""

import os

workers = 1
threads = 4
timeout = 120
preload_app = True
bind = f"0.0.0.0:{os.environ.get('PORT', '10000')}"

# Keep gunicorn's access log quiet unless DEBUG is set
accesslog = None if not os.environ.get("DEBUG") else "-"
errorlog = "-"
loglevel = "info"


def post_fork(server, worker):
    """Dispose SQLAlchemy engine after fork to avoid shared connections."""
    try:
        from app import db
        db.engine.dispose()
    except Exception:
        pass
