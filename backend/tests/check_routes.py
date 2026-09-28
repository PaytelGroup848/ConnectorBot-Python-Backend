import os
import sys

# Ensure backend root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.main import app
from fastapi.routing import APIRoute

def main():
    route_list = []
    for route in app.routes:
        if isinstance(route, APIRoute):
            methods = ",".join(sorted(route.methods))
            route_list.append(f"{methods:<15} {route.path}")
        elif hasattr(route, "path"):
            route_list.append(f"{'ROUTE':<15} {route.path}")

    print(f"\n==========================================")
    print(f" TOTAL REGISTERED BACKEND ROUTES: {len(route_list)}")
    print(f"==========================================")
    for r in sorted(route_list):
        print(f"  {r}")
    print(f"==========================================\n")

if __name__ == "__main__":
    main()

