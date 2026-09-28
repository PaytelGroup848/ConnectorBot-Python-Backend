import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.main import app

def print_routes(router, prefix=""):
    for r in router.routes:
        print(type(r), getattr(r, 'path', None), getattr(r, 'methods', None))
        if hasattr(r, 'app') and hasattr(r.app, 'routes'):
            print_routes(r.app, prefix=prefix + getattr(r, 'path', ''))

print_routes(app)

