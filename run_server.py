import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "vendor"))

import uvicorn
uvicorn.run("server:app", host="0.0.0.0", port=8000, loop="asyncio", http="h11")
